from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# ──────────────────── Auth ────────────────────


class TelegramAuthData(BaseModel):
    init_data: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ──────────────────── User ────────────────────


class UserCreate(BaseModel):
    telegram_id: int
    telegram_username: str | None = None
    telegram_first_name: str | None = None


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    telegram_id: int
    telegram_username: str | None
    telegram_first_name: str | None
    bookmarks_count: int
    created_at: datetime
    timezone: str = "Europe/Moscow"  # IANA timezone, default MSK
    settings: dict | None = None  # silent_mode, onboarding_*, language, …


class TimezoneUpdate(BaseModel):
    """Тело PATCH /api/v1/users/me/timezone."""

    timezone: str = Field(min_length=1, max_length=64)


# ──────────────────── Tag ────────────────────


class TagCreate(BaseModel):
    name: str
    color: str | None = None


class TagResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    color: str | None
    bookmarks_count: int


# ──────────────────── Folder ────────────────────


class FolderCreate(BaseModel):
    name: str
    emoji: str | None = None


class FolderUpdate(BaseModel):
    name: str | None = None
    emoji: str | None = None


class FolderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    emoji: str | None
    bookmarks_count: int
    created_at: datetime


# ──────────────────── Bookmark ────────────────────


class BookmarkCreate(BaseModel):
    raw_text: str
    url: str | None = None
    title: str | None = None
    source: str = "manual"
    source_message_id: int | None = None
    source_date: datetime | None = None
    content_type: str = "other"
    # Phase 3 — media fields
    media_file_id: str | None = None
    transcription: str | None = None
    media_duration: float | None = None
    # Phase 3B — document metadata
    document_page_count: int | None = None
    # Для live-прогресса в Telegram
    notify_chat_id: int | None = None
    notify_message_id: int | None = None
    # Silent mode: реакции вместо текстовых сообщений
    silent: bool = False
    # Phase 3D: auto-tag #voice for voice messages
    voice_tag: bool = False


class BookmarkUpdate(BaseModel):
    title: str | None = None
    is_favorite: bool | None = None
    is_archived: bool | None = None
    folder_id: UUID | None = None
    # Phase 2: можно передать dict для замены structured_data целиком,
    # либо явный None чтобы стереть (например кнопка "не список").
    # Используем Sentinel-подход через `exclude_unset` в endpoint.
    structured_data: dict | None = None
    # Тикет 0rn: каноничное редактируемое тело текста заметки (для любых типов;
    # для голосовых — тоже raw_text, не transcription). При существенном
    # изменении триггерит фоновую переобработку (embedding + AI-поля).
    # max_length — граница против DoS (огромный body → дорогой LLM-джоб + O(n²) difflib).
    raw_text: str | None = Field(default=None, max_length=50_000)


class BookmarkResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    source: str
    url: str | None
    raw_text: str
    title: str | None
    content_type: str
    media_file_id: str | None = None
    transcription: str | None = None
    media_duration: float | None = None
    document_page_count: int | None = None
    summary: str | None
    category: str | None
    tags: list[TagResponse] = []
    folder_id: UUID | None = None
    ai_status: str
    is_favorite: bool
    is_archived: bool
    created_at: datetime
    updated_at: datetime

    # Phase 1 — deep processing
    item_type: str | None = None
    takeaway: str | None = None
    key_ideas: list[str] | None = None
    entities: list[str] | None = None
    open_questions: list[str] | None = None

    # Phase 2 — structured content (task_list / plan / ...)
    structured_data: dict | None = None


class BookmarkListResponse(BaseModel):
    items: list[BookmarkResponse]
    total: int
    page: int
    per_page: int


# ──────────────────── Search ────────────────────


