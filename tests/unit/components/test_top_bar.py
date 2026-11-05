"""
Unit tests for TopBar patient-dropdown selection behavior.

Focus: set_selected_patient(), the slot the AppViewModel drives so that a
programmatically-selected patient (e.g. right after Create) is reflected in the
dropdown and the action buttons enable — without forcing the user to re-pick the
patient from the dropdown.

Regression guard for the "new patient not shown until you click the dropdown"
bug: set_selected_patient must (1) select the matching item, (2) enable the
Upload/Delete buttons that update_patient_list() disabled, and (3) NOT re-emit
patient_selected (which would bounce back through the ViewModel and redundantly
reload every page).

Author: iEEG BrainSense Development Team
Last Updated: 2026-06-04
"""

from types import SimpleNamespace

import pytest

from src.ui.components.top_bar import TopBar


def _patient(patient_id: str, patient_name: str = None):
    """Duck-typed stand-in for Patient (TopBar only reads these two fields)."""
    return SimpleNamespace(
        patient_id=patient_id,
        patient_name=patient_name or patient_id,
    )


@pytest.fixture
def top_bar(qtbot):
    """A TopBar populated with two patients and no current selection."""
    bar = TopBar()
    qtbot.addWidget(bar)
    bar.update_patient_list([_patient("ALICE"), _patient("BOB")])
    return bar


class TestSetSelectedPatient:
    """set_selected_patient() reflects programmatic selection in the dropdown."""

    def test_starts_with_no_selection_and_disabled_buttons(self, top_bar):
        """update_patient_list() leaves nothing selected and buttons disabled."""
        assert top_bar.patient_dropdown.currentIndex() == -1
        assert top_bar.upload_button.isEnabled() is False
        assert top_bar.delete_button.isEnabled() is False

    def test_selects_matching_item_and_enables_buttons(self, top_bar):
        """The matching id is selected and the action buttons are enabled."""
        top_bar.set_selected_patient("BOB")

        idx = top_bar.patient_dropdown.currentIndex()
        assert idx != -1
        assert top_bar.patient_dropdown.itemData(idx) == "BOB"
        assert top_bar.upload_button.isEnabled() is True
        assert top_bar.delete_button.isEnabled() is True

    def test_does_not_re_emit_patient_selected(self, top_bar):
        """
        Programmatic selection must be silent: re-emitting patient_selected would
        bounce back into AppViewModel.select_patient and redundantly reload every
        page (the echo guarded by blockSignals()).
        """
        emitted = []
        top_bar.patient_selected.connect(emitted.append)

        top_bar.set_selected_patient("BOB")

        assert emitted == []

    def test_unknown_id_is_noop(self, top_bar):
        """An id not in the list changes nothing (selection and buttons)."""
        top_bar.set_selected_patient("NOBODY")

        assert top_bar.patient_dropdown.currentIndex() == -1
        assert top_bar.upload_button.isEnabled() is False
        assert top_bar.delete_button.isEnabled() is False

    def test_dropdown_label_is_name_only_no_parentheses(self, qtbot):
        """
        The dropdown shows the patient name only — never "name (ID)". A
        user-created patient stores the name as typed ("test2") and an
        uppercased id ("TEST2"); the label must read "test2", not
        "test2 (TEST2)", while the id stays as item data for selection.
        """
        bar = TopBar()
        qtbot.addWidget(bar)
        bar.update_patient_list([
            _patient("ALPHA"),                 # name == id
            _patient("TEST2", "test2"),         # name differs from id (case)
        ])

        labels = [bar.patient_dropdown.itemText(i)
                  for i in range(bar.patient_dropdown.count())]
        assert labels == ["ALPHA", "test2"]
        assert "(" not in "".join(labels)
        # id still stored as data so selection logic is unaffected
        assert bar.patient_dropdown.itemData(1) == "TEST2"

    def test_manual_selection_still_emits(self, top_bar, qtbot):
        """
        Sanity: the user-driven path is unaffected — picking an item via the
        dropdown still emits patient_selected with the patient_id.
        """
        idx_bob = next(
            i for i in range(top_bar.patient_dropdown.count())
            if top_bar.patient_dropdown.itemData(i) == "BOB"
        )

        with qtbot.waitSignal(top_bar.patient_selected, timeout=1000) as blocker:
            top_bar.patient_dropdown.setCurrentIndex(idx_bob)

        assert blocker.args == ["BOB"]
        assert top_bar.upload_button.isEnabled() is True
        assert top_bar.delete_button.isEnabled() is True
