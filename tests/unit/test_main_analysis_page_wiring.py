"""
Regression test for MainWindow analysis-page lifecycle wiring.

Background / the bug this guards
--------------------------------
MainWindow propagates the patient/data lifecycle to its four analysis
pages (Snapshots PSD, Snapshots 5 Hz Band, Timeline LFP Threshold,
Timeline Peri-Event). This wiring used to be duplicated per page in two
independent places:

  * patient_selected -> page.load_patient / patient_cleared -> page.clear_view
    (one hand-written block per page), and
  * _on_data_uploaded, which refreshed pages by hand.

Those two lists drifted: _on_data_uploaded refreshed only THREE pages and
omitted the Timeline LFP Threshold page, so after a data upload that page's
event selector stayed empty while the others updated.

The fix introduces ONE source of truth, MainWindow._analysis_pages, that
patient_selected, patient_cleared, AND data_uploaded all fan out over. These
tests assert that EVERY page in _analysis_pages receives:

  * load_patient(patient_id) on patient_selected,
  * load_patient(patient_id) on data_uploaded, and
  * clear_view() on patient_cleared,

so a page can never again be silently omitted from one path.

Test strategy
-------------
We build a real MainWindow via __new__ + QMainWindow.__init__ (the same
technique as tests/unit/test_main_window_shutdown.py) so MainWindow.__init__
-- and its DI container, database, and full UI stack -- is skipped. We then:

  * attach MagicMock pages as _analysis_pages, and
  * attach the REAL AppViewModel / DataManagementViewModel (their __init__s
    only store service references, so MagicMock services suffice) so we can
    run the REAL MainWindow._connect_signals and emit the REAL Qt signals.

Because the production _connect_signals runs and the production signals are
emitted, the test cannot be satisfied by drift in either the wiring block or
_on_data_uploaded: both must fan out over _analysis_pages.
"""

from unittest.mock import MagicMock

import pytest

from main import MainWindow
from PySide6.QtWidgets import QMainWindow

from src.ui.viewmodels.app_viewmodel import AppViewModel
from src.ui.viewmodels.data_management_viewmodel import DataManagementViewModel


PATIENT_ID = "patient-123"


def _make_patient(patient_id: str = PATIENT_ID):
    """Minimal stand-in for a Patient: only .patient_id is consumed here."""
    patient = MagicMock()
    patient.patient_id = patient_id
    return patient


@pytest.fixture
def wired_window(qtbot):
    """
    Real MainWindow shell with mock pages and real lifecycle ViewModels,
    after the production MainWindow._connect_signals has run.

    Only the Qt base class is initialized (via __new__ + QMainWindow.__init__),
    so no DI container / DB / UI is created. We then attach exactly the
    collaborators _connect_signals touches: the four (mock) analysis pages
    behind _analysis_pages, the two real lifecycle ViewModels, and mock
    top_bar / main_layout (their signals are only .connect()'d, never emitted
    here). _toolbar_export_router is None, which the page-changed slot guards.
    """
    window = MainWindow.__new__(MainWindow)
    QMainWindow.__init__(window)
    qtbot.addWidget(window)

    # Four mock analysis pages, exposed both individually (as production code
    # names them) and as the single-source-of-truth list the slots iterate.
    window.snapshots_psd_page = MagicMock(name="snapshots_psd_page")
    window.snapshots_5hz_band_page = MagicMock(name="snapshots_5hz_band_page")
    window.timeline_lfp_threshold_page = MagicMock(name="timeline_lfp_threshold_page")
    window.timeline_peri_event_page = MagicMock(name="timeline_peri_event_page")
    window._analysis_pages = [
        window.snapshots_psd_page,
        window.snapshots_5hz_band_page,
        window.timeline_lfp_threshold_page,
        window.timeline_peri_event_page,
    ]

    # Real ViewModels (so the real Qt signals exist and can be emitted);
    # their constructors only stash the service references we pass as mocks.
    window.app_viewmodel = AppViewModel(patient_service=MagicMock())
    window.data_management_viewmodel = DataManagementViewModel(
        patient_service=MagicMock(),
        statistics_service=MagicMock(),
        upload_service=MagicMock(),
        path_resolver=MagicMock(),
    )

    # Collaborators _connect_signals only connects to (never emitted here).
    window.top_bar = MagicMock(name="top_bar")
    window.main_layout = MagicMock(name="main_layout")
    window.main_layout.current_page = "data_management"
    window._toolbar_export_router = None

    # Run the PRODUCTION wiring under test.
    window._connect_signals()
    return window


