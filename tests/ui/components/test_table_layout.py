"""
Tests for ``src.ui.components.table_layout``: content-sized columns that fill
the viewport when they fit and scroll inside the table when they don't, rows
sized from the font, elastic columns, and no resize feedback.
"""

import math

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QFontInfo
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QLabel, QTableWidget, QTableWidgetItem

from src.ui.components.table_layout import Elastic, FitColumnsController, fit_widths

# The stats tables' font and item padding (base_grouping_panel's table sheet).
STATS_QSS = "QTableWidget { font-size: 10px; } QTableWidget::item { padding: 2px; }"
CELL = "0.684 [0.601, 0.763]"
FILE_NAME = "Report_Json_Session_Report_20240115T101530.json"


def _make_table(qtbot, rows=3, columns=4, qss=STATS_QSS) -> QTableWidget:
    table = QTableWidget(rows, columns)
    table.setStyleSheet(qss)
    table.setHorizontalHeaderLabels([f"Column {c}" for c in range(columns)])
    for row in range(rows):
        for column in range(columns):
            table.setItem(row, column, QTableWidgetItem(CELL))
    qtbot.addWidget(table)
    return table


def _show(qtbot, table: QTableWidget, width: int, height: int = 200) -> None:
    table.resize(width, height)
    table.show()
    qtbot.wait(50)


def _resize_viewport(qtbot, table: QTableWidget, viewport_width: int) -> None:
    """Resize the table so its viewport is ``viewport_width`` px wide."""
    table.resize(viewport_width + table.width() - table.viewport().width(), table.height())
    qtbot.wait(50)


def _sections(table: QTableWidget) -> list:
    header = table.horizontalHeader()
    return [header.sectionSize(column) for column in range(header.count())]


class TestFitWidths:
    def test_spare_width_is_shared_in_proportion_to_natural(self):
        assert fit_widths([100, 50, 50], 400, floors={}, weights={}) == [200, 100, 100]

    def test_widths_sum_exactly_to_the_viewport(self):
        widths = fit_widths([33, 33, 34], 1001, floors={}, weights={})
        assert sum(widths) == 1001
        assert all(width >= natural for width, natural in zip(widths, [33, 33, 34]))

    def test_spare_goes_to_elastic_columns_by_weight(self):
        widths = fit_widths([100, 100, 100], 700, floors={0: 50, 2: 50}, weights={0: 1, 2: 3})
        assert widths == [200, 100, 400]

    def test_content_columns_keep_natural_widths_when_too_wide(self):
        assert fit_widths([300, 200], 100, floors={}, weights={}) == [300, 200]

    def test_elastic_columns_give_width_back_by_weight(self):
        widths = fit_widths([300, 300, 100], 500, floors={0: 50, 1: 50}, weights={0: 1, 1: 1})
        assert widths == [200, 200, 100]

    def test_elastic_columns_stop_at_their_floors(self):
        widths = fit_widths([300, 300, 100], 300, floors={0: 250, 1: 50}, weights={0: 1, 1: 1})
        assert widths == [250, 50, 100]

    def test_zero_weight_columns_never_flex(self):
        assert fit_widths([100, 100], 50, floors={0: 10}, weights={0: 0.0}) == [100, 100]
        assert fit_widths([100, 100], 300, floors={0: 10}, weights={0: 0.0}) == [100, 100]


