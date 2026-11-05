"""The plots' font family (``src/ui/widgets/plot_fonts.py``; plan M2.2).

The first installed family of the fallback chain wins, with DejaVu Sans behind
it for glyphs it lacks. macOS resolves the manuscript's Helvetica Neue, so the
plots and their export bytes are unchanged there. Without Helvetica — the
Windows / Linux case, simulated in a fresh process whose matplotlib font list
has none — every plot renders and exports without a single font warning.
"""

import importlib
import sys

import pytest
from matplotlib import font_manager

from src.ui.widgets.plot_fonts import PLOT_FONT_FAMILIES, plot_font_families, plot_font_family
from tests.ui.scaling._app_process import AppProcess, DisplayProfile

WIDGET_MODULES = (
    "src.ui.views.snapshots_psd.components.dual_hemisphere_psd_widget",
    "src.ui.views.snapshots_5hz_band.components.dual_hemisphere_auc_widget",
    "src.ui.views.timeline_lfp_threshold.components.dual_hemisphere_violin_widget",
    "src.ui.views.timeline_peri_event.components.peri_event_plot",
)
HELVETICAS = ["Helvetica Neue", "Helvetica"]


@pytest.fixture
def installed(monkeypatch):
    """Make matplotlib's font list exactly the given families."""
    def install(*families):
        monkeypatch.setattr(font_manager.fontManager, "ttflist",
                            [font_manager.FontEntry(name=family) for family in families])
        plot_font_family.cache_clear()
    yield install
    plot_font_family.cache_clear()


@pytest.mark.parametrize("families, expected", [
    (("DejaVu Sans", "Arial", "Helvetica", "Helvetica Neue"), "Helvetica Neue"),
    (("DejaVu Sans", "Arial", "Helvetica"), "Helvetica"),
    (("DejaVu Sans", "Liberation Sans", "Arial"), "Arial"),
    (("DejaVu Sans", "Nimbus Sans", "Liberation Sans"), "Liberation Sans"),
    (("DejaVu Sans", "Nimbus Sans"), "Nimbus Sans"),
    (("DejaVu Sans", "Verdana"), "DejaVu Sans"),
])
def test_first_installed_family_of_the_chain_wins(installed, families, expected):
    installed(*families)
    assert plot_font_family() == expected


def test_dejavu_sans_backs_up_glyphs_the_family_lacks(installed):
    installed("Arial", "DejaVu Sans")
    assert plot_font_families() == ["Arial", "DejaVu Sans"]
    installed("DejaVu Sans")
    assert plot_font_families() == ["DejaVu Sans"]


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS ships Helvetica Neue")
def test_macos_plots_draw_with_helvetica_neue():
    assert plot_font_family() == "Helvetica Neue"
    for module in WIDGET_MODULES:
        widget_module = importlib.import_module(module)
        assert widget_module._FONT == widget_module._RC["font.family"] == [
            "Helvetica Neue", "DejaVu Sans"], module


@pytest.mark.qt_subprocess
def test_no_font_warnings_without_helvetica(tmp_path):
    installed = {font.name for font in font_manager.fontManager.ttflist}
    expected = next(family for family in PLOT_FONT_FAMILIES
                    if family not in HELVETICAS and family in installed)
    child = AppProcess("tests.ui.plots._render:render_without_fonts",
                       {"drop": HELVETICAS, "out_dir": str(tmp_path / "exports")},
                       DisplayProfile(name="offscreen"), tmp_path)
    result = child.result()
    assert result["family"] == expected
    assert result["exports"] == 4 * 2 * 3  # kinds × states × formats
    assert result["warnings"] == []