def _assert_every_page(window, *, method: str, called_with):
    """Assert each page in _analysis_pages got exactly one `method` call."""
    for page in window._analysis_pages:
        call = getattr(page, method)
        if called_with is _NO_ARGS:
            call.assert_called_once_with()
        else:
            call.assert_called_once_with(called_with)


_NO_ARGS = object()  # sentinel: assert a no-argument call


class TestPatientSelectedFansOut:
    """patient_selected (a Patient OBJECT) -> load_patient on every page."""

    def test_load_patient_called_on_every_page(self, wired_window):
        wired_window.app_viewmodel.patient_selected.emit(_make_patient())

        _assert_every_page(
            wired_window, method="load_patient", called_with=PATIENT_ID
        )

    def test_uses_patient_id_attribute_not_object(self, wired_window):
        """The page receives patient.patient_id, never the Patient object."""
        patient = _make_patient("abc-999")
        wired_window.app_viewmodel.patient_selected.emit(patient)

        for page in wired_window._analysis_pages:
            page.load_patient.assert_called_once_with("abc-999")


class TestPatientClearedFansOut:
    """patient_cleared (no args) -> clear_view on every page."""

    def test_clear_view_called_on_every_page(self, wired_window):
        wired_window.app_viewmodel.patient_cleared.emit()

        _assert_every_page(
            wired_window, method="clear_view", called_with=_NO_ARGS
        )


class TestDataUploadedFansOut:
    """
    data_uploaded -> load_patient on every page (this is the page that the
    old hand-written _on_data_uploaded omitted).
    """

    def test_load_patient_called_on_every_page_for_selected_patient(
        self, wired_window
    ):
        # Make the uploaded patient the current selection so the guards pass.
        wired_window.app_viewmodel._current_patient = _make_patient(PATIENT_ID)

        wired_window.data_management_viewmodel.data_uploaded.emit(PATIENT_ID)

        _assert_every_page(
            wired_window, method="load_patient", called_with=PATIENT_ID
        )

    def test_threshold_page_is_refreshed_on_upload(self, wired_window):
        """Explicit guard for the exact page the bug skipped."""
        wired_window.app_viewmodel._current_patient = _make_patient(PATIENT_ID)

        wired_window.data_management_viewmodel.data_uploaded.emit(PATIENT_ID)

        wired_window.timeline_lfp_threshold_page.load_patient.assert_called_once_with(
            PATIENT_ID
        )

    def test_no_refresh_when_no_patient_selected(self, wired_window):
        """Early-return guard: nothing selected -> no page is touched."""
        wired_window.app_viewmodel._current_patient = None

        wired_window.data_management_viewmodel.data_uploaded.emit(PATIENT_ID)

        for page in wired_window._analysis_pages:
            page.load_patient.assert_not_called()

    def test_no_refresh_when_patient_id_mismatch(self, wired_window):
        """Early-return guard: upload for a different patient -> no refresh."""
        wired_window.app_viewmodel._current_patient = _make_patient("other-patient")

        wired_window.data_management_viewmodel.data_uploaded.emit(PATIENT_ID)

        for page in wired_window._analysis_pages:
            page.load_patient.assert_not_called()


class TestSlotsDirectly:
    """
    The fan-out slots iterate _analysis_pages independently of Qt signal
    delivery -- a fast, signal-free check of the core guarantee.
    """

    def test_load_patient_into_pages_hits_all(self, wired_window):
        wired_window._load_patient_into_pages(_make_patient(PATIENT_ID))
        _assert_every_page(
            wired_window, method="load_patient", called_with=PATIENT_ID
        )

    def test_clear_analysis_pages_hits_all(self, wired_window):
        wired_window._clear_analysis_pages()
        _assert_every_page(
            wired_window, method="clear_view", called_with=_NO_ARGS
        )
