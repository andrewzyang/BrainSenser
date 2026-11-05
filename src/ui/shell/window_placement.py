"""Window floor, launch screen and placement (plan §3.1, D3; M3.7).

Pure helpers — :func:`window_floor` and :func:`launch_geometry` over QtCore value
types, :func:`pick_launch_screen` over screen names — and the thin Qt glue that
applies them: :func:`keep_window_floor`, :func:`launch_screen`,
:func:`apply_initial_geometry`.

* **Floor (D3):** the window shrinks to 600×500 client px, or to the screen's
  available area minus the window frame where that is smaller. Until the
  platform reports the frame (before the native window exists, or never, as on
  offscreen screens without frames) the style's title-bar height stands in for
  it, so a window placed before its first show still fits with its title bar.
  The floor is re-applied at the first show, when the frame is known, when the
  window moves to another screen and when a screen's available area changes
  (Dock, taskbar, resolution, display scaling). Below a page's minimum height
  the page scrolls (``PageHost``).
* **Launch screen:** the screen the window was on when its geometry was last
  saved (by name), else the screen under the mouse pointer, else the primary one.
* **Saved geometry:** restored when Qt can put it back on the launch screen
  (moved onto it if the displays were rearranged). Qt refuses a memento saved at
  another screen width or display scaling (``restoreGeometry()`` returns False),
  and one that would leave the window's centre off the launch screen isn't used
  either; then the window opens as on first launch.
* **First launch:** maximised, except on very wide (≥ 2600 px) or ultrawide
  (aspect > 2) screens, which get a centred window of 80 % of the available height,
  at most 80 % of the width and 1.6 times as wide as tall. The centred geometry is
  also what un-maximising returns to. Wayland compositors place windows
  themselves, so there only the size is set.
"""

from typing import NamedTuple, Optional, Sequence

from PySide6.QtCore import QByteArray, QEvent, QMargins, QObject, QRect, QSize, Qt
from PySide6.QtGui import QCursor, QGuiApplication, QScreen
from PySide6.QtWidgets import QStyle, QWidget

from src.ui.policy.tokens import Dim
from src.ui.utils.screens import screen_of

MAXIMIZE_BELOW_WIDTH = 2600   # available width (logical px)
MAXIMIZE_MAX_ASPECT = 2.0     # available width / height
NORMAL_SHARE = 0.8            # of the available width and height
NORMAL_MAX_ASPECT = 1.6       # normal window width / height


class LaunchGeometry(NamedTuple):
    """How a window first opens: maximised or not, and its normal geometry."""

    maximized: bool
    normal: QRect  # client geometry, centred in the available area


def window_floor(available: QSize, frame: QSize) -> QSize:
    """The smallest client size a window may take on a screen with ``available``
    space, given the ``frame`` (title bar and borders) around its client area."""
    return QSize(Dim.WINDOW_MIN_W, Dim.WINDOW_MIN_H).boundedTo(available - frame)


def launch_geometry(available: QRect, floor: QSize) -> LaunchGeometry:
    """Where a window first opens on a screen whose available area is ``available``;
    the normal size is never below ``floor``."""
    height = max(floor.height(), round(available.height() * NORMAL_SHARE))
    width = max(floor.width(), min(round(available.width() * NORMAL_SHARE),
                                   round(height * NORMAL_MAX_ASPECT)))
    normal = QRect(0, 0, width, height)
    normal.moveCenter(available.center())
    maximized = (available.width() < MAXIMIZE_BELOW_WIDTH
                 and available.width() <= MAXIMIZE_MAX_ASPECT * available.height())
    return LaunchGeometry(maximized, normal)


def pick_launch_screen(screens: Sequence[str], last_screen: Optional[str],
                       under_pointer: Optional[str], primary: str) -> str:
    """Of the connected ``screens`` (names), the one the app opens on: the one
    its window was last on, else the one under the pointer, else ``primary``."""
    for candidate in (last_screen, under_pointer):
        if candidate is not None and candidate in screens:
            return candidate
    return primary


