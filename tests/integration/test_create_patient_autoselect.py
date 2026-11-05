"""
Integration test: creating a patient auto-reflects it in the TopBar dropdown.

Regression guard for the "new patient isn't shown until you click the dropdown"
bug. Wires a REAL AppViewModel (on a real PatientService + temp DB) to a REAL
TopBar exactly as MainWindow._connect_signals does in main.py, then drives the
real create flow and asserts the dropdown reflects the new patient and the
action buttons are enabled — no manual dropdown click required.

success_message / patient_created are intentionally left unconnected (as far as
this test is concerned) so no modal QMessageBox is raised; the dropdown wiring
under test does not depend on them.

Author: iEEG BrainSense Development Team
Last Updated: 2026-06-04
"""

import pytest

from src.core.path_resolver import PathResolver
from src.infrastructure.database.adapters.sqlite_adapter import SQLiteAdapter
from src.infrastructure.repositories.patient_repository import PatientRepository
from src.core.services.patient_service import PatientService
from src.infrastructure.database.schema import initialize_global_database
from src.ui.viewmodels.app_viewmodel import AppViewModel
from src.ui.components.top_bar import TopBar


@pytest.fixture
def wired(qtbot, tmp_path):
    """Real AppViewModel + TopBar wired identically to main.py, on a temp DB."""
    resolver = PathResolver(base_dir=tmp_path)
    adapter = SQLiteAdapter()
    initialize_global_database(adapter, resolver)
    service = PatientService(PatientRepository(adapter, resolver), adapter, resolver)

    app_vm = AppViewModel(service)
    top_bar = TopBar()
    qtbot.addWidget(top_bar)

    # Mirror MainWindow._connect_signals (main.py): AppViewModel -> TopBar.
    app_vm.patients_loaded.connect(top_bar.update_patient_list)
    app_vm.patient_selected.connect(
        lambda patient: top_bar.set_selected_patient(patient.patient_id)
    )
    app_vm.patient_cleared.connect(top_bar.clear_selection)

    return app_vm, top_bar


def test_create_patient_reflects_in_dropdown_and_enables_buttons(wired):
    """After create, the dropdown shows the new patient and buttons enable."""
    app_vm, top_bar = wired

    app_vm.create_patient("Jane Roe")

    idx = top_bar.patient_dropdown.currentIndex()
    assert idx != -1, "new patient should be auto-selected in the dropdown"
    # AppViewModel derives patient_id as name.upper().replace(" ", "_").
    assert top_bar.patient_dropdown.itemData(idx) == "JANE_ROE"
    assert app_vm.current_patient.patient_id == "JANE_ROE"
    assert top_bar.upload_button.isEnabled() is True
    assert top_bar.delete_button.isEnabled() is True


def test_clear_selection_resets_dropdown(wired):
    """Clearing the selection (e.g. after delete) blanks the dropdown."""
    app_vm, top_bar = wired
    app_vm.create_patient("Jane Roe")

    app_vm.clear_patient_selection()

    assert top_bar.patient_dropdown.currentIndex() == -1
    assert top_bar.upload_button.isEnabled() is False
    assert top_bar.delete_button.isEnabled() is False
