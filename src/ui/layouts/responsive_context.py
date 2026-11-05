"""ResponsiveContext: the window's layout classes, measured once at the shell (plan §4.4).

Owned by MainLayout, it watches the window's client area (MainLayout itself)
and the content stack, and classifies their sizes with the pure policy in
:mod:`src.ui.policy.layout`:

* WidthClass from the client width; ``window_class_changed`` tells MainWindow,
  which hands it to ShellViewModel (the sidebar's mode follows);
* HeightClass and Arrangement from the content stack's size, the ROW minimum
  coming from the ArrangementAware pages' honest minimum.

With the interface-size factor (:meth:`ResponsiveContext.set_scale`) they form
the Density every registered DensityAware page is commanded with — hidden pages
too, as Qt doesn't resize the pages a QStackedWidget isn't showing. Measuring at
the shell, never per page, keeps a page's own scrollbar from moving it across a
boundary, and makes every page switch together.

A burst of resize events is classified once, as soon as the event loop runs (a
0-ms timer), and the new arrangement is laid out before the next paint. Classes
are computed without history, except during an interactive resize: window
managers don't report edge drags to Qt, so resize bursts less than
``DRAG_PAUSE_MS`` apart count as one, and the policy's hysteresis bands keep
the classes from flapping while it lasts. Once the bursts pause, the classes
are computed afresh, so a resting window's classes never depend on history.

The context never restyles anything itself; the pages it commands do.
"""

from dataclasses import replace
from typing import List

from PySide6.QtCore import QCoreApplication, QEvent, QObject, QTimer, Signal
from PySide6.QtWidgets import QWidget

from src.ui.policy.layout import (Arrangement, Density, HeightClass, WidthClass,
                                  choose_arrangement, classify_content, classify_window)
from src.ui.policy.tokens import Dim
from src.ui.protocols.density_aware import ArrangementAware, DensityAware


class ResponsiveContext(QObject):
    """
    The layout classes of one window, pushed to its pages as a Density.

    Signals:
        window_class_changed: The window's WidthClass value ("narrow" | "wide");
            only on a change, never on construction, and before the pages get
            the density that comes with it.

    Example:
        >>> context = ResponsiveContext(main_layout, main_layout.content_stack)
        >>> context.register(page)      # page.apply_density(context.density) now
        >>> context.set_scale(1.25)     # Density.scale -> every page's plot
        >>> context.reclassify_now()    # e.g. after maximising
    """

    window_class_changed = Signal(str)

    # Resize bursts closer together than this are one interactive resize.
    DRAG_PAUSE_MS = 80

    def __init__(self, window_area: QWidget, content: QWidget):
        """
        Args:
            window_area: The widget as wide as the window's client area
                (MainLayout); it owns the context
            content: The widget the pages fill (the content stack)
        """
        super().__init__(window_area)
        self._window_area = window_area
        self._content = content
        self._pages: List[DensityAware] = []
        self._arranged: List[ArrangementAware] = []
        self._width_class = WidthClass.WIDE
        self._density = Density(WidthClass.WIDE, HeightClass.REGULAR, Arrangement.ROW)
        self._burst_is_drag = False
        self._burst = QTimer(self)
        self._burst.setSingleShot(True)
        self._burst.setInterval(0)
        self._burst.timeout.connect(self._on_burst)
        self._drag = QTimer(self)
        self._drag.setSingleShot(True)
        self._drag.setInterval(self.DRAG_PAUSE_MS)
        self._drag.timeout.connect(self._on_drag_paused)
        window_area.installEventFilter(self)
        content.installEventFilter(self)

    @property
    def width_class(self) -> WidthClass:
        """The window's width class."""
        return self._width_class

    @property
    def density(self) -> Density:
        """The density the pages were last commanded with."""
        return self._density

    def register(self, page: QWidget) -> None:
        """Command ``page`` with the current density now, and again on every
        change, if it is DensityAware; if it is ArrangementAware, its ROW
        minimum counts towards the arrangement."""
        if not isinstance(page, DensityAware):
            return
        self._pages.append(page)
        if isinstance(page, ArrangementAware):
            self._arranged.append(page)
        page.apply_density(self._density)

    def set_scale(self, factor: float) -> None:
        """Set the active interface-size factor of the window's display
        (``Density.scale``); the pages get it at once."""
        self._apply(replace(self._density, scale=float(factor)))

    def reclassify_now(self) -> None:
        """Classify the current sizes at once and without history, e.g. on the
        first show, after maximising or on a screen change."""
        self._burst.stop()
        self._reclassify(dragging=False)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.Resize and not self._burst.isActive():
            # A burst's first resize: a drag goes on if the last burst was a moment ago.
            self._burst_is_drag = self._drag.isActive()
            self._burst.start()
        return super().eventFilter(watched, event)

    def _on_burst(self) -> None:
        self._reclassify(dragging=self._burst_is_drag)
        self._drag.start()

    def _on_drag_paused(self) -> None:
        if self._burst_is_drag:
            self._reclassify(dragging=False)

    def _reclassify(self, dragging: bool) -> None:
        """The window class first, then — once its layout change has reached
        the content stack — the content classes; then the push."""
        width_class = classify_window(self._window_area.width(), self._width_class,
                                      dragging=dragging)
        if width_class is not self._width_class:
            self._width_class = width_class
            self.window_class_changed.emit(width_class.value)
            # Lay out now (e.g. the sidebar's new width), so the stack has its new size.
            QCoreApplication.sendPostedEvents(None, QEvent.Type.LayoutRequest)
        size = self._content.size()
        current = self._density
        self._apply(Density(
            width_class,
            classify_content(size.height(), current.height, dragging=dragging),
            choose_arrangement(size.width(), size.height(), self._row_minimum_width(),
                               current.arrangement, dragging=dragging),
            current.scale,
        ))

    def _row_minimum_width(self) -> int:
        """The widest ROW minimum of the arranged pages, plus the width a page
        host's vertical scrollbar takes from a page that scrolls."""
        if not self._arranged:
            return 0
        return max(page.row_minimum_width() for page in self._arranged) + Dim.SCROLLBAR

    def _apply(self, density: Density) -> None:
        if density == self._density:
            return
        self._density = density
        # Hidden pages first (plan §4.7); the shown page last, right before the flush.
        for page in sorted(self._pages, key=lambda page: page.isVisible()):
            page.apply_density(density)
        # Lay the new arrangement out now, so the next paint already shows it.
        QCoreApplication.sendPostedEvents(None, QEvent.Type.LayoutRequest)
