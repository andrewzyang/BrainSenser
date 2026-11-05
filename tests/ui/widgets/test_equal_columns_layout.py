"""
Tests for ``src.ui.widgets.equal_columns_layout``: equal columns that reflow in
whole steps (4 → 2 → 1) by the items' own minimum widths, cells of equal size,
height-for-width, an optimistic minimum, and a layout that settles inside a
resizable scroll area.
"""

from types import SimpleNamespace

import pytest
from PySide6.QtCore import QEvent, QObject, QSize, Qt
from PySide6.QtWidgets import QApplication, QLabel, QScrollArea, QVBoxLayout, QWidget

from src.ui.widgets.equal_columns_layout import EqualColumnsLayout

ITEM_MIN_W = 150
H_SPACING = 24
V_SPACING = 16
LONG_TEXT = "a title long enough to wrap onto several lines in a narrow column " * 2


def _grid(qtbot, count: int = 4, column_counts=(4, 2, 1)) -> SimpleNamespace:
    """A box laid out by an EqualColumnsLayout of ``count`` word-wrapped labels.

    Keep the returned namespace for the whole test: it holds the only strong
    reference to the box, and Qt deletes the box (and the layout) without it.
    """
    box = QWidget()
    grid = EqualColumnsLayout(box, column_counts=column_counts,
                              horizontal_spacing=H_SPACING, vertical_spacing=V_SPACING)
    items = []
    for i in range(count):
        label = QLabel(f"item {i}")
        label.setWordWrap(True)
        label.setMinimumWidth(ITEM_MIN_W)
        grid.addWidget(label)
        items.append(label)
    qtbot.addWidget(box)
    return SimpleNamespace(box=box, grid=grid, items=items)


def _width_for(columns: int) -> int:
    """The narrowest width that holds ``columns`` columns of ITEM_MIN_W."""
    return columns * ITEM_MIN_W + (columns - 1) * H_SPACING


def _lay_out(box: QWidget, width: int, height: int = 600) -> None:
    box.resize(width, height)
    box.show()
    QApplication.sendPostedEvents(None, QEvent.Type.LayoutRequest)
    QApplication.processEvents()


def _cells(items) -> tuple:
    """(distinct column x positions, distinct row y positions) of the shown items."""
    shown = [item for item in items if not item.isHidden()]
    return sorted({i.geometry().x() for i in shown}), sorted({i.geometry().y() for i in shown})


