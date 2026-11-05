"""Timeline → Peri-Event page."""

from src.ui.views.timeline_peri_event.factory import (
    create_timeline_peri_event_view,
)
from src.ui.views.timeline_peri_event.timeline_peri_event_view import (
    TimelinePeriEventView,
)

__all__ = [
    "TimelinePeriEventView",
    "create_timeline_peri_event_view",
]