class SearchRequest(BaseModel):
    query: str
    limit: int = Field(default=20, ge=1, le=50)
    offset: int = Field(default=0, ge=0)
    category: str | None = None
    tags: list[str] | None = None
    # Phase 1: попросить LLM сгенерировать саммари по топу результатов.
    # Default True — UI показывает "AI-ответ" над списком, как Google one-box.
    with_summary: bool = True
    # FR-7 (Connections): 'hybrid' (semantic+full-text) | 'semantic' (по смыслу).
    # Literal — невалидный mode отсекается на границе (422), не молча → hybrid.
    mode: Literal["hybrid", "semantic"] = "hybrid"


class SearchResult(BaseModel):
    bookmark: BookmarkResponse
    score: float


class SearchResponse(BaseModel):
    results: list[SearchResult]
    total: int
    query: str
    # AI-саммари по топ-N результатам с маркерами [1]..[N].
    # None если: запрос короткий, результатов нет, LLM упал или with_summary=False.
    summary: str | None = None


# ──────────────────── AI (internal) ────────────────────


class ReminderItem(BaseModel):
    """Один распознанный пункт сообщения для возможного reminder'а (Phase 2.6).

    AI разбивает входной текст на pieces; worker потом прогоняет
    `raw_date_phrase` через `nl_date.parse()` чтобы получить UTC datetime.
    """
    text: str  # текст пункта без даты, пригодный для отображения юзеру
    raw_date_phrase: str | None = None  # «завтра», «в пятницу в 18», None если даты нет


class AIClassification(BaseModel):
    """Результат глубокого AI-анализа закладки (Phase 1).

    Контракт одинаков для всех провайдеров (GigaChat/DeepSeek/Claude) —
    поэтому переключение через AI_PROVIDER ничего не ломает.
    """
    # Классика
    summary: str
    tags: list[str]
    category: str           # article | course | idea | event | tool | video | other
    language: str

    # Phase 1b — интент (зачем сохранил)
    item_type: str = "content"   # action | thought | content | reference

    # Phase 1c — глубокий анализ
    key_ideas: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    takeaway: str = ""

    # Phase 2.6 — Reminders × Task Lists.
    # Все поля опциональны: на короткой/обычной заметке AI вернёт пустой список
    # и single_statement=true, worker применит обычный bookmark-flow.
    # Worker (T3) решает финальный reminder_form по правилам PRD 2.6 —
    # AI отдаёт только сырой разбор, не финальное решение.
    reminder_items: list[ReminderItem] = Field(default_factory=list)
    single_statement: bool = True  # true для одного утверждения/задачи; false для multi-item
    reminder_form_hint: str | None = None  # AI's guess: task_list_with_reminders / single_reminder / composite_reminder / task_list_no_reminders / none


# ──────────────────── Reminders (Phase 2.5) ────────────────────


class ReminderCreate(BaseModel):
    """Тело POST /api/v1/reminders/."""

    bookmark_id: UUID | None = None
    fire_at: datetime  # UTC ожидается
    payload: dict = Field(default_factory=dict)


class ReminderUpdate(BaseModel):
    """Тело PATCH /api/v1/reminders/{id}.

    Snooze: меняем `fire_at` (статус → pending). Правка текста: `text`
    персистится в `payload["text"]`. Хотя бы одно из полей — иначе no-op.
    Можно слать только `text`, только `fire_at`, или оба (тикет 8uu).
    """

    fire_at: datetime | None = None
    text: str | None = None


class ReminderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    bookmark_id: UUID | None
    kind: str  # всегда "reminder" из этого endpoint
    fire_at: datetime
    status: str
    payload: dict
    created_at: datetime
    sent_at: datetime | None = None

    # B1 (2026-05-15): Mini App рендерит title в RemindersSheet — без этих полей
    # пришлось бы делать N+1 запросов к /bookmarks/{id}.
    bookmark_title: str | None = None
    bookmark_raw_text: str | None = None

    # E15: True если вернули существующее напоминание вместо создания дубля
    # (тот же текст + минута). Бот показывает «👌 Уже напомню…» вместо «🔔 Напомню…».
    deduplicated: bool = False


class ReminderListResponse(BaseModel):
    items: list[ReminderResponse]
    total: int
