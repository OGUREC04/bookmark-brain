"""Guard: ``shared/`` is a dependency leaf — it must not import project packages.

``shared.media`` (STT + document extraction) was extracted from ``bot.services``
(bead 3sr) so the FastAPI backend/worker can reuse it WITHOUT importing
``bot.*``. The bot and the backend are separate deploy artifacts; if ``shared``
ever imported ``bot`` or ``app`` it would couple them and break the backend
build (which ships no bot code).

The import-linter contract in ``pyproject.toml`` enforces ``shared -> bot`` in
CI. This pytest mirror also covers ``shared -> app`` (the backend is not a
lint-time root package) and keeps the guard self-contained — it runs wherever
the suite runs, with no sys.path setup. Same AST-scan pattern as
``test_cross_package_import_contract.py``.
"""
from __future__ import annotations

import ast
from pathlib import Path

_SHARED_DIR = Path(__file__).resolve().parent.parent / "shared"
_FORBIDDEN_ROOTS = {"bot", "app"}


def _iter_shared_files():
    for path in _SHARED_DIR.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        yield path


def _violations() -> list[tuple[str, str, int]]:
    """Return (relpath, imported_module, lineno) for every forbidden import.

    Catches both ``import bot...`` and ``from bot... import ...`` at module
    level AND function-nested (ast walks the whole tree).
    """
    found: list[tuple[str, str, int]] = []
    for path in _iter_shared_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        rel = path.relative_to(_SHARED_DIR.parent).as_posix()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] in _FORBIDDEN_ROOTS:
                        found.append((rel, alias.name, node.lineno))
            elif (
                isinstance(node, ast.ImportFrom)
                and node.module is not None
                and node.level == 0
                and node.module.split(".")[0] in _FORBIDDEN_ROOTS
            ):
                found.append((rel, node.module, node.lineno))
    return found


def test_shared_files_exist():
    """Sanity: the scanner sees shared sources (else the guard vacuously passes)."""
    assert list(_iter_shared_files()), "no .py files under shared/ — scan path is wrong"


def test_shared_does_not_import_project_packages():
    violations = _violations()
    assert not violations, (
        "shared/ must stay a dependency leaf (no bot/app imports). Found:\n"
        + "\n".join(f"  {rel}:{ln} imports `{mod}`" for rel, mod, ln in violations)
    )
