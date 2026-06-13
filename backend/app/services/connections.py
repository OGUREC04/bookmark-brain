"""Connections MVP — поиск похожих заметок и запись смысловых связей.

Ядро Phase 5A. Переиспользует SQL-идиому kNN из dedup_checker
(`1 - (embedding <=> CAST(:q AS vector))`), но логика — про СВЯЗИ, а не дубли:
top-k (а не LIMIT 3), порог 0.75 (а не 0.85), список (а не один dict).

Ребро пишется КАНОНИЧЕСКИ: (from_id, to_id) = отсортированная пара id. Косинус
симметричен (cos(A,B) == cos(B,A)), поэтому A→B и B→A дают одну и ту же строку,
а UNIQUE(from_id,to_id,kind) + ON CONFLICT DO NOTHING исключают дубль-реверс
(AD-3: одно ребро, читаем обе стороны).

Всё — чистый pgvector/SQL, 0 вызовов LLM (NFR-1).
"""
from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Порог косинуса для связи. Старт 0.75 (≠ дедуп 0.85) — калибруется на бэкфилле.
SIMILAR_THRESHOLD = 0.75
# Сколько рёбер максимум хранить на заметку (баланс «Посмотреть все» vs объём БД).
DEFAULT_K_STORE = 30
LINK_KIND_SIMILAR = "similar"


async def find_similar_bookmarks(
    session: AsyncSession,
    bookmark_id: UUID,
    user_id: UUID,
    embedding: list[float] | None,
    *,
    k: int = DEFAULT_K_STORE,
    threshold: float = SIMILAR_THRESHOLD,
) -> list[dict]:
    """Top-k семантически похожих заметок пользователя (cosine ≥ threshold).

    Скоуп по user_id (NFR-4), исключает саму заметку, архив и записи без
    эмбеддинга. Возвращает [{"id": str, "similarity": float}] по убыванию.
    Если эмбеддинга нет — пустой список (partial-заметки не связываем).
    """
    if embedding is None:
        return []

    query = text("""
        SELECT
            b.id,
            1 - (b.embedding <=> CAST(:query_embedding AS vector)) AS similarity
        FROM bookmarks b
        WHERE b.user_id = :user_id
          AND b.id != :current_id
          AND b.ai_status IN ('completed', 'partial')
          AND b.embedding IS NOT NULL
          AND b.is_archived = false
          AND 1 - (b.embedding <=> CAST(:query_embedding AS vector)) >= :threshold
        ORDER BY similarity DESC
        LIMIT :k
    """)
    result = await session.execute(
        query,
        {
            "user_id": str(user_id),
            "current_id": str(bookmark_id),
            "query_embedding": str(embedding),
            "threshold": threshold,
            "k": k,
        },
    )
    return [
        {"id": str(row.id), "similarity": float(row.similarity)}
        for row in result.fetchall()
    ]


def _canonical_pair(a: str, b: str) -> tuple[str, str]:
    """Упорядоченная пара id — одно ребро на любую из двух сторон."""
    return (a, b) if a <= b else (b, a)


async def build_links_for_bookmark(
    session: AsyncSession,
    bookmark_id: UUID,
    user_id: UUID,
    embedding: list[float] | None,
    *,
    k: int = DEFAULT_K_STORE,
    threshold: float = SIMILAR_THRESHOLD,
) -> int:
    """Находит похожие и пишет рёбра `kind='similar'`. Возвращает число созданных.

    Идемпотентно: ON CONFLICT (from_id,to_id,kind) DO NOTHING. Направление
    каноническое, поэтому повторная обработка любой из двух заметок не плодит
    дубль-реверс.
    """
    if embedding is None:
        return 0

    candidates = await find_similar_bookmarks(
        session, bookmark_id, user_id, embedding, k=k, threshold=threshold
    )
    if not candidates:
        return 0

    insert_sql = text("""
        INSERT INTO bookmark_links (user_id, from_id, to_id, kind, weight)
        VALUES (:user_id, :from_id, :to_id, 'similar', :weight)
        ON CONFLICT (from_id, to_id, kind) DO NOTHING
    """)

    created = 0
    src = str(bookmark_id)
    for cand in candidates:
        from_id, to_id = _canonical_pair(src, cand["id"])
        result = await session.execute(
            insert_sql,
            {
                "user_id": str(user_id),
                "from_id": from_id,
                "to_id": to_id,
                "weight": cand["similarity"],
            },
        )
        # asyncpg при ON CONFLICT DO NOTHING (skip) может вернуть rowcount=-1
        # (indeterminate), который truthy → испортил бы счётчик. Каждый INSERT —
        # ровно одна строка, поэтому реальная вставка ⇔ rowcount == 1.
        if (result.rowcount or 0) == 1:
            created += 1
    return created


