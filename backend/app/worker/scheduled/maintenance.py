"""Worker maintenance & one-shot jobs (worker split — djtn).

Nightly retries (``retry_failed_task`` / ``retry_partial_embeddings``) and the
manual one-shot backfill/reembed jobs (Phase 5A + Notes-as-Conversations).
``async_session`` and models are imported per-function (kept verbatim).
"""

from __future__ import annotations

import logging

from sqlalchemy import select

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


async def retry_failed_task(ctx: dict) -> None:
    """Cron: ночной retry для failed закладок."""
    from app.database import async_session
    from app.models import Bookmark

    async with async_session() as session:
        result = await session.execute(
            select(Bookmark.id).where(
                Bookmark.ai_status == "failed",
                Bookmark.retry_count < 3,
            )
        )
        bookmark_ids = [str(row[0]) for row in result.fetchall()]

    if not bookmark_ids:
        logger.info("No failed bookmarks to retry")
        return

    logger.info(f"Retrying {len(bookmark_ids)} failed bookmarks")
    for bid in bookmark_ids:
        await ctx["redis"].enqueue_job("process_bookmark_task", bid)


async def backfill_bookmark_links(ctx: dict | None = None, *, batch_size: int = 200) -> int:
    """One-shot джоба: строит смысловые связи для всех заметок с эмбеддингом (Phase 5A).

    Идёт по СУЩЕСТВУЮЩИМ эмбеддингам — 0 вызовов LLM и 0 запросов к Voyage,
    батчами (keyset по id), идемпотентно (ON CONFLICT DO NOTHING в
    build_links_for_bookmark). Возвращает число обработанных заметок.

    Запуск (один раз, пользователем): enqueue_job("backfill_bookmark_links").

    ВАЖНО (консистентность пространства): если существующие заметки
    пересчитывались под новый рецепт эмбеддинга (AD-7 — реальный текст + ИИ),
    запускать ПОСЛЕ пересчёта, иначе связи строятся в смешанном пространстве
    (старый рецепт ↔ новый). Пересчёт существующих — отдельный шаг (E1,
    требует бюджета Voyage); новые/переобработанные заметки уже на новом рецепте.
    """
    from app.database import async_session
    from app.models import Bookmark
    from app.services.connections import build_links_for_bookmark

    processed = 0
    failed = 0
    last_id = None
    async with async_session() as session:
        while True:
            stmt = (
                select(Bookmark.id, Bookmark.user_id, Bookmark.embedding)
                .where(
                    Bookmark.ai_status.in_(("completed", "partial")),
                    Bookmark.embedding.isnot(None),
                )
                .order_by(Bookmark.id)
                .limit(batch_size)
            )
            if last_id is not None:
                stmt = stmt.where(Bookmark.id > last_id)

            rows = (await session.execute(stmt)).fetchall()
            if not rows:
                break

            for row in rows:
                emb = row.embedding
                emb_list = emb.tolist() if hasattr(emb, "tolist") else list(emb)
                try:
                    await build_links_for_bookmark(
                        session, row.id, row.user_id, emb_list,
                    )
                except Exception as e:  # noqa: BLE001 — не валим весь бэкфилл
                    # one-shot, запускается оператором руками — сбои должны быть
                    # видны (warning), а не теряться в debug.
                    failed += 1
                    logger.warning(f"backfill: link build failed for {row.id}: {e}")
                processed += 1
                last_id = row.id

            await session.commit()

    logger.info(
        f"backfill_bookmark_links: processed {processed} bookmark(s), {failed} failed"
    )
    return processed


