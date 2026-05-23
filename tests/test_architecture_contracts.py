"""Architecture-contract guard (import-linter) wired into the test suite.

The import-linter contracts in pyproject.toml ([tool.importlinter]) encode
the load-bearing structural rules:

  1. Feature independence — bot.handlers.reminders and bot.handlers.tasks
     must not import each other directly (only via bot.common or the
     start.py orchestration hub). This freezes the de-leak refactor: the
     CRITICAL bug where tasks/nl_edit reached into reminders' private
     internals becomes impossible to reintroduce.
  2. Layered architecture — bot.common is the lowest shared layer and must
     never import a feature handler or the composition root.

CI runs `lint-imports` as a hard-fail step too; this test makes the same
check part of the local `pytest` run so a violation is caught before push,
not only in CI.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _lint_imports_cmd() -> list[str]:
    exe = shutil.which("lint-imports")
    if exe:
        return [exe]
    # Fall back to module invocation if the console script isn't on PATH.
    return [sys.executable, "-m", "importlinter.cli"]


def test_import_linter_contracts_hold():
    """All import-linter contracts in pyproject.toml must be KEPT."""
    # Force the child interpreter into UTF-8 so its banner/contract output
    # (which contains box-drawing + arrow glyphs like «↔») doesn't crash with
    # UnicodeEncodeError when its stdout pipe inherits a legacy code page
    # (e.g. cp1251 on Windows). We also decode the captured bytes as UTF-8.
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    try:
        proc = subprocess.run(
            _lint_imports_cmd(),
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=120,
        )
    except FileNotFoundError:
        pytest.skip("import-linter not installed (CI installs it as a hard gate)")
        return

    output = proc.stdout + proc.stderr
    assert proc.returncode == 0, (
        "import-linter contracts BROKEN — architecture violation introduced.\n"
        "Run `lint-imports` locally to see which contract broke.\n\n"
        + output
    )
    assert "Contracts: 2 kept, 0 broken." in output, (
        "Expected exactly 2 architecture contracts kept; output was:\n" + output
    )
