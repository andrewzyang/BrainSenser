"""Shared responsive base for the dual-panel manuscript-style plot widgets.

The four analysis plot widgets (Snapshots PSD / Snapshots 5 Hz Band AUC /
Timeline Peri-Event / Timeline LFP-Threshold violin) all embed a matplotlib
figure the same way and want the same responsive behavior. This base owns that
behavior once; each subclass implements only :meth:`render` (its panel drawing).

What the base provides
----------------------
* **Canvas embedding** via the shared :class:`MatplotlibWidget` (Expanding size
  policy) plus a sensible minimum height, so the plot fills its layout slot.
* **Display layout via matplotlib constrained-layout.** Instead of a hardcoded
  ``subplots_adjust(...)`` tuned for one figure size, the on-screen figure uses
  the constrained layout engine, which auto-fits titles / labels / legends to
  the *current* canvas size — labels never clip when the panel is short and no
  dead margin appears when it is large.
* **A render context per render** (:class:`RenderContext`). On screen it is
  derived from the canvas size (:func:`compute_display_context`): each panel is
  fitted to the manuscript's 5 × 4 in cell, side by side or stacked on a
  narrow / tall canvas, with text and lines scaled together (by the fit times
  the interface size, :meth:`set_ui_scale`, within bounds) and a compact mode
  for small cells.
  Subclasses create their axes with :meth:`panels`, route every font size
  through :meth:`fs` (statistics through :meth:`stat_fs`), every line width /
  marker size through :meth:`lw` / :meth:`ms`, and apply display-only rules
  when :attr:`on_screen`.
* **Scheduling.** A state change re-renders at once (:meth:`draw`); the canvas
  paints it lazily (not while hidden or mid-drag). Around each canvas draw —
  inside matplotlib's ``_is_drawing`` guard — the base re-renders first if the
  canvas size now calls for another context, so the first frame after a page
  switch is already final and a window drag costs one re-render, at its end.
* **Deterministic, manuscript-stable export.** :meth:`render_export` draws into a
  **fresh, fixed-size** figure with :data:`EXPORT_CTX` — independent of the
  on-screen window, canvas and interface size — using the manuscript
  ``subplots_adjust`` margins. PNG, PDF and SVG bytes depend only on the data.

MVVM note: this is a pure View-layer widget. It imports only matplotlib /
PySide6 / the shared canvas, font and token helpers — no ViewModels, services,
or models.
"""

from __future__ import annotations

import contextlib
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence, Tuple

import matplotlib
import matplotlib.style
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from PySide6.QtWidgets import QVBoxLayout, QWidget

from src.ui.policy.tokens import Dim
from src.ui.widgets.mpl_canvas import MatplotlibWidget
from src.ui.widgets.plot_fonts import plot_font_families

# Manuscript subplot margins used for *export* only (the on-screen figure uses
# constrained-layout instead). Matches the value every widget previously hard-
# coded in its ``_draw``, so exported figures keep the exact manuscript look.
_DEFAULT_EXPORT_ADJUST = dict(
    left=0.09, right=0.97, top=0.84, bottom=0.16, wspace=0.28,
)

# Repeatable exports (D6): SVG clip-path / marker ids are salted at random and
# PDF / SVG carry the export time unless these are fixed.
_SVG_HASH_SALT = "brainsenser-export"
_EXPORT_METADATA = {".pdf": {"CreationDate": None}, ".svg": {"Date": None}}

# Spine and tick strokes, which come from rcParams; on screen they scale with
# the line factor like every line width the widgets pass explicitly.
_STROKE_RC = (
    "axes.linewidth",
    "xtick.major.width", "xtick.minor.width", "xtick.major.size", "xtick.minor.size",
    "ytick.major.width", "ytick.minor.width", "ytick.major.size", "ytick.minor.size",
)

# On-screen typography (plan §4.6): a panel's fit is its share of the
# manuscript's 5 × 4 in cell; text follows it, times the interface size,
# within [1.15, 1.6] (ticks >= 9.6 px) in 0.05 steps.
_CELL_IN = (5.0, 4.0)
_TEXT_MIN, _TEXT_MAX, _TEXT_STEP = 1.15, 1.6, 0.05
_COMPACT_ENTER, _COMPACT_LEAVE = 0.95, 1.0
_ARRANGEMENT_HYSTERESIS = math.log(1.15)  # the other arrangement must fit 15 % better
_MIN_STACKED_CELL_H_IN = 2.2
# Statistic text is never smaller than this on screen (logical px).
STAT_MIN_PX = 11
# A generous mean glyph width (em) of the plot fonts: text wraps early, not late.
_GLYPH_EM = 0.6


