"""add transcription and media_duration columns for voice support

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-05-05 12:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("bookmarks", sa.Column("transcription", sa.Text(), nullable=True))
    op.add_column(
        "bookmarks",
        sa.Column("media_duration", sa.Float(), nullable=True),
    )
    # Widen media_file_id from VARCHAR(255) to TEXT — Telegram file_id can exceed 255 chars
    op.alter_column(
        "bookmarks",
        "media_file_id",
        type_=sa.Text(),
        existing_type=sa.String(255),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "bookmarks",
        "media_file_id",
        type_=sa.String(255),
        existing_type=sa.Text(),
        existing_nullable=True,
    )
    op.drop_column("bookmarks", "media_duration")
    op.drop_column("bookmarks", "transcription")