class TestColumnCount:
    @pytest.mark.parametrize("width, columns", [
        (_width_for(4), 4),
        (_width_for(4) - 1, 2),
        (_width_for(3), 2),          # three never: no 3 + 1 orphan row
        (_width_for(2), 2),
        (_width_for(2) - 1, 1),
        (ITEM_MIN_W - 40, 1),        # narrower than one item: still one column
    ])
    def test_the_largest_allowed_count_that_fits(self, qtbot, width, columns):
        g = _grid(qtbot)
        assert g.grid.columns_for_width(width) == columns

    def test_the_counts_may_be_given_in_any_order(self, qtbot):
        g = _grid(qtbot, count=2, column_counts=(1, 2))
        assert g.grid.columns_for_width(_width_for(2)) == 2

    def test_the_widest_item_minimum_sets_the_count(self, qtbot):
        g = _grid(qtbot)
        assert g.grid.columns_for_width(_width_for(4)) == 4
        g.items[2].setMinimumWidth(ITEM_MIN_W + 10)
        assert g.grid.columns_for_width(_width_for(4)) == 2

    @pytest.mark.parametrize("columns, rows", [(4, 1), (2, 2), (1, 4)])
    def test_four_items_fill_one_row_two_by_two_or_one_column(self, qtbot, columns, rows):
        g = _grid(qtbot)
        _lay_out(g.box, _width_for(columns))
        xs, ys = _cells(g.items)
        assert (len(xs), len(ys)) == (columns, rows)
        # Row-major order: item i sits in column i % columns, row i // columns.
        assert [xs.index(i.x()) for i in g.items] == [i % columns for i in range(4)]
        assert [ys.index(i.y()) for i in g.items] == [i // columns for i in range(4)]


class TestCells:
    def test_columns_are_equal_and_span_the_width_exactly(self, qtbot):
        g = _grid(qtbot)
        g.grid.setContentsMargins(7, 5, 11, 3)
        width = 1001  # (1001 − 18 − 3·24) / 4 is not a whole number
        _lay_out(g.box, width)
        widths = [i.width() for i in g.items]
        assert max(widths) - min(widths) <= 1
        assert g.items[0].x() == 7
        assert g.items[-1].geometry().right() == width - 11 - 1
        assert [b.x() - (a.x() + a.width()) for a, b in zip(g.items, g.items[1:])] == [H_SPACING] * 3
        assert all(i.y() == 5 for i in g.items)

    def test_every_cell_is_as_tall_as_the_tallest_item_at_its_width(self, qtbot):
        g = _grid(qtbot)
        g.items[1].setText(LONG_TEXT)
        _lay_out(g.box, _width_for(2))
        tallest = max(i.heightForWidth(i.width()) for i in g.items)
        assert tallest > g.items[0].heightForWidth(g.items[0].width())
        assert {i.height() for i in g.items} == {tallest}

    @pytest.mark.parametrize("columns", [4, 2, 1])
    def test_height_for_width_is_the_height_the_layout_uses(self, qtbot, columns):
        g = _grid(qtbot)
        g.grid.setContentsMargins(3, 9, 3, 13)
        g.items[3].setText(LONG_TEXT)
        width = _width_for(columns) + 6
        _lay_out(g.box, width, height=2000)
        bottom = max(i.geometry().bottom() for i in g.items) + 1
        assert g.grid.heightForWidth(width) == bottom + 13
        assert g.items[-1].height() >= g.items[-1].heightForWidth(g.items[-1].width())

    def test_hidden_items_take_no_cell(self, qtbot):
        g = _grid(qtbot)
        g.items[1].setMinimumWidth(10 * ITEM_MIN_W)  # would force one column if counted
        g.items[1].hide()
        _lay_out(g.box, _width_for(4))
        shown = [i for i in g.items if not i.isHidden()]
        pitch = (_width_for(4) + H_SPACING) / 4
        assert g.grid.columns_for_width(_width_for(4)) == 4
        assert [i.x() for i in shown] == [round(column * pitch) for column in range(3)]


class TestSizes:
    def test_minimum_is_optimistic_one_row_of_the_widest_minimum(self, qtbot):
        g = _grid(qtbot)
        g.grid.setContentsMargins(4, 6, 8, 10)
        g.items[0].setMinimumHeight(40)
        assert g.grid.hasHeightForWidth()
        assert g.grid.minimumSize() == QSize(ITEM_MIN_W + 12, 40 + 16)
        # The true height at that width (one column, four rows) is far taller.
        assert g.grid.heightForWidth(g.grid.minimumSize().width()) > 4 * 40

    def test_size_hint_is_every_item_side_by_side(self, qtbot):
        g = _grid(qtbot)
        hint = g.grid.sizeHint()
        widest = max(i.sizeHint().width() for i in g.items)
        assert hint.width() == 4 * widest + 3 * H_SPACING
        assert hint.height() == g.grid.heightForWidth(hint.width())

    def test_expands_horizontally_only(self, qtbot):
        g = _grid(qtbot)
        assert g.grid.expandingDirections() == Qt.Orientation.Horizontal


class _LayoutRequests(QObject):
    def __init__(self):
        super().__init__()
        self.count = 0

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.LayoutRequest:
            self.count += 1
        return False


class TestInResizableScrollArea:
    def _area(self, qtbot) -> SimpleNamespace:
        g = _grid(qtbot)
        g.items[0].setText(LONG_TEXT)
        g.page = QWidget()
        column = QVBoxLayout(g.page)
        column.addWidget(g.box)
        column.addStretch()
        g.area = QScrollArea()
        g.area.setWidgetResizable(True)
        g.area.setWidget(g.page)
        qtbot.addWidget(g.area)
        g.area.show()
        return g

    @staticmethod
    def _resize(area: QScrollArea, width: int, height: int = 300) -> None:
        area.resize(width, height)
        for _ in range(3):
            QApplication.processEvents()

    def test_content_height_follows_the_reflowed_height(self, qtbot):
        g = self._area(qtbot)
        self._resize(g.area, 1100)
        assert g.area.verticalScrollBar().maximum() == 0
        self._resize(g.area, 260)
        viewport = g.area.viewport()
        assert g.page.height() == max(viewport.height(), g.page.heightForWidth(viewport.width()))
        assert g.area.verticalScrollBar().maximum() > 0

    def test_settles_without_idle_relayout_after_a_resize_sweep(self, qtbot):
        g = self._area(qtbot)
        for width in list(range(240, 1100, 23)) + list(range(1100, 240, -31)):
            self._resize(g.area, width)
        self._resize(g.area, _width_for(2) + 30)
        geometry = [i.geometry() for i in g.items]
        requests = _LayoutRequests()
        for watched in (g.page, g.box):
            watched.installEventFilter(requests)
        for _ in range(10):
            QApplication.processEvents()
        assert requests.count == 0
        assert [i.geometry() for i in g.items] == geometry
