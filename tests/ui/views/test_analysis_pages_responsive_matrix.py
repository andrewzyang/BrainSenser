"""The analysis pages at the window sizes that matter (plan §3.1, §3.3; M3.3, M4.4, D9).

One real MainWindow with the shipped stylesheet and the synthetic populated
state of tests/ui/_synthetic.py; its ResponsiveContext classifies every window
size and commands the pages, hidden ones too. Checked on all four pages:

- the grouping panel is STACKED exactly on the §3.1 sizes that call for it —
  the setup sections in one row above a full-width table that shows its header
  and at least four rows — and ROW elsewhere; re-placed, never re-created;
- compact pages have 8-px margins, a 220-px plot minimum, ~28-px controls and
  group lists of three full rows, and fit without a page scrollbar down to the
  window floor's height; regular pages keep today's metrics;
- after a round trip through compact and STACKED, a regular page is
  pixel-identical to what it was;
- the interface size reaches every plot through its page only, and exports are
  byte-identical whatever the interface size and the window size (I9).
"""

import hashlib
import time

import pytest
from PySide6.QtCore import QEvent, QSize, Qt
from PySide6.QtWidgets import (QAbstractSpinBox, QApplication, QComboBox, QLineEdit,
                               QPushButton, QWidget)

from src.ui.app_style import apply_app_stylesheet
from src.ui.layouts import ResponsiveContext
from src.ui.policy.layout import (BOUNDARIES, Arrangement, Density, HeightClass, WidthClass,
                                  choose_arrangement, classify_content)
from src.ui.policy.tokens import DENSITY_SPECS, Dim
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
from tests.ui._synthetic import EVENT_COUNTS, GROUP_1, populate_main_window, settle
from tests.ui.responsive import invariants
from tests.ui.responsive.profiles import COMMON_SIZES, VIEWPORTS

pytestmark = [pytest.mark.responsive, pytest.mark.slow]

PAGES = ("timeline_lfp_threshold", "timeline_peri_event", "snapshots_canonical_bands",
         "snapshots_5hz_band")
USERS_MAC = (1280, 769)
COMPACT_ROW = (1024, 560)   # a short laptop window: compact, ROW
TALL_SPLIT = (960, 1010)    # half of a 1080p screen: STACKED
# Compact controls are ~28 px: the three paddings of the panel's controls give 26–30.
COMPACT_CONTROL_HEIGHTS = range(26, 31)
EXPORT_SCALES = (1.0, 1.25, 1.5, 2.0)


@pytest.fixture(scope="module")
def stylesheet(qapp):
    """The shipped stylesheet for the module (restored afterwards)."""
    previous = qapp.styleSheet()
    apply_app_stylesheet(qapp)
    yield
    qapp.setStyleSheet(previous)


@pytest.fixture(scope="module")
def window(qapp, stylesheet, tmp_path_factory):
    """The populated main window."""
    import main
    from src.ui.app_bootstrap import build_presentation

    win = main.MainWindow(container=build_presentation().container)
    win.resize(*USERS_MAC)
    win.show()
    populate_main_window(win, tmp_path_factory.mktemp("appdata"), settle_ms=100)
    yield win
    win.close()
    win.deleteLater()
    qapp.processEvents()


def _at(window, size, page: str = None):
    """Show ``page`` at a window ``size``. A new size settles as after any
    discrete event: no resize for longer than a drag pause."""
    if window.size() != QSize(*size):
        window.resize(*size)
        deadline = time.monotonic() + 3 * ResponsiveContext.DRAG_PAUSE_MS / 1000
        while time.monotonic() < deadline:
            QApplication.processEvents()
            time.sleep(0.005)
    if page is not None:
        window.main_layout.switch_page(page)
    QApplication.sendPostedEvents(None, QEvent.Type.LayoutRequest)
    QApplication.processEvents()
    return window.main_layout.get_page(page) if page is not None else None


def _arrangement(page) -> str:
    return invariants.section_arrangement([s.geometry() for s in page.grouping_panel._sections])


def _host(window):
    return window.main_layout.content_stack.currentWidget()


def _controls(page) -> list:
    return [w for w in page.grouping_panel.findChildren(QWidget)
            if isinstance(w, (QPushButton, QComboBox, QLineEdit)) and w.isVisible()
            and not isinstance(w.parentWidget(), QAbstractSpinBox)]


