"""
Factory for creating Snapshots PSD view with dependencies injected.

This module provides a factory function that wires together all components
of the Snapshots PSD analysis page using dependency injection.

Author: iEEG BrainSense Development Team
Last Updated: 2025-10-02
"""

from src.infrastructure.database.adapters.sqlite_adapter import SQLiteAdapter
from src.core.path_resolver import PathResolver
from src.infrastructure.repositories import SnapshotRepository
from src.core.services.snapshot_psd_analysis_service import SnapshotPsdAnalysisService
from src.ui.viewmodels.snapshots_psd_viewmodel import SnapshotsPsdViewModel
from src.ui.views.snapshots_psd.snapshots_psd_view import SnapshotsPsdView


def create_snapshots_psd_view(
    db_adapter: SQLiteAdapter,
    path_resolver: PathResolver
) -> SnapshotsPsdView:
    """
    Create Snapshots PSD view with all dependencies wired.

    This factory function implements the dependency injection pattern,
    creating and wiring:
    1. Repository layer (data access)
    2. Service layer (PSD analysis)
    3. ViewModel layer (presentation logic)
    4. View layer (UI components)

    Parameters
    ----------
    db_adapter : SQLiteAdapter
        Database adapter for connections
    path_resolver : PathResolver
        Path resolver for database locations

    Returns
    -------
    SnapshotsPsdView
        Fully wired view ready for use

    Example
    -------
    >>> from src.infrastructure.database.adapters import SQLiteAdapter
    >>> from src.core.path_resolver import PathResolver
    >>>
    >>> adapter = SQLiteAdapter()
    >>> resolver = PathResolver()
    >>> view = create_snapshots_psd_view(adapter, resolver)
    >>> # Add to main window
    >>> main_window.add_page(view)
    """

    # ========================================================================
    # LAYER 1: Repository (Data Access)
    # ========================================================================

    snapshot_repo = SnapshotRepository(
        adapter=db_adapter,
        path_resolver=path_resolver
    )

    # ========================================================================
    # LAYER 2: Services (Business Logic)
    # ========================================================================

    # PSD Analysis Service
    # Performs band power integration, Mann-Whitney U tests, bootstrap CIs
    analysis_service = SnapshotPsdAnalysisService()

    # ========================================================================
    # LAYER 3: ViewModel (Presentation Logic)
    # ========================================================================

    viewmodel = SnapshotsPsdViewModel(
        snapshot_repo=snapshot_repo,
        analysis_service=analysis_service
    )

    # ========================================================================
    # LAYER 4: View (UI)
    # ========================================================================

    view = SnapshotsPsdView(viewmodel)

    return view