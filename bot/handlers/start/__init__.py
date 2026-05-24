"""Оркестрация base-хендлеров бота (фасад пакета `start`).

Разбит на 3 домена со своими роутерами:
  • commands — /start, /help
  • listing  — /list, пагинация, удаление
  • ingest   — forward / text / media + подтверждение коротких сохранений
              (catch-all для текста, поэтому подключается ПОСЛЕДНИМ)

Обратная совместимость: `from bot.handlers.start import router` и
`bot.handlers.start.ensure_user` (патчится в тестах) сохранены.
"""
from aiogram import Router

from bot.common.auth import ensure_user

from .commands import router as _commands_router
from .ingest import router as _ingest_router
from .listing import router as _listing_router

router = Router()
router.include_router(_commands_router)
router.include_router(_listing_router)
# ingest содержит catch-all F.text — включаем последним внутри пакета.
router.include_router(_ingest_router)

__all__ = ["router", "ensure_user"]