class TestColumns:
    def test_fills_the_viewport_exactly_when_content_fits(self, qtbot):
        table = _make_table(qtbot)
        controller = FitColumnsController(table)
        _show(qtbot, table, controller.natural_width() + 300)
        assert abs(table.horizontalHeader().length() - table.viewport().width()) <= 1
        assert not table.horizontalScrollBar().isVisible()
        assert all(size >= natural for size, natural in zip(_sections(table), controller.natural_widths()))

    def test_scrolls_inside_the_table_when_content_does_not_fit(self, qtbot):
        table = _make_table(qtbot, columns=6)
        controller = FitColumnsController(table)
        _show(qtbot, table, 250)
        assert _sections(table) == controller.natural_widths()
        assert table.horizontalScrollBar().isVisible()
        assert table.horizontalScrollMode() == QAbstractItemView.ScrollMode.ScrollPerPixel

    def test_sections_are_fixed_so_header_modes_never_override_them(self, qtbot):
        table = _make_table(qtbot)
        FitColumnsController(table)
        header = table.horizontalHeader()
        assert all(header.sectionResizeMode(c) == QHeaderView.ResizeMode.Fixed for c in range(header.count()))
        assert not header.stretchLastSection()

    def test_a_spanned_message_does_not_widen_its_first_column(self, qtbot):
        from src.core.services.timeline_peri_event_service import InsufficientPeriEvent
        from src.ui.views.timeline_peri_event.components.grouping_panel import (
            TimelinePeriEventGroupingPanel,
        )
        panel = TimelinePeriEventGroupingPanel()
        qtbot.addWidget(panel)
        table = panel.stats_table
        controller = FitColumnsController(table)
        panel.populate_cluster_table({})
        without_message = controller.natural_widths()

        panel.populate_cluster_table({"Left": InsufficientPeriEvent("Left", "x" * 80, 1, 2)})
        assert table.columnSpan(0, 1) == 4
        assert table.sizeHintForIndex(table.model().index(0, 1)).width() > without_message[1]
        assert controller.natural_widths() == without_message

    def test_cell_widgets_count_toward_natural_width(self, qtbot):
        table = _make_table(qtbot, rows=1, columns=2)
        badge = QLabel("A cell widget wider than the cell's text")
        table.setCellWidget(0, 1, badge)
        assert FitColumnsController(table).natural_widths()[1] >= badge.sizeHint().width()

    def test_header_text_changes_are_remeasured(self, qtbot):
        table = _make_table(qtbot, rows=1, columns=2)
        controller = FitColumnsController(table)
        before = controller.natural_widths()[0]
        table.horizontalHeaderItem(0).setText("A header much longer than any of its cells")
        assert controller.natural_widths()[0] > before

    def test_never_changes_the_table_size_hints(self, qtbot):
        table = _make_table(qtbot, rows=30, columns=8)
        table.ensurePolished()
        before = (table.sizeHint(), table.minimumSizeHint())
        FitColumnsController(table)
        _show(qtbot, table, 300)
        assert (table.sizeHint(), table.minimumSizeHint()) == before


class TestElasticColumns:
    def _file_table(self, qtbot) -> QTableWidget:
        table = _make_table(qtbot, rows=3, columns=3)
        table.item(0, 1).setText(FILE_NAME)
        return table

    def test_elastic_column_takes_the_spare_width(self, qtbot):
        table = self._file_table(qtbot)
        controller = FitColumnsController(table, elastic={1: Elastic(min_em=8)})
        _show(qtbot, table, controller.natural_width() + 240)
        natural = controller.natural_widths()
        sections = _sections(table)
        assert (sections[0], sections[2]) == (natural[0], natural[2])
        assert abs(table.horizontalHeader().length() - table.viewport().width()) <= 1

    def test_elastic_column_shrinks_before_the_table_scrolls(self, qtbot):
        table = self._file_table(qtbot)
        controller = FitColumnsController(table, elastic={1: Elastic(min_em=8)})
        _show(qtbot, table, 800)
        natural = controller.natural_widths()
        _resize_viewport(qtbot, table, sum(natural) - 60)
        assert _sections(table) == [natural[0], natural[1] - 60, natural[2]]
        assert not table.horizontalScrollBar().isVisible()

    def test_elastic_column_stops_at_min_em_then_the_table_scrolls(self, qtbot):
        table = self._file_table(qtbot)
        controller = FitColumnsController(table, elastic={1: Elastic(min_em=8)})
        _show(qtbot, table, 800)
        natural = controller.natural_widths()
        floor = math.ceil(8 * QFontInfo(table.font()).pixelSize())
        assert natural[1] > floor
        _resize_viewport(qtbot, table, natural[0] + floor + natural[2] - 40)
        assert _sections(table) == [natural[0], floor, natural[2]]
        assert table.horizontalScrollBar().isVisible()

    def test_elastic_tables_elide_in_the_middle_on_one_line(self, qtbot):
        table = self._file_table(qtbot)
        FitColumnsController(table, elastic={1: Elastic(min_em=8)})
        assert table.textElideMode() == Qt.TextElideMode.ElideMiddle
        assert not table.wordWrap()

    def test_tables_without_elastic_columns_keep_their_elide_mode(self, qtbot):
        table = self._file_table(qtbot)
        FitColumnsController(table)
        assert table.textElideMode() == Qt.TextElideMode.ElideRight


