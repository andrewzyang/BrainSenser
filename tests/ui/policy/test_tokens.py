"""Design tokens: pure Python, today's values at 100 %, a monotonic type ramp."""

import re
import subprocess
import sys
from pathlib import Path

from src.ui.policy.tokens import DENSITY_SPECS, TYPE_PX, Dim, Space, TypeRole

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_tokens_import_no_qt():
    """ViewModels may import tokens, so the module must not pull in any Qt module."""
    code = (
        "import sys; import src.ui.policy.tokens; "
        "loaded = sorted(m for m in sys.modules if m.startswith(('PySide6', 'shiboken6'))); "
        "print(','.join(loaded))"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    )
    assert out.stdout.strip() == ""


def test_type_ramp_matches_stylesheet_today():
    assert [TYPE_PX[r] for r in TypeRole] == [10, 11, 12, 13, 14, 15, 18, 28]


def test_type_ramp_is_strictly_increasing():
    sizes = [TYPE_PX[r] for r in TypeRole]
    assert sizes == sorted(sizes) and len(set(sizes)) == len(sizes)


def test_body_size_is_the_global_font_rule():
    qss = (REPO_ROOT / "src" / "ui" / "style.qss").read_text()
    universal_rule = re.search(r"^\*\s*\{[^}]*?font-size:\s*(\d+)px", qss, re.MULTILINE)
    assert universal_rule and int(universal_rule.group(1)) == TYPE_PX[TypeRole.BODY]


def test_regular_density_is_today_and_window_floor_is_d3():
    regular = DENSITY_SPECS["regular"]
    assert (regular.page_margin, regular.plot_min_height, regular.list_rows) == (16, 260, 3)
    assert (Dim.WINDOW_MIN_W, Dim.WINDOW_MIN_H) == (600, 500)
    assert (Dim.EVENT_TYPES_MAX_W, Dim.GROUPS_MAX_W, Dim.CONTROLS_MAX_W) == (200, 200, 260)


def test_all_token_values_are_integer_px():
    for namespace in (Space, Dim):
        for name, value in vars(namespace).items():
            if name.isupper():
                assert isinstance(value, int) and value > 0, f"{namespace.__name__}.{name}"
