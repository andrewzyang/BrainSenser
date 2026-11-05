"""Responsive behaviour of the four plot widgets (``ResponsiveFigureWidget``).

The canvas expands both ways and the widgets survive 50×50 → 3840×2160 with
results on screen. On-screen typography is fit-to-cell (plan §4.6): the
``04_plots.md`` §3 table of canvas sizes, the hysteresis bands and the
interface-size factor are checked on the pure ``compute_display_context``, and
the widgets render with it (side by side or stacked). Scheduling: a resize
burst or a window drag costs one re-render and one draw, at its end; a hidden
plot draws nothing until its first paint, which is already at the final scale;
``is_layout_settled`` makes the waits deterministic. Scale and scheduling do not
depend on the data, so those tests use the idle plots, which redraw faster.
"""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QSizePolicy, QStackedWidget, QVBoxLayout, QWidget

from src.ui.views.snapshots_5hz_band.components.dual_hemisphere_auc_widget import (
    DualHemisphereAucWidget,
)
from src.ui.views.snapshots_psd.components.dual_hemisphere_psd_widget import (
    DualHemispherePsdWidget,
)
from src.ui.views.timeline_lfp_threshold.components.dual_hemisphere_violin_widget import (
    DualHemisphereViolinWidget,
)
from src.ui.views.timeline_peri_event.components.peri_event_plot import PeriEventPlot
from src.ui.widgets.mpl_canvas import MatplotlibCanvas
from src.ui.widgets.responsive_figure import RenderContext, compute_display_context
from tests.ui.plots import _states

PLOT_CLASSES = {"psd": DualHemispherePsdWidget, "auc": DualHemisphereAucWidget,
                "violin": DualHemisphereViolinWidget, "peri": PeriEventPlot}

# 04_plots.md §3: canvas (logical px) → arrangement, text (= line) and density,
# for fit = min(cell_w / 5 in, cell_h / 4 in) as noted. Text steps by 0.05.
DISPLAY_TABLE = [
    ((868, 417), "row", 1.15, "compact"),      # fit 0.87
    ((792, 276), "row", 1.15, "compact"),      # 0.69
    ((1048, 466), "row", 1.15, "regular"),     # 1.05, the user's Mac (1.17 before)
    ((1208, 516), "row", 1.2, "regular"),      # 1.21
    ((1688, 649), "row", 1.6, "regular"),      # 1.62
    ((728, 649), "column", 1.15, "compact"),   # 0.81
    ((1048, 901), "column", 1.15, "regular"),  # 1.13
    ((848, 1237), "column", 1.55, "regular"),  # 1.55
]


@pytest.fixture
def plots(qtbot):
    """The four idle plot widgets, on screen at 900×400 (compact, text 1.15) and settled.

    Every test drives the four together, so each wait is paid once.
    """
    widgets = {name: plot_class() for name, plot_class in PLOT_CLASSES.items()}
    for widget in widgets.values():
        qtbot.addWidget(widget)
        widget.resize(900, 400)
        widget.show()
    qtbot.waitUntil(lambda: _all_settled(widgets))
    return widgets


@pytest.fixture
def populated_plots(plots, qtbot):
    """``plots`` showing deterministic synthetic results."""
    for name, plot in plots.items():
        _states.show(name, plot)
    qtbot.waitUntil(lambda: _all_settled(plots))
    return plots


def _resize_and_settle(plots, qtbot, width, height):
    for plot in plots.values():
        plot.resize(width, height)
    qtbot.waitUntil(lambda: _all_settled(plots), timeout=10_000)


def _all_settled(plots) -> bool:
    return all(plot.is_layout_settled() for plot in plots.values())


def _text_scales(plots) -> dict:
    return {name: plot.fs(1.0) for name, plot in plots.items()}


def _counting(render, calls):
    """``render`` that also records each call in ``calls``."""
    def counting_render(self, fig):
        calls.append(fig)
        render(self, fig)
    return counting_render


def _count_renders(plots, monkeypatch) -> dict:
    renders = {name: [] for name in plots}
    for name, plot in plots.items():
        monkeypatch.setattr(type(plot), "render", _counting(type(plot).render, renders[name]))
    return renders


def _count_draws(plots) -> dict:
    draws = {name: [] for name in plots}
    for name, plot in plots.items():
        plot.findChild(MatplotlibCanvas).mpl_connect("draw_event", draws[name].append)
    return draws


def _counts(calls) -> dict:
    return {name: len(made) for name, made in calls.items()}


# ---------------------------------------------------------------------------
# Display context (pure)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("size, arrangement, text, density", DISPLAY_TABLE,
                         ids=[f"{w}x{h}" for (w, h), *_ in DISPLAY_TABLE])
def test_display_context_table(size, arrangement, text, density):
    context = compute_display_context(size[0] / 100, size[1] / 100)
    assert (context.arrangement, context.text, context.line, context.density) == (
        arrangement, text, text, density)