class TestRows:
    def test_rows_are_fixed_at_the_content_height(self, qtbot):
        table = _make_table(qtbot, rows=4, columns=2)
        controller = FitColumnsController(table)
        _show(qtbot, table, 600)
        assert table.verticalHeader().sectionResizeMode(0) == QHeaderView.ResizeMode.Fixed
        for row in range(4):
            assert table.rowHeight(row) == controller.row_height()
            assert table.sizeHintForRow(row) <= table.rowHeight(row) <= table.sizeHintForRow(row) + 2

    def test_rows_follow_a_larger_and_back_to_the_normal_font(self, qtbot):
        table = _make_table(qtbot, rows=4, columns=2)
        controller = FitColumnsController(table)
        _show(qtbot, table, 600)
        regular = controller.row_height()

        table.setStyleSheet(STATS_QSS.replace("10px", "15px"))
        qtbot.wait(50)
        assert controller.row_height() > regular
        assert all(table.rowHeight(r) >= table.sizeHintForRow(r) for r in range(4))

        table.setStyleSheet(STATS_QSS)
        qtbot.wait(50)
        assert controller.row_height() == regular
        assert all(table.rowHeight(r) <= table.sizeHintForRow(r) + 2 for r in range(4))

    def test_an_empty_table_already_has_its_row_height(self, qtbot):
        empty = FitColumnsController(_make_table(qtbot, rows=0, columns=2))
        filled = FitColumnsController(_make_table(qtbot, rows=2, columns=2))
        assert empty.row_height() == filled.row_height()

    def test_cell_widgets_count_toward_row_height(self, qtbot):
        table = _make_table(qtbot, rows=1, columns=2)
        badge = QLabel("three\nline\nbadge")
        table.setCellWidget(0, 1, badge)
        assert FitColumnsController(table).row_height() >= badge.sizeHint().height()


class TestNoFeedback:
    @pytest.mark.parametrize("rows, extra", [(3, 0), (3, 12), (40, 0), (40, 12)])
    def test_settles_and_stays_settled(self, qtbot, rows, extra):
        """Near the fit boundary, with and without a vertical scrollbar."""
        table = _make_table(qtbot, rows=rows, columns=5)
        controller = FitColumnsController(table)
        _show(qtbot, table, 300)
        _resize_viewport(qtbot, table, controller.natural_width() + extra)
        resized = []
        table.horizontalHeader().sectionResized.connect(lambda *args: resized.append(args))
        qtbot.wait(100)
        assert resized == []

    def test_a_resize_redistributes_without_remeasuring(self, qtbot, monkeypatch):
        table = _make_table(qtbot, rows=5, columns=4)
        controller = FitColumnsController(table)
        natural = controller.natural_width()
        _show(qtbot, table, natural + 400)
        measured = []
        cell_hint = table.sizeHintForIndex
        monkeypatch.setattr(table, "sizeHintForIndex", lambda index: measured.append(index) or cell_hint(index))
        _resize_viewport(qtbot, table, natural + 100)
        assert measured == []
        assert abs(table.horizontalHeader().length() - table.viewport().width()) <= 1

        table.item(0, 0).setText("new content is measured again")
        qtbot.wait(50)
        assert measured
