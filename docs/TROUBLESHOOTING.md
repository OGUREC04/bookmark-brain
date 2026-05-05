# Известные проблемы и решения

| Проблема | Причина | Решение |
|----------|---------|---------|
| GigaChat SDK 401 | SDK глючит с OAuth | Используем httpx напрямую, не SDK (`ai_classifier.py`) |
| GigaChat embeddings 402 | Бесплатный тариф не включает embeddings | Используем Voyage AI |
| arq CLI падает на Python 3.14 | `get_event_loop()` deprecated | `run_worker.py` использует `asyncio.run()` |
| Bot: `extra inputs not permitted` | Общий `.env` с лишними переменными | `bot/config.py`: `extra="ignore"` в model_config |
| Bot: `TelegramConflictError` | Два экземпляра бота одновременно | Убить все python: `taskkill /F /IM python.exe`, подождать 10 сек |
| Bot: HTML parse error с кириллицей | `<слово>` парсится как HTML-тег | `parse_mode=None` для plain text ответов |
| `.env` не находится | Settings ищет в CWD (backend/) | Абсолютный путь в `config.py`: `Path(__file__).resolve().parent.parent.parent / ".env"` |
| Поиск 500 если нет embeddings | Voyage API не ответил | Fallback: full-text → ILIKE поиск (`search.py`) |

## Дополнительно

Часть граблей окружения уже компилируется в `D:\brain\claude-memory-compiler\knowledge\concepts/`:
- `windows-bat-encoding`, `pypi-russia-mirror`, `python-314-no-wheels`, `onedrive-cmd-python`, `python-path-windows`, `ngrok-url-rotation`, `sqlalchemy-pgvector-cast` и др.

Грузятся через SessionStart hook как «Knowledge Base Index».
