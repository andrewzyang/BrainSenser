"""Timeline → LFP Threshold page."""

from src.ui.views.timeline_lfp_threshold.factory import create_timeline_lfp_threshold_view
from src.ui.views.timeline_lfp_threshold.timeline_lfp_threshold_view import TimelineLfpThresholdView

__all__ = [
    "TimelineLfpThresholdView",
    "create_timeline_lfp_threshold_view",
]
