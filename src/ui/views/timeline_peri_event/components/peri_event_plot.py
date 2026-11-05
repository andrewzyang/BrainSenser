"""Matplotlib dual-panel peri-event plot for the Timeline → Peri-Event page.

Renders the manuscript cluster-permutation peri-event figure (one panel per
hemisphere — **Electrode 1** = Left, **Electrode 2** = Right) embedded via the
shared :class:`ResponsiveFigureWidget`. The panel drawing is ported from
``scripts/create_figure_timeline_cluster_perm.py`` (``plot_panel`` /
``overlay_cluster_bars`` / ``_smooth`` / ``_tight_ylim`` / ``_format_p``)
with the lowercase-axis-label, side-1-only-y-label styling of the combined
3×3 manuscript figure.

The manuscript aesthetic is applied via :func:`matplotlib.rc_context` (scoped
by the base) so global rcParams are never mutated, with explicit per-artist
font sizes — routed through :meth:`fs` so they scale with the canvas — so
layout is correct on every redraw. On screen the figure uses constrained-layout
and responsive font scaling; exports render at a fixed canonical size so the
saved figure is manuscript-stable regardless of window size.

Public API mirrors the LFP-Threshold violin widget so the View can drive it
the same way: :meth:`render_skeleton`, :meth:`update_panel`,
:meth:`update_results`, :meth:`clear`, :meth:`export_state`, plus
:meth:`save_figure` for PNG export.
"""

from __future__ import annotations

import logging
from typing import Dict, Optional, Sequence

import numpy as np
from PySide6.QtWidgets import QWidget
from scipy.interpolate import PchipInterpolator

from src.ui.widgets.plot_fonts import plot_font_families
from src.ui.widgets.responsive_figure import ResponsiveFigureWidget

logger = logging.getLogger(__name__)


# ─── Palette (manuscript figure-style guide) ───────────────────────────────
JADE = "#2BA495"     # non-craving (Group 1)
ROSE = "#D97F86"     # craving (Group 2)
BLACK = "#000000"
CLUSTER_BAR_COLOR = "#555555"
GREY_MSG = "#888888"

_FONT = plot_font_families()

# Panel-title pad (pt). App-display only: titles are centered and raised
# slightly vs the manuscript scripts' loc="left"/pad=5. Shared by both
# call sites so skeleton/result/insufficient states line up identically.
_TITLE_PAD = 10

# On screen, CI bands reach at most this axes height, below the cluster bars
# at 0.94.
_BAND_TOP_MAX = 0.90

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


# ─── Stats-display helpers (ported from the figure script) ─────────────────
def _smooth(offset_bins: Sequence[int], grid: np.ndarray,
            y_vals: np.ndarray) -> np.ndarray:
    """Shape-preserving monotone-cubic (PCHIP) interpolation of the per-bin
    values onto ``grid``. NaN bins are dropped; ``extrapolate=False`` so the
    curve never overshoots past the populated bin range."""
    x = np.asarray(offset_bins, dtype=float)
    y = np.asarray(y_vals, dtype=float)
    mask = np.isfinite(y)
    if mask.sum() < 2:
        fill = np.nan if mask.sum() == 0 else float(y[mask][0])
        return np.full_like(grid, fill)
    pch = PchipInterpolator(x[mask], y[mask], extrapolate=False)
    return pch(grid)


def _tight_ylim(craving_mean: np.ndarray, neutral_mean: np.ndarray,
                pad_top_frac: float = 0.28, pad_bottom_frac: float = 0.35):
    """Mean-curve-driven y-limits with asymmetric padding (more bottom room
    for the lower-left legend, top room for the cluster bar)."""
    means = np.concatenate([np.asarray(craving_mean, dtype=float),
                            np.asarray(neutral_mean, dtype=float)])
    means = means[np.isfinite(means)]
    if len(means) == 0:
        return None
    y_min, y_max = float(means.min()), float(means.max())
    rng = y_max - y_min
    if rng == 0:
        return y_min - 1, y_max + 1
    return y_min - pad_bottom_frac * rng, y_max + pad_top_frac * rng