def _plot(page):
    return page.grouping_panel.parentWidget().layout().itemAt(0).widget()


def _row_minimum(window) -> int:
    return max(window.main_layout.get_page(p).row_minimum_width() for p in PAGES) + Dim.SCROLLBAR


class TestArrangement:
    @pytest.mark.parametrize("size", list(COMMON_SIZES), ids=lambda s: f"{s[0]}x{s[1]}")
    def test_stacked_exactly_on_the_common_sizes_that_call_for_it(self, window, size):
        for name in PAGES:
            page = _at(window, size, name)
            assert _arrangement(page) == COMMON_SIZES[size], name

    @pytest.mark.parametrize("size", VIEWPORTS, ids=lambda s: f"{s[0]}x{s[1]}")
    def test_the_panel_follows_the_policy_at_every_viewport(self, window, size):
        _at(window, size)
        stack = window.main_layout.content_stack.size()
        want = choose_arrangement(stack.width(), stack.height(), _row_minimum(window))
        assert window.main_layout.responsive_context.density.arrangement is want
        for name in PAGES:
            assert _arrangement(_at(window, size, name)) == want.name, name

    def test_stacked_puts_the_table_under_the_setup_sections_across_the_panel(self, window):
        for name in PAGES:
            page = _at(window, TALL_SPLIT, name)
            panel = page.grouping_panel
            *setup, table = panel._sections
            margins = panel.layout().contentsMargins()
            assert table.width() == panel.width() - margins.left() - margins.right()
            assert sum(s.width() for s in setup) + 2 * panel.layout().horizontalSpacing() \
                == table.width()  # uncapped: the setup row spans the panel too
            stats = panel.stats_table
            header = stats.horizontalHeader().height()
            assert stats.viewport().height() >= 4 * stats.rowHeight(0), name
            assert stats.minimumHeight() >= header + 4 * stats.rowHeight(0)

    def test_arranging_re_places_the_sections_and_keeps_their_content(self, window):
        pages = [window.main_layout.get_page(name) for name in PAGES]

        def state():
            return [(frozenset(id(w) for w in page.findChildren(QWidget)),
                     [page.grouping_panel.group1_list.item(i).text()
                      for i in range(page.grouping_panel.group1_list.count())],
                     page.grouping_panel.stats_table.rowCount()) for page in pages]

        _at(window, USERS_MAC)
        before = state()
        for size in (TALL_SPLIT, COMPACT_ROW, USERS_MAC):
            _at(window, size)
        assert state() == before


class TestDensity:
    def test_regular_pages_keep_todays_metrics(self, window):
        spec = DENSITY_SPECS[HeightClass.REGULAR.value]
        for name in PAGES:
            page = _at(window, USERS_MAC, name)
            margins = page.content_stack.parentWidget().layout().contentsMargins()
            assert (margins.left(), margins.top()) == (spec.page_margin, spec.page_margin)
            assert _plot(page).minimumHeight() == spec.plot_min_height
            assert {c.height() for c in _controls(page)} <= {38, 40, 42}, name
            assert page.grouping_panel.property("density") in (None, "regular")

    def test_compact_pages_are_tighter(self, window):
        spec = DENSITY_SPECS[HeightClass.COMPACT.value]
        for name in PAGES:
            page = _at(window, COMPACT_ROW, name)
            stack_height = window.main_layout.content_stack.height()
            assert classify_content(stack_height) is HeightClass.COMPACT
            margins = page.content_stack.parentWidget().layout().contentsMargins()
            assert (margins.left(), margins.bottom()) == (spec.page_margin, spec.page_margin)
            assert _plot(page).minimumHeight() == spec.plot_min_height
            heights = {c.height() for c in _controls(page)}
            assert heights <= set(COMPACT_CONTROL_HEIGHTS), (name, heights)

    @pytest.mark.parametrize("height", [Dim.WINDOW_MIN_H, 540, 580, 620, 660])
    def test_compact_pages_fit_without_a_page_scrollbar(self, window, height):
        """From the window floor up to the regular boundary, at a ROW width."""
        for name in PAGES:
            page = _at(window, (COMPACT_ROW[0], height), name)
            assert window.size() == QSize(COMPACT_ROW[0], height)
            stack = window.main_layout.content_stack
            assert stack.height() < BOUNDARIES.compact_below
            assert window.main_layout.responsive_context.density.height is HeightClass.COMPACT
            assert _host(window).verticalScrollBar().maximum() == 0, (name, height)
            assert page.minimumSizeHint().height() <= stack.height()

    def test_hidden_pages_already_have_the_window_density(self, window):
        _at(window, USERS_MAC, "data_management")
        _at(window, COMPACT_ROW)
        for name in PAGES:
            page = window.main_layout.get_page(name)
            assert not page.isVisible()
            assert page.grouping_panel.property("density") == "compact"
            assert _plot(page).minimumHeight() == DENSITY_SPECS["compact"].plot_min_height

    def test_a_regular_page_is_pixel_identical_after_compact_and_stacked(self, window):
        for name in PAGES:
            page = _at(window, USERS_MAC, name)
            settle(window, 100)
            before = page.grab().toImage()
            for size in (TALL_SPLIT, COMPACT_ROW):
                _at(window, size, name)
                settle(window, 50)
            page = _at(window, USERS_MAC, name)
            settle(window, 100)
            assert page.grab().toImage() == before, name


