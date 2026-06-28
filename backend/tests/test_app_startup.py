"""Guard: приложение реально импортируется и роуты регистрируются.

Юнит-тесты зовут эндпоинт-функции напрямую и НЕ ловят ошибки регистрации роутов:
например FastAPI «Status code 204 must not have a response body» падает при ИМПОРТЕ
main (декоратор @router.delete), а не при вызове функции. Этот смок ловит весь класс
«приложение не поднимется» (uvicorn падал бы на старте, юнит-тесты при этом зелёные).
"""
from __future__ import annotations


def test_app_imports_and_entries_routes_registered():
    # Если любой роутер сломан на регистрации — этот импорт бросит (как падал uvicorn).
    from main import app

    paths = {getattr(r, "path", "") for r in app.routes}
    assert "/api/v1/bookmarks/{bookmark_id}/thread" in paths
    assert "/api/v1/bookmarks/{bookmark_id}/entries" in paths
    assert "/api/v1/bookmarks/{bookmark_id}/entries/{entry_id}" in paths
    assert "/api/v1/bookmarks/{bookmark_id}/entries/upload" in paths
