"""Export contracts of the four plot widgets, as the code defines them today.

``ResponsiveFigureWidget.render_export(path, dpi)`` draws a fresh canonical
figure from ``EXPORT_CTX`` alone and lets matplotlib pick the format from the
extension. Each widget's
public export method writes 300 dpi by default: PSD's ``export_figure``
validates the extension first and raises, the other three return False on
failure. The PSD page sends its exports through ``run_export``, whose dpi must
reach the file. None of it touches the live on-screen figure.
"""

import xml.etree.ElementTree as ElementTree

import pytest
from PySide6.QtGui import QImage

from src.ui.export import build_snapshots_export_request, run_export
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
from tests.ui.plots import _states

PLOT_CLASSES = {"psd": DualHemispherePsdWidget, "auc": DualHemisphereAucWidget,
                "violin": DualHemisphereViolinWidget, "peri": PeriEventPlot}
# The method each view calls to export its plot.
PUBLIC_EXPORT = {"psd": "export_figure", "auc": "export_png",
                 "violin": "save_figure", "peri": "save_figure"}
# One pixel at 100 dpi: the tight bounding box rounds to whole pixels.
WIDTH_TOLERANCE_IN = 0.01


@pytest.fixture(params=PLOT_CLASSES)
def kind(request):
    return request.param


@pytest.fixture
def plot(kind, qtbot):
    """The widget on screen at 900×300, where its live text scale is 1.15 (compact)."""
    widget = PLOT_CLASSES[kind]()
    qtbot.addWidget(widget)
    widget.resize(900, 300)
    widget.show()
    qtbot.waitUntil(widget.is_layout_settled)
    return widget


@pytest.mark.parametrize("dpi", [200, 300])
def test_render_export_honours_dpi(plot, tmp_path, dpi):
    recorded_dpi, width_in = _png_dpi_and_width_in(_export(plot, tmp_path, dpi))
    assert recorded_dpi == dpi
    assert width_in == pytest.approx(_reference_width_in(plot, tmp_path), abs=WIDTH_TOLERANCE_IN)


def test_public_export_method_writes_300_dpi_png(plot, kind, tmp_path):
    path = tmp_path / "public.png"
    getattr(plot, PUBLIC_EXPORT[kind])(str(path))
    dpi, width_in = _png_dpi_and_width_in(path)
    assert dpi == 300
    assert width_in == pytest.approx(_reference_width_in(plot, tmp_path), abs=WIDTH_TOLERANCE_IN)


def test_psd_coordinator_dpi_reaches_the_file(qtbot, tmp_path):
    """The PSD page's path: ``run_export`` picks the dpi and ``export_figure`` writes it."""
    psd = DualHemispherePsdWidget()
    qtbot.addWidget(psd)
    passed = []

    def render(target, dpi):  # what SnapshotsPsdView._run_plot_export hands over
        passed.append(dpi)
        psd.export_figure(target, dpi=dpi)

    path = tmp_path / "coordinated.png"
    assert run_export(build_snapshots_export_request(str(path), render)).succeeded
    [dpi] = passed
    recorded_dpi, width_in = _png_dpi_and_width_in(path)
    assert recorded_dpi == dpi
    assert width_in == pytest.approx(_reference_width_in(psd, tmp_path), abs=WIDTH_TOLERANCE_IN)


def test_render_export_unknown_extension_raises_matplotlib_error(plot, tmp_path):
    with pytest.raises(ValueError, match="Format 'xyz' is not supported"):
        plot.render_export(str(tmp_path / "plot.xyz"), 100)


def test_public_export_method_rejects_unknown_extension_without_writing(plot, kind, tmp_path):
    path = tmp_path / "plot.xyz"
    export = getattr(plot, PUBLIC_EXPORT[kind])
    if kind == "psd":
        with pytest.raises(ValueError, match="Unsupported format"):
            export(str(path))
    else:
        assert export(str(path)) is False
    assert not path.exists()


def test_exports_are_valid_png_pdf_svg(plot, tmp_path):
    png, pdf, svg = (_export(plot, tmp_path, 100, ext) for ext in ("png", "pdf", "svg"))
    assert png.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    assert pdf.read_bytes()[:5] == b"%PDF-"
    assert ElementTree.parse(svg).getroot().tag == "{http://www.w3.org/2000/svg}svg"


def test_export_leaves_the_live_figure_alone(plot, tmp_path):
    figure = plot.findChild(MatplotlibCanvas).figure

    def live_state():
        return (plot.fs(1.0), tuple(figure.get_size_inches()),
                type(figure.get_layout_engine()), len(figure.axes))

    before = live_state()
    assert before[0] == pytest.approx(1.15)  # not the export's 1.0, so a leak would show
    for ext in ("png", "pdf", "svg"):
        _export(plot, tmp_path, 100, ext)
    assert live_state() == before


def test_exported_violin_has_no_legend(qtbot, tmp_path, monkeypatch):
    """As in the manuscript ``_plot_dist`` (D13): the in-axes ``n =`` labels, the
    group labels and the jade/rose fills carry what a legend would repeat."""
    violin = DualHemisphereViolinWidget()
    qtbot.addWidget(violin)
    _states.show("violin", violin)
    exported = []
    render = DualHemisphereViolinWidget.render

    def recording_render(self, fig):
        exported.append(fig)
        render(self, fig)

    monkeypatch.setattr(DualHemisphereViolinWidget, "render", recording_render)
    assert violin.save_figure(str(tmp_path / "violin.png"))
    [figure] = exported
    assert [axes.get_legend() for axes in figure.axes] == [None, None]
    for axes in figure.axes:
        assert {text.get_text() for text in axes.texts} >= {
            f"n = {_states.N_GROUP_1}", f"n = {_states.N_GROUP_2}"}


def test_export_ignores_the_on_screen_context(plot, qtbot, tmp_path):
    """``render_export`` reads only ``EXPORT_CTX``: stacking, density and the
    interface size of the live figure never reach the file, in any format."""
    def export_all(folder):
        folder.mkdir()
        return {ext: _export(plot, folder, 100, ext).read_bytes() for ext in ("png", "pdf", "svg")}

    before = export_all(tmp_path / "before")
    plot.resize(700, 900)
    plot.set_ui_scale(1.5)
    qtbot.waitUntil(plot.is_layout_settled)
    assert plot.stacked and plot.fs(1.0) >= 1.6
    assert export_all(tmp_path / "after") == before


def _export(plot, tmp_path, dpi, ext="png"):
    path = tmp_path / f"render_{dpi}.{ext}"
    plot.render_export(str(path), dpi)
    return path


def _reference_width_in(plot, tmp_path) -> float:
    """Width in inches of the 100-dpi export, the reference for every other dpi."""
    return _png_dpi_and_width_in(_export(plot, tmp_path, 100))[1]


def _png_dpi_and_width_in(path):
    """(dpi recorded in the PNG, pixel width / that dpi)."""
    image = QImage(str(path))
    dpi = round(image.dotsPerMeterX() * 0.0254)
    return dpi, image.width() / dpi
