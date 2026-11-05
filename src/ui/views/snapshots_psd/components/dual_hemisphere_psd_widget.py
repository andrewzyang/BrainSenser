"""Dual-hemisphere PSD plot widget for the Snapshots → PSD page.

Renders the manuscript snapshot-spectral figure (one panel per hemisphere —
**Electrode 1** = Left, **Electrode 2** = Right) embedded via the shared
:class:`ResponsiveFigureWidget`, reproducing the
Nature double-column aesthetic of ``scripts/snapshot_band_comparison.py``
(manuscript Figure 2): jade (non-craving) / rose (craving) mean curves at
1.0 pt, per-bin bootstrap 95 % CI shaded at α 0.12, FDR-significant canonical
bands shaded ``#E0E0E0`` at α 0.6 with a bold ``*`` above the band's greek
letter, Helvetica-Neue-light 7 pt, top/right spines hidden, left/bottom black
at α 0.3.

This is a **display-only** port. The per-group median PSD curve and its 95 %
bootstrap CI are computed upstream by the snapshot PSD analysis service and the
ViewModel; this widget only styles and draws them — no statistics are
recomputed here (MVVM: the widget is a pure View component). The manuscript
script is the *reference* for the look only; it is **never imported** — this
module depends solely on matplotlib / numpy / PySide6 + the shared
:class:`ResponsiveFigureWidget`, so the app stays standalone.

The manuscript aesthetic is applied via :func:`matplotlib.rc_context` (scoped
by the base) so global rcParams are never mutated — matching the sibling
Timeline plot widgets (:class:`PeriEventPlot`,
:class:`DualHemisphereViolinWidget`). On screen the figure uses constrained-
layout and responsive font scaling (base); exports render at a fixed canonical
size so the saved figure is manuscript-stable regardless of window size.

Public API mirrors the previous PyQtGraph widget so the View drives it
unchanged: :meth:`update_psd_data`, :meth:`update_band_statistics`,
:meth:`clear_plots`, :meth:`export_figure`.
"""

from __future__ import annotations

import logging
from typing import Dict, Optional, Tuple

import numpy as np
from matplotlib.transforms import offset_copy
from PySide6.QtWidgets import QWidget

from src.ui.widgets.plot_fonts import plot_font_families
from src.ui.widgets.responsive_figure import ResponsiveFigureWidget

logger = logging.getLogger(__name__)


# ─── Palette (manuscript figure-style guide) ───────────────────────────────
JADE = "#2BA495"      # non-craving curve / CI
ROSE = "#D97F86"      # craving curve / CI
BLACK = "#000000"     # text / spines / stars
SIG_BG = "#E0E0E0"    # FDR-significant band shading (alpha 0.6)
GREY_MSG = "#888888"  # skeleton / message text

_FONT = plot_font_families()

# Panel-title pad (pt). App-display only; matches the Timeline plot widgets so
# every spectral page's titles line up identically.
_TITLE_PAD = 10

# Display-only panel titles. Data/significance lookups still key off the
# hemisphere name ("Left"/"Right"); only the rendered title is the electrode
# label. Panel 1 (Left) → Electrode 1, panel 2 (Right) → Electrode 2.
_PANEL_TITLE = {"Left": "Electrode 1", "Right": "Electrode 2"}

# Manuscript spectral analysis window (Hz). Power above 40 Hz is excluded from
# analysis (signal quality); the device-native curve extends to ~96 Hz but is
# clipped to this window by ``set_xlim``.
FREQ_MIN, FREQ_MAX = 1.0, 40.0

# Canonical band → (f_lo, f_hi, greek label), ascending frequency. Names match
# the analysis service's ``SNAPSHOT_ANALYSIS_BANDS`` keys; ranges + greek labels
# match ``BANDS`` in scripts/snapshot_band_comparison.py.
BANDS: Tuple[Tuple[str, float, float, str], ...] = (
    ("Delta", 1.0, 4.0, "δ"),
    ("Theta", 4.0, 8.0, "θ"),
    ("Alpha", 8.0, 13.0, "α"),
    ("Beta", 13.0, 30.0, "β"),
    ("Gamma_low", 30.0, 40.0, "low γ"),
)

# rcParams scoped to this widget's draws only (never global).
_RC = {
    "font.family": _FONT,
    "font.weight": "light",
    "font.size": 7,
    "axes.labelweight": "light",
    "axes.titleweight": "light",
    "axes.linewidth": 0.5,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "savefig.dpi": 300,
}

# Per-group curve tuple: (median, lower_ci, upper_ci, n_events).
PsdCurve = Tuple[Optional[np.ndarray], Optional[np.ndarray],
                 Optional[np.ndarray], int]


