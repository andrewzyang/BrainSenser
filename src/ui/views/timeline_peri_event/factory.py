"""Factory for the Timeline → Peri-Event page.

Composition root that wires repositories → service → viewmodel → view. The
signature mirrors ``create_timeline_lfp_threshold_view`` — both consume
``db_adapter`` and ``path_resolver`` and construct repositories internally —
so ``main.py`` plugs all pages in with the same pair of arguments.
"""

from __future__ import annotations

from typing import Optional

from src.core.path_resolver import PathResolver
from src.core.services.timeline_peri_event_service import (
    TimelinePeriEventService,
)
from src.infrastructure.database.adapters.sqlite_adapter import SQLiteAdapter
from src.infrastructure.repositories import (
    SnapshotRepository,
    TimelineRepository,
)
from src.ui.viewmodels.timeline_peri_event_viewmodel import (
    TimelinePeriEventViewModel,
)
from src.ui.views.timeline_peri_event.timeline_peri_event_view import (
    TimelinePeriEventView,
)


def create_timeline_peri_event_view(
    db_adapter: SQLiteAdapter,
    path_resolver: PathResolver,
    app_viewmodel: Optional[object] = None,
) -> TimelinePeriEventView:
    """Build the full subgraph for the Timeline → Peri-Event page.

    Returns a :class:`TimelinePeriEventView` ready to
    ``add_page("timeline_peri_event", view)`` from ``main.py``.
    """
    snapshot_repo = SnapshotRepository(
        adapter=db_adapter,
        path_resolver=path_resolver,
    )
    timeline_repo = TimelineRepository(
        adapter=db_adapter,
        path_resolver=path_resolver,
    )
    service = TimelinePeriEventService(
        snapshot_repository=snapshot_repo,
        timeline_repository=timeline_repo,
    )
    viewmodel = TimelinePeriEventViewModel(
        service=service,
        snapshot_repository=snapshot_repo,
        timeline_repository=timeline_repo,
        app_viewmodel=app_viewmodel,
    )
    view = TimelinePeriEventView(viewmodel=viewmodel)
    return view
