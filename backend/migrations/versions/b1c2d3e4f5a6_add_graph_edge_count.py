"""add graph_layouts.edge_count for stale-by-connections threshold

Баннер «граф устарел» раньше загорался при ЛЮБОЙ новой заметке (node_count !=
current) — нервировал на +1. Теперь stale считается по росту СВЯЗЕЙ: храним число
связей на момент сборки (edge_count) и зажигаем баннер только при ≥ порога новых.

Existing rows get 0 (server_default) → первый /graph после деплоя покажет stale
один раз (current_edges - 0 >= порога), после пересборки edge_count актуализируется.

Revision ID: b1c2d3e4f5a6
Revises: a9b0c1d2e3f4
Create Date: 2026-06-14 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b1c2d3e4f5a6"
down_revision: Union[str, None] = "a9b0c1d2e3f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "graph_layouts",
        sa.Column("edge_count", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("graph_layouts", "edge_count")
