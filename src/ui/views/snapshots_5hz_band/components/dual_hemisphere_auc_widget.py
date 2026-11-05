"""
Dual-Hemisphere AUC Profile Widget for Snapshots 5 Hz Band page.

Renders the manuscript Figure 2 d–f greyscale aesthetic for the per-band
held-out LOO AUC profile of each hemisphere, side by side — via **matplotlib**
(the shared :class:`ResponsiveFigureWidget` + a scoped ``rc_context``) so the
page matches the Timeline pages' manuscript look instead of the prior PyQtGraph
approximation.

The panel drawing is **ported (reimplemented inline, NOT imported)** from
``_plot_per_band_profile`` in
``scripts/create_figure_predictive_ability_3x3.py`` (the published Figure 2
row-2 panel). The styling *plumbing* (the ``_RC`` dict, ``rc_context`` scoping,
the responsive figure base) mirrors the sibling Timeline widgets
(``DualHemisphereViolinWidget`` / ``PeriEventPlot``). Greyscale per-band-AUC
geometry comes from the manuscript script's row-2 panel.

States handled:

1. Pre-analysis empty state (``clear()``): both panels show a centered
   "Click compare to run analysis" placeholder with axes hidden — no plot
   (matches the sibling Timeline / PSD pages).
2. Result set for both hemispheres: full per-band curve + CI + modal marker +
   annotation per panel.
3. Unilateral implant (a ``None`` side passed to ``set_results``): the missing
   side keeps axes + reference lines and shows a centered greyed-out
   "no data — hemisphere not implanted" message.

Standalone: imports only ``PySide6``, ``matplotlib`` (via the base), ``numpy``,
and ``src.*`` presentation helpers (``fmt_p`` from the analysis kernel, plus the
``AucProfileResult`` type under ``TYPE_CHECKING``). It imports **nothing** from
``scripts/`` or ``results/`` — the manuscript script is a read-time aesthetic
reference whose styling is copied here, never imported at runtime.

The widget is purely a presentation surface: the parent View drives state via
``set_results`` / ``clear``; no signals are emitted outward. Public API is
preserved verbatim from the former PyQtGraph widget (``set_results``,
``clear``, ``export_png``) so the View / factory / tests are unchanged. On
screen the figure uses constrained-layout and responsive font scaling; exports
render at a fixed canonical size so the saved figure is manuscript-stable.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Dict, Optional

import numpy as np
from PySide6.QtWidgets import QWidget

from src.core.analysis.snapshot_loo_kernel import fmt_p
from src.ui.widgets.plot_fonts import plot_font_families
from src.ui.widgets.responsive_figure import ResponsiveFigureWidget

if TYPE_CHECKING:
    from src.core.services.snapshot_ml_analysis_service import AucProfileResult

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Color constants — manuscript greyscale aesthetic for the per-band AUC
# profile (Figure 2 d–f). Mirrors the Figure-Style-Guide ROC tokens in the
# project style guide. These NAMES are audited by the unit test (greyscale-only),
# so keep them greyscale hex literals.
# ---------------------------------------------------------------------------
COLOR_PLOT_BG = "#ffffff"        # Figure / axes background (white)
COLOR_AXIS = "#000000"           # Spines + tick labels
COLOR_CURVE = "#000000"          # ROC_CURVE — black per-band curve
COLOR_MODAL_FILL = "#000000"     # Modal-band triangle fill
COLOR_MODAL_OUTLINE = "#ffffff"  # Modal-band triangle outline (white)
COLOR_CI_FILL = "#BFBFBF"        # ROC_FILL — grey CI band
COLOR_REF = "#8A8A8A"            # ROC_CHANCE — chance / 0.7 reference lines
COLOR_MSG = "#888888"            # "no data" message text (not audited)

_FONT = plot_font_families()

# Panel-title pad (pt) — matches the sibling Timeline widgets so titles line up.
_TITLE_PAD = 10

# Manuscript axis envelope (scripts/create_figure_predictive_ability_3x3.py
# `_plot_per_band_profile`): hard y-limits, no adaptive widening.
Y_MIN = 0.30
Y_MAX = 0.95

# Fixed band envelope for the empty / no-data panels (manuscript window
# 5.31–37.5 Hz), so their x-ticks read as real band centres instead of the
# matplotlib 0–1 default. Populated panels set their x-range from the data.
X_MIN_DEFAULT = 4.0
X_MAX_DEFAULT = 38.0

LABEL_X = "band centre (Hz)"     # lowercase + British spelling (manuscript)
LABEL_Y = "loo auc"
HEADER_LEFT = "Electrode 1"
HEADER_RIGHT = "Electrode 2"
NO_DATA_TEXT = "no data — hemisphere not implanted"
# Pre-analysis placeholder — identical text on all four analysis pages.
PLACEHOLDER_TEXT = "Click compare to\nrun analysis"

# rcParams scoped to this widget's draws only (never global). Copied verbatim
# from the sibling Timeline widgets so all three pages share one look.
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


class DualHemisphereAucWidget(ResponsiveFigureWidget):
    """
    Two side-by-side matplotlib panels (Left | Right) showing per-band
    held-out LOO AUC, styled to the manuscript Figure 2 d–f aesthetic.

    Parameters
    ----------
    parent : QWidget | None
        Optional Qt parent.

    Notes
    -----
    Renders the **descriptive** per-band AUC profile (each band held fixed)
    plus its bootstrap CI, marks the modal band selected by the nested LOO
    inner loop, and reports the whole-pipeline LOO AUC + 95 % CI + FWER
    p-value as an in-axes bottom-right annotation (on screen: a line under
    the panel title). It does not perform analysis — all data arrives via
    :meth:`set_results`.
    """

    # -------------------------------------------------------------------
    # Construction
    # -------------------------------------------------------------------

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent, rc=_RC, facecolor=COLOR_PLOT_BG)

        # Render mode distinguishes the two empty-ish states:
        #   "empty"   → axes + reference lines only (pre-analysis / clear()).
        #   "results" → each side: AucProfileResult draws a curve; a None side
        #               draws the "not implanted" message.
        self._mode: str = "empty"
        self._results: Dict[str, Optional["AucProfileResult"]] = {
            "left": None, "right": None,
        }
        self.draw()

    # -------------------------------------------------------------------
    # Public API (verbatim signatures from the former PyQtGraph widget)
    # -------------------------------------------------------------------

    def set_results(
        self,
        left: Optional["AucProfileResult"],
        right: Optional["AucProfileResult"],
    ) -> None:
        """
        Render results for both hemispheres.

        Parameters
        ----------
        left : AucProfileResult | None
            Result for the left hemisphere; ``None`` for unilateral implants
            with no left-side recording.
        right : AucProfileResult | None
            Result for the right hemisphere; ``None`` for unilateral implants
            with no right-side recording.
        """
        self._mode = "results"
        self._results = {"left": left, "right": right}
        self.draw()

    def clear(self) -> None:
        """Reset to the pre-analysis empty state: both panels show axes + the
        two reference lines only (no curve, no message). Y range stays locked
        to ``[Y_MIN, Y_MAX]``."""
        self._mode = "empty"
        self._results = {"left": None, "right": None}
        self.draw()

    def export_png(self, path: str) -> bool:
        """
        Export both panels to a single 300-dpi PNG.

        Renders into a fresh canonical-size figure (via the base) so the export
        is a deterministic, manuscript-grade render independent of the on-screen
        window size. The method name / signature is unchanged so the View's
        ``export_plot`` calls it without modification.

        Parameters
        ----------
        path : str
            Destination file path. Caller owns directory creation / overwrite.

        Returns
        -------
        bool
            True on success, False on any failure.
        """
        try:
            self.render_export(path, 300)
            return True
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("Failed to export AUC figure: %s", exc, exc_info=True)
            return False

    # -------------------------------------------------------------------
    # Drawing
    # -------------------------------------------------------------------

    def render(self, fig) -> None:
        """Draw both hemisphere panels onto ``fig`` (base owns layout/draw)."""
        ax_left, ax_right = self.panels(fig)
        self._draw_panel(ax_left, self._results.get("left"), HEADER_LEFT,
                         show_ylabel=True)
        self._draw_panel(ax_right, self._results.get("right"), HEADER_RIGHT,
                         show_ylabel=self.stacked)

    def _draw_panel(self, ax, result, title: str, show_ylabel: bool) -> None:
        """Dispatch one panel by render state."""
        if self._mode == "empty":
            # Pre-analysis: centered placeholder, axes hidden — no plot. Matches
            # the sibling Timeline / PSD pages so all four share one empty look.
            self._draw_message(ax, title, PLACEHOLDER_TEXT, italic=False)
            return
        if result is None:
            # Post-analysis unilateral implant: the missing side keeps axes +
            # reference lines and shows the centered "not implanted" message.
            self._draw_axes_and_refs(ax, title, show_ylabel)
            ax.text(0.5, 0.5, self.wrap(NO_DATA_TEXT, self.fs(9)),
                    transform=ax.transAxes, ha="center", va="center",
                    color=COLOR_MSG, fontsize=self.fs(9), style="italic",
                    family=_FONT)
            return
        self._draw_result(ax, result, title, show_ylabel)

    def _draw_message(self, ax, title: str, msg: str, *, italic: bool) -> None:
        """Centered greyed-out message with axes fully hidden (no plot, no
        reference lines). Mirrors the sibling Timeline / PSD widgets' empty-state
        rendering so all four analysis pages share one pre-analysis look."""
        ax.set_title(title, fontsize=self.fs(8), loc="center",
                     pad=self.fs(_TITLE_PAD), family=_FONT)
        for sp in ("top", "right", "left", "bottom"):
            ax.spines[sp].set_visible(False)
        ax.set_xticks([])
        ax.set_yticks([])
        ax.text(0.5, 0.5, self.wrap(msg, self.fs(9)), transform=ax.transAxes,
                ha="center", va="center", color=COLOR_MSG, fontsize=self.fs(9),
                style="italic" if italic else "normal", family=_FONT)

    def _style_axes(self, ax) -> None:
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        for sp in ("left", "bottom"):
            ax.spines[sp].set_color(COLOR_AXIS)
            ax.spines[sp].set_alpha(0.3)
        ax.tick_params(colors=COLOR_AXIS, labelsize=self.fs(6))

    def _draw_refs(self, ax) -> None:
        """The 0.5 (chance, dashed) and 0.7 (target, dotted) reference lines."""
        ax.axhline(0.5, color=COLOR_REF, linestyle="--", linewidth=self.lw(0.6),
                   zorder=1)
        ax.axhline(0.7, color=COLOR_REF, linestyle=":", linewidth=self.lw(0.6),
                   zorder=1)

    def _label_axes(self, ax, title: str, show_ylabel: bool,
                    subtitle_pt: float = 0.0) -> None:
        """Axis labels and the panel title, raised ``subtitle_pt`` over the
        statistics line under it (on screen)."""
        ax.set_ylim(Y_MIN, Y_MAX)
        ax.set_xlabel(LABEL_X, fontsize=self.fs(7), color=COLOR_AXIS, labelpad=2,
                      family=_FONT)
        if show_ylabel:
            ax.set_ylabel(LABEL_Y, fontsize=self.fs(7), color=COLOR_AXIS,
                          labelpad=2, family=_FONT)
        ax.set_title(title, fontsize=self.fs(8), loc="center",
                     pad=self.fs(_TITLE_PAD) + subtitle_pt, family=_FONT)

    def _draw_axes_and_refs(self, ax, title: str, show_ylabel: bool) -> None:
        """Empty / no-data panel: reference lines + styled, labelled axes,
        no curve. Uses the fixed manuscript band envelope for the x-range so
        the ticks read as real band centres (not the matplotlib 0–1 default)."""
        self._draw_refs(ax)
        self._style_axes(ax)
        ax.set_xlim(X_MIN_DEFAULT, X_MAX_DEFAULT)
        self._label_axes(ax, title, show_ylabel)

    def _draw_result(self, ax, r, title: str, show_ylabel: bool) -> None:
        centers = np.asarray(r.band_centers_hz, dtype=float)
        aucs = np.asarray(r.per_band_auc, dtype=float)
        ci_lo = np.asarray(r.per_band_ci_lo, dtype=float)
        ci_hi = np.asarray(r.per_band_ci_hi, dtype=float)
        n_bands = centers.size
        if n_bands == 0:
            self._draw_axes_and_refs(ax, title, show_ylabel)
            return

        # CI band first so the curve sits on top.
        ax.fill_between(centers, ci_lo, ci_hi, color=COLOR_CI_FILL, alpha=0.35,
                        linewidth=0, zorder=2)
        # Black per-band AUC curve with small circle markers.
        ax.plot(centers, aucs, color=COLOR_CURVE, linewidth=self.lw(0.6), marker="o",
                markersize=self.ms(2.5), zorder=3)
        # Modal-band downward triangle (black fill, white edge).
        modal_idx = int(r.modal_band_idx)
        if 0 <= modal_idx < n_bands:
            ax.plot(centers[modal_idx], aucs[modal_idx], marker="v",
                    markersize=self.ms(7), color=COLOR_MODAL_FILL,
                    markeredgecolor=COLOR_MODAL_OUTLINE,
                    markeredgewidth=self.lw(0.6), zorder=5)
        self._draw_refs(ax)

        self._style_axes(ax)
        ax.set_xlim(float(centers[0]) - 1.0, float(centers[-1]) + 1.0)
        if self.on_screen:
            # On screen the block sits under the title, above the data: at
            # statistic size it would cover the CI band in the corner.
            subtitle_pt = self.stats_subtitle(ax, self._annotation_text(r).split("\n"))
            self._label_axes(ax, title, show_ylabel, subtitle_pt)
            return
        self._label_axes(ax, title, show_ylabel)

        # In-axes annotation block (modal band + pipeline AUC + CI + FWER p),
        # bottom-right — manuscript `_plot_modal_roc` convention.
        ax.text(0.97, 0.05, self._annotation_text(r), transform=ax.transAxes,
                ha="right", va="bottom", fontsize=self.fs(6), color=COLOR_AXIS,
                family=_FONT, linespacing=1.3, zorder=6)

    def _annotation_text(self, r) -> str:
        """Build the bottom-right annotation for one panel."""
        edges = np.asarray(r.band_edges_hz, dtype=float)
        # Defensive clamp so a malformed modal index can't crash the renderer.
        modal_idx = max(0, min(int(r.modal_band_idx), len(edges) - 1))
        lo, hi = float(edges[modal_idx][0]), float(edges[modal_idx][1])
        auc = float(r.pipeline_loo_auc)
        ci_lo = float(r.pipeline_loo_ci_lo)
        ci_hi = float(r.pipeline_loo_ci_hi)
        p_str = fmt_p(float(r.fwer_p), int(r.n_perm))
        return (
            f"modal {lo:.2f}–{hi:.2f} Hz\n"
            f"AUC {auc:.3f} [{ci_lo:.3f}, {ci_hi:.3f}]\n"
            f"p {p_str}"
        )