@dataclass(frozen=True)
class RenderContext:
    """How one render sizes and arranges the two panels."""

    target: str = "display"       # "display" | "export"
    text: float = 1.0             # multiplies the manuscript pt sizes
    line: float = 1.0             # multiplies line widths and marker sizes
    arrangement: str = "row"      # "row": side by side | "column": stacked
    density: str = "regular"      # "compact" for small cells: crowded ticks thin out
    panel_width_in: float = 5.0   # one panel's cell width (0.1-in steps), for wrapping


EXPORT_CTX = RenderContext(target="export")


def _pack(pieces: Sequence[str], joiner: str, width: int) -> list:
    """Greedily join ``pieces`` with ``joiner`` into lines of at most
    ``width`` characters (a piece longer than that gets a line of its own)."""
    lines = [pieces[0]]
    for piece in pieces[1:]:
        if len(lines[-1]) + len(joiner) + len(piece) <= width:
            lines[-1] += joiner + piece
        else:
            lines.append(piece)
    return lines


def compute_display_context(
    width_in: float,
    height_in: float,
    ui_scale: float = 1.0,
    prev: Optional[RenderContext] = None,
    *,
    ideal_aspect: float = 1.45,
) -> RenderContext:
    """The on-screen context for a ``width_in`` × ``height_in`` canvas (pure).

    The panels sit side by side or stacked, whichever gives cells closer to
    ``ideal_aspect`` (width / height); against ``prev`` the other arrangement
    has to be 15 % closer, and stacking needs cells at least 2.2 in tall.
    ``fit = min(cell_w / 5 in, cell_h / 4 in)``; text is ``ui_scale × fit``
    clamped to [1.15, 1.6], in 0.05 steps, and lines scale with it. The canvas
    pixel ratio already enlarges the text by the interface size; ``ui_scale``
    only undoes the 1/``ui_scale`` the logical canvas shrinks by, so the clamp
    applies to the product (outside it, text would grow with the square of the
    interface size). Compact is entered below fit 0.95 and left at 1.0.
    """
    width_in, height_in = max(float(width_in), 0.01), max(float(height_in), 0.01)

    def cell(arrangement: str) -> Tuple[float, float]:
        return (width_in / 2, height_in) if arrangement == "row" else (width_in, height_in / 2)

    def mismatch(arrangement: str) -> float:
        cell_w, cell_h = cell(arrangement)
        return abs(math.log(cell_w / cell_h / ideal_aspect))

    candidates = ["row"] + (["column"] if height_in / 2 >= _MIN_STACKED_CELL_H_IN else [])
    arrangement = min(candidates, key=mismatch)
    if (prev is not None and prev.arrangement in candidates
            and mismatch(prev.arrangement) < mismatch(arrangement) + _ARRANGEMENT_HYSTERESIS):
        arrangement = prev.arrangement
    cell_w, cell_h = cell(arrangement)
    fit = min(cell_w / _CELL_IN[0], cell_h / _CELL_IN[1])
    scaled = min(max(ui_scale * fit, _TEXT_MIN), _TEXT_MAX)
    text = round(round(scaled / _TEXT_STEP) * _TEXT_STEP, 2)
    was_compact = prev is not None and prev.density == "compact"
    compact = fit < (_COMPACT_LEAVE if was_compact else _COMPACT_ENTER)
    return RenderContext("display", text, text, arrangement,
                         "compact" if compact else "regular", round(cell_w, 1))


