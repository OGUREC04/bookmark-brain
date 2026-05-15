import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ENUM as PG_ENUM, JSONB, TSVECTOR, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    telegram_id: Mapped[int] = mapped_column(
        BigInteger, unique=True, nullable=False, index=True
    )
    telegram_username: Mapped[str | None] = mapped_column(String(255))
    telegram_first_name: Mapped[str | None] = mapped_column(String(255))
    telegram_photo_url: Mapped[str | None] = mapped_column(Text)

    settings: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    timezone: Mapped[str] = mapped_column(
        String(64), server_default="Europe/Moscow", default="Europe/Moscow", nullable=False
    )
    import_status: Mapped[str] = mapped_column(
        String(20), server_default="none", default="none"
    )
    last_import_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    bookmarks_count: Mapped[int] = mapped_column(Integer, server_default="0", default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_active: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    bookmarks: Mapped[list["Bookmark"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    tags: Mapped[list["Tag"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    folders: Mapped[list["Folder"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Bookmark(Base):
    __tablename__ = "bookmarks"
    __table_args__ = (
        Index("idx_bookmarks_user_created", "user_id", "created_at"),
        Index(
            "idx_bookmarks_ai_pending",
            "ai_status",
            postgresql_where="ai_status != 'completed'",
        ),
        Index(
            "idx_bookmarks_source_dedup",
            "user_id",
            "source",
            "source_message_id",
            unique=True,
            postgresql_where="source_message_id IS NOT NULL",
        ),
        Index(
            "idx_bookmarks_search_vector",
            "search_vector",
            postgresql_using="gin",
        ),
        Index(
            "idx_bookmarks_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        Index("idx_bookmarks_category", "user_id", "category"),
        Index("idx_bookmarks_item_type", "user_id", "item_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    # Source info
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="telegram")
    source_message_id: Mapped[int | None] = mapped_column(BigInteger)
    source_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Content
    url: Mapped[str | None] = mapped_column(Text)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str | None] = mapped_column(String(500))
    content_type: Mapped[str] = mapped_column(
        String(20), default="other", server_default="other"
    )
    media_file_id: Mapped[str | None] = mapped_column(Text)

    # Phase 3 — voice/audio transcription
    transcription: Mapped[str | None] = mapped_column(Text)
    media_duration: Mapped[float | None] = mapped_column(Float)

    # Phase 3B — document metadata (PDF page count etc.)
    document_page_count: Mapped[int | None] = mapped_column(Integer)

    # Full article text (Phase 1a — readability extraction)
    full_text: Mapped[str | None] = mapped_column(Text)

    # AI-generated (classic)
    summary: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(String(30))
    language: Mapped[str | None] = mapped_column(String(10))

    # AI-generated (Phase 1b — intent classification)
    # item_type: action | thought | content | reference
    item_type: Mapped[str | None] = mapped_column(String(20))

    # AI-generated (Phase 1c — deep analysis)
    key_ideas: Mapped[list | None] = mapped_column(JSONB)
    entities: Mapped[list | None] = mapped_column(JSONB)
    open_questions: Mapped[list | None] = mapped_column(JSONB)
    takeaway: Mapped[str | None] = mapped_column(Text)

    # Phase 2 — structured content (task_list / plan / idea / thought / goal)
    # Пример для task_list: {"type":"task_list","tasks":[{"text":"...","done":false,"deadline":null}]}
    # Если None — обычная заметка без структуры.
    structured_data: Mapped[dict | None] = mapped_column(JSONB)

    # Search
    embedding = mapped_column(Vector(1024), nullable=True)
    search_vector = mapped_column(TSVECTOR, nullable=True)

    # Processing state
    ai_status: Mapped[str] = mapped_column(
        String(20), default="pending", server_default="pending"
    )
    ai_error: Mapped[str | None] = mapped_column(Text)
    ai_processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retry_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    embedding_retry_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    embedding_last_attempt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Folder
    folder_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("folders.id", ondelete="SET NULL"), nullable=True
    )

    # User state
    is_favorite: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    is_archived: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    last_accessed: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Relationships
    user: Mapped["User"] = relationship(back_populates="bookmarks")
    folder: Mapped["Folder | None"] = relationship(back_populates="bookmarks")
    tags: Mapped[list["Tag"]] = relationship(
        secondary="bookmark_tags", back_populates="bookmarks"
    )


class Tag(Base):
    __tablename__ = "tags"
    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_tag_user_name"),
        Index("idx_tags_user", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    color: Mapped[str | None] = mapped_column(String(7))
    bookmarks_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    user: Mapped["User"] = relationship(back_populates="tags")
    bookmarks: Mapped[list["Bookmark"]] = relationship(
        secondary="bookmark_tags", back_populates="tags"
    )


class Folder(Base):
    __tablename__ = "folders"
    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_folder_user_name"),
        Index("idx_folders_user", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    emoji: Mapped[str | None] = mapped_column(String(10))
    bookmarks_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    user: Mapped["User"] = relationship(back_populates="folders")
    bookmarks: Mapped[list["Bookmark"]] = relationship(back_populates="folder")


class BookmarkTag(Base):
    __tablename__ = "bookmark_tags"
    __table_args__ = (Index("idx_bookmark_tags_tag", "tag_id"),)

    bookmark_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("bookmarks.id", ondelete="CASCADE"),
        primary_key=True,
    )
    tag_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tags.id", ondelete="CASCADE"),
        primary_key=True,
    )


class ScheduledMessage(Base):
    """Generic scheduler для напоминаний, дайджестов, surfacing.

    Phase 2.5 использует только kind='reminder'.
    Phase 6 расширит kind='digest', 'surfacing'.
    """

    __tablename__ = "scheduled_messages"
    __table_args__ = (
        # Partial index — cron сканирует только pending
        Index(
            "ix_scheduled_messages_pending_fire",
            "fire_at",
            postgresql_where="status = 'pending'",
        ),
        Index("ix_scheduled_messages_user_status", "user_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    bookmark_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("bookmarks.id", ondelete="CASCADE"),
        nullable=True,
    )
    # ENUM в БД — чтобы добавлять kinds в Phase 6 без миграции схемы (только ALTER TYPE).
    # Используем postgresql.ENUM с create_type=False (тип создан миграцией
    # a7b8c9d0e1f2_add_scheduled_messages.py). String(32) ломает INSERT —
    # asyncpg шлёт VARCHAR, Postgres ждёт scheduled_kind/scheduled_status ENUM.
    kind: Mapped[str] = mapped_column(
        PG_ENUM(
            "reminder", "digest", "surfacing", "nudge",
            name="scheduled_kind", create_type=False,
        ),
        nullable=False,
    )
    fire_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    status: Mapped[str] = mapped_column(
        PG_ENUM(
            "pending", "sending", "sent", "done", "cancelled", "failed",
            name="scheduled_status", create_type=False,
        ),
        nullable=False, server_default="pending", default="pending",
    )
    payload: Mapped[dict] = mapped_column(JSONB, server_default="{}", default=dict)
    retry_count: Mapped[int] = mapped_column(Integer, server_default="0", default=0)
    message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # B1 (2026-05-15): Mini App нужен title/preview закладки при list_upcoming.
    # lazy="noload" — не загружать автоматически, только при явном selectinload.
    bookmark: Mapped["Bookmark | None"] = relationship(
        "Bookmark",
        foreign_keys=[bookmark_id],
        lazy="noload",
    )
