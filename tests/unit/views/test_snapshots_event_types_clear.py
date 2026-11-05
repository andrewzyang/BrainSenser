"""
Regression tests: snapshot views clear the grouping panel's event-types list
when switching to a patient with no snapshot data.

Bug: selecting an empty patient (e.g. a freshly created one) left the PREVIOUS
patient's event types — with their n= counts — showing in the grouping panel on
both the canonical-bands (PSD) and 5 Hz-band pages. Root cause: the views only
called ``set_available_event_types`` when ``n_events > 0``, so an empty load
never refreshed (cleared) the list.

These tests pin the fix: ``_on_data_loaded(0)`` and ``_on_patient_changed`` must
leave the event-types list empty.

Author: iEEG BrainSense Development Team
Last Updated: 2026-06-04
"""

from unittest.mock import MagicMock

import pytest

from src.ui.views.snapshots_psd.snapshots_psd_view import SnapshotsPsdView
from src.ui.viewmodels.snapshots_psd_viewmodel import SnapshotsPsdViewModel
from src.ui.views.snapshots_5hz_band.snapshots_5hz_band_view import Snapshots5HzBandView
from src.ui.viewmodels.snapshots_5hz_band_viewmodel import Snapshots5HzBandViewModel


def _mock_signal():
    sig = MagicMock()
    sig.connect = MagicMock()
    sig.disconnect = MagicMock()
    return sig


PREVIOUS_PATIENT_COUNTS = {"Craving": 25, "Neutral/Happy": 62, "Anxious": 9}


@pytest.fixture
def psd_view(qtbot):
    """SnapshotsPsdView wired to a mock VM (canonical-bands page)."""
    vm = MagicMock(spec=SnapshotsPsdViewModel)
    for name in [
        "patient_changed", "data_loaded", "analysis_started", "analysis_complete",
        "psd_curves_ready", "band_statistics_ready", "error_occurred",
        "progress_updated", "analysis_refresh_required", "analysis_refresh_cleared",
    ]:
        setattr(vm, name, _mock_signal())
    vm.get_effect_size_value.return_value = "rank_biserial"
    vm.get_timeline_band_center.return_value = None
    vm.event_counts = {}
    view = SnapshotsPsdView(viewmodel=vm)
    qtbot.addWidget(view)
    return view, vm


@pytest.fixture
def band_view(qtbot):
    """Snapshots5HzBandView wired to a mock VM (5 Hz-band page)."""
    vm = MagicMock(spec=Snapshots5HzBandViewModel)
    for name in [
        "patient_changed", "data_loaded", "analysis_started", "analysis_complete",
        "auc_profiles_ready", "band_table_ready", "error_occurred", "progress_updated",
    ]:
        setattr(vm, name, _mock_signal())
    vm.event_counts = {}
    view = Snapshots5HzBandView(viewmodel=vm)
    qtbot.addWidget(view)
    return view, vm


@pytest.mark.parametrize("view_fixture", ["psd_view", "band_view"])
class TestEventTypesClearedOnEmptyPatient:
    """Both snapshot pages must drop stale event types for an empty patient."""

    def test_empty_data_load_clears_event_types(self, view_fixture, request):
        view, vm = request.getfixturevalue(view_fixture)
        # Simulate a previous patient having populated the panel.
        view.grouping_panel.set_available_event_types(PREVIOUS_PATIENT_COUNTS)
        assert view.grouping_panel.event_types_list.count() == 3

        # New empty patient: VM reports {} and emits data_loaded(0).
        vm.event_counts = {}
        view._on_data_loaded(0)

        assert view.grouping_panel.event_types_list.count() == 0

    def test_nonempty_data_load_populates_event_types(self, view_fixture, request):
        view, vm = request.getfixturevalue(view_fixture)
        vm.event_counts = {"A": 3, "B": 4}
        view._on_data_loaded(2)

        assert view.grouping_panel.event_types_list.count() == 2

    def test_patient_changed_clears_event_types_eagerly(self, view_fixture, request):
        view, vm = request.getfixturevalue(view_fixture)
        view.grouping_panel.set_available_event_types(PREVIOUS_PATIENT_COUNTS)
        assert view.grouping_panel.event_types_list.count() == 3

        # Switching to any patient clears the prior list before data arrives.
        view._on_patient_changed("TEST2")

        assert view.grouping_panel.event_types_list.count() == 0
