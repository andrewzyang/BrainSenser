"""Plot exports do not depend on the window size or the display scale.

Two fresh processes (``QT_SCALE_FACTOR`` 1 and 2) build the real main window
with the synthetic results and, at two window sizes, export each analysis
page's plot as PNG, PDF and SVG through the app's own path: top bar Save Plot →
the page's ``export_plot`` → the widget's export method → ``render_export``
(the save dialog answers with the target path). The two sizes put the on-screen
figures at different font scales and the two processes at DPR 1 and 2; the
bytes must not change — for PDF and SVG too, which carry no creation date and
a fixed SVG id salt (M2.1, D6).
"""

import hashlib
import math
import time
from pathlib import Path

import pytest

from tests.ui.scaling._app_process import (
    MESSAGES,
    AppProcess,
    accept_synthetic_results,
    open_main_window,
    populate,
    qt_scale_profile,
    show_page,
    wait_settled,
)

pytestmark = [pytest.mark.export_determinism, pytest.mark.qt_subprocess]

# Plot widget → the page that hosts it.
PLOTS = {"psd": "snapshots_canonical_bands", "auc": "snapshots_5hz_band",
         "violin": "timeline_lfp_threshold", "peri": "timeline_peri_event"}
FORMATS = ("png", "pdf", "svg")
# A small and a large window, so the plot text differs at both scale factors (the
# factor scales the fit before the [1.15, 1.6] clamp: at factor 2 two large
# windows would both reach 1.6).
WINDOW_SIZES = ((800, 500), (1920, 1040))
SCALE_FACTORS = (1, 2)


@pytest.fixture(scope="module")
def exports(tmp_path_factory):
    """{scale factor: child result}; the two processes run at once."""
    children = {}
    for factor in SCALE_FACTORS:
        workdir = tmp_path_factory.mktemp(f"export_sf{factor}")
        payload = {"sizes": WINDOW_SIZES, "out_dir": str(workdir / "exports")}
        children[factor] = AppProcess(f"{__name__}:export_plots", payload,
                                      qt_scale_profile(factor), workdir)
    return {factor: child.result() for factor, child in children.items()}


def test_every_export_went_through_the_app_path(exports):
    """Guards the comparisons below: each process ran at its DPR, every export
    succeeded, and the window sizes changed every plot's on-screen font scale."""
    for factor, result in exports.items():
        assert result["dpr"] == factor
        assert {(kind, title) for kind, title, _ in result["messages"]} == {
            ("information", "Export Successful")}
        assert len(result["messages"]) == len(PLOTS) * len(FORMATS) * len(WINDOW_SIZES)
        for plot in PLOTS:
            scales = {result["font_scale"][f"{plot}@{w}x{h}"] for w, h in WINDOW_SIZES}
            assert len(scales) == len(WINDOW_SIZES), (factor, plot, scales)


@pytest.mark.parametrize("fmt", FORMATS)
@pytest.mark.parametrize("plot", PLOTS)
def test_export_bytes_identical_across_window_size_and_scale_factor(exports, plot, fmt):
    digests = {f"QT_SCALE_FACTOR={factor} {w}x{h}": result["md5"][f"{plot}.{fmt}@{w}x{h}"]
               for factor, result in exports.items() for w, h in WINDOW_SIZES}
    assert len(set(digests.values())) == 1, digests


# ---------------------------------------------------------------------------
# Child side (runs in the AppProcess)
# ---------------------------------------------------------------------------

def export_plots(payload) -> dict:
    from PySide6.QtWidgets import QFileDialog

    from src.ui.widgets.responsive_figure import ResponsiveFigureWidget

    sizes = [tuple(size) for size in payload["sizes"]]
    out_dir = Path(payload["out_dir"])
    out_dir.mkdir()
    win = open_main_window(*sizes[0])
    populate(win)
    accept_synthetic_results(win)
    target = {}
    QFileDialog.getSaveFileName = staticmethod(lambda *_args, **_kwargs: (target["path"], ""))

    md5, font_scale = {}, {}
    last_export = None
    for width, height in sizes:
        if last_export is not None:
            _wait_for_next_second(last_export)
        win.resize(width, height)
        wait_settled(win)
        for plot, page in PLOTS.items():
            show_page(win, page)
            figure = win.main_layout.get_page(page).findChild(ResponsiveFigureWidget)
            font_scale[f"{plot}@{width}x{height}"] = round(figure.fs(1.0), 3)
            for fmt in FORMATS:
                path = out_dir / f"{plot}_{width}x{height}.{fmt}"
                target["path"] = str(path)
                win.top_bar.save_plot_clicked.emit()
                md5[f"{plot}.{fmt}@{width}x{height}"] = hashlib.md5(path.read_bytes()).hexdigest()
                last_export = time.time()
    return {"md5": md5, "font_scale": font_scale, "dpr": win.devicePixelRatioF(),
            "messages": MESSAGES}


def _wait_for_next_second(since: float) -> None:
    """Sleep into the wall-clock second after ``since``.

    PDF CreationDate has one-second resolution; with every export of the next
    size in a later second, a date in the PDF could not match by chance.
    """
    time.sleep(max(0.0, math.floor(since) + 1 - time.time()))
