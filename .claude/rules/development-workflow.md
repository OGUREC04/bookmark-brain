# Development Workflow

> Extends [git-workflow.md](~/.claude/rules/common/git-workflow.md) with the full dev pipeline.
>
> **Атомы цикла уже глобальны** — здесь только их порядок сшивки + project-шаги (БТ, пути).
> PRD-триггер → `common/ccpm-boundaries.md` · развилки → `common/surface-architecture-forks.md` ·
> Beads → `common/tracking.md` · docs-with-code → `common/docs-with-code.md` (+ хук `check-docs-update.py`).

## Триаж новой задачи (с чего начинать)

| Тип | Маршрут |
|---|---|
| Тривиал (<1ч), опечатка, правка 1 файла | сразу делать |
| Bugfix (даже многошаговый) | план если нужно → TDD → review. **БЕЗ PRD** |
| Infra (миграция / deps / рефактор без UX) | **БЕЗ PRD** |
| **Фича ≥1ч** | ПОЛНЫЙ ЦИКЛ ↓ |

## Полный цикл фичи

0. **Research & Reuse** _(обязательно до нового кода)_
   - `gh search repos` / `gh search code` → library docs (Context7) → npm/PyPI
   - Адаптировать проверенное вместо net-new

1. **PRD** (`docs/prd/`) — триггер и состав в `ccpm-boundaries.md`.
   Проблема, user stories, ≥10 edge cases, success, out-of-scope. **До кода.**

2. **Развилки** — `surface-architecture-forks.md`. Sync/async, новая либа, in-place vs backfill,
   inline vs worker. Вынести таблицей, **ждать ответа**.

3. **План + Beads** — `planner`/`architect`, декомпозиция, `bd create` с зависимостями.

4. **TDD** — `tdd-guide`. RED → GREEN → IMPROVE. Прагматичный порог покрытия — см. `bookmark-brain.md §12`.

5. **Review** — `code-reviewer` сразу после кода. `security-reviewer` обязателен при
   auth / user input / `/api/` / secrets (см. `bookmark-brain.md §5`).

6. **ADR** (`docs/decisions/`) — если приняли значимое **архитектурное** решение
   (почему так, а не иначе). Не каждая фича рождает ADR.

7. **БТ** (`docs/requirements/`) — создать/обновить living-doc «**как ведёт себя сейчас**»
   (флоу, use cases, корнер-кейсы). **В ТОМ ЖЕ PR что код.**
   - **ОБЕ стороны одной фичи:** секции «Bot/Backend» И «Mini App» (фронт — отдельный репо
     `bookmark-brain-miniapp`, но БТ канонично здесь, в `docs/requirements/`).
   - Шаблон + конвенция: `docs/requirements/README.md` + `_ШАБЛОН.md`.
   - Хук `check-docs-update.py` напомнит при правке поведенческого кода — но напоминание ≠ замена: БТ пишем сами.

8. **Commit & Push** — conventional commits (`feat/fix/refactor/docs/test/chore/perf/ci`).

9. **Закрытие** — `bd close` + **Post-Phase Docs Sync**: сверить evergreen-доки
   (`ARCHITECTURE.md`, `SPEC.md`, `API.md`, `BOT-COMMANDS.md` если менялись команды) с
   зашипленным кодом, обновить `Проверено: YYYY-MM-DD`. Конвенция — `docs/README.md`.

## Жанры доков — НЕ смешивать

| Документ | Отвечает на | Природа |
|---|---|---|
| PRD (`docs/prd/`) | зачем строили, что решили | snapshot |
| ADR (`docs/decisions/`) | почему выбрали такой подход | вечное решение |
| **БТ (`docs/requirements/`)** | **как ведёт себя сейчас** | **living-doc** |
| `BOT-COMMANDS.md` | что вводит пользователь | reference |
| `SPEC.md` / `ARCHITECTURE.md` | как устроено внутри | техническое |

Полная версия таблицы + правило living-doc — `docs/requirements/README.md`.
