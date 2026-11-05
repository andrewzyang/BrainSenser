"""Matplotlib canvas for the app's plot widgets.

:class:`MatplotlibCanvas` is the Agg canvas the plots draw on and
:class:`MatplotlibWidget` the container that embeds it (both moved here from
``src/ui/views/timeline_peri_event/components/matplotlib_canvas.py``, which
re-exports them). On top of matplotlib's Qt canvas, the canvas:

* binds PySide6 whatever the import order: PySide6 is imported before
  ``backend_qtagg`` (``backend_qt5agg`` binds the installed PyQt5 when it is
  imported first);
* connects its window's screen signals once — matplotlib 3.10.0 adds another
  connection on every show, i.e. on every page switch;
* hints its minimum height, so the live figure size never feeds back into the
  page layout (a page in a scroll area could otherwise never shrink again);
* hands wheel events to the nearest scroll area, so the page scrolls under a
  plot (a synthetic wheel event would not propagate there by itself);
* draws lazily: not while hidden (the first paint after a show draws), and not
  on every step of a window drag — the last frame is shown stretched until
  resize events pause for ``RESIZE_SETTLE_MS``, then the canvas draws once;
* enters ``draw_scope`` around every draw, inside matplotlib's ``_is_drawing``
  guard, so its owner can re-render for the new size first without that
  re-render queueing another draw.
"""

import contextlib
from typing import Callable, ContextManager, Optional

