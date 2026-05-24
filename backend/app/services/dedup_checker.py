"""Поиск дубликатов и похожих закладок.

1. find_near_duplicate — двухуровневый:
   Pass 1: embedding cosine > 0.85 (семантический)
   Pass 2: text overlap > 60% (ловит копипаст с эмодзи/форматированием)
   Для task_list ↔ task_list overlap считается по ПУНКТАМ
   (`structured_data.tasks[].text`), а не по raw_text — чтобы бот-генерённый
   заголовок/подсказки не влияли на сравнение (bug u4z).
2. find_similar_unclosed_task_list — cosine > 0.7, только незакрытые task_list

Используется worker'ом после создания embedding.
"""
from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

NEAR_DUPLICATE_THRESHOLD = 0.85  # embedding-based (ниже чем 0.95 — ловим перефразированные)
TASK_LIST_SIMILARITY_THRESHOLD = 0.7
LOOKBACK_DAYS = 7
TEXT_OVERLAP_THRESHOLD = 0.6  # ≥60% строк совпадают → дубль


import re as _re

# Служебные строки нашего бот-рендера — игнорируем при сравнении.
# Только chrome (заголовок 📋, футеры Reply/Примеры/Выполнено/таймкоды),
# но НЕ ловим ☐/✅/⏰ — это маркеры пунктов, их нужно сохранять.
_BOT_NOISE_RE = _re.compile(
    r"^\s*(?:📋|↩️|💬|"
    r"Выполнено:|Reply:|Примеры:|Ответь reply|Ответь на это сообщение|"
    r"\[\d{2}:\d{2}\])",
    _re.IGNORECASE,
)


def _normalize_line(line: str) -> str:
    """Нормализует строку для сравнения: убирает эмодзи, bullet-маркеры,
    нумерацию, даты — оставляет только смысловой текст пункта.
    """
    # Убираем эмодзи и спецсимволы (☐, ✅, ⏰, 📋, ↩️, etc.)
    line = _re.sub(r'[^\w\s,.()\-]', '', line)
    # Убираем bullet-маркеры в начале строки (-, •, *, —, −)
    line = _re.sub(r'^\s*[-•*—−]\s*', '', line)
    # Убираем нумерацию в начале (1. 2) 3- и т.д.)
    line = _re.sub(r'^\s*\d+[.):\-]\s*', '', line)
    # Убираем даты в формате DD.MM
    line = _re.sub(r'\d{2}\.\d{2}', '', line)
    return line.strip().lower()


def _meaningful_lines(text: str) -> set[str]:
    """Возвращает множество нормализованных смысловых строк.

    Отфильтровывает: пустые, короче 3 символов, служебные строки бот-рендера
    (📋, Reply:, Выполнено:, …) — без них сравнение работает корректно
    даже когда новый текст это forward-нутый бот-рендер старого.
    """
    out: set[str] = set()
    for raw_line in text.split("\n"):
        if _BOT_NOISE_RE.match(raw_line):
            continue
        norm = _normalize_line(raw_line)
        if len(norm) >= 3:
            out.add(norm)
    return out


def _text_overlap(new_text: str, existing_text: str) -> float:
    """Симметричная мера пересечения смысловых строк.

    Возвращает max(matched/|new|, matched/|existing|). Так копия с разной
    «нагрузкой» вокруг (forward бот-рендера vs голый список) всё равно
    распознаётся как дубль с одной из сторон.
    """
    new_lines = _meaningful_lines(new_text)
    existing_lines = _meaningful_lines(existing_text)
    if not new_lines or not existing_lines:
        return 0.0
    matched = len(new_lines & existing_lines)
    if matched == 0:
        return 0.0
    return max(matched / len(new_lines), matched / len(existing_lines))


def _task_items(structured: dict | None) -> set[str]:
    """Нормализованные тексты пунктов task_list.

    Берём ТОЛЬКО `structured_data.tasks[].text` — это чистый смысл пункта,
    без бот-генерённого заголовка/подсказок/маркеров. Сравнение по этому
    множеству устойчиво к тому, как список отрендерен (bug u4z).
    """
    if not isinstance(structured, dict):
        return set()
    out: set[str] = set()
    for t in structured.get("tasks", []) or []:
        if not isinstance(t, dict):
            continue
        norm = _normalize_line(str(t.get("text", "")))
        if len(norm) >= 3:
            out.add(norm)
    return out


