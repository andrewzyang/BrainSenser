"""
SplashViewModel - presentation logic for the startup splash screen.

Owns the non-widget Qt media objects (QMediaPlayer, QAudioOutput) and
publishes lifecycle signals that the view and the application bootstrap
listen to. The view attaches its QVideoWidget to vm.player at setup time,
which keeps QtMultimediaWidgets out of this file.

All terminal events (natural end, error, timeout, user skip) funnel through
_emit_closed_once() so the application bootstrap has a single signal to
connect to for "splash is done, show the main window". The one-shot guard
prevents double-fire races (e.g., user clicks to skip in the same tick as
natural playback completion).

Author: iEEG BrainSense Development Team
Last Updated: 2026-04-12
"""

import logging
from typing import Optional

from PySide6.QtCore import QObject, Signal, QTimer, QUrl
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput

from src.core.models import SplashConfig
from src.core.services import SplashService

logger = logging.getLogger(__name__)


class SplashViewModel(QObject):
    """
    ViewModel for the startup splash screen.

    Signals:
        playback_started: Emitted when QMediaPlayer.play() is issued.
        playback_finished: Emitted on natural EndOfMedia.
        playback_failed: Emitted with an error message on decoder error
            or fallback timeout.
        playback_skipped: Emitted when the user dismisses the splash.
        closed: Emitted exactly once after any terminal event. The bootstrap
            should connect here to trigger main window construction.
    """

    playback_started = Signal()
    playback_finished = Signal()
    playback_failed = Signal(str)
    playback_skipped = Signal()
    closed = Signal()

    def __init__(self, splash_service: SplashService):
        super().__init__()
        self._service = splash_service
        self._config: Optional[SplashConfig] = None
        self._player: Optional[QMediaPlayer] = None
        self._audio: Optional[QAudioOutput] = None
        self._timeout: Optional[QTimer] = None
        self._closed_emitted = False
        self._logger = logging.getLogger(__name__)

    @property
    def player(self) -> Optional[QMediaPlayer]:
        """Underlying media player. The view attaches its QVideoWidget here."""
        return self._player

    @property
    def config(self) -> Optional[SplashConfig]:
        return self._config

    def prepare(self) -> bool:
        """
        Load config and construct the media player.

        Returns:
            True if the splash is ready to play; False if the asset is
            unavailable and the splash should be skipped entirely.
        """
        self._config = self._service.get_splash_config()
        if self._config is None:
            return False

        self._player = QMediaPlayer(self)
        self._audio = QAudioOutput(self)
        self._player.setAudioOutput(self._audio)
        self._player.setSource(QUrl.fromLocalFile(str(self._config.video_path)))
        self._player.mediaStatusChanged.connect(self._on_media_status_changed)
        self._player.errorOccurred.connect(self._on_error_occurred)

        self._timeout = QTimer(self)
        self._timeout.setSingleShot(True)
        self._timeout.timeout.connect(self._on_timeout)

        self._logger.info("SplashViewModel prepared for %s", self._config.video_path)
        return True

    def start_playback(self) -> None:
        """Begin video playback. Starts the fallback timeout."""
        if self._player is None or self._config is None:
            self._logger.warning("start_playback called before prepare() succeeded")
            self._emit_closed_once()
            return

        self._timeout.start(self._config.fallback_timeout_ms)
        self._player.play()
        self.playback_started.emit()
        self._logger.info("Splash playback started")

    def skip(self) -> None:
        """User-initiated dismissal."""
        if self._config is None or not self._config.allow_skip:
            return
        if self._closed_emitted:
            return
        self._logger.info("Splash skipped by user")
        self._stop_player()
        self.playback_skipped.emit()
        self._emit_closed_once()

    def _on_media_status_changed(self, status: QMediaPlayer.MediaStatus) -> None:
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self._logger.info("Splash playback finished naturally")
            self._stop_player()
            self.playback_finished.emit()
            self._emit_closed_once()
        elif status == QMediaPlayer.MediaStatus.InvalidMedia:
            self._logger.warning("Splash media is invalid")
            self._stop_player()
            self.playback_failed.emit("invalid media")
            self._emit_closed_once()

    def _on_error_occurred(self, _error: QMediaPlayer.Error, error_string: str) -> None:
        self._logger.warning("Splash playback error: %s", error_string)
        self._stop_player()
        self.playback_failed.emit(error_string or "unknown playback error")
        self._emit_closed_once()

    def _on_timeout(self) -> None:
        if self._closed_emitted:
            return
        self._logger.warning("Splash playback hit fallback timeout")
        self._stop_player()
        self.playback_failed.emit("playback timeout")
        self._emit_closed_once()

    def _stop_player(self) -> None:
        if self._timeout is not None and self._timeout.isActive():
            self._timeout.stop()
        if self._player is not None:
            self._player.stop()

    def _emit_closed_once(self) -> None:
        if self._closed_emitted:
            return
        self._closed_emitted = True
        self.closed.emit()
