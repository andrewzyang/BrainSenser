"""Layout class types: pure Python, boundaries clear of common sizes, sidebar resolution."""

import subprocess
import sys
from pathlib import Path

import pytest

from src.ui.policy.layout import (
    BOUNDARIES, SidebarMode, SidebarPreference, WidthClass, resolve_sidebar_mode,
)

REPO_ROOT = Path(__file__).resolve().parents[3]

# Window client widths and content-stack heights of common maximised windows (plan §3.1).
COMMON_WINDOW_WIDTHS = (1093, 1280, 1366, 1024, 1164, 1512, 960, 640, 1080)
COMMON_CONTENT_HEIGHTS = (496, 590, 647, 550, 719, 656, 649, 565, 932, 960, 780, 1800)
MIN_MARGIN = 25


def test_layout_imports_no_qt():
    code = (
        "import sys; import src.ui.policy.layout; "
        "print(','.join(sorted(m for m in sys.modules if m.startswith(('PySide6', 'shiboken6')))))"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    )
    assert out.stdout.strip() == ""


def test_boundaries_keep_clear_of_common_maximised_sizes():
    for width in COMMON_WINDOW_WIDTHS:
        assert abs(width - BOUNDARIES.rail_below) >= MIN_MARGIN, width
    for height in COMMON_CONTENT_HEIGHTS:
        assert abs(height - BOUNDARIES.compact_below) >= MIN_MARGIN, height


@pytest.mark.parametrize("preference, width_class, override, expected", [
    (SidebarPreference.AUTO, WidthClass.WIDE, None, SidebarMode.LABELS),
    (SidebarPreference.AUTO, WidthClass.NARROW, None, SidebarMode.ICONS),
    (SidebarPreference.LABELS, WidthClass.NARROW, None, SidebarMode.LABELS),
    (SidebarPreference.ICONS, WidthClass.WIDE, None, SidebarMode.ICONS),
    (SidebarPreference.AUTO, WidthClass.NARROW, SidebarMode.LABELS, SidebarMode.LABELS),
    (SidebarPreference.LABELS, WidthClass.WIDE, SidebarMode.ICONS, SidebarMode.ICONS),
])
def test_resolve_sidebar_mode(preference, width_class, override, expected):
    assert resolve_sidebar_mode(preference, width_class, override) is expected