async def get_related(
    session: AsyncSession,
    bookmark_id: UUID,
    user_id: UUID,
    *,
    limit: int = 5,
    include_all: bool = False,
) -> list[dict]:
    """Связанные заметки (обе стороны ребра), по убыванию веса.

    Скоуп по user_id (NFR-4). Для каждого ребра отдаёт «другую» заметку как
    карточку: [{id, title, summary, item_type, weight, created_at}].
    `include_all=True` снимает лимит («Посмотреть все связи»).
    """
    # cap — фиксированная строка (не пользовательский ввод) → без инъекции.
    cap = "" if include_all else "LIMIT :limit"
    query = text(f"""
        SELECT
            b.id, b.title, b.summary, b.item_type, b.created_at,
            l.weight
        FROM bookmark_links l
        JOIN bookmarks b
          ON b.id = CASE WHEN l.from_id = :bid THEN l.to_id ELSE l.from_id END
        WHERE l.user_id = :user_id
          AND (l.from_id = :bid OR l.to_id = :bid)
          AND l.kind = 'similar'
          AND b.is_archived = false
        ORDER BY l.weight DESC
        {cap}
    """)
    params: dict = {"bid": str(bookmark_id), "user_id": str(user_id)}
    if not include_all:
        params["limit"] = limit
    result = await session.execute(query, params)
    return [
        {
            "id": str(r.id),
            "title": r.title,
            "summary": r.summary,
            "item_type": r.item_type,
            "weight": float(r.weight),
            "created_at": r.created_at,
        }
        for r in result.fetchall()
    ]


async def count_related(
    session: AsyncSession, bookmark_id: UUID, user_id: UUID
) -> int:
    """Число связей заметки — для кнопки «🔗 Похожие (N)» в боте (показ только при N>0)."""
    # JOIN + is_archived=false как в get_related: иначе кнопка «Похожие (N)»
    # считала бы и связи на архивные заметки, которых в списке нет (фантомный N).
    query = text("""
        SELECT COUNT(*) AS n
        FROM bookmark_links l
        JOIN bookmarks b
          ON b.id = CASE WHEN l.from_id = :bid THEN l.to_id ELSE l.from_id END
        WHERE l.user_id = :user_id
          AND (l.from_id = :bid OR l.to_id = :bid)
          AND l.kind = 'similar'
          AND b.is_archived = false
    """)
    result = await session.execute(
        query, {"bid": str(bookmark_id), "user_id": str(user_id)}
    )
    row = result.fetchone()
    return int(row.n) if row else 0


# ── Граф (AD-2/AD-8) ──────────────────────────────────────────────────────
# Тяжёлую раскладку (позиции узлов) считает КЛИЕНТ (react-force-graph) и
# присылает на сохранение — сервер остаётся лёгким, что важно на многих юзерах.

GRAPH_NODE_CAP = 300  # NFR-3: лимит узлов полного графа (выше — кластеризация/позже)


async def _neighbor_edges(session: AsyncSession, user_id: UUID, ids: list[str]) -> list:
    """Рёбра, у которых хотя бы один конец в ids (для BFS эго-графа).

    `IN :ids` с expanding-bindparam (а не `= ANY(:ids)`): asyncpg в text()-режиме
    не принимает python-список как массив, expanding раскрывает его в IN-список.
    """
    if not ids:
        return []
    query = text("""
        SELECT from_id, to_id, weight
        FROM bookmark_links
        WHERE user_id = :user_id
          AND kind = 'similar'
          AND (from_id IN :ids OR to_id IN :ids)
    """).bindparams(bindparam("ids", expanding=True))
    result = await session.execute(query, {"user_id": str(user_id), "ids": ids})
    return result.fetchall()


async def _node_cards(session: AsyncSession, user_id: UUID, ids: list[str]) -> list[dict]:
    """Метаданные узлов (для подписей в графе), скоуп по user_id."""
    if not ids:
        return []
    query = text("""
        SELECT id, title, item_type
        FROM bookmarks
        WHERE user_id = :user_id AND id IN :ids
    """).bindparams(bindparam("ids", expanding=True))
    result = await session.execute(query, {"user_id": str(user_id), "ids": ids})
    return [
        {"id": str(r.id), "title": r.title, "item_type": r.item_type}
        for r in result.fetchall()
    ]


