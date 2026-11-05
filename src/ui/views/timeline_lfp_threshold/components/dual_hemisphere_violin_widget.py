"""Matplotlib dual-panel violin plot for the Timeline → LFP Threshold page.

Renders the manuscript threshold-distribution figure — one panel per
hemisphere (**Electrode 1** = Left, **Electrode 2** = Right) — embedded via the
shared :class:`ResponsiveFigureWidget`. Each panel shows jade/rose violins
(Group 1 / Group 2) with white-fill boxplots (colored edge, black
median/whiskers), the L2-LR decision threshold as a dashed horizontal line with
a ``µV`` label above it, an inline AUC / 95 % CI / permutation-p metrics block
in the inter-violin gap just below the line (on screen: under the panel title),
a Mann-Whitney significance bracket, and ``n =`` labels (on screen: under the
group names). Like the manuscript ``_plot_dist`` it has no legend: the group
labels, their ``n`` and the jade/rose fills carry it. ``InsufficientResult`` /
skeleton panels fall back to a centered message.

The panel drawing is ported from ``_plot_dist`` / ``_style_ax`` in
``results/lfp_threshold/timeline_mean20_threshold.py`` (the primary manuscript
threshold figure), styled via :func:`matplotlib.rc_context` (scoped by the
base) so global rcParams are never mutated — matching the sibling
Timeline → Peri-Event page (:class:`PeriEventPlot`). The only app-specific
addition over the manuscript ``_plot_dist`` is the inline metrics block (the
manuscript carries AUC/CI in a separate ROC panel, which the app does not
render) and the user-driven dynamic x-tick group labels (the manuscript
hardcodes ``Non-craving`` / ``Craving``). On screen the figure uses constrained-
layout and responsive font scaling; exports render at a fixed canonical size so
the saved figure is manuscript-stable regardless of window size.

Public API mirrors the previous PyQtGraph widget so the View drives it
unchanged: :meth:`update_results`, :meth:`update_panel`,
:meth:`render_skeleton`, :meth:`set_group_labels`, :meth:`clear`,
:meth:`export_state`, plus :meth:`save_figure` for 300-dpi PNG export.
"""

from __future__ import annotations

import logging
from typing import Dict, Optional

import numpy as np
from PySide6.QtWidgets import QWidget

from src.ui.widgets.plot_fonts import plot_font_families
from src.ui.widgets.responsive_figure import ResponsiveFigureWidget

logger = logging.getLogger(__name__)


# ─── Palette (manuscript figure-style guide) ───────────────────────────────
JADE = "#2BA495"        # Group 1 violin edge + box edge
JADE_LIGHT = "#8DD4CA"  # Group 1 violin fill
ROSE = "#D97F86"        # Group 2 violin fill
ROSE_DARK = "#AC4E8D"   # Group 2 violin edge + box edge
BLACK = "#000000"
GREY_MSG = "#888888"

_FONT = plot_font_families()

# Panel-title pad (pt). App-display only; matches PeriEventPlot so both
# Timeline tabs' titles line up identically.
_TITLE_PAD = 10

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


def fmt_p(p: float, n_perm: int) -> str:
    """Format a permutation p-value as a self-contained `<`/`=`-prefixed
    string. Mirrors the manuscript-script convention so the in-app metrics
    block reads identically to the published figure annotation. Same logic
    also lives in `grouping_panel.py:fmt_p` (table footer); keep them in
    lockstep — the helper is 8 lines and 2-copy duplication is cheaper than a
    shared utility module."""
    floor = 1.0 / (n_perm + 1)
    if p <= floor + 1e-12:
        return f"< {floor:.4f}"
    if p < 0.001:
        return "< 0.001"
    if p < 0.01:
        return f"= {p:.4f}"
    return f"= {p:.3f}"


def _sig_bracket_text(mw_p: float) -> str:
    if mw_p < 0.001:
        return "***"
    if mw_p < 0.01:
        return "**"
    if mw_p < 0.05:
        return "*"
    return "n.s."


def _can_violin(vals: np.ndarray) -> bool:
    """matplotlib's ``violinplot`` builds a Gaussian KDE, which raises on
    fewer than two points or zero-variance (constant) data. The service
    only emits ``ThresholdMlResult`` for sufficiently-populated groups, so
    this guard is purely defensive against a degenerate edge group."""
    return vals.size >= 2 and float(np.std(vals)) > 1e-9


