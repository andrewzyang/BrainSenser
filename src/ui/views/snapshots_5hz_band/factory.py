"""
Factory for creating the Snapshots 5 Hz Band view with dependencies injected.

Mirrors :func:`src.ui.views.snapshots_psd.factory.create_snapshots_psd_view`:
builds the repository / service / ViewModel / view chain with the
db_adapter and path_resolver supplied by the application container, then
hands back the fully wired view.

No service references ever leak into :class:`Snapshots5HzBandView` — services
flow View ← VM ← factory.

Author: iEEG BrainSense Development Team
"""

from src.core.path_resolver import PathResolver
from src.core.services.snapshot_ml_analysis_service import (
    SnapshotMlAnalysisService,
)
from src.infrastructure.database.adapters.sqlite_adapter import SQLiteAdapter
from src.infrastructure.repositories import SnapshotRepository
from src.ui.viewmodels.snapshots_5hz_band_viewmodel import Snapshots5HzBandViewModel
from src.ui.views.snapshots_5hz_band.snapshots_5hz_band_view import Snapshots5HzBandView


def create_snapshots_5hz_band_view(
    db_adapter: SQLiteAdapter,
    path_resolver: PathResolver,
) -> Snapshots5HzBandView:
    """
    Create the Snapshots 5 Hz Band view with all dependencies wired.

    The wiring stack mirrors :func:`create_snapshots_psd_view`:

    1. **Repository** — :class:`SnapshotRepository` for data access (used
       by the ViewModel to load per-patient snapshot records before
       building the PSD dataset).
    2. **Service** — :class:`SnapshotMlAnalysisService` (the per-band
       LOO + FWER pipeline behind manuscript Figure 2 d–f).
    3. **ViewModel** — :class:`Snapshots5HzBandViewModel` orchestrates state
       and dispatches the worker; constructed as
       ``Snapshots5HzBandViewModel(snapshot_repo, ml_service)``.
    4. **View** — :class:`Snapshots5HzBandView` is pure UI; it never holds a
       service reference.

    Parameters
    ----------
    db_adapter : SQLiteAdapter
        Shared database adapter.
    path_resolver : PathResolver
        Resolves global / per-patient database paths.

    Returns
    -------
    Snapshots5HzBandView
        Fully wired view ready to be inserted into the main layout.

    Examples
    --------
    >>> view = create_snapshots_5hz_band_view(db_adapter, path_resolver)
    >>> main_layout.add_page("snapshots_5hz_band", view)
    """

    snapshot_repo = SnapshotRepository(
        adapter=db_adapter,
        path_resolver=path_resolver,
    )
    ml_service = SnapshotMlAnalysisService()

    viewmodel = Snapshots5HzBandViewModel(
        snapshot_repo=snapshot_repo,
        ml_service=ml_service,
    )

    return Snapshots5HzBandView(viewmodel)