# ----------------------------------------------------------------- Qt glue

def _window_frame(window: QWidget) -> QSize:
    """The frame around ``window``'s client area: the platform's once it reports
    one, else (no native window yet, or a platform without frames) the style's
    title-bar height."""
    handle = window.windowHandle()
    margins = handle.frameMargins() if handle is not None else QMargins()
    if margins.isNull():
        return QSize(0, window.style().pixelMetric(QStyle.PixelMetric.PM_TitleBarHeight,
                                                   None, window))
    return QSize(margins.left() + margins.right(), margins.top() + margins.bottom())


def apply_window_floor(window: QWidget) -> None:
    """Set ``window``'s minimum size to the floor of the screen it is on."""
    window.setMinimumSize(window_floor(screen_of(window).availableGeometry().size(),
                                       _window_frame(window)))


class _FloorKeeper(QObject):
    """Re-applies the floor when the window changes screens or its screen's
    available area changes. Connects at the window's first show, when its
    native window (and so the frame) exists."""

    def __init__(self, window: QWidget):
        super().__init__(window)
        self._window = window
        self._area_connection = None  # to the current screen's availableGeometryChanged
        window.installEventFilter(self)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.Show:
            watched.removeEventFilter(self)
            handle = watched.windowHandle()
            handle.screenChanged.connect(self._follow_screen)
            self._follow_screen(screen_of(handle))
        return False

    def _follow_screen(self, screen: Optional[QScreen]) -> None:
        if self._area_connection is not None:
            QObject.disconnect(self._area_connection)
            self._area_connection = None
        if screen is None:
            return
        self._area_connection = screen.availableGeometryChanged.connect(self._reapply)
        apply_window_floor(self._window)

    def _reapply(self) -> None:
        apply_window_floor(self._window)


def keep_window_floor(window: QWidget) -> None:
    """Give ``window`` the floor of its screen now and keep it there."""
    apply_window_floor(window)
    _FloorKeeper(window)


def launch_screen(last_screen: Optional[str] = None) -> QScreen:
    """The screen the app opens on; ``last_screen`` is the name of the one its
    window was last saved on (see :func:`pick_launch_screen`)."""
    screens = QGuiApplication.screens()
    pointer = QGuiApplication.screenAt(QCursor.pos())
    primary = QGuiApplication.primaryScreen()
    name = pick_launch_screen([screen.name() for screen in screens], last_screen,
                              None if pointer is None else pointer.name(), primary.name())
    # Of screens with equal names, the pointer's and then the primary one win.
    return next(screen for screen in (pointer, primary, *screens)
                if screen is not None and screen.name() == name)


def apply_initial_geometry(window: QWidget, screen: QScreen, memento: Optional[bytes]) -> bool:
    """Place ``window``, not shown yet, on ``screen``: its floor there, then the
    saved geometry ``memento`` (``saveGeometry()`` bytes, or None) if Qt restores
    it onto ``screen``, else the first-launch geometry (see :func:`launch_geometry`).
    ``show()`` then opens the window as placed, maximised or not. Returns whether
    the memento was restored."""
    window.setScreen(screen)
    apply_window_floor(window)
    if memento and window.restoreGeometry(QByteArray(memento)):
        if screen.availableGeometry().contains(window.geometry().center()):
            return True
        # Restored off the launch screen: start afresh
        window.setWindowState(window.windowState() & ~(Qt.WindowState.WindowMaximized
                                                      | Qt.WindowState.WindowFullScreen))
    launch = launch_geometry(screen.availableGeometry(), window.minimumSize())
    if QGuiApplication.platformName().startswith("wayland"):
        window.resize(launch.normal.size())  # the compositor places windows itself
    else:
        window.setGeometry(launch.normal)
    if launch.maximized:
        window.setWindowState(window.windowState() | Qt.WindowState.WindowMaximized)
    return False
