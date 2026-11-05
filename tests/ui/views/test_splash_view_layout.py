"""Splash layout and behaviour (plan M1.4, D19; shell SH-13–SH-16).

The 16:9 video covers the screen when its artwork survives the crop and is
fitted on its own white background otherwise; the splash covers the launch
screen, holds plain white once playback ends, stops floating above other
applications when this one loses focus, and is skipped under Reduce motion.
A stand-in ViewModel only: no media player, no video file.
"""

import sys

import pytest
from PySide6.QtCore import QObject, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtTest import QTest

from src.ui.views.splash import splash_view
from src.ui.views.splash.splash_view import (
    COVER_ASPECT_RANGE,
    VIDEO_ASPECT,
    SplashView,
    motion_reduced,
    video_rect,
)

# Where the brand artwork sits in the 16:9 frame (fractions of its width / height).
ARTWORK_X = (0.123, 0.908)
ARTWORK_Y = (0.274, 0.726)


class _SplashViewModel(QObject):
    """Stand-in for SplashViewModel: no player; a click or key skips."""

    closed = Signal()
    player = None

    def skip(self) -> None:
        self.closed.emit()


@pytest.fixture
def splash(qtbot, qapp):
    view = SplashView(_SplashViewModel(), qapp.primaryScreen())
    qtbot.addWidget(view)
    view.show()
    qtbot.waitExposed(view)
    return view


@pytest.mark.parametrize("size, expected", [
    ((1920, 1080), QRect(0, 0, 1920, 1080)),        # 16:9: exact
    ((1440, 900), QRect(-80, 0, 1600, 900)),        # 16:10: cover, sides cropped
    ((2560, 1080), QRect(0, -180, 2560, 1440)),     # 21:9: cover, top and bottom cropped
    ((1024, 768), QRect(0, 96, 1024, 576)),         # 4:3: fit, white above and below
    ((1080, 1920), QRect(0, 656, 1080, 608)),       # portrait: fit
    ((5120, 1080), QRect(1600, 0, 1920, 1080)),     # 32:9 and wider: fit, white at the sides
])
def test_video_covers_or_fits(size, expected):
    assert video_rect(QSize(*size)) == expected


@pytest.mark.parametrize("aspect", [0.5, 0.75, 1.0, 1.25, 1.33, 1.44, 1.45, 1.5, 1.6, 1.78,
                                    2.0, 2.37, 3.0, 3.5, 3.9, 3.95, 4.5])
def test_artwork_always_stays_whole(aspect):
    """The crop never reaches the artwork; a fitted frame is shown entirely."""
    height = 1000
    screen = QRect(0, 0, round(aspect * height), height)
    video = video_rect(screen.size())
    assert abs(video.width() / video.height() - VIDEO_ASPECT) < 0.01
    artwork = QRect(round(video.x() + ARTWORK_X[0] * video.width()),
                    round(video.y() + ARTWORK_Y[0] * video.height()),
                    round((ARTWORK_X[1] - ARTWORK_X[0]) * video.width()),
                    round((ARTWORK_Y[1] - ARTWORK_Y[0]) * video.height()))
    assert screen.adjusted(-1, -1, 1, 1).contains(artwork)
    covering = COVER_ASPECT_RANGE[0] <= aspect <= COVER_ASPECT_RANGE[1]
    assert video.contains(screen.adjusted(1, 1, -1, -1)) == covering


def test_splash_covers_the_launch_screen(splash, qapp):
    screen = qapp.primaryScreen()
    assert splash.screen() is screen
    assert splash.geometry() == screen.geometry()
    assert splash._video_widget.geometry() == video_rect(splash.size())


def test_background_is_the_video_white(splash, qtbot):
    splash.resize(600, 1000)  # portrait: the fitted video leaves white bands
    qtbot.waitUntil(lambda: splash._video_widget.y() > 0)
    image = splash.grab().toImage()
    assert QColor(image.pixel(5, 5)) == QColor("#ffffff")


def test_once_playback_ends_the_splash_holds_white_until_closed(splash, qtbot):
    QTest.mouseClick(splash, Qt.MouseButton.LeftButton)  # skip
    assert not splash._video_widget.isVisible()
    assert splash.isVisible()  # the launch closes it, once the main window is up


def test_stops_floating_above_other_apps_when_the_app_loses_focus(splash, qapp):
    handle = splash.windowHandle()
    qapp.applicationStateChanged.emit(Qt.ApplicationState.ApplicationActive)
    assert handle.flags() & Qt.WindowType.WindowStaysOnTopHint
    qapp.applicationStateChanged.emit(Qt.ApplicationState.ApplicationInactive)
    assert not handle.flags() & Qt.WindowType.WindowStaysOnTopHint
    # An ordinary window: on macOS a splash-type window would float at pop-up level.
    assert handle.type() == Qt.WindowType.Window
    assert splash.isVisible()


def test_reduce_motion_is_only_asked_of_macos(monkeypatch):
    monkeypatch.setattr(QGuiApplication, "platformName", staticmethod(lambda: "offscreen"))
    assert motion_reduced() is False


@pytest.mark.skipif(sys.platform != "darwin", reason="AppKit")
def test_reduce_motion_reads_the_macos_setting(monkeypatch):
    """The real accessibility setting, whatever it is (no app data is read)."""
    monkeypatch.setattr(QGuiApplication, "platformName", staticmethod(lambda: "cocoa"))
    assert isinstance(motion_reduced(), bool)


def test_reduce_motion_falls_back_when_appkit_is_missing(monkeypatch):
    monkeypatch.setattr(QGuiApplication, "platformName", staticmethod(lambda: "cocoa"))

    def missing(*_args, **_kwargs):
        raise OSError("no AppKit here")

    monkeypatch.setattr(splash_view.ctypes, "CDLL", missing)
    assert motion_reduced() is False
