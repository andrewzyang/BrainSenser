"""ResponsiveContext and its home in MainLayout (plan §4.4, §4.7; M3.2).

A fake shell — a window area holding a sidebar and the content stack — and
recording pages. Registered pages get the current density at once, hidden ones
too; a burst of resizes is classified once, on the next event-loop turn, with
the window class first and the content classes measured after its layout
change; the hidden pages are commanded before the shown one. Classes have no
history on discrete events, hold within the bands during a drag (resize bursts
closer than DRAG_PAUSE_MS), and are computed afresh once the drag pauses.
"""

from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QHBoxLayout, QLabel, QStackedWidget, QWidget

from src.ui.components import Sidebar, TopBar
from src.ui.layouts import MainLayout, PageHost, ResponsiveContext
from src.ui.policy.layout import (BOUNDARIES, Arrangement, Density, HeightClass,
                                  WidthClass)
from src.ui.policy.tokens import Dim

DEFAULT = Density(WidthClass.WIDE, HeightClass.REGULAR, Arrangement.ROW)
# A window area comfortably inside every class: wide, regular and ROW.
AT_REST = (1400, 800)


class _Page(QWidget):
    """A DensityAware page that records every density it is commanded with."""

    def __init__(self, log: list = None, name: str = ""):
        super().__init__()
        self.densities = []
        self._log, self._name = log, name

    def apply_density(self, density: Density) -> None:
        self.densities.append(density)
        if self._log is not None:
            self._log.append(("push", self._name))


class _ArrangedPage(_Page):
    """An ArrangementAware page with a fixed ROW minimum."""

    def __init__(self, row_minimum: int, **kwargs):
        super().__init__(**kwargs)
        self._row_minimum = row_minimum

    def row_minimum_width(self) -> int:
        return self._row_minimum


def _settle(qapp, rounds: int = 3) -> None:
    """A few event-loop turns: quick enough to stay inside one drag."""
    for _ in range(rounds):
        qapp.processEvents()


@pytest.fixture
def make_shell(qtbot, qapp, monkeypatch):
    """A shown window area at rest: a sidebar beside the content stack, which
    becomes the icon rail when the window class is NARROW, as the real one does
    through ShellViewModel. ``drag_pause_ms`` overrides DRAG_PAUSE_MS."""
    def make(drag_pause_ms: int = None) -> SimpleNamespace:
        if drag_pause_ms is not None:
            monkeypatch.setattr(ResponsiveContext, "DRAG_PAUSE_MS", drag_pause_ms)
        area = QWidget()
        layout = QHBoxLayout(area)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        sidebar = QWidget()
        sidebar.setFixedWidth(Dim.SIDEBAR_W)
        content = QStackedWidget()
        layout.addWidget(sidebar)
        layout.addWidget(content)
        qtbot.addWidget(area)
        context = ResponsiveContext(area, content)
        emitted = []

        def on_window_class(value: str) -> None:
            emitted.append(value)
            sidebar.setFixedWidth(Dim.SIDEBAR_RAIL_W if value == "narrow" else Dim.SIDEBAR_W)

        context.window_class_changed.connect(on_window_class)
        area.resize(*AT_REST)
        area.show()
        _settle(qapp)
        return SimpleNamespace(area=area, sidebar=sidebar, content=content, context=context,
                               emitted=emitted)
    return make


@pytest.fixture
def shell(make_shell):
    return make_shell()


def _page(shell, page=None) -> _Page:
    page = page or _Page()
    shell.content.addWidget(page)
    shell.context.register(page)
    return page


def _resize(shell, qapp, width: int, height: int) -> None:
    shell.area.resize(width, height)
    _settle(qapp)


class TestConstruction:
    def test_starts_wide_regular_row_at_scale_one(self, shell, qtbot):
        assert (shell.context.width_class, shell.context.density) == (WidthClass.WIDE, DEFAULT)
        with qtbot.assertNotEmitted(shell.context.window_class_changed):
            shell.context.reclassify_now()
        assert shell.emitted == []