def _log10(arr: Optional[np.ndarray]) -> Optional[np.ndarray]:
    """``log10`` with a positivity guard (non-positive → NaN, which matplotlib
    skips). Mirrors the manuscript's ``np.where(matrix > 0, matrix, np.nan)``
    before the log. This is a display-axis transform only — the underlying
    median / CI statistic the ViewModel computed is unchanged."""
    if arr is None:
        return None
    a = np.asarray(arr, dtype=float)
    return np.log10(np.where(a > 0, a, np.nan))


class DualHemispherePsdWidget(ResponsiveFigureWidget):
    """Two side-by-side matplotlib panels: Left / Right hemisphere PSD."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent, rc=_RC)

        self._freq_axis: Optional[np.ndarray] = None
        # Per-hemisphere curves: {"Left"/"Right": {"craving"/"non_craving": PsdCurve}}.
        self._data: Dict[str, Dict[str, PsdCurve]] = {"Left": {}, "Right": {}}
        # Per-hemisphere FDR-significance flags: {"Left"/"Right": {band: bool}}.
        self._sig: Dict[str, Dict[str, bool]] = {"Left": {}, "Right": {}}

        self.draw()

    # ------------------------------------------------------------------
    # Public API (parity with the former PyQtGraph widget)
    # ------------------------------------------------------------------

    def update_psd_data(
        self,
        freq_axis: np.ndarray,
        left_craving: PsdCurve,
        left_non_craving: PsdCurve,
        right_craving: PsdCurve,
        right_non_craving: PsdCurve,
    ) -> None:
        """Store both hemispheres' per-group curves and redraw.

        Each ``*_craving`` / ``*_non_craving`` is
        ``(median, lower_ci, upper_ci, n_events)`` — raw linear median PSD
        (µV²/Hz) plus a 95 % bootstrap percentile CI, exactly as produced by
        the ViewModel. Curves are displayed (log10-scaled), never recomputed.
        """
        self._freq_axis = freq_axis
        self._data["Left"] = {"craving": left_craving,
                              "non_craving": left_non_craving}
        self._data["Right"] = {"craving": right_craving,
                               "non_craving": right_non_craving}
        self.draw()

    def update_band_statistics(
        self,
        band_results_left: Dict,
        band_results_right: Optional[Dict] = None,
    ) -> None:
        """Shade each hemisphere's own FDR-significant bands and redraw.

        ``band_results_*`` map band name → ``BandComparisonResult``. Each panel
        is shaded from its OWN hemisphere's results (FDR is corrected within a
        participant-hemisphere), so the two panels may mark different bands.
        Right may be empty/None when the patient has no right-hemisphere data.
        """
        self._sig["Left"] = self._significant_bands(band_results_left)
        self._sig["Right"] = self._significant_bands(band_results_right or {})
        self.draw()

    def clear_plots(self) -> None:
        """Reset all state and render the idle skeleton message."""
        self._freq_axis = None
        self._data = {"Left": {}, "Right": {}}
        self._sig = {"Left": {}, "Right": {}}
        self.draw()

    def export_figure(self, file_path: str, dpi: int = 300) -> None:
        """Save both panels to a single combined PNG / PDF / SVG.

        Renders into a fresh canonical-size figure (via the base) so the export
        is deterministic and manuscript-stable regardless of the on-screen
        window size. Raises ``ValueError`` for any unsupported extension.
        """
        ext = file_path.rsplit(".", 1)[-1].lower() if "." in file_path else ""
        if ext not in ("png", "pdf", "svg"):
            raise ValueError(
                f"Unsupported format: {ext}. Use .png, .pdf, or .svg"
            )
        self.render_export(file_path, dpi)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _significant_bands(band_results: Dict) -> Dict[str, bool]:
        """Reduce a hemisphere's ``BandComparisonResult`` dict to
        ``{band_name: is_significant}``. Tolerant of missing attributes."""
        return {
            band_name: bool(getattr(result, "is_significant", False))
            for band_name, result in (band_results or {}).items()
        }

    @staticmethod
    def _has_curve(curve: Optional[PsdCurve]) -> bool:
        """True iff a per-group curve carries a real central series."""
        return bool(curve) and curve[0] is not None

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------

    def render(self, fig) -> None:
        """Draw both hemisphere panels onto ``fig`` (base owns layout/draw)."""
        ax1, ax2 = self.panels(fig)
        self._draw_panel(ax1, "Left", show_ylabel=True)
        self._draw_panel(ax2, "Right", show_ylabel=self.stacked)

    def _draw_panel(self, ax, hemisphere: str, show_ylabel: bool) -> None:
        data = self._data.get(hemisphere) or {}
        craving = data.get("craving")
        non_craving = data.get("non_craving")

        if self._freq_axis is None or not (
            self._has_curve(craving) or self._has_curve(non_craving)
        ):
            self._draw_message(
                ax, _PANEL_TITLE[hemisphere],
                "Click compare to\nrun analysis",
            )
            return

        sig = self._sig.get(hemisphere, {})
        freq = np.asarray(self._freq_axis, dtype=float)

        # FDR-significant band shading sits behind everything.
        for band_name, f_lo, f_hi, _greek in BANDS:
            if sig.get(band_name):
                ax.axvspan(f_lo, f_hi, color=SIG_BG, alpha=0.6, zorder=0,
                           linewidth=0)

        # Group 1 (Jade) then Group 2 (Rose) — manuscript plot order
        # (Group 1 = non-craving class, Group 2 = craving class).
        self._plot_group(ax, freq, non_craving, JADE, "Group 1")
        self._plot_group(ax, freq, craving, ROSE, "Group 2")

        self._style_ax(ax, _PANEL_TITLE[hemisphere], show_ylabel,
                       ylabel=r"$\log_{10}$ power ($\mu$V$^2$/Hz)")
        ax.set_xlim(FREQ_MIN, FREQ_MAX)
        ax.set_xlabel("frequency (Hz)", fontsize=self.fs(7), color=BLACK,
                      labelpad=2, family=_FONT)
        ax.legend(fontsize=self.fs(6), frameon=False, loc="lower left",
                  handlelength=1.2, handletextpad=0.4)

        # Headroom so band labels + significance stars sit in empty space above
        # the curves (manuscript: +30 % of the y-range).
        y_lo, y_hi = ax.get_ylim()
        ax.set_ylim(y_lo, y_hi + (y_hi - y_lo) * 0.30)

        self._draw_band_labels(ax, sig)

    def _plot_group(self, ax, freq: np.ndarray, curve: Optional[PsdCurve],
                    color: str, label: str) -> None:
        if not self._has_curve(curve):
            return
        median, lo, hi, n = curve
        ax.plot(freq, _log10(median), color=color, linewidth=self.lw(1.0), zorder=3,
                label=f"{label} (n = {int(n)})")
        if lo is not None and hi is not None:
            ax.fill_between(freq, _log10(lo), _log10(hi), color=color,
                            alpha=0.12, linewidth=0, zorder=2)

    def _draw_band_labels(self, ax, sig: Dict[str, bool]) -> None:
        """Greek label for all five bands (axes-y 0.94) + a bold ``*`` above
        each FDR-significant band (axes-y 0.99). x in data coords via the
        x-axis-transform; y in axes fraction — on screen, a fixed number of
        points below the top instead, so the two rows never collide on a
        short panel."""
        trans = ax.get_xaxis_transform()
        star_y, greek_y = 0.99, 0.94
        star_trans = greek_trans = trans
        if self.on_screen:
            star_y = greek_y = 1.0
            star_trans = offset_copy(trans, fig=ax.figure, y=-self.fs(2), units="points")
            greek_trans = offset_copy(trans, fig=ax.figure, y=-self.fs(12), units="points")
        for band_name, f_lo, f_hi, greek in BANDS:
            mid = (f_lo + f_hi) / 2.0
            if sig.get(band_name):
                ax.text(mid, star_y, "*", transform=star_trans, ha="center",
                        va="top", fontsize=self.stat_fs(8), fontweight="bold",
                        color=BLACK, zorder=5, family=_FONT)
            ax.text(mid, greek_y, greek, transform=greek_trans, ha="center", va="top",
                    fontsize=self.fs(6), color=BLACK, alpha=0.75, zorder=5,
                    family=_FONT)

    def _style_ax(self, ax, title: str, show_ylabel: bool, ylabel: str) -> None:
        ax.set_facecolor("white")
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        for sp in ("left", "bottom"):
            ax.spines[sp].set_color(BLACK)
            ax.spines[sp].set_alpha(0.3)
        ax.tick_params(colors=BLACK, labelsize=self.fs(6))
        if show_ylabel:
            ax.set_ylabel(ylabel, fontsize=self.fs(7), color=BLACK, labelpad=2,
                          family=_FONT)
        ax.set_title(title, fontsize=self.fs(8), loc="center",
                     pad=self.fs(_TITLE_PAD), family=_FONT)

    def _draw_message(self, ax, title: str, msg: str) -> None:
        ax.set_title(title, fontsize=self.fs(8), loc="center",
                     pad=self.fs(_TITLE_PAD), family=_FONT)
        for sp in ("top", "right", "left", "bottom"):
            ax.spines[sp].set_visible(False)
        ax.set_xticks([])
        ax.set_yticks([])
        ax.text(0.5, 0.5, self.wrap(msg, self.fs(9)), transform=ax.transAxes,
                ha="center", va="center", color=GREY_MSG, fontsize=self.fs(9),
                family=_FONT)
