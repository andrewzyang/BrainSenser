"""
EmptyStateWidget placement (D18): on regular pages the block keeps today's top
margin; on taller, huge-screen pages it moves into the upper area — never dead
centre, never lower than Dim.EMPTY_STATE_TOP_MAX — and it moves smoothly.
"""

import pytest
from PySide6.QtWidgets import QApplication, QLabel

from src.ui.components.empty_state import EmptyStateWidget
from src.ui.policy.tokens import Dim, Space


@pytest.fixture
def empty_state(qtbot) -> EmptyStateWidget:
    widget = EmptyStateWidget()
    qtbot.addWidget(widget)
    return widget


def _block_top(widget: EmptyStateWidget, height: int) -> int:
    """The y of the block's first item (the icon pill) at ``height``."""
    widget.resize(1000, height)
    widget.show()
    for _ in range(3):
        QApplication.processEvents()
    icon = next(label for label in widget.findChildren(QLabel) if not label.pixmap().isNull())
    return icon.y()


@pytest.mark.parametrize("height", [300, 654, Dim.EMPTY_STATE_REGULAR_H])
def test_regular_pages_keep_the_block_at_the_top_margin(empty_state, height):
    assert _block_top(empty_state, height) == Space.X10


def test_huge_pages_put_the_block_in_the_upper_area(empty_state):
    height = 2006  # the empty Data page on a maximised 4K window at 100 %
    top = _block_top(empty_state, height)
    assert Space.X10 < top <= Dim.EMPTY_STATE_TOP_MAX
    assert top < height / 4


def test_the_block_never_sits_below_the_cap(empty_state):
    assert _block_top(empty_state, 6000) == Dim.EMPTY_STATE_TOP_MAX


def test_the_block_moves_smoothly_and_returns(empty_state):
    tops = [_block_top(empty_state, height)
            for height in range(Dim.EMPTY_STATE_REGULAR_H, Dim.EMPTY_STATE_REGULAR_H + 400, 20)]
    steps = [b - a for a, b in zip(tops, tops[1:])]
    assert all(0 <= step <= 4 for step in steps) and tops[-1] > tops[0]
    assert _block_top(empty_state, 654) == Space.X10
