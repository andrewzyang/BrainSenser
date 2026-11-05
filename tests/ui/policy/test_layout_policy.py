"""Layout classification (plan §3.1, §4.4; M3.1): common sizes, drags, no flapping.

On discrete events the classes are computed without history, so every common
maximised size of plan §3.1 lands in the class the table assigns it, whatever
came before (I7b). While dragging, the previous class holds within the
hysteresis bands, so a ±1-px drag back and forth across a boundary changes the
class at most once, and the common sizes stay put even then: every boundary is
more than the ±8-px reach plus a band away from them. Boundaries come from
BOUNDARIES; the numbers here are the §3.1 sizes.
"""

import pytest

from src.ui.policy.layout import (
    BOUNDARIES, Arrangement, HeightClass, WidthClass,
    choose_arrangement, classify_content, classify_window,
)
from src.ui.policy.tokens import Dim

N, W = WidthClass.NARROW, WidthClass.WIDE
C, R = HeightClass.COMPACT, HeightClass.REGULAR
ROW, STACKED = Arrangement.ROW, Arrangement.STACKED

# Plan §3.1: window client size and the classes it gets. The content stack is
# the client area less the sidebar (icon rail when NARROW) and the top bar.
COMMON_SIZES = {
    "Windows 1366×768 @ 125 %": ((1093, 546), N, C, ROW),
    "Windows 1920×1080 @ 150 %": ((1280, 640), W, C, ROW),
    "1366×768 @ 100 %": ((1366, 697), W, R, ROW),
    "macOS Larger Text 13-inch": ((1024, 600), N, C, ROW),
    "the user's Mac, Dock hidden": ((1280, 769), W, R, ROW),
    "the user's Mac, Dock shown": ((1280, 706), W, R, ROW),
    "the user's Mac at 110 %": ((1164, 699), W, R, ROW),
    "the user's Mac at 125 %": ((1024, 615), N, C, ROW),
    "MacBook Pro 14-inch full screen": ((1512, 982), W, R, ROW),
    "half of a 1080p screen": ((960, 1010), N, R, STACKED),
    "macOS Split View tile": ((640, 830), N, R, STACKED),
    "portrait 1080×1920": ((1080, 1850), N, R, STACKED),
}
# The analysis pages' ROW minimum with a page host's scrollbar: ~550 px on
# macOS, ~560 at 96 dpi; the table holds for any value in this range.
ROW_MIN_WIDTHS = (480, 560, 640)
REACH = 8  # common sizes ±8 px (I7b)
FLAPS = 10


def _content(client: tuple, width_class: WidthClass) -> tuple:
    width, height = client
    sidebar = Dim.SIDEBAR_RAIL_W if width_class is WidthClass.NARROW else Dim.SIDEBAR_W
    return width - sidebar, height - Dim.TOPBAR_H


def _classes(client: tuple, row_min_width: int, prev=None, dragging=False) -> tuple:
    width_class = classify_window(client[0], prev and prev[0], dragging=dragging)
    width, height = _content(client, width_class)
    return (width_class,
            classify_content(height, prev and prev[1], dragging=dragging),
            choose_arrangement(width, height, row_min_width, prev and prev[2],
                               dragging=dragging))


EVERY_CLASS = [(w, h, a) for w in WidthClass for h in HeightClass for a in Arrangement]


class TestCommonSizes:
    @pytest.mark.parametrize("row_min_width", ROW_MIN_WIDTHS)
    @pytest.mark.parametrize("name", COMMON_SIZES)
    def test_each_common_size_gets_its_classes(self, name, row_min_width):
        client, *expected = COMMON_SIZES[name]
        assert _classes(client, row_min_width) == tuple(expected)

    @pytest.mark.parametrize("name", COMMON_SIZES)
    def test_within_reach_the_classes_never_depend_on_history(self, name):
        """I7b: ±8 px around a common size, arriving from any class, dragging or not."""
        client, *expected = COMMON_SIZES[name]
        for dx in range(-REACH, REACH + 1):
            for dy in (-REACH, 0, REACH):
                size = (client[0] + dx, client[1] + dy)
                for prev in EVERY_CLASS:
                    for dragging in (False, True):
                        got = _classes(size, ROW_MIN_WIDTHS[1], prev, dragging)
                        assert got == tuple(expected), (size, prev, dragging)


class TestDiscreteEvents:
    """Without dragging, the previous class never matters and the boundaries are exact."""

    def test_window_boundary(self):
        edge = BOUNDARIES.rail_below
        for prev in (None, *WidthClass):
            assert classify_window(edge - 1, prev) is N
            assert classify_window(edge, prev) is W

    def test_content_boundary(self):
        edge = BOUNDARIES.compact_below
        for prev in (None, *HeightClass):
            assert classify_content(edge - 1, prev) is C
            assert classify_content(edge, prev) is R

    def test_arrangement_boundaries(self):
        row_min, widest = 560, BOUNDARIES.stacked_max_width
        tall = round(widest / BOUNDARIES.stacked_enter_aspect) + 100  # aspect well below 'enter'
        for prev in (None, *Arrangement):
            assert choose_arrangement(row_min - 1, 100, row_min, prev) is STACKED
            assert choose_arrangement(row_min, 100, row_min, prev) is ROW
            assert choose_arrangement(widest - 1, tall, row_min, prev) is STACKED
            assert choose_arrangement(widest, tall, row_min, prev) is ROW
            height = 800
            enter = BOUNDARIES.stacked_enter_aspect * height
            assert choose_arrangement(int(enter) - 1, height, row_min, prev) is STACKED
            assert choose_arrangement(int(enter) + 1, height, row_min, prev) is ROW


