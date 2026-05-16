# AGENTS.md — orientation for AI coding agents & new developers

BookmarkBrain = Telegram bot (aiogram 3.x) + FastAPI backend + arq worker.
This file is the **first thing to read**. It is curated and intentionally
short. Deep docs are linked, not inlined.

## Run / test / lint (exact commands)

```bash
# Windows dev: Python is C:/Python314/python.exe ; set PYTHONUTF8=1
# Full test suite (run from repo root):
PYTHONUTF8=1 PYTHONPATH=. python -m pytest tests/ backend/tests/ -q
#   expected: 522 passed, 18 deselected   (integration tests need a real DB → deselected)

# Architecture contracts (HARD gate, also in CI):
lint-imports                       # must print: Contracts: 2 kept, 0 broken.

# Lint (HARD gate on bot/, also in CI):
python -m ruff check bot/          # must be clean

# Start the stack locally: see .claude/STARTUP.md (Docker / backend / worker / bot / ngrok)
```

CI: `.github/workflows/test.yml` runs import-linter, `ruff check bot/`,
mypy, and the full suite as hard-fail steps on PRs to `main`.

## Repository map (where things live)

```
bot/
  main.py                 # composition root: builds Dispatcher, include_router order
  common/                 # SHARED, domain-agnostic infra (lowest bot layer)
    text.py datetime.py nl.py telegram.py   # safe(), format_fire_at(), …
  handlers/
    start.py              # orchestration hub: auth (_ensure_user), routing, catch-all
    reminders/            # FEATURE package — owns its Router, facade __init__
    tasks/                # FEATURE package — owns its Router, facade __init__
    <other handlers>.py
  api_client.py state_store.py services/    # backend/redis clients
backend/
  app/
    api/                  # FastAPI routers
    services/             # business logic (bookmark_processor, ai_classifier, …)
    worker/               # arq worker package (telegram/dedup/processing/scheduled/…)
  main.py run_worker.py
tests/  backend/tests/    # pytest; backend/tests has its own conftest
docs/                     # ARCHITECTURE.md (data model/auth/env), BOT-UX.md, etc.
```

Each feature package (`reminders/`, `tasks/`, `worker/`) is a **facade**:
`__init__.py` aggregates sub-module routers via `include_router` and
re-exports the public API in `__all__`. One concept per sub-file, < 800 LOC
hard (< 400 typical) — files are read whole into agent context, keep them small.

## Dependency rules (ENFORCED — do not violate)

Encoded in `pyproject.toml [tool.importlinter]`, hard-failed in CI:

1. **Feature independence.** `bot.handlers.reminders` and
   `bot.handlers.tasks` MUST NOT import each other. Shared code goes in
   `bot.common`. (A 1600-LOC split shipped a CRITICAL bug from exactly this
   lateral coupling — the contract makes it impossible to reintroduce.)
2. **Layering.** `bot.main` → `bot.handlers` → `bot.common`. `bot.common`
   never imports a handler or the composition root.
3. **No relative cross-package imports** (ruff `TID`). Cross-feature use is
   explicit absolute imports so the import graph IS the architecture map.

`bot.handlers.start` is the legitimate orchestration hub — it may import
both features (the only allowed bridge; `ignore_imports` in the contract).

## How to add code without breaking the architecture

- **New shared helper used by 2+ features?** Put it in `bot/common/` with a
  PUBLIC (non-underscore) name + add to `bot/common/__init__.py` `__all__`.
  Never import another feature package to reuse a helper.
- **New handler in a feature?** Add a sub-module in that feature package
  with its own `Router()`; wire it in the package `__init__.py` aggregator
  (order matters: specific filters before catch-all). Export public symbols
  via `__all__`; keep internals `_`-prefixed and out of the facade.
- **Cross-feature call needed?** Route it through `bot.handlers.start`
  (orchestration) or extract the shared part to `bot.common`. Do not add a
  `reminders → tasks` import.
- After any structural change run `lint-imports` + `ruff check bot/` +
  the full suite. The guard tests
  `tests/test_cross_package_import_contract.py` and
  `tests/test_architecture_contracts.py` will catch facade/layer breaks.

## Conventions

- Public API = non-underscore, listed in the package `__all__`. Internals
  stay `_`-prefixed and are NOT re-exported via the facade.
- Module-level docstring on every package `__init__.py` and sub-module —
  it is the navigation anchor agents read first.
- Commits: `type(scope): summary` (feat/fix/refactor/test/chore/docs).
- Russian is the product/user-facing language; code identifiers & docs in
  English; comments may be Russian.

See `docs/ARCHITECTURE.md` (data model, auth, env vars) and `CLAUDE.md`
(product principles) for non-structural detail.
