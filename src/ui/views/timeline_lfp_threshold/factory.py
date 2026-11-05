"""
Factory for the Timeline → LFP Threshold page.

Composition root that wires repositories → service → viewmodel → view. The
DI container does not need to know about this page; this factory is the
only composition site.

The signature mirrors `create_snapshots_5hz_band_view` — both consume
`db_adapter` and `path_resolver` and construct repositories internally —
so `main.py` can plug all four pages in with the same pair of arguments.
"""

from __future__ import annotations

from typing import Optional

from src.core.path_resolver import PathResolver
from src.core.services.timeline_threshold_ml_service import (
    TimelineThresholdMlService,
)
from src.infrastructure.database.adapters.sqlite_adapter import SQLiteAdapter
from src.infrastructure.repositories import (
    SnapshotRepository,
    TimelineRepository,
)
from src.ui.viewmodels.timeline_lfp_threshold_viewmodel import TimelineLfpThresholdViewModel
from src.ui.views.timeline_lfp_threshold.timeline_lfp_threshold_view import TimelineLfpThresholdView


def create_timeline_lfp_threshold_view(
    db_adapter: SQLiteAdapter,
    path_resolver: PathResolver,
    app_viewmodel: Optional[object] = None,
) -> TimelineLfpThresholdView:
    """Build the full subgraph for the Timeline → LFP Threshold page.

    Parameters
    ----------
    db_adapter, path_resolver
        Shared infrastructure primitives. Used to construct the snapshot
        and timeline repositories the service needs.
    app_viewmodel
        Optional :class:`AppViewModel` whose ``data_loaded`` signal clears
        the in-memory result cache on fresh imports / `is_outlier` re-flags.

    Returns
    -------
    TimelineLfpThresholdView
        Ready to ``add_page("timeline_lfp_threshold", view)`` from `main.py`.
    """
    snapshot_repo = SnapshotRepository(
        adapter=db_adapter,
        path_resolver=path_resolver,
    )
    timeline_repo = TimelineRepository(
        adapter=db_adapter,
        path_resolver=path_resolver,
    )
    service = TimelineThresholdMlService(
        snapshot_repository=snapshot_repo,
        timeline_repository=timeline_repo,
    )
    viewmodel = TimelineLfpThresholdViewModel(
        service=service,
        snapshot_repository=snapshot_repo,
        timeline_repository=timeline_repo,
        app_viewmodel=app_viewmodel,
    )
    view = TimelineLfpThresholdView(viewmodel=viewmodel)
    return view