class TestRegister:
    def test_a_page_gets_the_current_density_at_once(self, shell):
        page = _page(shell)
        assert page.densities == [DEFAULT]

    def test_a_hidden_page_is_commanded_too(self, shell, qapp):
        shown, hidden = _page(shell), _page(shell)
        assert hidden.isHidden()
        _resize(shell, qapp, AT_REST[0], BOUNDARIES.compact_below - 100)
        assert shown.densities[-1].height is hidden.densities[-1].height is HeightClass.COMPACT

    def test_pages_without_apply_density_are_left_alone(self, shell, qapp):
        plain = QLabel("not density-aware")
        shell.content.addWidget(plain)
        shell.context.register(plain)
        _resize(shell, qapp, AT_REST[0], BOUNDARIES.compact_below - 100)
        assert shell.context.density.height is HeightClass.COMPACT


class TestClassification:
    def test_the_content_height_sets_the_density(self, shell, qapp):
        page = _page(shell)
        _resize(shell, qapp, AT_REST[0], BOUNDARIES.compact_below - 100)
        assert page.densities[-1].height is HeightClass.COMPACT
        _resize(shell, qapp, AT_REST[0], BOUNDARIES.compact_below + 100)
        assert page.densities[-1].height is HeightClass.REGULAR

    def test_the_arranged_pages_row_minimum_and_a_scrollbar_set_the_arrangement(self, shell, qapp):
        page = _page(shell, _ArrangedPage(700))
        width = Dim.SIDEBAR_RAIL_W + 700 + Dim.SCROLLBAR  # NARROW: the sidebar is the rail
        _resize(shell, qapp, width - 1, 400)
        assert page.densities[-1].arrangement is Arrangement.STACKED
        _resize(shell, qapp, AT_REST[0], AT_REST[1])
        _resize(shell, qapp, width, 400)
        assert page.densities[-1].arrangement is Arrangement.ROW

    def test_the_content_classes_see_the_window_class_layout_change(self, shell, qapp):
        """Narrow: the rail gives the content stack the width ROW needs."""
        page = _page(shell, _ArrangedPage(900))
        _resize(shell, qapp, BOUNDARIES.rail_below - 100, 400)  # NARROW: 956 beside the rail
        assert shell.sidebar.width() == Dim.SIDEBAR_RAIL_W
        assert page.densities[-1] == Density(WidthClass.NARROW, HeightClass.COMPACT,
                                             Arrangement.ROW)

    def test_one_push_per_burst_with_the_final_classes(self, shell, qapp):
        page = _page(shell)
        for height in (500, 900, 500, 900, 500):
            shell.area.resize(BOUNDARIES.rail_below - 100, height)
        assert page.densities == [DEFAULT]  # nothing until the event loop runs
        _settle(qapp)
        assert page.densities == [DEFAULT, Density(WidthClass.NARROW, HeightClass.COMPACT,
                                                   Arrangement.ROW)]
        assert shell.emitted == ["narrow"]

    def test_unchanged_classes_push_nothing(self, shell, qapp):
        page = _page(shell)
        for width in range(AT_REST[0], AT_REST[0] + 50, 10):
            _resize(shell, qapp, width, AT_REST[1])
        assert page.densities == [DEFAULT]
        assert shell.emitted == []

    def test_the_window_class_comes_first_then_hidden_pages_then_the_shown_one(self, shell, qapp):
        log = []
        shell.context.window_class_changed.connect(lambda value: log.append(("emit", value)))
        _page(shell, _Page(log, "shown"))
        _page(shell, _Page(log, "hidden"))
        log.clear()
        _resize(shell, qapp, BOUNDARIES.rail_below - 100, AT_REST[1])
        assert log == [("emit", "narrow"), ("push", "hidden"), ("push", "shown")]