class DualHemisphereViolinWidget(ResponsiveFigureWidget):
    """Two side-by-side matplotlib panels (Electrode 1 = Left, Electrode 2 = Right)."""

    # Violins are tall: panels stay side by side down to a squarer canvas.
    IDEAL_ASPECT = 1.05

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent, rc=_RC)

        # Dynamic violin x-tick labels (user's selected event groups). Default
        # to generic placeholders until the View supplies the selection.
        self._g1_label: str = "Group 1"
        self._g2_label: str = "Group 2"

        # None → skeleton; ThresholdMlResult / InsufficientResult → rendered.
        self._results: Dict[str, object] = {"Left": None, "Right": None}
        self.draw()

    # ------------------------------------------------------------------
    # Public API (parity with the former PyQtGraph widget)
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

    def set_group_labels(self, g1_label: str, g2_label: str) -> None:
        """Replace the violin x-tick labels for both panels. Called by the
        View when the user clicks Compare so the ticks reflect the active
        selection (e.g. ``"Happy" / "Neutral"``) instead of the generic
        ``"Group 1" / "Group 2"`` placeholders. Persists across subsequent
        skeleton / result renders until the next call."""
        self._g1_label = str(g1_label) if g1_label else "Group 1"
        self._g2_label = str(g2_label) if g2_label else "Group 2"
        self.draw()

    def export_state(self) -> bool:
        """True iff at least one panel currently shows a full result."""
        from src.core.services.timeline_threshold_ml_service import (
            ThresholdMlResult,
        )
        return any(isinstance(r, ThresholdMlResult)
                   for r in self._results.values())

    def save_figure(self, path: str) -> bool:
        try:
            self.render_export(path, 300)
            return True
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("Failed to save threshold figure: %s", exc,
                         exc_info=True)
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
        from src.core.services.timeline_threshold_ml_service import (
            InsufficientResult,
            ThresholdMlResult,
        )
        if isinstance(result, ThresholdMlResult):
            self._draw_result(ax, result, title, show_ylabel)
        elif isinstance(result, InsufficientResult):
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
        X = np.asarray(r.X, dtype=float)
        y = np.asarray(r.y, dtype=int)
        group1 = X[y == 0]   # position 0, JADE family
        group2 = X[y == 1]   # position 1, ROSE family
        n_g1, n_g2 = int(group1.size), int(group2.size)

        # ── Violins (real α=0.4 — matplotlib, not the PyQtGraph pre-blend) ─
        for vals, pos, fill, edge in (
            (group1, 0, JADE_LIGHT, JADE),
            (group2, 1, ROSE, ROSE_DARK),
        ):
            if not _can_violin(vals):
                continue
            parts = ax.violinplot(vals, positions=[pos], widths=0.6,
                                  showextrema=False, showmedians=False)
            for pc in parts["bodies"]:
                pc.set_facecolor(fill)
                pc.set_edgecolor(edge)
                pc.set_alpha(0.4)
                pc.set_linewidth(self.lw(0.6))

        # ── Boxplots (white fill, colored edge, black median/whiskers) ──
        box_data, box_pos, box_edges = [], [], []
        for vals, pos, edge in (
            (group1, 0, JADE), (group2, 1, ROSE_DARK),
        ):
            if vals.size >= 1:
                box_data.append(vals)
                box_pos.append(pos)
                box_edges.append(edge)
        if box_data:
            bp = ax.boxplot(
                box_data, positions=box_pos, widths=0.18,
                patch_artist=True, showfliers=False,
                medianprops=dict(color=BLACK, linewidth=self.lw(1.5)),
                whiskerprops=dict(color=BLACK, linewidth=self.lw(0.8)),
                capprops=dict(color=BLACK, linewidth=self.lw(0.8)),
            )
            for box, edge in zip(bp["boxes"], box_edges):
                box.set_facecolor("white")
                box.set_edgecolor(edge)
                box.set_linewidth(self.lw(0.8))

        # ── Axis ranges (pooled p1/p99 + asymmetric padding, manuscript) ──
        if X.size:
            y_lo = float(np.percentile(X, 1))
            y_hi = float(np.percentile(X, 99))
        else:
            y_lo, y_hi = 0.0, 1.0
        y_range = max(y_hi - y_lo, 1.0)
        ax.set_ylim(y_lo - y_range * 0.15, y_hi + y_range * 0.25)
        # Violins sit at data x = 0 / 1 (manuscript geometry). Symmetric about
        # 0.5 so the axes-fraction-centered threshold label / metrics block
        # land in the inter-violin gap.
        ax.set_xlim(-0.5, 1.5)

        # ── Threshold line + µV label (centered above the line) ──────────
        thr = float(r.lr_threshold)
        threshold = f"{thr:.0f} µV"
        ax.axhline(thr, color=BLACK, linestyle="--", linewidth=self.lw(0.8),
                   alpha=0.6, zorder=2)
        # On a narrow screen panel the gap between the violins (a fifth of the
        # axes) cannot hold the label; it joins the statistics line instead.
        label_on_line = (not self.on_screen
                         or len(threshold) <= self.line_chars(self.stat_fs(6.5), share=0.17))
        if label_on_line:
            # x in axes coords (0.5 = panel center), y in data coords — same
            # blended transform the manuscript uses for this label.
            ax.text(0.5, thr, threshold, fontsize=self.stat_fs(6.5), color=BLACK,
                    ha="center", va="bottom", family=_FONT, zorder=6,
                    transform=ax.get_yaxis_transform())

        # ── Inline AUC / CI / perm-p metrics block (centered below line) ──
        # On screen it sits under the panel title, above the data: at
        # statistic size it is wider than the gap between the violins.
        n_perm = int(round(1.0 / max(float(r.perm_p_floor), 1e-12)) - 1)
        p_text = fmt_p(float(r.perm_p), n_perm)
        subtitle_pt = 0.0
        if self.on_screen:
            statistics = [
                f"AUC {float(r.auc_loo):.3f} [{float(r.auc_ci[0]):.3f}, "
                f"{float(r.auc_ci[1]):.3f}] CI₉₅",
                f"p {p_text} (perm.)",
            ]
            if not label_on_line:
                statistics.insert(0, f"threshold {threshold}")
            subtitle_pt = self.stats_subtitle(ax, statistics)
        else:
            metrics = "\n".join([
                f"AUC = {float(r.auc_loo):.3f}",
                f"[{float(r.auc_ci[0]):.3f}, {float(r.auc_ci[1]):.3f}]  CI₉₅",
                f"p {p_text}  (perm.)",
            ])
            ax.text(0.5, thr, metrics, fontsize=self.fs(7), color=BLACK,
                    ha="center", va="top", family=_FONT, linespacing=1.3,
                    zorder=6, transform=ax.get_yaxis_transform())

        # ── n labels (data x = 0/1, axes y = 0.02) ───────────────────────
        # On screen they go under the group names instead, off the violins.
        if not self.on_screen:
            for pos, n_val in ((0, n_g1), (1, n_g2)):
                ax.text(pos, 0.02, f"n = {n_val}", fontsize=self.fs(6), color=BLACK,
                        ha="center", va="bottom", family=_FONT,
                        transform=ax.get_xaxis_transform())

        # ── Significance bracket (manuscript formula, data coords) ───────
        y_bar = y_hi + y_range * 0.10
        ax.plot([0, 0, 1, 1], [y_bar * 0.99, y_bar, y_bar, y_bar * 0.99],
                color=BLACK, linewidth=self.lw(0.6), zorder=4)
        ax.text(0.5, y_bar * 1.005, _sig_bracket_text(float(r.mann_whitney_p)),
                ha="center", va="bottom", fontsize=self.stat_fs(8), color=BLACK,
                family=_FONT)

        # ── Axis styling / labels / ticks ────────────────────────────────
        self._style_axes(ax)
        ax.set_xticks([0, 1])
        if self.on_screen:
            # Each label wraps (at " + " first) to its violin's half of the
            # axes, less the y-axis margin.
            size = self.stat_fs(6.5)
            ax.set_xticklabels(
                [f"{self.wrap(label, size, share=0.38, sep=' + ')}\nn = {n_val}"
                 for label, n_val in ((self._g1_label, n_g1), (self._g2_label, n_g2))],
                fontsize=size, color=BLACK, family=_FONT)
        else:
            ax.set_xticklabels([self._g1_label, self._g2_label],
                               fontsize=self.fs(6.5), color=BLACK, family=_FONT)
        # Hide x tick marks but keep the group labels (manuscript).
        ax.tick_params(axis="x", which="both", length=0)
        if show_ylabel:
            ax.set_ylabel("lfp (µV)", fontsize=self.fs(7), color=BLACK, labelpad=2,
                          family=_FONT)
        ax.set_title(title, fontsize=self.fs(8), loc="center",
                     pad=self.fs(_TITLE_PAD) + subtitle_pt, family=_FONT)
