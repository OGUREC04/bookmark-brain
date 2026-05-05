from datetime import datetime
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
    # Для live-прогресса в Telegram
    notify_chat_id: int | None = None
    notify_message_id: int | None = None
    # Silent mode: реакции вместо текстовых сообщений
    silent: bool = False


class BookmarkUpdate(BaseModel):
    title: str | None = None
    is_favorite: bool | None = None
    is_archived: bool | None = None
    folder_id: UUID | None = None
    # Phase 2: можно передать dict для замены structured_data целиком,
    # либо явный None чтобы стереть (например кнопка "не список").
    # Используем Sentinel-подход через `exclude_unset` в endpoint.
    structured_data: dict | None = None


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