async def ego_graph(
    session: AsyncSession,
    user_id: UUID,
    center: UUID,
    *,
    depth: int = 2,
    node_cap: int = 150,
) -> dict:
    """Локальный (эго) граф вокруг заметки: BFS по рёбрам на `depth` шагов.

    Скоуп по user_id (NFR-4), ограничен `node_cap` узлами. Возвращает
    {"nodes": [{id,title,item_type}], "edges": [{from,to,weight}], "center": id}.
    Считается на лету — узлов мало, мгновенно (без кэша).
    """
    center_s = str(center)
    visited: set[str] = {center_s}
    frontier: set[str] = {center_s}
    edges: dict[tuple[str, str], float] = {}

    for _ in range(max(depth, 1)):
        if not frontier or len(visited) >= node_cap:
            break
        rows = await _neighbor_edges(session, user_id, list(frontier))
        next_frontier: set[str] = set()
        for r in rows:
            f, t, w = str(r.from_id), str(r.to_id), float(r.weight)
            edges[(f, t)] = w
            for nid in (f, t):
                if nid not in visited:
                    visited.add(nid)
                    next_frontier.add(nid)
        frontier = next_frontier

    # Центр ВСЕГДА в выборке: list(set)[:cap] недетерминирован и мог бы выкинуть
    # центр → клиент получил бы center без узла (битый рендер графа).
    others = [n for n in visited if n != center_s]
    node_ids = [center_s] + others[: max(node_cap - 1, 0)]
    node_set = set(node_ids)
    kept_edges = [
        {"from": f, "to": t, "weight": w}
        for (f, t), w in edges.items()
        if f in node_set and t in node_set
    ]
    nodes = await _node_cards(session, user_id, node_ids)
    return {"nodes": nodes, "edges": kept_edges, "center": center_s}


async def get_full_graph(
    session: AsyncSession, user_id: UUID, *, node_cap: int = GRAPH_NODE_CAP
) -> dict:
    """Полный граф пользователя: узлы (заметки с эмбеддингом) + все рёбра.

    Ограничен node_cap (NFR-3). Координаты НЕ считает — это делает клиент
    (см. save_graph_layout). Возвращает {"nodes": [...], "edges": [...]}.
    """
    node_rows = (await session.execute(
        text("""
            SELECT id, title, item_type
            FROM bookmarks
            WHERE user_id = :user_id
              AND embedding IS NOT NULL
              AND is_archived = false
            ORDER BY created_at DESC
            LIMIT :cap
        """),
        {"user_id": str(user_id), "cap": node_cap},
    )).fetchall()
    nodes = [
        {"id": str(r.id), "title": r.title, "item_type": r.item_type}
        for r in node_rows
    ]
    node_set = {n["id"] for n in nodes}

    edge_rows = (await session.execute(
        text("""
            SELECT from_id, to_id, weight
            FROM bookmark_links
            WHERE user_id = :user_id AND kind = 'similar'
        """),
        {"user_id": str(user_id)},
    )).fetchall()
    edges = [
        {"from": str(r.from_id), "to": str(r.to_id), "weight": float(r.weight)}
        for r in edge_rows
        if str(r.from_id) in node_set and str(r.to_id) in node_set
    ]
    return {"nodes": nodes, "edges": edges}


async def current_graph_node_count(session: AsyncSession, user_id: UUID) -> int:
    """Текущее число узлов графа (заметок с эмбеддингом) — для флага stale."""
    result = await session.execute(
        text("""
            SELECT COUNT(*) AS n
            FROM bookmarks
            WHERE user_id = :user_id
              AND embedding IS NOT NULL
              AND is_archived = false
        """),
        {"user_id": str(user_id)},
    )
    row = result.fetchone()
    return int(row.n) if row else 0


async def get_graph_layout(session: AsyncSession, user_id: UUID) -> dict | None:
    """Закэшированная раскладка полного графа или None, если ещё не строилась."""
    result = await session.execute(
        text("""
            SELECT nodes, node_count, built_at
            FROM graph_layouts
            WHERE user_id = :user_id
        """),
        {"user_id": str(user_id)},
    )
    row = result.fetchone()
    if row is None:
        return None
    return {
        "nodes": row.nodes,
        "node_count": int(row.node_count),
        "built_at": row.built_at,
    }


async def save_graph_layout(
    session: AsyncSession, user_id: UUID, nodes: list, node_count: int
) -> None:
    """Сохраняет/обновляет раскладку (координаты узлов с клиента) — кэш по кнопке."""
    import json

    await session.execute(
        text("""
            INSERT INTO graph_layouts (user_id, nodes, node_count, built_at)
            VALUES (:user_id, CAST(:nodes AS jsonb), :node_count, now())
            ON CONFLICT (user_id) DO UPDATE
              SET nodes = EXCLUDED.nodes,
                  node_count = EXCLUDED.node_count,
                  built_at = now()
        """),
        {
            "user_id": str(user_id),
            "nodes": json.dumps(nodes),
            "node_count": node_count,
        },
    )
    await session.commit()
