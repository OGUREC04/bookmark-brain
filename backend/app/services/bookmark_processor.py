import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Bookmark, Tag, BookmarkTag, User
from app.services.ai_classifier import BaseClassifier, ClassificationError, RetryableError
from app.services.article_fetcher import fetch_article
from app.services.embeddings import BaseEmbeddingService, EmbeddingError, RetryableEmbeddingError
from app.services.reminder_intent import detect_reminder_intent
from app.services.reminder_router import ReminderForm, route as route_reminder
from app.services.task_list_detector import build_structured_data, detect as detect_task_list

logger = logging.getLogger(__name__)

MAX_RETRIES = 3


def _build_embedding_text(bookmark: Bookmark, classification) -> str:
    """Собирает текст для embedding из самых ёмких полей.

    Это важно для семантического поиска: title+takeaway+key_ideas дают
    гораздо более чистый эмбеддинг, чем сырой текст статьи.
    """
    parts: list[str] = []
    if bookmark.title:
        parts.append(bookmark.title)
    if classification.takeaway:
        parts.append(classification.takeaway)
    if classification.summary:
        parts.append(classification.summary)
    if classification.key_ideas:
        parts.extend(classification.key_ideas)
    if classification.tags:
        parts.append(" ".join(classification.tags))
    # Fallback если AI почему-то ничего не дал
    if not parts:
        parts.append(bookmark.raw_text[:2000])
    return "\n".join(parts)