async def reembed_all_bookmarks(ctx: dict | None = None, *, batch_size: int = 100) -> int:
    """One-shot джоба: пере-эмбеддит ВСЕ заметки новым рецептом (AD-7).

    Нужна после смены рецепта эмбеддинга (реальный текст + ИИ-поля). Старые
    заметки эмбеддились по старому рецепту (только ИИ-выжимка) — связи/дедуп для
    них считались бы в СТАРОМ пространстве, ровно от которого мы уходили. Прогон
    делает пространство единым. 0 вызовов LLM (только Voyage-эмбеддинги).

    Запуск вручную на деплое: enqueue_job("reembed_all_bookmarks"), ПЕРЕД
    backfill_bookmark_links (сначала единый рецепт, потом по нему строим связи).

    Идёт батчами (keyset по id), best-effort на элемент. Возвращает число
    успешно переэмбедженных заметок.
    """
    from types import SimpleNamespace

    from app.database import async_session
    from app.models import Bookmark
    from app.services.bookmark_processor import _build_embedding_text
    from app.services.embeddings import (
        EmbeddingError,
        RetryableEmbeddingError,
        create_embedding_service,
    )

    embedding_service = create_embedding_service(
        provider=settings.EMBEDDING_PROVIDER,
        auth_key=settings.GIGACHAT_AUTH_KEY,
        api_key=settings.VOYAGE_API_KEY,
        ca_bundle=settings.GIGACHAT_CA_BUNDLE,
    )
    processed = 0
    last_id = None
    try:
        while True:
            async with async_session() as session:
                stmt = (
                    select(Bookmark)
                    .where(Bookmark.ai_status.in_(("completed", "partial")))
                    .order_by(Bookmark.id)
                    .limit(batch_size)
                )
                if last_id is not None:
                    stmt = stmt.where(Bookmark.id > last_id)

                bookmarks = (await session.execute(stmt)).scalars().all()
                if not bookmarks:
                    break

                for bm in bookmarks:
                    last_id = bm.id
                    # Теги lazy-не-загружены → None; основной сигнал в реальном тексте.
                    clf = SimpleNamespace(
                        takeaway=bm.takeaway,
                        summary=bm.summary,
                        key_ideas=bm.key_ideas,
                        tags=None,
                    )
                    try:
                        emb = await embedding_service.get_embedding(
                            _build_embedding_text(bm, clf)
                        )
                        bm.embedding = emb
                        processed += 1
                    except (EmbeddingError, RetryableEmbeddingError) as e:
                        logger.warning(f"reembed: failed for {bm.id}: {e}")

                await session.commit()
    finally:
        await embedding_service.close()

    logger.info(f"reembed_all_bookmarks: re-embedded {processed} bookmark(s)")
    return processed


async def reembed_bookmark_task(ctx: dict | None = None, bookmark_id: str = "") -> bool:
    """Classify-free пере-индексация ОДНОЙ заметки под её лог дописок (Notes as Conversations).

    Дёргается с debounce (arq _job_id) при изменении note_entries. Пересобирает
    embedding из raw_text + неудалённых дописок, обновляет bookmarks.entries_text
    (денорм под FTS-триггер), пересчитывает связи. НЕ трогает ai_status/classify/
    summary/title — Brain молчит, речь только про индекс (FR-5/NFR-1). 0 вызовов LLM.
    """
    from types import SimpleNamespace
    from uuid import UUID

    from app.database import async_session
    from app.models import Bookmark, NoteEntry
    from app.services.bookmark_processor import _build_embedding_text
    from app.services.connections import build_links_for_bookmark
    from app.services.embeddings import (
        EmbeddingError,
        RetryableEmbeddingError,
        create_embedding_service,
    )

    bid = UUID(bookmark_id)
    embedding_service = create_embedding_service(
        provider=settings.EMBEDDING_PROVIDER,
        auth_key=settings.GIGACHAT_AUTH_KEY,
        api_key=settings.VOYAGE_API_KEY,
        ca_bundle=settings.GIGACHAT_CA_BUNDLE,
    )
    try:
        async with async_session() as session:
            bm = await session.get(Bookmark, bid)
            if bm is None:
                return False

            bodies = (
                await session.execute(
                    select(NoteEntry.body)
                    .where(
                        NoteEntry.bookmark_id == bid,
                        NoteEntry.is_deleted.is_(False),
                    )
                    .order_by(NoteEntry.created_at)
                )
            ).scalars().all()

            # Денорм под FTS-триггер: он видит только колонки строки bookmarks, а не
            # таблицу note_entries. Обновление entries_text пересоберёт search_vector
            # (триггер расширен миграцией e4f5a6b7c8d9 на UPDATE OF entries_text).
            bm.entries_text = "\n".join(b for b in bodies if b) or None

            clf = SimpleNamespace(
                takeaway=bm.takeaway, summary=bm.summary,
                key_ideas=bm.key_ideas, tags=None,
            )
            emb = None
            try:
                emb = await embedding_service.get_embedding(
                    _build_embedding_text(bm, clf, list(bodies))
                )
                bm.embedding = emb
            except (EmbeddingError, RetryableEmbeddingError) as e:
                logger.warning(f"reembed_bookmark: embed failed for {bid}: {e}")

            await session.flush()
            if emb is not None:
                await build_links_for_bookmark(session, bid, bm.user_id, emb)
            await session.commit()
        return True
    finally:
        await embedding_service.close()


