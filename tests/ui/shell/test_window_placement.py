"""Window floor and first-launch geometry: the pure helpers (plan §3.1, D3).

QtCore value types only; no QApplication. The Qt glue is exercised on emulated
screens in ``test_window_placement_screens.py``.
"""

import pytest
from PySide6.QtCore import QRect, QSize

from src.ui.policy.tokens import Dim
from src.ui.shell.window_placement import (
    MAXIMIZE_BELOW_WIDTH,
    MAXIMIZE_MAX_ASPECT,
    NORMAL_MAX_ASPECT,
    NORMAL_SHARE,
    launch_geometry,
    window_floor,
)

FLOOR = QSize(Dim.WINDOW_MIN_W, Dim.WINDOW_MIN_H)


@pytest.mark.parametrize("available, frame, expected", [
    ((1280, 797), (0, 28), (600, 500)),   # the user's Mac
    ((1093, 576), (0, 30), (600, 500)),   # Windows 1366×768 @ 125 %
    ((1024, 520), (0, 28), (600, 492)),   # too short for 500 plus the title bar
    ((560, 900), (2, 30), (558, 500)),    # too narrow for 600
    ((640, 480), (0, 0), (600, 480)),     # no frame at all
])
def test_floor_is_600x500_clamped_to_available_minus_frame(available, frame, expected):
    assert window_floor(QSize(*available), QSize(*frame)) == QSize(*expected)


@pytest.mark.parametrize("width, height", [
    (1093, 576), (1280, 640), (1280, 797), (1440, 850), (1920, 1040), (2560, 1400),
    (MAXIMIZE_BELOW_WIDTH - 1, 1400), (2400, 1200),  # just below the width / at the aspect limit
])
def test_maximised_below_2600_px_wide_and_aspect_2(width, height):
    assert launch_geometry(QRect(0, 0, width, height), FLOOR).maximized


@pytest.mark.parametrize("width, height", [
    (MAXIMIZE_BELOW_WIDTH, 1400), (3840, 2120), (5120, 2840),  # very wide
    (3440, 1400), (2560, 1080), (2402, 1200),                  # ultrawide: aspect > 2
])
def test_centred_on_very_wide_and_ultrawide_screens(width, height):
    assert not launch_geometry(QRect(0, 0, width, height), FLOOR).maximized


@pytest.mark.parametrize("available, expected", [
    # 80 % of the height; width = min(80 % of the width, 1.6 × height)
    (QRect(0, 0, 3840, 2120), QRect(563, 212, 2714, 1696)),  # 4K @ 100 %
    (QRect(0, 0, 3440, 1400), QRect(824, 140, 1792, 1120)),  # ultrawide
    (QRect(0, 0, 1280, 797), QRect(129, 80, 1021, 638)),     # the user's Mac (restore size)
])
def test_normal_geometry_is_centred_80_percent_at_most_1_6_wide(available, expected):
    assert launch_geometry(available, FLOOR).normal == expected


def test_normal_geometry_never_below_the_floor():
    """On Windows 1366×768 @ 125 % 80 % of the height is 461 px; the floor wins."""
    available = QRect(0, 0, 1093, 576)
    normal = launch_geometry(available, FLOOR).normal
    assert normal.size() == QSize(800, 500)  # the 1.6 cap applies to the floored height
    assert available.contains(normal)


@pytest.mark.parametrize("available", [
    QRect(1440, 0, 1920, 1050), QRect(-1920, 25, 1920, 1055), QRect(0, 38, 1512, 944),
    QRect(2560, 0, 3440, 1400), QRect(0, 0, 640, 830), QRect(0, 0, 1080, 1850),
])
def test_normal_geometry_lies_centred_inside_the_available_area(available):
    normal = launch_geometry(available, FLOOR).normal
    assert available.contains(normal)
    assert abs(normal.center().x() - available.center().x()) <= 1
    assert abs(normal.center().y() - available.center().y()) <= 1
    assert normal.height() == max(FLOOR.height(), round(available.height() * NORMAL_SHARE))
    assert normal.width() <= max(FLOOR.width(), NORMAL_MAX_ASPECT * normal.height() + 1)


def test_launch_rule_constants_are_the_plan_values():
    assert (MAXIMIZE_BELOW_WIDTH, MAXIMIZE_MAX_ASPECT) == (2600, 2.0)
    assert (NORMAL_SHARE, NORMAL_MAX_ASPECT) == (0.8, 1.6)