class TestHistory:
    def test_discrete_events_have_no_history(self, shell, qapp, qtbot):
        """Resizes further apart than DRAG_PAUSE_MS: the exact boundary every time."""
        page = _page(shell)
        pause = shell.context.DRAG_PAUSE_MS * 2
        for height, expected in ((BOUNDARIES.compact_below - 5, HeightClass.COMPACT),
                                 (BOUNDARIES.compact_below + 5, HeightClass.REGULAR),
                                 (BOUNDARIES.compact_below - 5, HeightClass.COMPACT)):
            qtbot.wait(pause)
            _resize(shell, qapp, AT_REST[0], height)
            assert page.densities[-1].height is expected

    def test_a_drag_holds_the_class_within_the_band_and_never_flaps(self, make_shell, qapp):
        shell = make_shell(drag_pause_ms=60_000)  # every resize below is one drag
        page = _page(shell)
        edge = BOUNDARIES.compact_below
        for _ in range(10):
            for height in (edge + 1, edge, edge - 1, edge, edge + 1):
                _resize(shell, qapp, AT_REST[0], height)
        assert [d.height for d in page.densities] == [HeightClass.REGULAR]
        _resize(shell, qapp, AT_REST[0], edge - BOUNDARIES.compact_hysteresis - 1)
        for _ in range(10):
            for height in (edge + 1, edge, edge - 1):
                _resize(shell, qapp, AT_REST[0], height)
        assert [d.height for d in page.densities] == [HeightClass.REGULAR, HeightClass.COMPACT]

    def test_once_the_drag_pauses_the_classes_are_computed_afresh(self, make_shell, qapp,
                                                                  qtbot):
        shell = make_shell(drag_pause_ms=300)
        page = _page(shell)
        _resize(shell, qapp, AT_REST[0], BOUNDARIES.compact_below - 5)  # within the band
        assert page.densities[-1].height is HeightClass.REGULAR
        qtbot.waitUntil(lambda: page.densities[-1].height is HeightClass.COMPACT, timeout=3000)

    def test_reclassify_now_is_immediate_and_has_no_history(self, make_shell, qapp):
        shell = make_shell(drag_pause_ms=60_000)
        page = _page(shell)
        _resize(shell, qapp, AT_REST[0], BOUNDARIES.compact_below - 5)
        assert page.densities[-1].height is HeightClass.REGULAR  # held by the drag
        shell.area.resize(BOUNDARIES.rail_below - 100, BOUNDARIES.compact_below - 5)
        shell.context.reclassify_now()
        assert shell.emitted == ["narrow"]
        assert page.densities[-1] == Density(WidthClass.NARROW, HeightClass.COMPACT,
                                             Arrangement.ROW)


class TestScale:
    def test_set_scale_pushes_the_factor_once(self, shell):
        page = _page(shell)
        shell.context.set_scale(1.25)
        shell.context.set_scale(1.25)
        assert page.densities == [DEFAULT, Density(WidthClass.WIDE, HeightClass.REGULAR,
                                                   Arrangement.ROW, 1.25)]

    def test_the_scale_survives_reclassification(self, shell, qapp):
        page = _page(shell)
        shell.context.set_scale(1.5)
        _resize(shell, qapp, AT_REST[0], BOUNDARIES.compact_below - 100)
        assert (page.densities[-1].height, page.densities[-1].scale) == (HeightClass.COMPACT, 1.5)


class TestMainLayout:
    @pytest.fixture
    def layout(self, qtbot):
        layout = MainLayout(Sidebar(), TopBar())
        qtbot.addWidget(layout)
        return layout

    def test_owns_a_context_on_its_own_width_and_the_content_stack(self, layout, qapp):
        assert isinstance(layout.responsive_context, ResponsiveContext)
        assert layout.responsive_context.parent() is layout
        layout.resize(BOUNDARIES.rail_below - 100, 900)
        layout.show()
        _settle(qapp)
        assert layout.responsive_context.width_class is WidthClass.NARROW

    def test_add_page_registers_the_page_not_its_host(self, layout):
        page = _Page()
        layout.add_page("one", page)
        assert page.densities == [DEFAULT]
        assert isinstance(page.parentWidget().parentWidget().parentWidget(), PageHost)

    def test_hidden_pages_get_every_density(self, layout, qapp):
        first, second = _Page(), _Page()
        layout.add_page("first", first)
        layout.add_page("second", second)
        layout.switch_page("first")
        layout.resize(AT_REST[0], BOUNDARIES.compact_below - 100)
        layout.show()
        _settle(qapp)
        assert not second.isVisible()
        assert second.densities[-1].height is HeightClass.COMPACT

    def test_add_banner_sits_between_the_top_bar_and_the_pages(self, layout):
        right = layout.content_stack.parentWidget().layout()
        first, second = QLabel("first"), QLabel("second")
        layout.add_banner(first)
        layout.add_banner(second)
        order = [right.itemAt(i).widget() for i in range(right.count())]
        assert order == [layout.top_bar, first, second, layout.content_stack]