async def retry_partial_embeddings(ctx: dict) -> None:
    """Cron: retry embedding for partial bookmarks (classification OK, embedding failed).

    Runs daily at 5:00 AM (after retry_failed at 3:00 AM).
    Max 5 retries per bookmark, circuit breaker after 5 consecutive failures.
    """
    from datetime import datetime, timezone

    from app.database import async_session
    from app.models import Bookmark
    from app.services.embeddings import (
        EmbeddingError,
        RetryableEmbeddingError,
        create_embedding_service,
    )

    MAX_EMBEDDING_RETRIES = 5
    CIRCUIT_BREAKER_THRESHOLD = 5

    embedding_service = create_embedding_service(
        provider=settings.EMBEDDING_PROVIDER,
        auth_key=settings.GIGACHAT_AUTH_KEY,
        api_key=settings.VOYAGE_API_KEY,
        ca_bundle=settings.GIGACHAT_CA_BUNDLE,
    )

    async with async_session() as session:
        result = await session.execute(
            select(Bookmark).where(
                Bookmark.ai_status == "partial",
                Bookmark.embedding_retry_count < MAX_EMBEDDING_RETRIES,
            )
        )
        bookmarks = result.scalars().all()

    if not bookmarks:
        logger.info("No partial bookmarks to retry embeddings")
        await embedding_service.close()
        return

    logger.info(f"Retrying embeddings for {len(bookmarks)} partial bookmarks")
    consecutive_failures = 0

    for bookmark in bookmarks:
        if consecutive_failures >= CIRCUIT_BREAKER_THRESHOLD:
            logger.warning("Circuit breaker tripped — stopping embedding retries")
            break

        try:

            # Единый рецепт эмбеддинга (AD-7): реальный текст заметки + ИИ-поля.
            # Иначе ретрай создавал бы эмбеддинги в СТАРОМ пространстве (только
            # ИИ-поля), несовместимом с новыми/переобработанными заметками →
            # смешанное пространство и кривые связи/дедуп. Теги lazy-не-загружены.
            from types import SimpleNamespace

            from app.services.bookmark_processor import _build_embedding_text

            _clf = SimpleNamespace(
                takeaway=bookmark.takeaway,
                summary=bookmark.summary,
                key_ideas=bookmark.key_ideas,
                tags=None,
            )
            embedding_text = _build_embedding_text(bookmark, _clf)
            embedding = await embedding_service.get_embedding(embedding_text)

            async with async_session() as session:
                result = await session.execute(
                    select(Bookmark).where(Bookmark.id == bookmark.id)
                )
                bm = result.scalar_one()
                bm.embedding = embedding
                bm.ai_status = "completed"
                bm.ai_error = None
                bm.embedding_last_attempt = datetime.now(timezone.utc)
                await session.commit()

            consecutive_failures = 0
            logger.info(f"Embedding retry succeeded for {bookmark.id}")

        except (EmbeddingError, RetryableEmbeddingError) as e:
            consecutive_failures += 1
            async with async_session() as session:
                result = await session.execute(
                    select(Bookmark).where(Bookmark.id == bookmark.id)
                )
                bm = result.scalar_one()
                bm.embedding_retry_count += 1
                bm.embedding_last_attempt = datetime.now(timezone.utc)
                if bm.embedding_retry_count >= MAX_EMBEDDING_RETRIES:
                    bm.ai_status = "completed_no_embedding"
                    bm.ai_error = f"Permanent: embedding failed after {MAX_EMBEDDING_RETRIES} retries"
                    logger.warning(f"Bookmark {bookmark.id} marked completed_no_embedding")
                await session.commit()

            logger.warning(f"Embedding retry failed for {bookmark.id}: {e}")

        except Exception as e:
            consecutive_failures += 1
            logger.error(f"Unexpected error retrying embedding for {bookmark.id}: {e}")

    await embedding_service.close()