def test_arrangement_flips_only_when_the_other_fits_15_percent_better():
    def arrangement(aspect, prev):
        prev_context = None if prev is None else RenderContext(arrangement=prev)
        return compute_display_context(8.4, 8.4 / aspect, prev=prev_context).arrangement

    # Without history the crossover is the ideal panel aspect, 1.45 ...
    assert (arrangement(1.50, None), arrangement(1.40, None)) == ("row", "column")
    # ... with it, the band is 1.45 / √1.15 ≈ 1.35 to 1.45 × √1.15 ≈ 1.55.
    assert (arrangement(1.40, "row"), arrangement(1.33, "row")) == ("row", "column")
    assert (arrangement(1.50, "column"), arrangement(1.57, "column")) == ("column", "row")


def test_stacking_needs_cells_at_least_2_2_in_tall():
    assert compute_display_context(3.0, 4.0).arrangement == "row"  # stacked cells: 2 in
    assert compute_display_context(4.0, 5.0).arrangement == "column"


def test_compact_is_entered_below_fit_0_95_and_left_at_1():
    def density(fit, prev):
        prev_context = None if prev is None else RenderContext(density=prev)
        return compute_display_context(10 * fit, 4 * fit, prev=prev_context).density

    assert (density(0.94, None), density(0.97, None)) == ("compact", "regular")
    assert (density(0.97, "compact"), density(1.0, "compact")) == ("compact", "regular")


def test_the_clamp_applies_to_the_fit_times_the_interface_size():
    """The canvas pixel ratio already enlarges the text by the interface size; the
    factor only undoes the shrinking of the logical canvas, so a canvas the same
    physical size gets the same text factor at every interface size."""
    # The user's 1048×466 canvas (fit 1.048) at 125 % is 838×373 logical px: still 1.15.
    assert compute_display_context(8.38, 3.73, ui_scale=1.25).text == 1.15
    # Inside the band the product counts: 1.25 × 1.048 = 1.31 → 1.3.
    assert compute_display_context(10.48, 4.66, ui_scale=1.25).text == 1.3
    # Never above 1.6, however big the canvas or the interface size (not 2 × 1.6).
    assert compute_display_context(30.0, 12.0, ui_scale=2.0).text == 1.6


# ---------------------------------------------------------------------------
# Widgets
# ---------------------------------------------------------------------------

def test_plot_expands_both_ways(qtbot):
    host = QWidget()
    qtbot.addWidget(host)
    layout = QVBoxLayout(host)
    for name, plot_class in PLOT_CLASSES.items():
        plot = plot_class()
        policy = plot.findChild(MatplotlibCanvas).sizePolicy()
        expanding = QSizePolicy.Policy.Expanding
        assert policy.horizontalPolicy() == policy.verticalPolicy() == expanding, name
        layout.addWidget(plot)  # the host owns it from here
        assert layout.itemAt(layout.count() - 1).expandingDirections() == (
            Qt.Orientation.Horizontal | Qt.Orientation.Vertical), name


def test_resize_smoke_from_50x50_to_4k(populated_plots, qtbot):
    """No exception (pytest-qt fails the test on one in a Qt callback) and a redraw at each size."""
    draws = _count_draws(populated_plots)
    for size in ((50, 50), (3840, 2160)):
        drawn = _counts(draws)
        _resize_and_settle(populated_plots, qtbot, *size)
        qtbot.waitUntil(lambda: all(len(draws[name]) > drawn[name] for name in draws))


def test_users_canvas_renders_regular_at_1_15(populated_plots, qtbot):
    """1048×466 (fit 1.048): side by side and regular; text 1.17 → 1.15, lines 1.00 → 1.15."""
    _resize_and_settle(populated_plots, qtbot, 1048, 466)
    for name, plot in populated_plots.items():
        figure = plot.findChild(MatplotlibCanvas).figure
        left, right = figure.axes
        assert (plot.fs(1.0), plot.lw(1.0), plot.stacked, plot.compact) == (
            1.15, 1.15, False, False), name
        assert left.yaxis.get_ticklabels()[0].get_fontsize() == pytest.approx(6 * 1.15), name
        assert left.spines["left"].get_linewidth() == pytest.approx(0.5 * 1.15), name
        assert left.get_position().y0 == pytest.approx(right.get_position().y0), name


def test_tall_canvas_stacks_the_panels_each_with_its_y_label(populated_plots, qtbot):
    _resize_and_settle(populated_plots, qtbot, 728, 900)
    for name, plot in populated_plots.items():
        top, bottom = plot.findChild(MatplotlibCanvas).figure.axes
        assert plot.stacked, name
        assert top.get_position().y0 > bottom.get_position().y1, name
        assert top.get_ylabel() and bottom.get_ylabel(), name


# ---------------------------------------------------------------------------
# Scheduling
# ---------------------------------------------------------------------------