class ResponsiveFigureWidget(QWidget):
    """Base for the dual-panel matplotlib plot widgets.

    Subclasses must implement :meth:`render`, which receives a
    :class:`matplotlib.figure.Figure`, creates its two axes with
    :meth:`panels`, and draws every panel — sourcing each font size through
    :meth:`fs` / :meth:`stat_fs` and each line width / marker size through
    :meth:`lw` / :meth:`ms`, so everything scales with the context. ``render``
    must work on *any* figure it is handed (the live on-screen one and the
    throwaway export one), so it must not touch ``self._mpl``, must not call
    ``subplots_adjust`` / ``set_layout_engine`` (the base owns layout) and must
    never draw (``draw`` / ``draw_idle``): the base decides when to draw.

    Construction contract: the base does **not** render on ``__init__``
    (subclass state is not ready yet). The subclass sets up its state, then
    calls :meth:`draw` once at the end of its own ``__init__``.
    """

    # Panel aspect (width / height) the arrangement aims for.
    IDEAL_ASPECT = 1.45

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        *,
        rc: Optional[dict] = None,
        export_adjust: Optional[dict] = None,
        export_size: Tuple[float, float] = (10.0, 4.0),
        facecolor: str = "white",
        min_height_px: int = Dim.PLOT_MIN_H,
        width: float = 10.0,
        height: float = 4.0,
        dpi: int = 100,
    ) -> None:
        super().__init__(parent)

        self._rc = dict(rc or {})
        self._export_adjust = dict(export_adjust or _DEFAULT_EXPORT_ADJUST)
        self._export_size = export_size
        self._facecolor = facecolor
        self._stat_min_pt = STAT_MIN_PX * 72 / dpi  # the canvas draws 1 in as `dpi` logical px
        self._ui_scale = 1.0
        # The context of the last on-screen render, and of the render in progress.
        self._context = compute_display_context(width, height,
                                                ideal_aspect=self.IDEAL_ASPECT)
        self._rendering: Optional[RenderContext] = None

        self._mpl = MatplotlibWidget(self, width=width, height=height, dpi=dpi)
        self._mpl.canvas.draw_scope = self._drawing
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._mpl)
        if min_height_px:
            self.setMinimumHeight(int(min_height_px))

    # ------------------------------------------------------------------
    # Render context (read by render())
    # ------------------------------------------------------------------

    @property
    def context(self) -> RenderContext:
        """The context of the render in progress; between renders, the on-screen one."""
        return self._rendering if self._rendering is not None else self._context

    @property
    def on_screen(self) -> bool:
        """True unless rendering an export: display-only rules apply."""
        return self.context.target == "display"

    @property
    def stacked(self) -> bool:
        """True when the panels are stacked (each then labels its own y axis)."""
        return self.context.arrangement == "column"

    @property
    def compact(self) -> bool:
        """True for a compact on-screen render (exports are always regular)."""
        return self.context.density == "compact"

    def fs(self, pt: float) -> float:
        """Scale a manuscript point size by the context's text factor (export: 1.0)."""
        return float(pt) * self.context.text

    def stat_fs(self, pt: float) -> float:
        """:meth:`fs` for statistic text, which on screen never drops below
        ``STAT_MIN_PX``; exports keep the manuscript size."""
        size = self.fs(pt)
        return max(size, self._stat_min_pt) if self.on_screen else size

    def lw(self, pt: float) -> float:
        """Scale a manuscript line width by the context's line factor."""
        return float(pt) * self.context.line

    def ms(self, pt: float) -> float:
        """Scale a manuscript marker size by the context's line factor."""
        return float(pt) * self.context.line

    def panels(self, fig: Figure):
        """The two hemisphere axes on ``fig``: side by side, or stacked when
        the canvas is narrow or tall."""
        return fig.subplots(2, 1) if self.stacked else fig.subplots(1, 2)

    def line_chars(self, size_pt: float, share: float = 0.8) -> int:
        """How many characters at ``size_pt`` fit on ``share`` of the panel
        width (an estimate that errs short)."""
        width_pt = share * self.context.panel_width_in * 72
        return max(1, int(width_pt / (_GLYPH_EM * size_pt)))

    def wrap(self, text: str, size_pt: float, share: float = 0.8, sep: str = " ") -> str:
        """``text`` wrapped on screen to ``share`` of the panel width at
        ``size_pt``, breaking at ``sep`` first, then at spaces, then after the
        slashes of a word still too long ("Drinking/Craving"); exports keep it
        as is."""
        if not self.on_screen:
            return text
        width = self.line_chars(size_pt, share)
        lines = []
        for line in text.split("\n"):
            for part in _pack(line.split(sep), sep, width):
                for words in _pack(part.split(" "), " ", width):
                    pieces = words.split("/")
                    lines += _pack([piece + "/" for piece in pieces[:-1]] + pieces[-1:], "", width)
        return "\n".join(lines)

    def stats_subtitle(self, ax, parts: Sequence[str]) -> float:
        """On-screen placement of a panel's statistics block: ``parts`` joined
        by " · " just above the axes — outside the data, under the panel title
        (wrapped on a narrow panel). Returns the height it takes (pt), for the
        caller to add to the title pad."""
        size = self.stat_fs(7)
        text = self.wrap(" · ".join(parts), size, share=0.9, sep=" · ")
        gap = self.fs(3)
        ax.annotate(text, (0.5, 1.0), xycoords="axes fraction", xytext=(0, gap),
                    textcoords="offset points", ha="center", va="bottom",
                    fontsize=size, color="black", linespacing=1.2,
                    family=plot_font_families(), annotation_clip=False)
        return gap + 1.2 * size * (text.count("\n") + 1)

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------

    def render(self, fig: Figure) -> None:  # pragma: no cover - abstract
        """Draw all panels onto ``fig``. Implemented by subclasses."""
        raise NotImplementedError

    def draw(self) -> None:
        """Re-render the on-screen figure for the current state.

        Subclasses call this after every state change. The figure's artists
        are rebuilt now; the canvas paints them on its next draw, which waits
        while the plot is hidden or the window is being dragged.
        """
        context = self._display_context()
        with self._style(context):
            self._render_display(context)
        self._mpl.canvas.draw_idle()

    def set_ui_scale(self, factor: float) -> None:
        """Set the interface-size factor the on-screen text follows (pages
        push it; exports never read it). Takes effect on the next draw."""
        if float(factor) != self._ui_scale:
            self._ui_scale = float(factor)
            self._mpl.canvas.draw_idle()

    def is_layout_settled(self) -> bool:
        """True when the frame on screen is final: no drag or draw pending,
        and the last render's context is the one the canvas size calls for.
        Hidden plots count as settled; they render when shown.

        Lets tests and the responsive harness wait for the final frame
        deterministically instead of sleeping.
        """
        canvas = self._mpl.canvas
        if canvas.is_resizing():
            return False
        if not self.isVisible():
            return True
        return not canvas.draw_pending() and self._display_context() == self._context

    def _display_context(self) -> RenderContext:
        width_in, height_in = self._mpl.figure.get_size_inches()
        return compute_display_context(width_in, height_in, self._ui_scale, self._context,
                                       ideal_aspect=self.IDEAL_ASPECT)

    @contextlib.contextmanager
    def _drawing(self):
        """The canvas's draw scope: first re-render if the canvas size now
        calls for another context, then let the canvas draw under the same
        rcParams."""
        context = self._display_context()
        with self._style(context):
            if context != self._context:
                self._render_display(context)
            yield

    def _render_display(self, context: RenderContext) -> None:
        fig = self._mpl.figure
        fig.clear()
        try:
            fig.set_layout_engine("constrained")
        except Exception:  # pragma: no cover - older mpl fallback
            pass
        fig.set_facecolor(self._facecolor)
        self._render(fig, context)
        self._context = context

    def _render(self, fig: Figure, context: RenderContext) -> None:
        self._rendering = context
        try:
            self.render(fig)
        finally:
            self._rendering = None

    @contextlib.contextmanager
    def _style(self, context: RenderContext):
        """matplotlib's default style under the widget's rcParams, so a user
        ``matplotlibrc`` cannot leak in; strokes scaled for the context."""
        rc = dict(self._rc)
        if context.target == "export":
            rc["svg.hashsalt"] = _SVG_HASH_SALT
        elif context.line != 1.0:
            for key in _STROKE_RC:
                rc[key] = rc.get(key, matplotlib.rcParamsDefault[key]) * context.line
        with matplotlib.style.context("default"), matplotlib.rc_context(rc):
            yield

    # ------------------------------------------------------------------
    # Deterministic export
    # ------------------------------------------------------------------

    def render_export(self, path: str, dpi: int) -> None:
        """Render the panels into a fresh canonical-size figure and save.

        Reads only :data:`EXPORT_CTX` — never the on-screen context, canvas or
        interface size — and fixes the SVG hash salt and leaves out creation
        dates, so the bytes of every format depend only on the data. Uses the
        manuscript ``subplots_adjust`` margins (not constrained-layout) plus
        ``bbox_inches="tight"``. Does not validate the file extension — callers
        that need that (e.g. PSD ``export_figure``) check it themselves before
        calling.
        """
        with self._style(EXPORT_CTX):
            export_fig = Figure(figsize=self._export_size)
            FigureCanvasAgg(export_fig)  # attach a canvas so savefig has a backend
            export_fig.set_facecolor(self._facecolor)
            self._render(export_fig, EXPORT_CTX)
            export_fig.subplots_adjust(**self._export_adjust)
            export_fig.savefig(
                path, dpi=dpi, bbox_inches="tight", facecolor=self._facecolor,
                metadata=_EXPORT_METADATA.get(Path(path).suffix.lower()),
            )