class BookmarkProcessor:
    def __init__(
        self,
        session: AsyncSession,
        classifier: BaseClassifier,
        embedding_service: BaseEmbeddingService,
    ):
        self.session = session
        self.classifier = classifier
        self.embedding_service = embedding_service

    async def process_bookmark(self, bookmark_id: UUID, progress_callback=None) -> None:
        # Загружаем закладку
        result = await self.session.execute(
            select(Bookmark).where(Bookmark.id == bookmark_id)
        )
        bookmark = result.scalar_one_or_none()

        if bookmark is None:
            logger.warning(f"Bookmark {bookmark_id} not found, skipping")
            return

        if bookmark.ai_status not in ("pending", "failed"):
            logger.info(f"Bookmark {bookmark_id} status={bookmark.ai_status}, skipping")
            return

        is_first_processing = bookmark.ai_processed_at is None

        if bookmark.retry_count >= MAX_RETRIES:
            logger.warning(f"Bookmark {bookmark_id} exceeded max retries, skipping")
            return

        # Ставим статус processing
        bookmark.ai_status = "processing"
        await self.session.flush()

        # Шаг 0: Скачиваем и парсим статью (если есть URL)
        # trafilatura вытаскивает title+полный_текст+lang,
        # это даёт качественно лучший вход для AI vs только <title>+raw_text.
        if progress_callback:
            await progress_callback("🔗 Загружаю статью...")
        text_for_ai = bookmark.raw_text
        if bookmark.url:
            article = await fetch_article(bookmark.url)
            if article.text:
                bookmark.full_text = article.text
                # Если forward не содержал осмысленного текста — используем
                # извлечённый текст статьи; иначе объединяем.
                # Эвристика: raw_text короткий (< 200 симв) = скорее всего просто ссылка
                if len(bookmark.raw_text) < 200:
                    text_for_ai = article.text
                else:
                    text_for_ai = f"{bookmark.raw_text}\n\n---\n\n{article.text}"
            if article.title and not bookmark.title:
                bookmark.title = article.title
            await self.session.flush()

        # Шаг 1: AI-классификация (глубокий анализ)
        if progress_callback:
            await progress_callback("🤖 AI анализирует текст...")
        try:
            classification = await self.classifier.classify(text_for_ai, bookmark.url)
            # Классические поля
            bookmark.summary = classification.summary
            bookmark.category = classification.category
            bookmark.language = classification.language
            # Phase 1b — интент
            bookmark.item_type = classification.item_type
            # Phase 1c — глубокий анализ
            bookmark.takeaway = classification.takeaway or None
            bookmark.key_ideas = classification.key_ideas or None
            bookmark.entities = classification.entities or None
            bookmark.open_questions = classification.open_questions or None
            # Если title всё ещё пустой — берём takeaway или summary
            if not bookmark.title:
                bookmark.title = (
                    classification.takeaway
                    or classification.summary
                    or bookmark.raw_text[:100]
                )[:100]
        except RetryableError as e:
            logger.warning(f"Retryable classifier error for {bookmark_id}: {e}")
            bookmark.ai_status = "failed"
            bookmark.ai_error = str(e)
            bookmark.retry_count += 1
            await self.session.flush()
            raise  # arq перепоставит в очередь
        except ClassificationError as e:
            logger.error(f"Classification failed for {bookmark_id}: {e}")
            bookmark.ai_status = "failed"
            bookmark.ai_error = str(e)
            bookmark.retry_count += 1
            await self.session.flush()
            # Не выходим сразу — попробуем хотя бы task_list-детекцию по raw_text.
            # GigaChat иногда отказывает на нецензурном контенте; детектор по
            # маркерам и пунктам всё равно может распознать список задач.
            classification = None  # type: ignore[assignment]
            try:
                detection = detect_task_list(bookmark.raw_text, ai_item_type=None)
                structured = build_structured_data(detection)
                if structured is not None:
                    bookmark.structured_data = structured
                    # Минимальные поля для рендера task_list
                    if not bookmark.title:
                        bookmark.title = "Список задач"
                    bookmark.item_type = "action"
                    bookmark.ai_status = "partial"  # классификация упала, но список спасли
                    bookmark.ai_error = (bookmark.ai_error or "") + " | task_list rescued via detector"
                    await self.session.flush()
            except Exception as det_err:
                logger.debug(f"Fallback task_list detection failed for {bookmark_id}: {det_err}")
            return

        # Шаг 1.5: Детекция task_list (Phase 2)
        # Работаем по raw_text (то что юзер сам напечатал), а не по article.text —
        # списки задач живут в юзер-контенте, не в скачанных статьях.
        # Детектор НЕ трогает обычные заметки и никогда не бросает исключений.
        try:
            detection = detect_task_list(
                bookmark.raw_text,
                ai_item_type=classification.item_type,
            )
            structured = build_structured_data(detection)
            if structured is not None:
                # Прогоняем через NL-редактор для извлечения дат из текста пунктов
                # ("до вторника", "сегодня-завтра" → deadline поле)
                try:
                    from datetime import date as _date
                    from app.services.task_list_editor import apply_nl_edit
                    _today = _date.today().isoformat()
                    structured = await apply_nl_edit(
                        structured,
                        f"Сегодня {_today}. "
                        "Для каждого пункта: если в тексте есть дата или срок "
                        "(«до вторника», «сегодня-завтра», «на этой неделе» и т.п.) — "
                        "1) поставь deadline в формате YYYY-MM-DD, "
                        "2) ПОЛНОСТЬЮ УДАЛИ упоминание даты/срока из text. "
                        "НЕ заменяй дату на ISO-формат в тексте — просто убери. "
                        "Примеры: «Алгосы до вторника» → text=«Алгосы», deadline=«2026-05-06». "
                        "«Узнать про возврат, сегодня-завтра» → text=«Узнать про возврат», deadline=завтра. "
                        "Если даты нет — не трогай пункт.",
                    )
                except Exception as e:
                    logger.debug(f"Deadline extraction failed for {bookmark_id}: {e}")
                bookmark.structured_data = structured
                # Если юзер явно попросил список — форсим item_type=action,
                # даже если AI сказал что-то другое.
                if detection.forced_by_user:
                    bookmark.item_type = "action"
                logger.info(
                    f"Bookmark {bookmark_id} detected as task_list "
                    f"({len(detection.tasks)} tasks, forced={detection.forced_by_user})"
                )
        except Exception as e:
            # Никогда не валим процессинг из-за детектора
            logger.warning(f"task_list detector failed for {bookmark_id}: {e}")

        # Шаг 2: Embedding (из ёмких полей — title + takeaway + key_ideas + summary)
        # Это качественно лучше чем сырой текст: убран шум, остались только смыслы.
        if progress_callback:
            await progress_callback("📊 Создаю embedding...")
        try:
            text_for_embedding = _build_embedding_text(bookmark, classification)
            embedding = await self.embedding_service.get_embedding(text_for_embedding)
            bookmark.embedding = embedding
        except (EmbeddingError, RetryableEmbeddingError) as e:
            logger.warning(f"Embedding failed for {bookmark_id}: {e}")
            # Классификация прошла, но embedding нет — partial
            bookmark.ai_status = "partial"
            bookmark.ai_error = f"Embedding failed: {e}"
            bookmark.ai_processed_at = datetime.now(timezone.utc)
            await self._create_tags(bookmark, classification.tags)
            await self.session.flush()
            return

        # Шаг 3: Создаём теги
        if progress_callback:
            await progress_callback("🏷 Сохраняю теги...")
        await self._create_tags(bookmark, classification.tags)

        # Всё ок
        bookmark.ai_status = "completed"
        bookmark.ai_error = None
        bookmark.ai_processed_at = datetime.now(timezone.utc)

        # Phase 2.5: Reminder intent detection.
        # Запускаем после успешной классификации — анализируем raw_text + summary.
        # Флаг всегда переписывается (включая False), чтобы при reprocess'e
        # старое значение не залипало.
        intent_text = " ".join(filter(None, [bookmark.raw_text, bookmark.summary]))
        intent = detect_reminder_intent(intent_text)
        # ВАЖНО: dict(...) делает копию — иначе SQLAlchemy не видит мутацию
        # JSONB по тому же id объекта (см. ниже Phase 2.6 фикс).
        structured = dict(bookmark.structured_data or {})
        structured["reminder_intent"] = intent.has_intent
        bookmark.structured_data = structured
        if intent.has_intent:
            logger.info(f"Reminder intent detected for bookmark {bookmark_id}")

        # Phase 2.6: Save-flow router.
        # Если AI вернул reminder_items — резолвим даты через nl_date.parse и
        # принимаем финальное решение про reminder_form. Хендлеры T4-T8 читают
        # `structured_data.reminder_decision` чтобы среагировать соответствующим
        # образом (3-button UI / per-item create / composite / strong-flow).
        # Best-effort: любая ошибка не валит классификацию.
        try:
            # Загружаем timezone юзера. По умолчанию Europe/Moscow если null
            # (например, у legacy юзеров до миграции).
            user_result = await self.session.execute(
                select(User.timezone).where(User.id == bookmark.user_id)
            )
            user_tz = user_result.scalar_one_or_none() or "Europe/Moscow"

            decision = route_reminder(
                text=bookmark.raw_text or "",
                classification=classification,
                user_tz=user_tz,
            )
            if decision.form != ReminderForm.NONE:
                # Мерджим в structured_data, не перезатирая task_list если он есть.
                # `dict(...)` создаёт КОПИЮ — присваивание new-dict-object меняет
                # identity, SQLAlchemy помечает поле dirty и flush'ит JSONB.
                # Без копии: structured = bookmark.structured_data возвращает ту же
                # ссылку, мутация in-place ORM не замечает (тест-баг 2026-05-15).
                structured = dict(bookmark.structured_data or {})
                structured["reminder_decision"] = decision.to_dict()
                bookmark.structured_data = structured
                logger.info(
                    f"Reminder router for {bookmark_id}: form={decision.form.value}, "
                    f"dated_items={len(decision.dated_items)}, "
                    f"needs_hour={len(decision.needs_hour_items)}, "
                    f"strong={decision.strong_intent}, explicit={decision.explicit_trigger}"
                )
        except Exception as e:
            logger.warning(f"Reminder router failed for {bookmark_id}: {e}")

        await self.session.flush()

        # Обновляем счётчик юзера (только при первом процессинге, не при reprocess)
        if is_first_processing:
            await self.session.execute(
                update(User)
                .where(User.id == bookmark.user_id)
                .values(bookmarks_count=func.coalesce(User.bookmarks_count, 0) + 1)
            )
            await self.session.flush()

        logger.info(f"Bookmark {bookmark_id} processed successfully")

    async def _create_tags(self, bookmark: Bookmark, tag_names: list[str]) -> None:
        """Создаёт теги (batch upsert) и связывает с закладкой."""
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        # Normalize tag names
        clean_names = list({n.strip().lower()[:100] for n in tag_names if n.strip()})
        if not clean_names:
            return

        # Batch upsert tags — one query instead of N
        tag_values = [{"user_id": bookmark.user_id, "name": n} for n in clean_names]
        stmt = (
            pg_insert(Tag)
            .values(tag_values)
            .on_conflict_do_nothing(index_elements=["user_id", "name"])
            .returning(Tag.id, Tag.name)
        )
        result = await self.session.execute(stmt)
        inserted = {row.name: row.id for row in result.fetchall()}

        # Fetch any that already existed (not returned by ON CONFLICT DO NOTHING)
        missing = [n for n in clean_names if n not in inserted]
        if missing:
            existing_result = await self.session.execute(
                select(Tag.id, Tag.name).where(
                    Tag.user_id == bookmark.user_id,
                    Tag.name.in_(missing),
                )
            )
            for row in existing_result.fetchall():
                inserted[row.name] = row.id

        # Batch insert bookmark-tag links
        link_values = [
            {"bookmark_id": bookmark.id, "tag_id": tag_id}
            for tag_id in inserted.values()
        ]
        if link_values:
            link_stmt = (
                pg_insert(BookmarkTag)
                .values(link_values)
                .on_conflict_do_nothing()
            )
            await self.session.execute(link_stmt)

        await self.session.flush()
