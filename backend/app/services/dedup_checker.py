"""Поиск дубликатов и похожих закладок.

1. find_near_duplicate — двухуровневый:
   Pass 1: embedding cosine > 0.85 (семантический)
   Pass 2: text overlap > 60% по raw_text (ловит копипаст с эмодзи/форматированием)
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


def _normalize_line(line: str) -> str:
    """Нормализует строку для сравнения: убирает эмодзи, пунктуацию, нумерацию."""
    import re
    # Убираем эмодзи и спецсимволы (☐, ✅, ⏰, 📋, ↩️, etc.)
    line = re.sub(r'[^\w\s,.()\-]', '', line)
    # Убираем нумерацию в начале (1. 2) 3- и т.д.)
    line = re.sub(r'^\s*\d+[.):\-]\s*', '', line)
    # Убираем даты в формате DD.MM
    line = re.sub(r'\d{2}\.\d{2}', '', line)
    return line.strip().lower()


def _text_overlap(new_text: str, existing_text: str) -> float:
    """Доля строк нового текста, которые содержатся в существующем.

    Сравнивает нормализованные строки. Пропускает пустые и очень короткие (<3 символа).
    """
    new_lines = {
        _normalize_line(l) for l in new_text.split('\n')
        if len(_normalize_line(l)) >= 3
    }
    existing_lines = {
        _normalize_line(l) for l in existing_text.split('\n')
        if len(_normalize_line(l)) >= 3
    }

    if not new_lines:
        return 0.0

    matched = sum(1 for nl in new_lines if nl in existing_lines)
    return matched / len(new_lines)


async def find_near_duplicate(
    session: AsyncSession,
    bookmark_id: UUID,
    user_id: UUID,
    embedding: list[float],
    raw_text: str = "",
) -> dict | None:
    """Ищет дубликат: embedding (cosine > 0.85) + text overlap (> 60%).

    Два уровня проверки:
    1. Embedding — ловит семантические дубли (перефразированные)
    2. Text overlap — ловит копипаст с форматированием (эмодзи, нумерация)

    Возвращает dict или None.
    """
    # Уровень 1: embedding similarity
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
        # Высокий embedding similarity (>0.95) — сразу дубль
        if sim >= 0.95:
            pass  # точно дубль, не нужен text check
        elif raw_text and row.raw_text:
            # Средний embedding (0.85-0.95) — нужен text overlap для подтверждения
            overlap = _text_overlap(raw_text, row.raw_text)
            if overlap < TEXT_OVERLAP_THRESHOLD:
                continue  # не достаточно похож текстово

        structured = row.structured_data
        is_task_list = (
            isinstance(structured, dict)
            and structured.get("type") == "task_list"
        )

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
            session, bookmark_id, user_id, raw_text,
        )
        if match:
            return match

    return None


async def _find_by_text_overlap(
    session: AsyncSession,
    bookmark_id: UUID,
    user_id: UUID,
    raw_text: str,
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
        overlap = _text_overlap(raw_text, row.raw_text)
        if overlap >= TEXT_OVERLAP_THRESHOLD:
            structured = row.structured_data
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
