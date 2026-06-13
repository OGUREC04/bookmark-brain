"""Структурные тесты схемы Connections MVP — задача 1 (без БД).

Проверяем определения моделей BookmarkLink / GraphLayout и наличие/корректность
миграции a9b0c1d2e3f4 через метаданные SQLAlchemy. Реальный накат к Postgres
(`alembic upgrade`) и интеграционные тесты — отдельно (нужна живая БД).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

from sqlalchemy import CheckConstraint, UniqueConstraint


def test_bookmark_link_table_shape():
    from app.models import BookmarkLink

    t = BookmarkLink.__table__
    assert t.name == "bookmark_links"
    assert {
        "id", "user_id", "from_id", "to_id", "kind", "weight", "created_at",
    } <= set(t.columns.keys())

    # FK CASCADE на всех трёх ссылках (NFR-4: чистка рёбер при удалении).
    for col in ("user_id", "from_id", "to_id"):
        fks = list(t.c[col].foreign_keys)
        assert fks, f"{col} должен быть FK"
        assert all(fk.ondelete == "CASCADE" for fk in fks)
        assert t.c[col].nullable is False


def test_bookmark_link_unique_and_check():
    from app.models import BookmarkLink

    t = BookmarkLink.__table__
    uniques = [c for c in t.constraints if isinstance(c, UniqueConstraint)]
    assert any(
        {col.name for col in u.columns} == {"from_id", "to_id", "kind"}
        for u in uniques
    ), "нужен UNIQUE(from_id, to_id, kind) против дублей рёбер"

    checks = [c for c in t.constraints if isinstance(c, CheckConstraint)]
    assert any(
        "from_id" in str(c.sqltext) and "to_id" in str(c.sqltext) for c in checks
    ), "нужен CHECK(from_id <> to_id) — без самосвязи"


def test_link_kind_enum_values():
    from app.models import BookmarkLink

    enum_type = BookmarkLink.__table__.c.kind.type
    assert set(enum_type.enums) == {"similar", "manual", "derived_from_space"}
    # Тип создаётся миграцией, не ORM-ом (иначе asyncpg шлёт VARCHAR).
    assert enum_type.create_type is False


def test_graph_layout_table_shape():
    from app.models import GraphLayout

    t = GraphLayout.__table__
    assert t.name == "graph_layouts"
    assert t.c.user_id.primary_key
    assert list(t.c.user_id.foreign_keys)[0].ondelete == "CASCADE"
    assert {"user_id", "nodes", "node_count", "built_at"} <= set(t.columns.keys())


def test_migration_revision_chain():
    """Миграция ревизуется от текущего head a8b9c0d1e2f3 и имеет up/down."""
    path = (
        Path(__file__).resolve().parent.parent
        / "migrations" / "versions" / "a9b0c1d2e3f4_add_bookmark_links.py"
    )
    spec = importlib.util.spec_from_file_location("_mig_bookmark_links", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    assert mod.revision == "a9b0c1d2e3f4"
    assert mod.down_revision == "a8b9c0d1e2f3"  # реальный head (после scheduled+analytics)
    assert callable(mod.upgrade) and callable(mod.downgrade)
    assert mod.LINK_KIND_VALUES == ("similar", "manual", "derived_from_space")
