"""
SplashService - resolves the startup splash asset.

Pure business logic: given a directory where assets live, this service
locates the splash video, verifies it exists, and returns an immutable
SplashConfig. A missing asset is non-fatal - the service returns None and
the caller skips the splash entirely.

No Qt imports. The service layer stays UI-framework agnostic so it can be
unit-tested without a QApplication instance.

Author: iEEG BrainSense Development Team
Last Updated: 2026-04-12
"""

import logging
from pathlib import Path
from typing import Optional

from src.core.models import SplashConfig

logger = logging.getLogger(__name__)


class SplashService:
    """
    Resolves the startup splash video and returns a SplashConfig.

    The service is constructed with an absolute path to the directory
    containing the splash asset. It performs a readable-file check and
    returns either a populated SplashConfig or None.

    Returning None (rather than raising) is intentional: the splash is a
    cosmetic feature and must never block application startup. Callers
    should treat None as "no splash available" and proceed directly to the
    main window.
    """

    SPLASH_VIDEO_FILENAME = "brainsenser_splash_screen.mp4"

    def __init__(self, assets_dir: Path):
        self._assets_dir = Path(assets_dir)
        self._logger = logging.getLogger(__name__)

    def get_splash_config(self) -> Optional[SplashConfig]:
        """
        Resolve and validate the splash video.

        Returns:
            SplashConfig if the video file exists and is readable;
            None if the asset is missing or unreadable (splash should
            be skipped, not an error).
        """
        video_path = self._assets_dir / self.SPLASH_VIDEO_FILENAME

        if not video_path.is_file():
            self._logger.info(
                "Splash video not found at %s, skipping splash screen",
                video_path,
            )
            return None

        self._logger.info("Splash video resolved: %s", video_path)
        return SplashConfig(video_path=video_path)