@pytest.mark.parametrize("panel_type", [
    SnapshotsGroupingPanel, Snapshots5HzBandGroupingPanel,
    TimelineLfpThresholdGroupingPanel, TimelinePeriEventGroupingPanel,
], ids=lambda cls: cls.__name__)
def test_compact_group_lists_show_three_full_rows_at_the_panel_minimum(panel_type, qtbot,
                                                                       stylesheet):
    """D11 in both densities: at its compact minimum, a group list shows exactly three rows."""
    panel = panel_type()
    qtbot.addWidget(panel)
    panel.set_available_event_types(EVENT_COUNTS)
    for row in range(panel.event_types_list.count()):
        item = panel.event_types_list.item(row)
        item.setSelected(item.data(Qt.ItemDataRole.UserRole) in GROUP_1)
    panel._add_to_group(1)
    panel.apply_density(Density(WidthClass.WIDE, HeightClass.COMPACT, Arrangement.ROW))
    panel.resize(1048, panel.minimumSizeHint().height())
    panel.show()
    for _ in range(3):
        QApplication.processEvents()
    rows = DENSITY_SPECS[HeightClass.COMPACT.value].list_rows
    members = panel.group1_list
    assert members.count() > rows
    assert members.viewport().height() == rows * members.sizeHintForRow(0)


class TestInterfaceScale:
    """M4.4: Density.scale reaches the plots only through their pages; exports ignore it."""

    def test_set_scale_reaches_every_plot(self, window):
        context = window.main_layout.responsive_context
        _at(window, USERS_MAC)
        try:
            for scale in EXPORT_SCALES:
                context.set_scale(scale)
                for name in PAGES:
                    assert _plot(window.main_layout.get_page(name))._ui_scale == scale, name
        finally:
            context.set_scale(1.0)

    def test_exports_are_identical_at_every_interface_size_and_window_size(self, window,
                                                                          tmp_path):
        context = window.main_layout.responsive_context
        digests = {}
        try:
            for size in (USERS_MAC, COMPACT_ROW, TALL_SPLIT):
                for scale in EXPORT_SCALES:
                    _at(window, size)
                    context.set_scale(scale)
                    for name in PAGES:
                        plot = _plot(window.main_layout.get_page(name))
                        for fmt in ("png", "pdf", "svg"):
                            path = tmp_path / f"{name}.{fmt}"
                            plot.render_export(str(path), 100)
                            digests.setdefault((name, fmt), set()).add(
                                hashlib.md5(path.read_bytes()).hexdigest())
        finally:
            context.set_scale(1.0)
        assert all(len(found) == 1 for found in digests.values()), digests

    def test_only_the_page_scaffold_sets_a_plots_interface_size(self):
        """R5: the scale flows ResponsiveContext → page → plot, nowhere else."""
        from pathlib import Path
        root = Path(__file__).resolve().parents[3] / "src"
        callers = sorted(str(path.relative_to(root)) for path in root.rglob("*.py")
                         if ".set_ui_scale(" in path.read_text(encoding="utf-8"))
        assert callers == ["ui/views/_shared/analysis_page_scaffold.py"]