def _task_list_overlap(new_s: dict | None, existing_s: dict | None) -> float | None:
    """Overlap по пунктам двух task_list'ов (симметричный).

    Возвращает None, если хотя бы один из них не task_list с пунктами —
    тогда caller падает обратно на текстовый overlap по raw_text.
    """
    new_items = _task_items(new_s)
    existing_items = _task_items(existing_s)
    if not new_items or not existing_items:
        return None
    matched = len(new_items & existing_items)
    if matched == 0:
        return 0.0
    return max(matched / len(new_items), matched / len(existing_items))


def _dup_overlap(
    new_text: str,
    new_structured: dict | None,
    existing_text: str,
    existing_structured: dict | None,
) -> float:
    """Единая мера дубликатности.

    task_list ↔ task_list → сравнение по ПУНКТАМ (без бот-заголовка/подсказок).
    Иначе — по смысловым строкам raw_text.
    """
    item_overlap = _task_list_overlap(new_structured, existing_structured)
    if item_overlap is not None:
        return item_overlap
    return _text_overlap(new_text, existing_text)


async def find_near_duplicate(
    session: AsyncSession,
    bookmark_id: UUID,
    user_id: UUID,
    embedding: list[float] | None,
    raw_text: str = "",
    new_structured: dict | None = None,
) -> dict | None:
    """Ищет дубликат: embedding (cosine > 0.85) + text overlap (> 60%).

    Два уровня проверки:
    1. Embedding — ловит семантические дубли (перефразированные).
       Пропускается если embedding=None (partial после GigaChat-fail).
    2. Text overlap — ловит копипаст с форматированием (эмодзи, нумерация).
       Работает всегда.

    Возвращает dict или None.
    """
    rows: list = []
    # Уровень 1: embedding similarity (только если есть embedding)
    if embedding is not None:
        query = text("""
            SELECT
                b.id,
                b.title,
                b.summary,
                b.item_type,
                b.structured_data,
                b.raw_text,
                b.created_at,
                1 - (b.embedding <=> CAST(:query_embedding AS vector)) AS similarity
            FROM bookmarks b
            WHERE b.user_id = :user_id
              AND b.id != :current_id
              AND b.ai_status IN ('completed', 'partial')
              AND b.embedding IS NOT NULL
              AND b.is_archived = false
              AND 1 - (b.embedding <=> CAST(:query_embedding AS vector)) > :threshold
            ORDER BY similarity DESC
            LIMIT 3
        """)

        result = await session.execute(
            query,
            {
                "user_id": str(user_id),
                "current_id": str(bookmark_id),
                "query_embedding": str(embedding),
                "threshold": NEAR_DUPLICATE_THRESHOLD,
            },
        )
        rows = result.fetchall()

    # Pass 1: проверяем embedding-кандидатов на text overlap
    for row in rows:
        sim = float(row.similarity)
        structured = row.structured_data
        is_task_list = (
            isinstance(structured, dict)
            and structured.get("type") == "task_list"
        )

        # Высокий embedding similarity (>0.95) — сразу дубль
        if sim >= 0.95:
            pass  # точно дубль, не нужен text check
        elif raw_text and row.raw_text:
            # Средний embedding (0.85-0.95) — нужно подтверждение.
            # task_list ↔ task_list сравниваем по пунктам (bug u4z), иначе по raw_text.
            overlap = _dup_overlap(raw_text, new_structured, row.raw_text, structured)
            if overlap < TEXT_OVERLAP_THRESHOLD:
                continue  # не достаточно похож

        return {
            "id": str(row.id),
            "title": row.title,
            "summary": row.summary,
            "item_type": row.item_type,
            "is_task_list": is_task_list,
            "created_at": row.created_at,
            "similarity": sim,
        }

    # Pass 2: text overlap без embedding (ловит копипаст с эмодзи/форматированием)
    # Embedding может сильно отличаться если юзер скопировал отрендеренный текст
    # (эмодзи ☐/✅/⏰ → AI выдаёт другой title/summary → другой embedding)
    if raw_text and len(raw_text) >= 20:
        match = await _find_by_text_overlap(
            session, bookmark_id, user_id, raw_text, new_structured,
        )
        if match:
            return match

    return None


