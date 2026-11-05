"""Screens are looked up only through ``src.ui.utils.screens.screen_of``.

``QWidget.screen()`` and ``QWindow.screen()`` make the application's QScreen a
child of the caller's Python wrapper, and the cycle collector can then delete
the QScreen (see the helper's docstring). The ban covers ``src/`` and
``main.py``; it is an AST scan, so comments and strings never count.
"""

import ast
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
HELPER = "src/ui/utils/screens.py"


def screen_calls(source: str) -> list[int]:
    """Line numbers of every ``<expression>.screen(...)`` call in ``source``."""
    return [node.lineno for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == "screen"]


def _scanned_files() -> list[Path]:
    return [*sorted((PROJECT_ROOT / "src").rglob("*.py")), PROJECT_ROOT / "main.py"]


def test_screens_are_looked_up_only_through_screen_of():
    offenders = [f"{path.relative_to(PROJECT_ROOT).as_posix()}:{line}"
                 for path in _scanned_files()
                 if path.relative_to(PROJECT_ROOT).as_posix() != HELPER
                 for line in screen_calls(path.read_text(encoding="utf-8"))]

    assert offenders == [], f"use src.ui.utils.screens.screen_of(), not .screen(): {offenders}"


def test_the_helper_makes_the_one_screen_call():
    assert len(screen_calls((PROJECT_ROOT / HELPER).read_text(encoding="utf-8"))) == 1


@pytest.mark.parametrize("source, banned", [
    ("widget.screen()", True),
    ("self.windowHandle().screen().name()", True),
    ("QWidget.screen(widget)", True),
    ("screen_of(widget)", False),
    ("QGuiApplication.primaryScreen()", False),
    ("widget.screen", False),
    ("# widget.screen()", False),
    ('"""widget.screen()"""', False),
])
def test_the_scan_finds_screen_calls_only(source, banned):
    assert bool(screen_calls(source)) is banned
