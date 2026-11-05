"""
SplashView - top-level frameless widget that plays the startup video.

The view owns the QVideoWidget (UI concern) and wires it to the media
player exposed by SplashViewModel. It forwards user dismissal gestures
(mouse click, Esc/Space/Enter) into the viewmodel's skip() API. When the
viewmodel emits `closed` the view holds plain white until the application
bootstrap closes it, right after the main window is up.

This widget is intentionally not a QSplashScreen subclass - QSplashScreen
does not support video. A frameless top-level QWidget with the SplashScreen
window type gives the same taskbar/focus semantics while allowing a
QVideoWidget child.

Author: iEEG BrainSense Development Team
Last Updated: 2026-10-27
"""

import ctypes
import logging

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QGuiApplication, QKeyEvent, QMouseEvent, QResizeEvent, QScreen
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import QWidget

from src.ui.viewmodels import SplashViewModel

logger = logging.getLogger(__name__)

# The splash video: a 16:9 frame on a white background.
VIDEO_ASPECT = 16 / 9
VIDEO_BACKGROUND = "#ffffff"
# Its artwork spans x 12.3–90.8 % and y 27.4–72.6 % of the frame, so a centred
# crop that fills the screen keeps it whole between these screen aspect ratios;
# outside them the frame is fitted and the white background shows around it.
COVER_ASPECT_RANGE = (1.45, 3.9)


def video_rect(size: QSize) -> QRect:
    """Where the 16:9 video goes on a splash of ``size``: covering it, cropped
    evenly, when the artwork survives the crop; otherwise fitted inside it."""
    low, high = COVER_ASPECT_RANGE
    fill = max if low * size.height() <= size.width() <= high * size.height() else min
    height = fill(size.height(), size.width() / VIDEO_ASPECT)
    width = height * VIDEO_ASPECT
    return QRect(round((size.width() - width) / 2), round((size.height() - height) / 2),
                 round(width), round(height))


def motion_reduced() -> bool:
    """Whether macOS asks apps to reduce motion (System Settings ▸ Accessibility ▸
    Display ▸ Reduce motion); the splash is skipped then. Qt does not expose the
    setting, so AppKit's NSWorkspace is asked directly. False on other platforms."""
    if QGuiApplication.platformName() != "cocoa":
        return False
    try:
        objc = ctypes.CDLL("/usr/lib/libobjc.A.dylib")
        ctypes.CDLL("/System/Library/Frameworks/AppKit.framework/AppKit")  # NSWorkspace
    except OSError:
        logger.warning("Could not read the Reduce motion setting", exc_info=True)
        return False
    for lookup in (objc.objc_getClass, objc.sel_registerName):
        lookup.restype, lookup.argtypes = ctypes.c_void_p, [ctypes.c_char_p]
    message = ("objc_msgSend", objc)
    send_object = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)(message)
    send_bool = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)(message)
    workspace = send_object(objc.objc_getClass(b"NSWorkspace"),
                            objc.sel_registerName(b"sharedWorkspace"))
    return send_bool(workspace, objc.sel_registerName(b"accessibilityDisplayShouldReduceMotion"))


class SplashView(QWidget):
    """
    Frameless top-level view that renders the splash video at full screen.

    The view is strictly UI: it holds a QVideoWidget, binds it to
    `viewmodel.player` during construction, and forwards dismissal gestures
    to the viewmodel. All playback decisions live in the viewmodel.

    The widget covers the full geometry of the launch screen (including under
    the macOS menu bar, which the SplashScreen window type stacks beneath). The
    video covers the screen or fits inside it (see video_rect) on the video's
    own white background. It stays above other applications' windows only
    until this application loses focus.
    """

    def __init__(self, viewmodel: SplashViewModel, screen: QScreen, parent=None):
        super().__init__(
            parent,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.SplashScreen
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.viewmodel = viewmodel
        self._video_widget = QVideoWidget(self)

        self._setup_ui()
        self._bind_player()
        self._connect_signals()
        self._cover_screen(screen)

    def _setup_ui(self) -> None:
        self.setStyleSheet(f"background-color: {VIDEO_BACKGROUND};")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        # The widget gets the frame's own aspect (resizeEvent, video_rect);
        # expanding hides any one-pixel rounding sliver.
        self._video_widget.setAspectRatioMode(
            Qt.AspectRatioMode.KeepAspectRatioByExpanding
        )

    def _bind_player(self) -> None:
        player = self.viewmodel.player
        if player is not None:
            player.setVideoOutput(self._video_widget)
        else:
            logger.warning("SplashView created with no player on viewmodel")

    def _connect_signals(self) -> None:
        # Once playback is over, show the white background instead of whatever
        # the stopped player leaves on screen, until the bootstrap closes us.
        self.viewmodel.closed.connect(self._video_widget.hide)
        QGuiApplication.instance().applicationStateChanged.connect(
            self._on_application_state_changed
        )

    def _cover_screen(self, screen: QScreen) -> None:
        self.setScreen(screen)
        # Use full screen.geometry() (not availableGeometry) so the splash
        # extends under the menu bar / dock areas for a true full-screen
        # appearance. Manual setGeometry is instant - unlike showFullScreen,
        # it does not trigger the macOS Space transition animation.
        self.setGeometry(screen.geometry())

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._video_widget.setGeometry(video_rect(self.size()))

    def _on_application_state_changed(self, state: Qt.ApplicationState) -> None:
        handle = self.windowHandle()
        if (state != Qt.ApplicationState.ApplicationActive and handle is not None
                and handle.flags() & Qt.WindowType.WindowStaysOnTopHint):
            # From now on an ordinary frameless window. Not just without the
            # stay-on-top hint: on macOS a splash-type window floats at the pop-up
            # menu level, so that alone would raise it. Set on the native window,
            # because QWidget.setWindowFlags() would hide and re-create it.
            handle.setFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        self.viewmodel.skip()
        super().mousePressEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (
            Qt.Key.Key_Escape,
            Qt.Key.Key_Space,
            Qt.Key.Key_Return,
            Qt.Key.Key_Enter,
        ):
            self.viewmodel.skip()
        else:
            super().keyPressEvent(event)