async def _find_by_text_overlap(
    session: AsyncSession,
    bookmark_id: UUID,
    user_id: UUID,
    raw_text: str,
    new_structured: dict | None = None,
) -> dict | None:
    """Pass 2: ищем дубль чисто по текстовому пересечению.

    Берём последние 20 закладок за LOOKBACK_DAYS дней и считаем
    _text_overlap в Python. Если ≥ TEXT_OVERLAP_THRESHOLD — дубль.
    """
    query = text("""
        SELECT
            b.id,
            b.title,
            b.summary,
            b.item_type,
            b.structured_data,
            b.raw_text,
            b.created_at
        FROM bookmarks b
        WHERE b.user_id = :user_id
          AND b.id != :current_id
          AND b.ai_status IN ('completed', 'partial')
          AND b.is_archived = false
          AND b.created_at > NOW() - make_interval(days => :lookback)
          AND b.raw_text IS NOT NULL
          AND length(b.raw_text) > 10
        ORDER BY b.created_at DESC
        LIMIT 20
    """)

    result = await session.execute(
        query,
        {
            "user_id": str(user_id),
            "current_id": str(bookmark_id),
            "lookback": LOOKBACK_DAYS,
        },
    )
    rows = result.fetchall()

    for row in rows:
        if not row.raw_text:
            continue
        structured = row.structured_data
        # task_list ↔ task_list — по пунктам (bug u4z), иначе по raw_text.
        overlap = _dup_overlap(raw_text, new_structured, row.raw_text, structured)
        if overlap >= TEXT_OVERLAP_THRESHOLD:
            is_task_list = (
                isinstance(structured, dict)
                and structured.get("type") == "task_list"
            )
            logger.info(
                "Text overlap dedup: %.0f%% overlap between %s and %s",
                overlap * 100, bookmark_id, row.id,
            )
            return {
                "id": str(row.id),
                "title": row.title,
                "summary": row.summary,
                "item_type": row.item_type,
                "is_task_list": is_task_list,
                "created_at": row.created_at,
                "similarity": overlap,  # используем overlap как similarity
            }

    return None


async def find_similar_unclosed_task_list(
    session: AsyncSession,
    bookmark_id: UUID,
    user_id: UUID,
    embedding: list[float],
) -> dict | None:
    """Ищет похожий незакрытый task_list для данного юзера.

    Returns dict {"id", "title", "structured_data", "created_at", "similarity"}
    или None если подходящего нет.
    """
    # pgvector cosine distance: <=> возвращает distance (0=identical, 2=opposite)
    # similarity = 1 - distance
    query = text("""
        SELECT
            b.id,
            b.title,
            b.structured_data,
            b.created_at,
            1 - (b.embedding <=> CAST(:query_embedding AS vector)) AS similarity
        FROM bookmarks b
        WHERE b.user_id = :user_id
          AND b.id != :current_id
          AND b.structured_data->>'type' = 'task_list'
          AND b.ai_status IN ('completed', 'partial')
          AND b.created_at > NOW() - INTERVAL '7 days'
          AND b.embedding IS NOT NULL
          AND b.is_archived = false
          AND 1 - (b.embedding <=> CAST(:query_embedding AS vector)) > :threshold
        ORDER BY similarity DESC
        LIMIT 3
    """)

    result = await session.execute(
        query,
        {
            "user_id": str(user_id),
            "current_id": str(bookmark_id),
            "query_embedding": str(embedding),
            "threshold": TASK_LIST_SIMILARITY_THRESHOLD,
        },
    )
    rows = result.fetchall()

    if not rows:
        return None

    # Post-filter: список должен быть незакрытым (хотя бы 1 задача с done=false)
    for row in rows:
        structured = row.structured_data
        if not isinstance(structured, dict):
            continue
        tasks = structured.get("tasks", [])
        if not tasks:
            continue
        has_undone = any(not t.get("done", False) for t in tasks)
        if has_undone:
            done_count = sum(1 for t in tasks if t.get("done", False))
            return {
                "id": str(row.id),
                "title": row.title,
                "structured_data": structured,
                "created_at": row.created_at,
                "similarity": float(row.similarity),
                "done_count": done_count,
                "total_count": len(tasks),
            }

    return None
