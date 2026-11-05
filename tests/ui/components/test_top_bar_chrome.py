"""
TopBar chrome: the "Delete Patient…" button and the confirmation it opens
(MainWindow._on_delete_patient), the patient combo's size, tooltip and cursor,
and the Save Plot tooltip. Measured under the app stylesheet; no dialog runs
modally (``QMessageBox.exec`` is replaced).
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from PySide6.QtGui import QFontMetricsF
from PySide6.QtWidgets import QMessageBox, QWidget

import main
from src.ui.app_style import apply_app_stylesheet
from src.ui.components.top_bar import TopBar
from src.ui.policy.tokens import Dim

LONG_NAME = "Constance Wilhelmina Fitzgerald-Rutherford III"


def _patient(patient_id: str, patient_name: str = None):
    """Duck-typed stand-in for Patient (TopBar only reads these two fields)."""
    return SimpleNamespace(patient_id=patient_id, patient_name=patient_name or patient_id)


@pytest.fixture
def top_bar(qtbot, qapp):
    apply_app_stylesheet(qapp)  # the UI conftest restores the session's sheet
    bar = TopBar()
    qtbot.addWidget(bar)
    bar.resize(1080, 51)
    bar.show()
    qtbot.wait(10)
    return bar


def _text_room(combo) -> int:
    """Width the combo's line edit draws text in (contents minus its 2-px side margins)."""
    editor = combo.lineEdit()
    margins = editor.textMargins()
    return editor.contentsRect().width() - margins.left() - margins.right() - 4


# ------------------------------------------------------------ Delete Patient…

def test_delete_button_says_delete_patient_with_an_icon(top_bar):
    assert top_bar.delete_button.text() == "Delete Patient…"
    assert not top_bar.delete_button.icon().isNull()


@pytest.fixture
def delete_host(qtbot):
    """A widget standing in for MainWindow, with a selected patient."""
    host = QWidget()
    qtbot.addWidget(host)
    host.app_viewmodel = MagicMock(
        current_patient=_patient("JANE_ROE", "Jane Roe"))
    return host


def _answer_with(monkeypatch, label):
    """Replace exec (it records the box) and answer with the button labelled ``label``.

    The box is never run, so the answer is what ``clickedButton()`` reports.
    """
    boxes = []
    monkeypatch.setattr(QMessageBox, "exec", lambda box: boxes.append(box) or 0)
    monkeypatch.setattr(QMessageBox, "clickedButton", lambda box: next(
        (b for b in box.buttons() if b.text() == label), None))
    return boxes


def test_delete_confirmation_names_the_patient_and_what_goes(delete_host, monkeypatch):
    boxes = _answer_with(monkeypatch, None)

    main.MainWindow._on_delete_patient(delete_host)

    (box,) = boxes
    assert box.text() == "Delete “Jane Roe”?"
    assert "everything imported for them" in box.informativeText()
    assert "cannot be undone" in box.informativeText()
    assert sorted(b.text() for b in box.buttons()) == ["Cancel", "Delete Patient"]
    delete = next(b for b in box.buttons() if b.text() == "Delete Patient")
    assert box.buttonRole(delete) == QMessageBox.ButtonRole.DestructiveRole
    cancel = box.button(QMessageBox.StandardButton.Cancel)
    assert box.defaultButton() is cancel
    assert box.escapeButton() is cancel


def test_confirming_deletes_the_patient(delete_host, monkeypatch):
    _answer_with(monkeypatch, "Delete Patient")

    main.MainWindow._on_delete_patient(delete_host)

    delete_host.app_viewmodel.delete_patient.assert_called_once_with("JANE_ROE")


def test_cancel_keeps_the_patient(delete_host, monkeypatch):
    _answer_with(monkeypatch, "Cancel")

    main.MainWindow._on_delete_patient(delete_host)

    delete_host.app_viewmodel.delete_patient.assert_not_called()


def test_no_selected_patient_asks_nothing(delete_host, monkeypatch):
    boxes = _answer_with(monkeypatch, None)
    delete_host.app_viewmodel.current_patient = None

    main.MainWindow._on_delete_patient(delete_host)

    assert boxes == []


# -------------------------------------------------------------- patient combo

def test_combo_is_at_least_14_characters_wide(top_bar):
    combo = top_bar.patient_dropdown
    x_width = QFontMetricsF(combo.font()).horizontalAdvance("X")

    assert combo.minimumContentsLength() == 14
    assert combo.minimumSizeHint().width() >= 14 * x_width
    assert combo.width() >= combo.minimumSizeHint().width()


def test_placeholder_is_not_clipped(top_bar):
    combo = top_bar.patient_dropdown
    placeholder = combo.lineEdit().placeholderText()

    assert QFontMetricsF(combo.font()).horizontalAdvance(placeholder) <= _text_room(combo)


def test_combo_grows_with_the_longest_name_up_to_the_cap(top_bar, qtbot):
    combo = top_bar.patient_dropdown
    empty_width = combo.width()

    top_bar.update_patient_list([_patient("LONG", LONG_NAME)])
    qtbot.wait(10)

    assert combo.maximumWidth() == Dim.PATIENT_COMBO_MAX_W
    assert empty_width < combo.width() == Dim.PATIENT_COMBO_MAX_W


def test_selected_name_shows_its_start_and_tooltip(top_bar):
    top_bar.update_patient_list([_patient("LONG", LONG_NAME), _patient("BOB")])

    top_bar.set_selected_patient("LONG")

    combo = top_bar.patient_dropdown
    assert LONG_NAME in combo.toolTip()
    assert combo.lineEdit().cursorPosition() == 0


def test_picking_a_patient_updates_the_tooltip(top_bar):
    top_bar.update_patient_list([_patient("LONG", LONG_NAME), _patient("BOB")])
    combo = top_bar.patient_dropdown

    combo.setCurrentIndex(combo.findData("BOB"))

    assert "BOB" in combo.toolTip()
    assert combo.lineEdit().cursorPosition() == 0


def test_tooltip_clears_with_the_selection(top_bar):
    top_bar.update_patient_list([_patient("LONG", LONG_NAME)])
    top_bar.set_selected_patient("LONG")

    top_bar.clear_selection()
    assert top_bar.patient_dropdown.toolTip() == ""

    top_bar.set_selected_patient("LONG")
    top_bar.update_patient_list([])  # e.g. the last patient was deleted
    assert top_bar.patient_dropdown.toolTip() == ""


# ------------------------------------------------------------------ Save Plot

def test_save_plot_tooltip_explains_the_export(top_bar):
    tooltip = top_bar.save_plot_button.toolTip()

    assert "manuscript-format figure" in tooltip
    assert "on-screen layout may differ" in tooltip
