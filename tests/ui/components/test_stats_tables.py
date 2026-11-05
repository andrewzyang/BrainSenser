"""
The statistics tables of the four grouping panels (plan M1.6, D10).

Columns are as wide as their content, fill the table when they fit and scroll
inside it when they don't (FitColumnsController); the header is measured in the
font it paints with; rows are one line of the table font; there is no
row-number column; a near fit narrows the header padding instead of scrolling;
Shift+wheel scrolls sideways; spanned messages keep their full text as a
tooltip; an earlier span never outlives its result. Synthetic results only.
"""

import gc
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QFontInfo, QTextDocument, QWheelEvent
from PySide6.QtWidgets import QAbstractItemView, QApplication, QTableWidget

from src.core.services.timeline_peri_event_service import InsufficientPeriEvent
from src.core.services.timeline_threshold_ml_service import InsufficientResult, ThresholdMlResult
from src.ui.app_style import apply_app_stylesheet
from src.ui.components.table_layout import FitColumnsController
from src.ui.policy.tokens import Dim
from src.ui.views.snapshots_5hz_band.components.grouping_panel import (
    Snapshots5HzBandGroupingPanel,
)
from src.ui.views.snapshots_psd.components.grouping_panel import SnapshotsGroupingPanel
from src.ui.views.timeline_lfp_threshold.components.grouping_panel import (
    TimelineLfpThresholdGroupingPanel,
)
from src.ui.views.timeline_peri_event.components.grouping_panel import (
    TimelinePeriEventGroupingPanel,
)


def _psd_rows():
    return [dict(band_label=f"{band} ({hemi})", freq_range=freq, group1_median_text="0.734",
                 group2_median_text="1.208", central_tendency_ci_text="[-0.123, 0.456]",
                 p_value_text="0.0123", p_value_highlight=True, q_value_text="0.0456",
                 q_value_highlight=False, effect_size_value_text="0.345",
                 effect_size_ci_text="[0.123, 0.567]")
            for hemi in ("L", "R")
            for band, freq in (("Delta", "1-4 Hz"), ("Theta", "4-8 Hz"), ("Alpha", "8-13 Hz"),
                               ("Beta", "13-30 Hz"), ("Gamma_low", "30-40 Hz"))]


def _auc_profile(modal: int):
    centers = 7.75 + np.arange(11) * 2.93
    auc = np.full(centers.size, 0.6)
    return SimpleNamespace(band_centers_hz=centers, band_edges_hz=np.c_[centers - 2.44, centers + 2.44],
                           per_band_auc=auc, per_band_ci_lo=auc - 0.08, per_band_ci_hi=auc + 0.08,
                           modal_band_idx=modal, fwer_p=0.0021, n_perm=10000)


def _threshold_result(hemisphere: str):
    return MagicMock(spec=ThresholdMlResult, hemisphere=hemisphere, n_neutral=114, n_craving=70,
                     lr_threshold=985.0, lr_threshold_ci=(940.0, 1030.0), auc_loo=0.684,
                     auc_ci=(0.601, 0.763), sensitivity_lr=0.6, sens_ci=(0.48, 0.71),
                     specificity_lr=0.68, spec_ci=(0.59, 0.76), mann_whitney_p=0.0003,
                     perm_p=1 / 1001, perm_p_floor=1 / 1001, verdict=True)


def _fill(panel):
    """Synthetic results in ``panel``'s table."""
    if isinstance(panel, SnapshotsGroupingPanel):
        panel.set_effect_size_header("Rank-biserial r")
        panel.update_statistics_table(_psd_rows())
    elif isinstance(panel, Snapshots5HzBandGroupingPanel):
        panel.populate_ml_table(_auc_profile(1), _auc_profile(2))
    elif isinstance(panel, TimelineLfpThresholdGroupingPanel):
        panel.populate_threshold_table({"Left": _threshold_result("Left"),
                                        "Right": _threshold_result("Right")})
    else:
        panel.populate_cluster_table({})
    return panel


PANELS = [SnapshotsGroupingPanel, Snapshots5HzBandGroupingPanel,
          TimelineLfpThresholdGroupingPanel, TimelinePeriEventGroupingPanel]


