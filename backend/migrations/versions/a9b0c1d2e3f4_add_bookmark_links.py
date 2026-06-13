"""add bookmark_links + graph_layouts for Connections MVP (Phase 5A)

bookmark_links: смысловые связи между заметками одного пользователя.
  kind ENUM — в MVP только 'similar' (cosine в weight); 'manual' /
  'derived_from_space' зарезервированы под Phase 6 (Smart Spaces) без миграции
  схемы (ALTER TYPE ADD VALUE). Ребро пишется один раз, читаем обе стороны
  (from_id=X OR to_id=X) — отсюда два индекса по weight DESC.

graph_layouts: кэш раскладки полного графа (on-demand, AD-8). Координаты узлов
  считаются по явному действию и сохраняются; stale определяется по node_count.

Revision ID: a9b0c1d2e3f4
Revises: a8b9c0d1e2f3
Create Date: 2026-06-13 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a9b0c1d2e3f4"
down_revision: Union[str, None] = "a8b9c0d1e2f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


LINK_KIND_VALUES = ("similar", "manual", "derived_from_space")


def upgrade() -> None:
    # Создаём enum-тип явно (как scheduled_kind в a7b8c9d0e1f2) —
    # inline create_type бывает нестабилен с alembic.
    link_kind = postgresql.ENUM(
        *LINK_KIND_VALUES, name="link_kind", create_type=False
    )
    bind = op.get_bind()
    link_kind.create(bind, checkfirst=True)

    op.create_table(
        "bookmark_links",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        # Денормализованный user_id (AD-1): связи всегда внутри одного юзера →
        # WHERE user_id=X одним индексом для related/graph без двойного JOIN.
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "from_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("bookmarks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "to_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("bookmarks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", link_kind, nullable=False),
        sa.Column("weight", sa.Float(), nullable=False),  # cosine для similar
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "from_id", "to_id", "kind", name="uq_bookmark_links_pair_kind"
        ),
        sa.CheckConstraint("from_id <> to_id", name="ck_bookmark_links_no_self"),
    )
    op.create_index("idx_bookmark_links_user", "bookmark_links", ["user_id"])
    # weight DESC — индекс по выражению; op.create_index не принимает sa.text как
    # колонку (падает на холодной БД), поэтому DDL напрямую.
    op.execute(sa.text(
        "CREATE INDEX idx_bookmark_links_from_weight "
        "ON bookmark_links (from_id, weight DESC)"
    ))
    op.execute(sa.text(
        "CREATE INDEX idx_bookmark_links_to_weight "
        "ON bookmark_links (to_id, weight DESC)"
    ))

    op.create_table(
        "graph_layouts",
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "nodes",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("node_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "built_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )


def downgrade() -> None:
    op.drop_table("graph_layouts")
    op.drop_index("idx_bookmark_links_to_weight", table_name="bookmark_links")
    op.drop_index("idx_bookmark_links_from_weight", table_name="bookmark_links")
    op.drop_index("idx_bookmark_links_user", table_name="bookmark_links")
    op.drop_table("bookmark_links")

    bind = op.get_bind()
    postgresql.ENUM(name="link_kind").drop(bind, checkfirst=True)