def _format_p(p: float, n_perm: int) -> str:
    floor = 1.0 / (n_perm + 1)
    if p <= floor + 1e-12:
        return f"p < {floor:.4f}"
    if p < 0.001:
        return "p < 0.001"
    if p < 0.01:
        return f"p = {p:.4f}"
    return f"p = {p:.3f}"


class PeriEventPlot(ResponsiveFigureWidget):
    """Two side-by-side matplotlib panels (Electrode 1 = Left, Electrode 2 = Right)."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent, rc=_RC)

        # None → skeleton; PeriEventResult / InsufficientPeriEvent → rendered.
        self._results: Dict[str, object] = {"Left": None, "Right": None}
        self.draw()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update_results(self, results: Dict[str, object]) -> None:
        for hemi in ("Left", "Right"):
            self._results[hemi] = (results or {}).get(hemi)
        self.draw()

    def update_panel(self, hemisphere: str, result) -> None:
        if hemisphere not in self._results:
            logger.warning("Unknown hemisphere %r", hemisphere)
            return
        self._results[hemisphere] = result
        self.draw()

    def render_skeleton(self) -> None:
        self._results = {"Left": None, "Right": None}
        self.draw()

    def clear(self) -> None:
        self.render_skeleton()

    def export_state(self) -> bool:
        """True iff at least one panel currently shows a full result."""
        from src.core.services.timeline_peri_event_service import PeriEventResult
        return any(isinstance(r, PeriEventResult) for r in self._results.values())

    def save_figure(self, path: str) -> bool:
        try:
            self.render_export(path, 300)
            return True
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("Failed to save peri-event figure: %s", exc, exc_info=True)
            return False

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------

    def render(self, fig) -> None:
        """Draw both hemisphere panels onto ``fig`` (base owns layout/draw)."""
        ax1, ax2 = self.panels(fig)
        self._draw_panel(ax1, self._results.get("Left"), "Electrode 1",
                         show_ylabel=True)
        self._draw_panel(ax2, self._results.get("Right"), "Electrode 2",
                         show_ylabel=self.stacked)

    def _draw_panel(self, ax, result, title: str, show_ylabel: bool) -> None:
        from src.core.services.timeline_peri_event_service import (
            InsufficientPeriEvent,
            PeriEventResult,
        )
        if isinstance(result, PeriEventResult):
            self._draw_result(ax, result, title, show_ylabel)
        elif isinstance(result, InsufficientPeriEvent):
            self._draw_message(ax, title, f"insufficient data\n{result.reason}",
                               italic=True)
        else:
            self._draw_message(
                ax, title, "Click compare to\nrun analysis",
                italic=False,
            )

    def _style_axes(self, ax) -> None:
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        for sp in ("left", "bottom"):
            ax.spines[sp].set_color(BLACK)
            ax.spines[sp].set_alpha(0.3)
        ax.tick_params(colors=BLACK, labelsize=self.fs(6))

    def _draw_message(self, ax, title: str, msg: str, *, italic: bool) -> None:
        ax.set_title(title, fontsize=self.fs(8), loc="center",
                     pad=self.fs(_TITLE_PAD), family=_FONT)
        for sp in ("top", "right", "left", "bottom"):
            ax.spines[sp].set_visible(False)
        ax.set_xticks([])
        ax.set_yticks([])
        ax.text(0.5, 0.5, self.wrap(msg, self.fs(9)), transform=ax.transAxes,
                ha="center", va="center", color=GREY_MSG, fontsize=self.fs(9),
                style="italic" if italic else "normal", family=_FONT)

    def _draw_result(self, ax, r, title: str, show_ylabel: bool) -> None:
        offset_bins = list(r.offset_bins)
        grid = np.linspace(offset_bins[0], offset_bins[-1], 200)

        # Group 1 (Jade) — non-craving class.
        n_mean = _smooth(offset_bins, grid, r.neutral_mean)
        n_lo = _smooth(offset_bins, grid, r.neutral_lo)
        n_hi = _smooth(offset_bins, grid, r.neutral_hi)
        ax.fill_between(grid, n_lo, n_hi, color=JADE, alpha=0.12,
                        zorder=2, linewidth=0)
        ax.plot(grid, n_mean, color=JADE, linewidth=self.lw(1.0), zorder=3,
                label=f"Group 1 (n = {r.n_neutral})")

        # Group 2 (Rose) — craving class.
        c_mean = _smooth(offset_bins, grid, r.craving_mean)
        c_lo = _smooth(offset_bins, grid, r.craving_lo)
        c_hi = _smooth(offset_bins, grid, r.craving_hi)
        ax.fill_between(grid, c_lo, c_hi, color=ROSE, alpha=0.12,
                        zorder=2, linewidth=0)
        ax.plot(grid, c_mean, color=ROSE, linewidth=self.lw(1.0), zorder=3,
                label=f"Group 2 (n = {r.n_craving})")

        yl = _tight_ylim(r.craving_mean, r.neutral_mean)
        if yl is not None:
            if self.on_screen and any(cl["p"] <= 0.05 for cl in r.clusters):
                # Keep the CI bands below the cluster bars, so no p-value sits
                # on data (the manuscript limits follow the means only).
                band_top = np.nanmax(np.r_[n_hi, c_hi])
                yl = (yl[0], max(yl[1], yl[0] + (band_top - yl[0]) / _BAND_TOP_MAX))
            ax.set_ylim(*yl)

        # Event-press reference line.
        ax.axvline(0, color=BLACK, linestyle="--", linewidth=self.lw(0.8),
                   alpha=0.3, zorder=1)

        self._style_axes(ax)
        ax.set_xticks(offset_bins)
        ax.set_xticklabels(self._bin_labels(offset_bins), fontsize=self.fs(6),
                           family=_FONT)
        ax.set_xlabel(self.wrap("time from snapshot press (min)", self.fs(7)),
                      fontsize=self.fs(7), color=BLACK, labelpad=2, family=_FONT)
        if show_ylabel:
            ax.set_ylabel("narrowband lfp power (µV)", fontsize=self.fs(7),
                          color=BLACK, labelpad=2, family=_FONT)
        ax.set_title(title, fontsize=self.fs(8), loc="center",
                     pad=self.fs(_TITLE_PAD), family=_FONT)
        ax.legend(fontsize=self.fs(6), frameon=False, loc="lower left",
                  handlelength=1.2, handletextpad=0.4)

        self._overlay_cluster_bars(ax, r)

    def _bin_labels(self, offset_bins) -> list:
        """A label on every bin; on screen, when more than 7 would sit on a
        compact panel or crowd a wider one, on every second bin, counted from
        the bin nearest 0 (the press), so 0 stays labelled. The tick marks stay
        on every bin."""
        labels = [str(b) for b in offset_bins]
        if not self.on_screen or len(labels) <= 7:
            return labels
        # Each label with a two-character gap to the next must fit the row.
        crowded = len(labels) * (max(map(len, labels)) + 2) > self.line_chars(self.fs(6))
        if self.compact or crowded:
            anchor = min(range(len(labels)), key=lambda i: abs(offset_bins[i]))
            labels = [label if (i - anchor) % 2 == 0 else ""
                      for i, label in enumerate(labels)]
        return labels

    def _overlay_cluster_bars(self, ax, r) -> None:
        """Grey bar above the curves spanning each significant (p ≤ 0.05)
        cluster, with the cluster permutation p-value annotated above it.
        One bar per significant cluster (the permutation test yields one
        p-value per cluster, not per bin)."""
        trans = ax.get_xaxis_transform()  # x = data, y = axes
        bar_y = 0.94
        text_y = 0.97
        for cl in r.clusters:
            if cl["p"] > 0.05:
                continue
            x0 = cl["start_bin"]
            x1 = cl["end_bin"]
            if x1 == x0:
                x0 -= 2.0
                x1 += 2.0
            ax.plot([x0, x1], [bar_y, bar_y], color=CLUSTER_BAR_COLOR,
                    linewidth=self.lw(1.8), solid_capstyle="butt", transform=trans,
                    clip_on=False)
            xm = (cl["start_bin"] + cl["end_bin"]) / 2.0
            ax.text(xm, text_y, _format_p(cl["p"], r.n_perm), fontsize=self.stat_fs(6),
                    color=BLACK, ha="center", va="bottom", transform=trans,
                    clip_on=False, family=_FONT)