@pytest.fixture(scope="module", autouse=True)
def app_style(qapp):
    """The production stylesheet, once for the module (a restyle re-polishes
    every live widget); the previous one is back afterwards."""
    previous = qapp.styleSheet()
    apply_app_stylesheet(qapp)
    yield
    qapp.setStyleSheet(previous)


@pytest.fixture(params=PANELS, ids=lambda cls: cls.__name__)
def panel(request, qtbot):
    widget = _fill(request.param())
    qtbot.addWidget(widget)
    return widget


def _settle():
    for _ in range(5):  # the controller refits on a 0-ms timer
        QApplication.processEvents()


def _alone(panel, viewport_width: int, height: int = 600):
    """``panel``'s table on its own, with a viewport ``viewport_width`` px wide."""
    table = panel.stats_table
    table.setParent(None)
    table.resize(viewport_width, height)
    table.show()
    _settle()
    table.resize(viewport_width + table.width() - table.viewport().width(), height)
    _settle()
    return table


def _plain(text: str) -> str:
    doc = QTextDocument()
    doc.setHtml(text)
    return doc.toPlainText()


class TestLayout:
    def test_header_is_measured_in_the_table_font(self, panel):
        header = panel.stats_table.horizontalHeader()
        assert QFontInfo(header.font()).pixelSize() == QFontInfo(panel.stats_table.font()).pixelSize()

    def test_no_row_number_column(self, panel):
        assert panel.stats_table.verticalHeader().isHidden()

    def test_rows_are_one_line_of_the_table_font(self, panel):
        table = _alone(panel, 1200)
        assert table.rowCount() > 0
        for row in range(table.rowCount()):
            assert table.sizeHintForRow(row) <= table.rowHeight(row) <= table.sizeHintForRow(row) + 1

    def test_columns_fill_the_table_when_they_fit(self, panel):
        natural = panel._stats_columns.natural_width()
        table = _alone(panel, natural + 300)
        assert abs(table.horizontalHeader().length() - table.viewport().width()) <= 1
        assert not table.horizontalScrollBar().isVisible()

    def test_columns_scroll_inside_the_table_when_they_do_not(self, qtbot):
        panel = _fill(SnapshotsGroupingPanel())
        qtbot.addWidget(panel)
        natural = panel._stats_columns.natural_widths()
        table = _alone(panel, sum(natural) // 2)
        header = table.horizontalHeader()
        assert [header.sectionSize(c) for c in range(header.count())] == natural
        assert table.horizontalScrollBar().isVisible()
        assert table.horizontalScrollMode() == QAbstractItemView.ScrollMode.ScrollPerPixel

    def test_table_scrollbars_are_easy_to_grab(self, panel):
        table = panel.stats_table
        assert table.horizontalScrollBar().sizeHint().height() == Dim.TABLE_SCROLLBAR
        assert table.verticalScrollBar().sizeHint().width() == Dim.TABLE_SCROLLBAR

    def test_psd_columns_are_all_centred(self, qtbot):
        panel = _fill(SnapshotsGroupingPanel())
        qtbot.addWidget(panel)
        table = panel.stats_table
        assert {Qt.AlignmentFlag(table.item(row, column).textAlignment())
                for row in range(table.rowCount()) for column in range(table.columnCount())
                } == {Qt.AlignmentFlag.AlignCenter}


class TestNearFit:
    """A table at most Dim.TABLE_NEAR_FIT px too wide tightens its header padding."""

    def test_a_near_fit_tightens_the_padding_instead_of_scrolling(self, qtbot):
        panel = _fill(SnapshotsGroupingPanel())
        qtbot.addWidget(panel)
        regular = panel._stats_columns.natural_width()
        table = _alone(panel, regular - Dim.TABLE_NEAR_FIT + 4)
        assert panel._stats_columns.natural_width() < table.viewport().width()
        assert not table.horizontalScrollBar().isVisible()
        header = table.horizontalHeader()
        assert all(header.sectionSize(c) >= header.sectionSizeHint(c) for c in range(header.count()))

    def test_a_table_that_scrolls_anyway_keeps_the_regular_padding(self, qtbot):
        panel = _fill(SnapshotsGroupingPanel())
        qtbot.addWidget(panel)
        regular = panel._stats_columns.natural_width()
        table = _alone(panel, regular - Dim.TABLE_NEAR_FIT - 40)
        assert panel._stats_columns.natural_width() == regular
        assert table.horizontalScrollBar().isVisible()

    def test_the_padding_comes_back_when_the_table_fits_again(self, qtbot):
        panel = _fill(SnapshotsGroupingPanel())
        qtbot.addWidget(panel)
        regular = panel._stats_columns.natural_width()
        table = _alone(panel, regular - 8)
        assert panel._stats_columns.natural_width() < regular
        table.resize(table.width() + 40, table.height())
        _settle()
        assert panel._stats_columns.natural_width() == regular
        assert abs(table.horizontalHeader().length() - table.viewport().width()) <= 1


class TestShiftWheel:
    def _wheel(self, table, modifiers):
        center = QPointF(table.viewport().rect().center())
        QApplication.sendEvent(table.viewport(), QWheelEvent(
            center, QPointF(table.viewport().mapToGlobal(center.toPoint())), QPoint(),
            QPoint(0, -120), Qt.MouseButton.NoButton, modifiers, Qt.ScrollPhase.NoScrollPhase,
            False))

    def test_shift_wheel_scrolls_sideways(self, qtbot):
        panel = _fill(SnapshotsGroupingPanel())
        qtbot.addWidget(panel)
        table = _alone(panel, panel._stats_columns.natural_width() // 2, height=120)
        sideways, down = table.horizontalScrollBar(), table.verticalScrollBar()
        self._wheel(table, Qt.KeyboardModifier.ShiftModifier)
        assert sideways.value() > 0
        assert down.value() == 0

    def test_a_plain_wheel_still_scrolls_down(self, qtbot):
        panel = _fill(SnapshotsGroupingPanel())
        qtbot.addWidget(panel)
        table = _alone(panel, panel._stats_columns.natural_width() // 2, height=120)
        self._wheel(table, Qt.KeyboardModifier.NoModifier)
        assert table.horizontalScrollBar().value() == 0
        assert table.verticalScrollBar().value() > 0


def test_a_table_freed_from_python_tears_down_quietly(qtbot):
    """The column controller still gets events and model signals while Qt
    destroys its table; they must not reach a half-released Python object."""
    table = QTableWidget(3, 3)
    FitColumnsController(table)
    table.show()
    QApplication.processEvents()
    with qtbot.captureExceptions() as exceptions:
        del table
        gc.collect()
    assert exceptions == []


class TestSpans:
    def test_peri_event_insufficient_message_keeps_its_full_text(self, qtbot):
        panel = TimelinePeriEventGroupingPanel()
        qtbot.addWidget(panel)
        panel.populate_cluster_table({"Left": InsufficientPeriEvent("Left", "x" * 80, 1, 2)})
        message = panel.stats_table.item(0, 1)
        assert panel.stats_table.columnSpan(0, 1) == 4
        assert _plain(message.toolTip()) == message.text()

    def test_threshold_insufficient_message_keeps_its_full_text(self, qtbot):
        panel = TimelineLfpThresholdGroupingPanel()
        qtbot.addWidget(panel)
        panel.populate_threshold_table({"Left": InsufficientResult("Left", "y" * 80, 1, 2),
                                        "Right": _threshold_result("Right")})
        message = panel.stats_table.item(0, 1)
        assert panel.stats_table.columnSpan(0, 1) == 7
        assert _plain(message.toolTip()) == message.text()

    def test_a_full_result_drops_an_earlier_span(self, qtbot):
        panel = TimelineLfpThresholdGroupingPanel()
        qtbot.addWidget(panel)
        panel.populate_threshold_table({"Left": InsufficientResult("Left", "too few", 1, 2),
                                        "Right": _threshold_result("Right")})
        panel.populate_threshold_table({"Left": _threshold_result("Left"),
                                        "Right": _threshold_result("Right")})
        table = panel.stats_table
        assert all(table.columnSpan(row, column) == 1
                   for row in range(table.rowCount()) for column in range(table.columnCount()))
        assert table.item(0, 2).text() == "985 [940, 1030]"