from PySide6.QtCore import QRectF, QSize, QTimer
from PySide6.QtGui import QImage, QPainter, QResizeEvent
from PySide6.QtWidgets import (
    QAbstractScrollArea,
    QApplication,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

# After PySide6 (see the module docstring).
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure


class MatplotlibCanvas(FigureCanvasQTAgg):
    """Matplotlib figure embedded in PySide6 (Expanding in both directions)."""

    # Resize events closer together than this are one drag: no draw until it pauses.
    RESIZE_SETTLE_MS = 80

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        width: float = 10,
        height: float = 6,
        dpi: int = 100
    ):
        self.fig = Figure(figsize=(width, height), dpi=dpi)
        self.fig.patch.set_facecolor('#ffffff')

        super().__init__(self.fig)

        # Context-manager factory entered around every draw (see the module docstring).
        self.draw_scope: Callable[[], ContextManager] = contextlib.nullcontext
        self._needs_draw = True    # a draw was asked for and has not happened yet
        self._frame_shown = False  # a frame is on screen, painted since the last show
        self._screen_window = None
        # Owned timers, so nothing fires once the canvas is deleted (matplotlib
        # queues its idle draw on an unowned QTimer.singleShot).
        self._idle_timer = QTimer(self)
        self._idle_timer.setSingleShot(True)
        self._idle_timer.setInterval(0)
        self._idle_timer.timeout.connect(self._draw_if_due)
        self._settle_timer = QTimer(self)
        self._settle_timer.setSingleShot(True)
        self._settle_timer.setInterval(self.RESIZE_SETTLE_MS)
        self._settle_timer.timeout.connect(self._on_resize_settled)

        self.setParent(parent)  # after the state above: reparenting sends a hide event

        FigureCanvasQTAgg.setSizePolicy(
            self,
            QSizePolicy.Expanding,
            QSizePolicy.Expanding
        )
        FigureCanvasQTAgg.updateGeometry(self)

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------

    def draw(self):
        """Render the figure, then request a repaint; mid-drag, wait for the
        drag to pause."""
        if self._is_drawing:
            return
        if self.is_resizing():
            self._needs_draw = True
            return
        self._render_frame()
        self.update()

    def draw_idle(self):
        """Queue a draw; while hidden or mid-drag, only remember that one is due."""
        if self._is_drawing:
            return
        self._needs_draw = True
        if self.isVisible() and not self.is_resizing():
            self._idle_timer.start()

    def draw_pending(self) -> bool:
        """True while a requested draw has not happened yet."""
        return self._needs_draw

    def is_resizing(self) -> bool:
        """True during a window drag, while the last frame is shown stretched."""
        return self._settle_timer.isActive()

    def _render_frame(self):
        # matplotlib's own guard (FigureCanvasQT.draw) covers only the repaint
        # request, so draw_idle calls made while the figure renders would
        # queue another draw; this one covers draw_scope and the whole render.
        self._is_drawing = True
        try:
            with self.draw_scope():
                FigureCanvasAgg.draw(self)
            self._needs_draw = False
        finally:
            self._is_drawing = False

    def _draw_if_due(self):
        if self._needs_draw and self.isVisible() and self.width() > 0 and self.height() > 0:
            self.draw()

    # ------------------------------------------------------------------
    # Qt events
    # ------------------------------------------------------------------

    def showEvent(self, event):  # noqa: N802 (Qt override)
        window = self.window().windowHandle()
        if window is not self._screen_window:
            self._screen_window = window
            super().showEvent(event)  # connects the window's screen signals
        else:
            self._update_pixel_ratio()
        if self._needs_draw:
            self.draw_idle()  # the draw skipped while hidden (the first paint may come first)

    def hideEvent(self, event):  # noqa: N802 (Qt override)
        # The next show paints a fresh frame, never a stretched one.
        self._frame_shown = False
        if self.is_resizing():
            self._settle_timer.stop()
            self._on_resize_settled()
        super().hideEvent(event)

    def paintEvent(self, event):  # noqa: N802 (Qt override)
        if self.is_resizing():
            self._paint_stretched()
            return
        if self._needs_draw:
            self._render_frame()  # before painting, so no first frame is stale
        super().paintEvent(event)
        self._frame_shown = hasattr(self, "renderer")

    def resizeEvent(self, event):  # noqa: N802 (Qt override)
        if self._frame_shown and event.size() != event.oldSize():
            # Part of a drag (or a single maximise/restore): keep the figure at
            # the drawn size and stretch that frame until the resizing pauses.
            QWidget.resizeEvent(self, event)
            self._settle_timer.start()
            self.update()
            return
        super().resizeEvent(event)

    def _on_resize_settled(self):
        # matplotlib's resize handling at the final size: figure size, resize_event, draw_idle.
        super().resizeEvent(QResizeEvent(self.size(), self.size()))

    def _paint_stretched(self):
        buffer = self.buffer_rgba()  # the last frame; the figure keeps its size mid-drag
        frame = QImage(buffer, buffer.shape[1], buffer.shape[0], QImage.Format.Format_RGBA8888)
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            painter.drawImage(QRectF(self.rect()), frame)
        finally:
            painter.end()

    def wheelEvent(self, event):  # noqa: N802 (Qt override)
        super().wheelEvent(event)  # matplotlib's scroll_event
        parent = self.parentWidget()
        while parent is not None and not isinstance(parent, QAbstractScrollArea):
            parent = parent.parentWidget()
        if parent is not None:
            # Sent explicitly: Qt never propagates a synthetic wheel event, and
            # also ignoring a real one would deliver it twice.
            QApplication.sendEvent(parent.viewport(), event)

    # ------------------------------------------------------------------
    # Size hints
    # ------------------------------------------------------------------

    def sizeHint(self):  # noqa: N802 (Qt override)
        # matplotlib hints the live figure size; the minimum height keeps a
        # big figure from holding its page (and the window) at that height.
        return QSize(super().sizeHint().width(), self.minimumHeight())


class MatplotlibWidget(QWidget):
    """Container for one :class:`MatplotlibCanvas`."""

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        width: float = 10,
        height: float = 6,
        dpi: int = 100,
    ):
        super().__init__(parent)

        self.canvas = MatplotlibCanvas(self, width, height, dpi)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.canvas)

    @property
    def figure(self) -> Figure:
        """Access matplotlib figure"""
        return self.canvas.fig
