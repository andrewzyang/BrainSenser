"""
SplashConfig data model for the startup splash screen.

Immutable configuration describing the splash asset and playback guardrails.
Produced by SplashService after validating the asset on disk; consumed by
SplashViewModel to drive QMediaPlayer. Qt-free by design so the model layer
remains independent of the UI framework.

Author: iEEG BrainSense Development Team
Last Updated: 2026-04-12
"""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SplashConfig:
    """
    Immutable configuration for the startup splash screen.

    Attributes:
        video_path: Absolute path to a readable video file.
        fallback_timeout_ms: Hard cap on total playback time. If playback has
            not reached EndOfMedia by this deadline, the viewmodel treats the
            splash as failed and transitions to the main window. Protects
            against decoder stalls, buffering hangs, and missing codecs.
        allow_skip: Whether the user may dismiss the splash early via mouse
            click or keyboard.
    """

    video_path: Path
    fallback_timeout_ms: int = 8000
    allow_skip: bool = True
