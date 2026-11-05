"""ScreenWatcher: tells the main window when its display changes (plan §4.7).

A display change is a change of the window's screen (its identity), of that
screen's device pixel ratio or of its logical size — what :class:`ScreenMetrics`
holds. The screen's available area is not part of it: a Dock or taskbar that
appears is not a display change (the window floor follows that by itself,
``keep_window_floor``).

Changes are reported 250 ms after the last related Qt signal, and never while a
mouse button is down, so a window dragged across several displays is reported
once, where it is dropped. Metrics equal to the last reported ones are not
reported again. The watcher holds no ViewModel; MainWindow wires it.
"""

from typing import Optional

from PySide6.QtCore import QEvent, QObject, QTimer, Qt, Signal
from PySide6.QtGui import QGuiApplication, QScreen, QWindow

from src.ui.policy.scale import ScreenMetrics
from src.ui.utils.screens import screen_of

DEBOUNCE_MS = 250


def read_screen_metrics(screen: QScreen) -> ScreenMetrics:
    """``screen`` as Qt reports it: its name, the logical size of its full
    geometry (this session's interface size included) and its DPR."""
    size = screen.geometry().size()
    return ScreenMetrics(screen.name(), size.width(), size.height(), screen.devicePixelRatio())


class ScreenWatcher(QObject):
    """
    Reports the display changes of one native window.

    Signals:
        display_changed: The window's new ScreenMetrics, only when they differ
            from ``metrics`` (the last reported).

    Example:
        >>> watcher = ScreenWatcher(window.windowHandle(), window)
        >>> show(watcher.metrics)                        # read first,
        >>> watcher.display_changed.connect(show)        # then connect
    """

    display_changed = Signal(object)  # ScreenMetrics

    def __init__(self, window: QWindow, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._window = window
        self._metrics = read_screen_metrics(screen_of(window))
        self._geometry_connection = None  # to the current screen's geometryChanged

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(DEBOUNCE_MS)
        self._timer.timeout.connect(self._report)

        window.screenChanged.connect(self._follow)
        window.installEventFilter(self)  # QEvent.DevicePixelRatioChange
        self._watch(screen_of(window))

    @property
    def metrics(self) -> ScreenMetrics:
        """The window's display as last reported (at first, as constructed)."""
        return self._metrics

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.DevicePixelRatioChange:
            self._schedule()
        return False

    def _follow(self, screen: Optional[QScreen]) -> None:
        """The window moved to ``screen``."""
        self._watch(screen)
        self._schedule()

    def _watch(self, screen: Optional[QScreen]) -> None:
        """Watch ``screen`` (only) for size and scaling changes."""
        if self._geometry_connection is not None:
            QObject.disconnect(self._geometry_connection)
            self._geometry_connection = None
        if screen is not None:
            self._geometry_connection = screen.geometryChanged.connect(self._schedule)

    def _schedule(self) -> None:
        """Something about the display may have changed: report it once things settle."""
        self._timer.start()

    def _report(self) -> None:
        if QGuiApplication.mouseButtons() != Qt.MouseButton.NoButton:
            self._timer.start()  # held while the window is dragged
            return
        screen = screen_of(self._window)
        if screen is None:
            return
        metrics = read_screen_metrics(screen)
        if metrics != self._metrics:
            self._metrics = metrics
            self.display_changed.emit(metrics)
