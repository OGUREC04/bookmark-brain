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
| Голосовое >30с: «Не удалось распознать (ошибка 400)» | Sync Yandex STT режет на 30с, Hybrid fallback на async требует S3 envs | Добавить `YANDEX_S3_BUCKET / ACCESS_KEY / SECRET_KEY` в `.env`, redeploy. Bucket: public-read ACL, KMS off, регион `ru-central1` |
| POST /bookmarks 500 на повторе сообщения | Не обработан `IntegrityError` на `idx_bookmarks_source_dedup` | Фикс 2026-05-11: catch → return existing (idempotent). См. `backend/app/api/bookmarks.py::create_bookmark` |
| Reply «10 готово» зачёркивает не тот пункт | LLM мискаунтил длинный JSON без numbered repr | Фикс 2026-05-11: numbered repr в payload + post-validation. См. `task_list_editor.py::_validate_no_hallucinated_add` |
| Merge/dedup-update: «✅ Оригинал обновлён» без видимого списка | Re-render шёл ПОСЛЕ delete с silent swallow | Фикс 2026-05-11: re-render first + явные `logger.warning`. См. `docs/bugs/2026-05-11-task-list-duplicates-and-merge-ui.md` |
| SSH `Permission denied` после нескольких попыток | fail2ban забанил IP | Подождать 15 мин ИЛИ через VNC консоль: `fail2ban-client unban <IP>` |
| Beget «Сменил пароль» — SSH/VNC не пускают | Кнопка «Изменить пароль» меняет ТОЛЬКО пароль панели, root system отдельно | Сброс root: Rescue-режим (mount + chroot + `passwd`) или тикет в поддержку |

## Дополнительно

Часть граблей окружения уже компилируется в `D:\brain\claude-memory-compiler\knowledge\concepts/`:
- `windows-bat-encoding`, `pypi-russia-mirror`, `python-314-no-wheels`, `onedrive-cmd-python`, `python-path-windows`, `ngrok-url-rotation`, `sqlalchemy-pgvector-cast` и др.

Грузятся через SessionStart hook как «Knowledge Base Index».
