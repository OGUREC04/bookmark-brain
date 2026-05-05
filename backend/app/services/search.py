import logging
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Bookmark
from app.services.embeddings import BaseEmbeddingService

logger = logging.getLogger(__name__)


class SearchService:
    def __init__(self, session: AsyncSession, embedding_service: BaseEmbeddingService):
        self.session = session
        self.embedding_service = embedding_service

    async def search(
        self,
        user_id: UUID,
        query: str,
        limit: int = 20,
        offset: int = 0,
        category: str | None = None,
        tags: list[str] | None = None,
    ) -> tuple[list[tuple[Bookmark, float]], int]:
        """Гибридный поиск: semantic (pgvector) + full-text (tsvector).

        Возвращает (список (bookmark, score), total_count).
        """
        # Определяем вес: короткие запросы → больше full-text,
        # длинные → больше semantic
        word_count = len(query.split())
        if word_count <= 2:
            semantic_weight, text_weight = 0.5, 0.5
        else:
            semantic_weight, text_weight = 0.7, 0.3

        # Получаем embedding запроса (с fallback)
        query_embedding = None
        try:
            query_embedding = await self.embedding_service.get_embedding(query)
        except Exception as e:
            logger.warning(f"Embedding failed, falling back to full-text: {e}")

        use_semantic = query_embedding is not None
        embedding_literal = ""
        if use_semantic:
            embedding_literal = "[" + ",".join(str(v) for v in query_embedding) + "]"
        else:
            # Только full-text
            semantic_weight, text_weight = 0.0, 1.0

        # Строим WHERE условия
        where_clauses = ["b.user_id = :user_id"]
        params: dict = {"user_id": str(user_id), "lim": limit, "off": offset}

        if category:
            where_clauses.append("b.category = :category")
            params["category"] = category

        # Фильтр по тегам (через JOIN)
        tag_join = ""
        if tags:
            tag_join = """
                INNER JOIN bookmark_tags bt ON bt.bookmark_id = b.id
                INNER JOIN tags t ON t.id = bt.tag_id AND t.name = ANY(:tag_names)
            """
            params["tag_names"] = tags

        where_sql = " AND ".join(where_clauses)

        # Semantic score SQL
        # ВАЖНО: используем CAST(... AS vector) вместо ::vector,
        # потому что SQLAlchemy парсит `::vector` как именованный параметр `:vector`.
        if use_semantic:
            semantic_score_sql = """
                CASE
                    WHEN b.embedding IS NOT NULL
                    THEN 1 - (b.embedding <=> CAST(:query_embedding AS vector))
                    ELSE 0
                END
            """
        else:
            semantic_score_sql = "0"

        # Основной запрос: hybrid score
        sql = f"""
            WITH scored AS (
                SELECT
                    b.id,
                    {semantic_score_sql} AS semantic_score,
                    CASE
                        WHEN b.search_vector IS NOT NULL
                             AND b.search_vector @@ plainto_tsquery('russian', :query)
                        THEN ts_rank(b.search_vector, plainto_tsquery('russian', :query))
                        ELSE 0
                    END AS text_score
                FROM bookmarks b
                {tag_join}
                WHERE {where_sql}
                GROUP BY b.id, b.embedding, b.search_vector
            ),
            ranked AS (
                SELECT
                    id,
                    ({semantic_weight} * semantic_score + {text_weight} * text_score) AS score
                FROM scored
                WHERE semantic_score > 0 OR text_score > 0
            )
            SELECT id, score
            FROM ranked
            ORDER BY score DESC
            LIMIT :lim OFFSET :off
        """

        count_sql = f"""
            WITH scored AS (
                SELECT
                    b.id,
                    {semantic_score_sql} AS semantic_score,
                    CASE
                        WHEN b.search_vector IS NOT NULL
                             AND b.search_vector @@ plainto_tsquery('russian', :query)
                        THEN ts_rank(b.search_vector, plainto_tsquery('russian', :query))
                        ELSE 0
                    END AS text_score
                FROM bookmarks b
                {tag_join}
                WHERE {where_sql}
                GROUP BY b.id, b.embedding, b.search_vector
            )
            SELECT COUNT(*) FROM scored
            WHERE semantic_score > 0 OR text_score > 0
        """

        params["query"] = query
        if use_semantic:
            params["query_embedding"] = embedding_literal

        # Выполняем оба запроса
        result = await self.session.execute(text(sql), params)
        rows = result.fetchall()

        count_result = await self.session.execute(text(count_sql), params)
        total = count_result.scalar() or 0

        # Fallback: если ничего не найдено — пробуем ILIKE по raw_text/title/url
        if not rows:
            fallback_sql = f"""
                SELECT b.id, 0.1 AS score
                FROM bookmarks b
                {tag_join}
                WHERE {where_sql}
                  AND (
                    b.raw_text ILIKE :like_query ESCAPE '\\'
                    OR b.title ILIKE :like_query ESCAPE '\\'
                    OR b.url ILIKE :like_query ESCAPE '\\'
                  )
                ORDER BY b.created_at DESC
                LIMIT :lim OFFSET :off
            """
            # Escape LIKE wildcards to prevent injection
            escaped_query = (
                query.replace("\\", "\\\\")
                .replace("%", "\\%")
                .replace("_", "\\_")
            )
            params["like_query"] = f"%{escaped_query}%"
            result = await self.session.execute(text(fallback_sql), params)
            rows = result.fetchall()

            if rows:
                fallback_count_sql = f"""
                    SELECT COUNT(*)
                    FROM bookmarks b
                    {tag_join}
                    WHERE {where_sql}
                      AND (
                        b.raw_text ILIKE :like_query ESCAPE '\\'
                        OR b.title ILIKE :like_query ESCAPE '\\'
                        OR b.url ILIKE :like_query ESCAPE '\\'
                      )
                """
                count_result = await self.session.execute(text(fallback_count_sql), params)
                total = count_result.scalar() or 0

        if not rows:
            return [], 0

        # Загружаем полные объекты Bookmark
        bookmark_ids = [row[0] for row in rows]
        scores_map = {row[0]: row[1] for row in rows}

        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        stmt = (
            select(Bookmark)
            .options(selectinload(Bookmark.tags))
            .where(Bookmark.id.in_(bookmark_ids))
        )
        bookmarks_result = await self.session.execute(stmt)
        bookmarks = {b.id: b for b in bookmarks_result.scalars().all()}

        # Собираем результат в порядке score
        results = []
        for bid in bookmark_ids:
            if bid in bookmarks:
                results.append((bookmarks[bid], float(scores_map[bid])))

        return results, total
