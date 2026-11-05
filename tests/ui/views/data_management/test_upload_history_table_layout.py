"""
Upload table sizing (plan M1.5): no wrapper scroll area and no 800-px minimum,
at least the header and three rows tall, content-sized columns with an elastic
middle-elided File Name, badges at their full size, Size right-aligned and
sorted by value, a px message font, and a context menu at the click position.
"""

from types import SimpleNamespace

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QApplication, QMenu, QScrollArea

from src.ui.components.badge import Badge
from src.ui.policy.tokens import TYPE_PX, TypeRole
from src.ui.views.data_management.components import upload_history_table
from src.ui.views.data_management.components.upload_history_table import UploadHistoryTable
from tests.ui.views.data_management._data import make_upload

COLUMNS = (UploadHistoryTable.COL_DATE, UploadHistoryTable.COL_FILENAME,
           UploadHistoryTable.COL_SIZE, UploadHistoryTable.COL_TYPE)


@pytest.fixture
def uploads(qtbot, app_stylesheet) -> SimpleNamespace:
    """A shown upload table with twelve four-badge rows."""
    widget = UploadHistoryTable()
    qtbot.addWidget(widget)
    widget.populate_uploads([make_upload(i) for i in range(12)])
    return SimpleNamespace(widget=widget, table=widget.table)


def _show(widget, width: int, height: int = 400) -> None:
    widget.resize(width, height)
    widget.show()
    for _ in range(4):
        QApplication.processEvents()


def _sections(table) -> list:
    header = table.horizontalHeader()
    return [header.sectionSize(column) for column in COLUMNS]


class TestSize:
    def test_no_wrapper_scroll_area_and_no_minimum_width(self, uploads):
        assert uploads.widget.findChildren(QScrollArea) == []
        assert uploads.table.parentWidget() is uploads.widget
        assert uploads.table.minimumWidth() == 0
        assert uploads.widget.minimumSizeHint().width() <= 200

    def test_minimum_and_preferred_height_are_the_header_and_three_rows(self, uploads):
        _show(uploads.widget, 1000)
        table = uploads.table
        rows = table.horizontalHeader().height() + 3 * table.rowHeight(0)
        assert abs(uploads.widget.minimumSizeHint().height() - rows) <= 2
        assert uploads.widget.sizeHint().height() == uploads.widget.minimumSizeHint().height()

    def test_rows_are_one_line_tall_and_fit_the_badges(self, uploads):
        _show(uploads.widget, 1000)
        table = uploads.table
        heights = {table.rowHeight(row) for row in range(table.rowCount())}
        assert heights == {uploads.widget._fit.row_height()}
        cell = table.cellWidget(0, UploadHistoryTable.COL_TYPE)
        assert cell.height() >= cell.minimumSizeHint().height()

    def test_vertical_scrollbar_stays_inside_a_narrow_table(self, uploads):
        _show(uploads.widget, 765)
        scrollbar = uploads.table.verticalScrollBar()
        assert scrollbar.isVisible()
        left = scrollbar.mapTo(uploads.widget, QPoint(0, 0)).x()
        assert left + scrollbar.width() <= uploads.widget.width()


class TestColumns:
    @pytest.mark.parametrize("width", [1400, 900, 420])
    def test_badges_are_never_clipped(self, uploads, width):
        _show(uploads.widget, width)
        for row in range(uploads.table.rowCount()):
            cell = uploads.table.cellWidget(row, UploadHistoryTable.COL_TYPE)
            assert cell.width() >= cell.sizeHint().width()
            for badge in cell.findChildren(Badge):
                assert badge.size() == badge.sizeHint()
                assert cell.rect().contains(badge.geometry())

    def test_wide_tables_give_the_spare_width_to_the_file_name(self, uploads):
        _show(uploads.widget, 1600)
        natural = uploads.widget._fit.natural_widths()
        sections = _sections(uploads.table)
        assert sections[0] == natural[0] and sections[2:] == natural[2:]
        assert sections[1] > natural[1]
        assert uploads.table.horizontalScrollBar().maximum() == 0

    def test_narrow_tables_elide_the_file_name_in_the_middle_first(self, uploads):
        _show(uploads.widget, 1600)
        table = uploads.table
        natural = uploads.widget._fit.natural_widths()
        chrome = uploads.widget.width() - table.viewport().width()
        _show(uploads.widget, sum(natural) - 60 + chrome)
        sections = _sections(table)
        assert sections[1] == natural[1] - 60
        assert sections[0] == natural[0] and sections[2:] == natural[2:]
        assert table.horizontalScrollBar().maximum() == 0
        assert table.textElideMode() == Qt.TextElideMode.ElideMiddle
        item = table.item(0, UploadHistoryTable.COL_FILENAME)
        assert item.toolTip() == item.text()

    def test_narrower_still_the_table_scrolls_inside_itself(self, uploads):
        _show(uploads.widget, 420)
        natural = uploads.widget._fit.natural_widths()
        assert _sections(uploads.table)[1] < natural[1]
        assert uploads.table.horizontalScrollBar().maximum() > 0
        assert uploads.widget.width() == 420


class TestSizeColumn:
    def test_sorts_by_value_not_text(self, qtbot, app_stylesheet):
        widget = UploadHistoryTable()
        qtbot.addWidget(widget)
        widget.populate_uploads([make_upload(i, size_mb) for i, size_mb
                                 in enumerate((0.5, 2.0, 10.0, 9.0, 123.4))])
        table = widget.table
        table.sortItems(UploadHistoryTable.COL_SIZE, Qt.SortOrder.AscendingOrder)
        texts = [table.item(row, UploadHistoryTable.COL_SIZE).text()
                 for row in range(table.rowCount())]
        assert texts == ["0.50 MB", "2.00 MB", "9.00 MB", "10.00 MB", "123.40 MB"]

    def test_is_right_aligned(self, uploads):
        alignment = uploads.table.item(0, UploadHistoryTable.COL_SIZE).textAlignment()
        assert alignment & Qt.AlignmentFlag.AlignRight.value


class TestEmptyHistory:
    def test_message_font_is_in_px_and_its_row_taller_than_a_data_row(self, qtbot, app_stylesheet):
        widget = UploadHistoryTable()
        qtbot.addWidget(widget)
        widget.populate_uploads([])
        _show(widget, 800)
        item = widget.table.item(0, 0)
        assert item.font().pixelSize() == TYPE_PX[TypeRole.CAPTION]
        assert item.font().pointSize() == -1
        assert widget.table.rowHeight(0) == round(2.5 * widget._fit.row_height())


class TestContextMenu:
    def test_opens_at_the_click_position(self, uploads, monkeypatch):
        shown_at = []

        class RecordingMenu(QMenu):
            def exec(self, position):
                shown_at.append(position)

        monkeypatch.setattr(upload_history_table, "QMenu", RecordingMenu)
        _show(uploads.widget, 1000)
        click = QPoint(40, 30)  # customContextMenuRequested is in viewport coordinates
        uploads.widget.show_context_menu(click)
        assert shown_at == [uploads.table.viewport().mapToGlobal(click)]
        assert shown_at[0] != uploads.table.mapToGlobal(click)
