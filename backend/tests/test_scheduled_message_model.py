"""Regression: ScheduledMessage.kind/status должны быть Postgres ENUM,
не String. Иначе INSERT через ORM ломается на проде с
`column "kind" is of type scheduled_kind but expression is of type
character varying`.

Этот баг не ловится моками (session.execute мокнут), только живой Postgres
показал его на e2e smoke. Тест проверяет тип колонки на уровне metadata,
чтобы случайный rollback к String(32) поймали в CI.
"""
from __future__ import annotations

from app.models import ScheduledMessage
from sqlalchemy.dialects.postgresql import ENUM as PG_ENUM


def _column_type(name: str):
    return ScheduledMessage.__table__.c[name].type


class TestEnumColumns:
    def test_kind_is_pg_enum(self):
        col_type = _column_type("kind")
        assert isinstance(col_type, PG_ENUM), (
            f"ScheduledMessage.kind должен быть postgresql.ENUM, "
            f"а не {type(col_type).__name__}. См. миграцию "
            f"a7b8c9d0e1f2_add_scheduled_messages.py — там создан scheduled_kind."
        )
        assert col_type.name == "scheduled_kind"
        assert "reminder" in col_type.enums
        assert col_type.create_type is False  # type создан миграцией

    def test_status_is_pg_enum(self):
        col_type = _column_type("status")
        assert isinstance(col_type, PG_ENUM), (
            f"ScheduledMessage.status должен быть postgresql.ENUM, "
            f"а не {type(col_type).__name__}."
        )
        assert col_type.name == "scheduled_status"
        # Все 6 статусов из миграции
        assert set(col_type.enums) == {
            "pending", "sending", "sent", "done", "cancelled", "failed",
        }
        assert col_type.create_type is False
