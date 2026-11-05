"""Plot text stays legible and off the data at every canvas size (plan M2.5, I8).

Three fresh processes render the four plot widgets — with Helvetica Neue as on
macOS, with Arial as on Windows (Helvetica taken out of matplotlib's font list),
and with Helvetica Neue at a 125 % interface size (``QT_SCALE_FACTOR`` 1.25 and
the plots' interface size 1.25, as a page pushes it) — at canvas sizes from
600×220 to 3608×1405 and at 368×260 (a 600×500 window with the labelled
sidebar), in the result, mixed and skeleton states, the violin with groups of 2
and of 5 event types. Every drawn frame must pass the I6 detector (text sizes in
band, nothing outside the figure, no two texts overlapping, no statistic over a
data mark), keep tick labels at the 1.15 floor (9.6 px), show every statistic
and, on the peri-event plot, label the event press at 0. Synthetic data only.
"""

import pytest

from tests.ui.plots import _states
from tests.ui.scaling._app_process import AppProcess, DisplayProfile, qt_scale_profile

pytestmark = [pytest.mark.responsive, pytest.mark.qt_subprocess, pytest.mark.slow]

SIZES = ((368, 260), (600, 220), (792, 276), (868, 417), (1048, 466), (1208, 516),
         (728, 649), (1048, 901), (848, 1237), (1688, 649), (3608, 1405))
# Font → the families the child removes so the plots resolve it.
FONTS = {"Helvetica Neue": [], "Arial": ["Helvetica Neue", "Helvetica"]}
# One child per (font, interface size in %).
RUNS = (("Helvetica Neue", 100), ("Arial", 100), ("Helvetica Neue", 125))
CASES = [(kind, state, event_types) for kind in _states.KINDS for state in _states.STATES
         for event_types in ((2, 5) if kind == "violin" else (2,))]
TICK_MIN_PX = 6 * 1.15 * 100 / 72 - 0.01  # 6-pt ticks at the 1.15 floor
STAT_MIN_PX = 11 - 0.05

# Statistics each result panel shows (compared with newlines as spaces).
_N = (f"n = {_states.N_GROUP_1}", f"n = {_states.N_GROUP_2}")
STATISTICS = {
    "psd": [],
    "auc": ["AUC 0.712 [0.611, 0.803]", "p 0.0021", "modal 8.24–13.12 Hz"],
    "violin": ["985 µV", "AUC 0.684 [0.601, 0.763]", "p < 0.0010 (perm.)", "***", *_N],
    "peri": ["p = 0.012"],
}
# Significance stars the PSD panels carry (3 left, 2 right).
PSD_STARS = {"result": 5, "mixed": 3, "skeleton": 0}


@pytest.fixture(scope="module")
def frames(tmp_path_factory) -> dict:
    """{(font, interface size): child result}; the processes run at once."""
    children = {
        (font, percent): AppProcess(
            f"{__name__}:measure", {"drop": FONTS[font], "ui_scale": percent / 100},
            (qt_scale_profile(percent / 100) if percent != 100
             else DisplayProfile(name="offscreen")),
            tmp_path_factory.mktemp(f"{font.replace(' ', '_')}_{percent}"))
        for font, percent in RUNS}
    return {run: child.result() for run, child in children.items()}


@pytest.mark.parametrize("font, percent", RUNS,
                         ids=[f"{font}-{percent}%" for font, percent in RUNS])
@pytest.mark.parametrize("kind, state, event_types", CASES,
                         ids=[f"{kind}-{state}-{types}types" for kind, state, types in CASES])
def test_plot_text_at_every_size(frames, font, percent, kind, state, event_types):
    result = frames[(font, percent)]
    if result["family"] != font:
        pytest.skip(f"{font} is not installed (the plots resolved {result['family']})")
    problems = result["cells"][f"{kind}/{state}/{event_types}"]
    assert not problems, "\n".join(problems)


# ---------------------------------------------------------------------------
# Child side (runs in the AppProcess)
# ---------------------------------------------------------------------------

def measure(payload) -> dict:
    from tests.ui.plots._render import drop_fonts, settle

    drop_fonts(payload["drop"])
    from src.ui.widgets.plot_fonts import plot_font_family

    cells = {}
    ui_scale = payload["ui_scale"]
    for kind, state, event_types in CASES:
        widget = _states.make(kind)
        _states.show(kind, widget, state, event_types)
        widget.set_ui_scale(ui_scale)
        widget.setMinimumHeight(0)
        widget.show()
        problems = []
        for width, height in SIZES:
            widget.resize(width, height)
            settle(widget)
            problems += [f"{width}×{height}: {problem}"
                         for problem in _check(widget, kind, state, ui_scale)]
        widget.close()
        cells[f"{kind}/{state}/{event_types}"] = problems
    return {"family": plot_font_family(), "cells": cells}


def _check(widget, kind, state, ui_scale) -> list:
    from src.ui.widgets.mpl_canvas import MatplotlibCanvas
    from tests.ui.responsive.invariants import check_plot_text

    canvas = widget.findChild(MatplotlibCanvas)
    figure = canvas.figure
    problems = [v.detail for v in check_plot_text(figure, canvas.device_pixel_ratio, kind,
                                                  ui_scale)]
    px_per_pt = figure.dpi / canvas.device_pixel_ratio / 72
    ticks = [label for ax in figure.axes for axis in (ax.xaxis, ax.yaxis)
             for label in axis.get_ticklabels() if label.get_visible() and label.get_text()]
    problems += [f"tick '{label.get_text()}' at {label.get_fontsize() * px_per_pt:.1f} px"
                 for label in ticks if label.get_fontsize() * px_per_pt < TICK_MIN_PX
                 or ("n = " in label.get_text()
                     and label.get_fontsize() * px_per_pt < STAT_MIN_PX)]
    if state != "skeleton":
        drawn = [text.get_text() for text in figure.findobj(lambda a: hasattr(a, "get_text"))
                 if text.get_visible()]
        shown = " ".join(drawn).replace("\n", " ")
        problems += [f"statistic '{statistic}' not shown"
                     for statistic in STATISTICS[kind] if statistic not in shown]
        if kind == "psd" and drawn.count("*") != PSD_STARS[state]:
            problems.append(f"{drawn.count('*')} significance stars, not {PSD_STARS[state]}")
        if kind == "peri":
            left = figure.axes[0]
            zero = [label.get_text() for tick, label in zip(left.get_xticks(),
                                                            left.get_xticklabels()) if tick == 0]
            if zero != ["0"]:
                problems.append(f"the event press is labelled {zero}, not '0'")
    return problems
