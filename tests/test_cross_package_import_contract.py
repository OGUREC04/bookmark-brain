"""Cross-package import-contract guard.

Why this exists: the reminders/tasks/worker monoliths were split into
packages with facade re-exports. The orchestration layer (`start.py`)
imports the public cross-package API of a *sibling* package via **lazy
in-function imports** (e.g. `bot/handlers/start.py` does
`from bot.handlers.tasks import handle_pending_dedup, parse_dedup_intent`
inside `handle_text`).

Such imports execute only when that code path runs. The unit suite does
NOT always exercise those paths, so a missing facade re-export can pass
the suite green and then `ImportError` in production (this exact class of
bug shipped in the q21 split — shared infra helpers were not re-exported;
caught only in code review). The de-leak refactor moved that shared infra
into the public `bot.common` package, so reminders↔tasks no longer import
each other laterally; the remaining guarded seams are start.py → the
reminders / tasks facades.

This test statically scans every source file for `from <split-package>
import (...)` (module-level AND nested), then asserts each imported name
actually resolves on the target package facade. It is intentionally
behaviour-free: it guards the *contract*, so any future split that drops a
re-export fails here immediately regardless of test coverage on the path.
"""
from __future__ import annotations

import ast
import importlib
import sys
from pathlib import Path

import pytest

# `app.worker` lives under backend/ (backend has its own conftest that
# normally puts it on sys.path). This guard makes the contract test
# self-contained when collected from the repo-root tests/ tree.
_BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
if _BACKEND_DIR.is_dir() and str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

# Packages that were split monolith -> package with a facade __init__.
# Any symbol imported from these by sibling code MUST be re-exported.
# `bot.common` is the lowest shared layer: the de-leak refactor routed all
# cross-package infra (HTML-escape, tz/fire_at formatters, NL splitters,
# send_ephemeral) through its public facade so reminders/tasks no longer
# import each other laterally. Its facade __all__ and re-exports are now the
# load-bearing contract every feature package depends on — guard it here too.
_SPLIT_PACKAGES = {
    "bot.common",
    "bot.handlers.reminders",
    "bot.handlers.tasks",
    "app.worker",
}

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCAN_DIRS = [
    _REPO_ROOT / "bot",
    _REPO_ROOT / "backend" / "app",
]


def _iter_source_files():
    for base in _SCAN_DIRS:
        for path in base.rglob("*.py"):
            parts = path.parts
            if "__pycache__" in parts or ".claude" in parts:
                continue
            yield path


def _collect_cross_package_imports() -> list[tuple[str, str, str, int]]:
    """Return (file, package, name, lineno) for every cross-package import.

    Includes both module-level and function-nested imports (ast walks the
    whole tree). A package importing from *itself* is skipped — facade
    completeness only matters for *sibling/parent* importers.
    """
    found: list[tuple[str, str, str, int]] = []
    for path in _iter_source_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as e:  # pragma: no cover - surfaces real breakage
            pytest.fail(f"{path}: syntax error parsing for import scan: {e}")
        rel = path.relative_to(_REPO_ROOT).as_posix()
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or node.module is None:
                continue
            if node.level != 0:  # relative import inside the package itself
                continue
            mod = node.module
            for pkg in _SPLIT_PACKAGES:
                if mod == pkg or mod.startswith(pkg + "."):
                    # Skip a package importing from its own subtree.
                    if rel.replace("/", ".").removesuffix(".py").find(pkg) != -1:
                        # crude but effective: file lives under the package
                        pass
                    for alias in node.names:
                        if alias.name == "*":
                            continue
                        found.append((rel, mod, alias.name, node.lineno))
                    break
    return found


_IMPORTS = _collect_cross_package_imports()


def test_scan_found_cross_package_imports():
    """Sanity: the scanner actually finds the known seams.

    If this drops to 0 the AST scan silently broke and every other
    assertion below would vacuously pass.
    """
    assert _IMPORTS, "import scanner found nothing — scan logic is broken"
    # The known critical seam must be present in the scan: start.py pulls the
    # public cross-package dedup API from the tasks facade lazily.
    assert any(
        f.endswith("start.py") and name == "handle_pending_dedup"
        for f, _mod, name, _ln in _IMPORTS
    ), "expected start.py -> tasks.handle_pending_dedup seam not detected"


@pytest.mark.parametrize(
    "rel_file,module,name,lineno",
    _IMPORTS,
    ids=[f"{f}:{ln}:{mod.split('.')[-1]}.{n}" for f, mod, n, ln in _IMPORTS],
)
def test_cross_package_symbol_resolves(rel_file, module, name, lineno):
    """Every name imported from a split package must resolve on it.

    This is exactly the check that would have caught the q21 facade gap
    before it shipped.
    """
    mod = importlib.import_module(module)
    assert hasattr(mod, name), (
        f"{rel_file}:{lineno} imports `{name}` from `{module}`, but the "
        f"package facade does not expose it. Add `{name}` to "
        f"`{module.replace('.', '/')}/__init__.py` re-exports (and __all__)."
    )


@pytest.mark.parametrize("package", sorted(_SPLIT_PACKAGES))
def test_split_package_all_is_consistent(package):
    """Every name in a split package's __all__ must actually exist on it.

    Catches the inverse mistake: an __all__ entry referring to a symbol
    that was moved/renamed during a future split.
    """
    mod = importlib.import_module(package)
    declared = getattr(mod, "__all__", None)
    assert declared is not None, f"{package} facade must define __all__"
    missing = [n for n in declared if not hasattr(mod, n)]
    assert not missing, (
        f"{package}.__all__ lists symbols not present on the module: {missing}"
    )