class TestDragging:
    """While dragging, the previous class holds within the bands."""

    def test_window_band(self):
        edge, band = BOUNDARIES.rail_below, BOUNDARIES.rail_hysteresis
        assert classify_window(edge + band - 1, N, dragging=True) is N
        assert classify_window(edge + band, N, dragging=True) is W
        assert classify_window(edge - band, W, dragging=True) is W
        assert classify_window(edge - band - 1, W, dragging=True) is N

    def test_content_band(self):
        edge, band = BOUNDARIES.compact_below, BOUNDARIES.compact_hysteresis
        assert classify_content(edge + band - 1, C, dragging=True) is C
        assert classify_content(edge + band, C, dragging=True) is R
        assert classify_content(edge - band, R, dragging=True) is R
        assert classify_content(edge - band - 1, R, dragging=True) is C

    def test_row_minimum_band_is_one_sided(self):
        """ROW doesn't fit below its minimum, so it turns STACKED right there;
        STACKED holds a band beyond it."""
        row_min, band = 560, BOUNDARIES.stacked_hysteresis
        assert choose_arrangement(row_min - 1, 100, row_min, ROW, dragging=True) is STACKED
        assert choose_arrangement(row_min + band - 1, 100, row_min, STACKED, dragging=True) is STACKED
        assert choose_arrangement(row_min + band, 100, row_min, STACKED, dragging=True) is ROW

    def test_aspect_band(self):
        height = 800
        enter = BOUNDARIES.stacked_enter_aspect * height
        leave = BOUNDARIES.stacked_leave_aspect * height
        between = int((enter + leave) / 2)
        assert choose_arrangement(between, height, 560, ROW, dragging=True) is ROW
        assert choose_arrangement(between, height, 560, STACKED, dragging=True) is STACKED
        assert choose_arrangement(int(leave), height, 560, STACKED, dragging=True) is STACKED
        assert choose_arrangement(int(leave) + 1, height, 560, STACKED, dragging=True) is ROW


def _changes(classes: list) -> int:
    return sum(a is not b for a, b in zip(classes, classes[1:]))


def _drag(classify, values: list, start):
    """Classes along a drag through ``values``, starting in class ``start``."""
    seen, prev = [], start
    for value in values:
        prev = classify(value, prev)
        seen.append(prev)
    return seen


def _jitter(edge: int) -> list:
    """±1 px back and forth across ``edge``, FLAPS times, from either side."""
    return [edge - 1, edge, edge + 1, edge, edge - 1] * FLAPS


class TestNoFlapping:
    """I7b anti-flap: a ±1-px drag across any boundary changes the class at most once."""

    @pytest.mark.parametrize("start", list(WidthClass))
    def test_window(self, start):
        for edge in (BOUNDARIES.rail_below, BOUNDARIES.rail_below + BOUNDARIES.rail_hysteresis,
                     BOUNDARIES.rail_below - BOUNDARIES.rail_hysteresis):
            seen = _drag(lambda w, p: classify_window(w, p, dragging=True), _jitter(edge), start)
            assert _changes([start] + seen) <= 1, (edge, seen)

    @pytest.mark.parametrize("start", list(HeightClass))
    def test_content(self, start):
        for edge in (BOUNDARIES.compact_below,
                     BOUNDARIES.compact_below + BOUNDARIES.compact_hysteresis,
                     BOUNDARIES.compact_below - BOUNDARIES.compact_hysteresis):
            seen = _drag(lambda h, p: classify_content(h, p, dragging=True), _jitter(edge), start)
            assert _changes([start] + seen) <= 1, (edge, seen)

    @pytest.mark.parametrize("start", list(Arrangement))
    def test_arrangement_by_width(self, start):
        row_min, band = 560, BOUNDARIES.stacked_hysteresis
        widest = BOUNDARIES.stacked_max_width
        tall = round(widest / BOUNDARIES.stacked_enter_aspect) + 100
        for edge, height in ((row_min, 100), (row_min + band, 100),
                             (widest, tall), (widest + band, tall), (widest - band, tall)):
            seen = _drag(lambda w, p: choose_arrangement(w, height, row_min, p, dragging=True),
                         _jitter(edge), start)
            assert _changes([start] + seen) <= 1, (edge, seen)

    @pytest.mark.parametrize("start", list(Arrangement))
    def test_arrangement_by_aspect(self, start):
        width = 1000
        for aspect in (BOUNDARIES.stacked_enter_aspect, BOUNDARIES.stacked_leave_aspect):
            edge = round(width / aspect)
            seen = _drag(lambda h, p: choose_arrangement(width, h, 560, p, dragging=True),
                         _jitter(edge), start)
            assert _changes([start] + seen) <= 1, (aspect, seen)

    def test_a_drag_from_far_away_reaches_the_history_free_class(self):
        """Dragging across a whole band ends where a discrete event would put it."""
        edge, band = BOUNDARIES.rail_below, BOUNDARIES.rail_hysteresis
        down = _drag(lambda w, p: classify_window(w, p, dragging=True),
                     list(range(edge + 2 * band, edge - 2 * band, -1)), W)
        assert down[-1] is classify_window(edge - 2 * band + 1)
        assert _changes(down) == 1