def test_resize_burst_costs_one_rerender_and_one_draw(plots, qtbot, monkeypatch):
    renders, draws = _count_renders(plots, monkeypatch), _count_draws(plots)
    for height in range(420, 920, 50):  # 10 synchronous resizes, as in a drag
        for plot in plots.values():
            plot.resize(1700, height)
    qtbot.waitUntil(lambda: _all_settled(plots))
    assert _counts(renders) == _counts(draws) == dict.fromkeys(plots, 1)
    assert _text_scales(plots) == dict.fromkeys(plots, 1.6)


def test_drag_stretches_the_last_frame_until_resizing_pauses(qtbot, monkeypatch):
    """Resize events 20 ms apart, with events processed in between: no render
    and no draw while they keep coming (the canvas paints its last frame
    stretched), then exactly one of each. The pause is widened from 80 ms so a
    loaded machine cannot end the drag early."""
    monkeypatch.setattr(MatplotlibCanvas, "RESIZE_SETTLE_MS", 400)
    plots = {name: plot_class() for name, plot_class in PLOT_CLASSES.items()}
    for plot in plots.values():
        qtbot.addWidget(plot)
        plot.resize(900, 400)
        plot.show()
    qtbot.waitUntil(lambda: _all_settled(plots))
    for plot in plots.values():
        plot.findChild(MatplotlibCanvas).repaint()  # the frame a drag starts from is on screen
    renders, draws = _count_renders(plots, monkeypatch), _count_draws(plots)
    for step in range(1, 11):
        for plot in plots.values():
            plot.resize(900 + 80 * step, 400 + 47 * step)
        qtbot.wait(20)
        assert all(plot.findChild(MatplotlibCanvas).is_resizing() for plot in plots.values())
        assert not any(plot.is_layout_settled() for plot in plots.values())
    assert _counts(renders) == _counts(draws) == dict.fromkeys(plots, 0)
    qtbot.waitUntil(lambda: _all_settled(plots))
    assert _counts(renders) == _counts(draws) == dict.fromkeys(plots, 1)
    assert _text_scales(plots) == dict.fromkeys(plots, 1.6)


def test_hidden_plot_draws_on_its_first_paint_at_its_final_scale(qtbot):
    stack = QStackedWidget()
    qtbot.addWidget(stack)
    stack.addWidget(QWidget())
    plots = {name: plot_class() for name, plot_class in PLOT_CLASSES.items()}
    drawn_at = {name: [] for name in plots}
    for name, plot in plots.items():
        stack.addWidget(plot)
        _states.show(name, plot)  # results arrive while the page is hidden
        plot.findChild(MatplotlibCanvas).mpl_connect(
            "draw_event", lambda _event, plot=plot, name=name: drawn_at[name].append(plot.fs(1.0)))
    stack.resize(900, 400)
    stack.show()
    qtbot.waitExposed(stack)
    stack.resize(1700, 870)
    qtbot.wait(50)
    assert drawn_at == {name: [] for name in plots}  # a hidden plot never draws
    assert all(len(plot.findChild(MatplotlibCanvas).figure.axes) == 2 for plot in plots.values())
    for index, (name, plot) in enumerate(plots.items(), start=1):
        stack.setCurrentIndex(index)
        qtbot.waitUntil(plot.is_layout_settled)
        assert drawn_at[name] == [1.6], name


def test_interface_size_rerenders_once(plots, qtbot, monkeypatch):
    renders = _count_renders(plots, monkeypatch)
    for plot in plots.values():
        plot.set_ui_scale(1.5)
    qtbot.waitUntil(lambda: _all_settled(plots))
    assert _text_scales(plots) == dict.fromkeys(plots, 1.35)  # 1.5 × fit 0.9
    for plot in plots.values():
        plot.set_ui_scale(1.5)  # unchanged: nothing to redo
    qtbot.waitUntil(lambda: _all_settled(plots))
    assert _counts(renders) == dict.fromkeys(plots, 1)


def test_is_layout_settled_waits_for_the_resize_to_pause(plots, qtbot):
    assert _text_scales(plots) == dict.fromkeys(plots, 1.15)
    for plot in plots.values():
        plot.resize(1700, 870)  # calls for 1.6
    assert not any(plot.is_layout_settled() for plot in plots.values())
    qtbot.waitUntil(lambda: _all_settled(plots))
    assert _text_scales(plots) == dict.fromkeys(plots, 1.6)


def test_is_layout_settled_needs_the_context_to_match_the_canvas(plots):
    """A canvas size the last render was not made for is unsettled even with nothing scheduled."""
    for plot in plots.values():
        # Calls for 1.6; without a resize event nothing is queued.
        plot.findChild(MatplotlibCanvas).figure.set_size_inches(17.0, 8.7)
    assert not any(plot.is_layout_settled() for plot in plots.values())
