"""
Unit tests for MlProgressDialog.

Pins the visibility + signal contract used by the analysis views:

  * ``start(msg)`` shows the dialog (modal) — the ONLY path that does —
    and resets the bar to 0.
  * ``update_progress(percent, msg)`` refreshes label + bar value only;
    it never shows or hides the dialog.
  * ``reset()`` hides + clears state from any visibility / state.
  * Cancel button emits ``cancel_requested`` and disables itself
    until the next ``update_progress`` call (so the user can't
    spam-click cancel).
  * Esc routes through Cancel rather than silently dismissing.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from src.ui.components.ml_progress_dialog import MlProgressDialog


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def dialog(qapp):
    widget = MlProgressDialog()
    yield widget
    widget.deleteLater()


class TestVisibility:
    def test_starts_hidden(self, dialog):
        assert dialog.isVisible() is False

    def test_start_shows_dialog(self, dialog):
        dialog.start("Starting…")
        assert dialog.isVisible() is True

    def test_update_progress_does_not_show(self, dialog):
        # Content-only: a progress emission never opens the popup.
        dialog.update_progress(10, "Step 1")
        assert dialog.isVisible() is False

    def test_update_progress_after_start_keeps_visible(self, dialog):
        dialog.start()
        dialog.update_progress(50, "Working")
        assert dialog.isVisible() is True

    def test_update_progress_100_does_not_hide(self, dialog):
        # Visibility is owned by start()/reset(), never by the percent value.
        dialog.start()
        dialog.update_progress(100, "Done")
        assert dialog.isVisible() is True

    def test_reset_hides_dialog(self, dialog):
        dialog.start("Mid")
        assert dialog.isVisible() is True
        dialog.reset()
        assert dialog.isVisible() is False

    def test_reset_when_already_hidden_is_safe(self, dialog):
        # Nothing should raise — reset() is idempotent.
        dialog.reset()
        dialog.reset()
        assert dialog.isVisible() is False


class TestProgressContent:
    def test_update_sets_label_and_bar(self, dialog):
        dialog.update_progress(37, "Permutation 370/1000")
        assert dialog._step_label.text() == "Permutation 370/1000"
        assert dialog._progress_bar.value() == 37

    def test_clamps_below_zero(self, dialog):
        dialog.update_progress(-5, "Bad")
        assert dialog._progress_bar.value() == 0

    def test_clamps_above_hundred(self, dialog):
        dialog.update_progress(120, "Over")
        assert dialog._progress_bar.value() == 100


class TestCancel:
    def test_cancel_button_emits_signal(self, dialog, qapp):
        received = []
        dialog.cancel_requested.connect(lambda: received.append(True))
        dialog.update_progress(20, "Working")
        dialog._cancel_btn.click()
        assert received == [True]

    def test_cancel_disables_button_until_next_progress(self, dialog):
        dialog.update_progress(20, "Working")
        dialog._cancel_btn.click()
        assert dialog._cancel_btn.isEnabled() is False
        # Next progress event re-enables it (worker is still draining).
        dialog.update_progress(30, "Cancelling cleanup")
        assert dialog._cancel_btn.isEnabled() is True

    def test_cancel_updates_label_to_cancelling(self, dialog):
        dialog.update_progress(20, "Working")
        dialog._cancel_btn.click()
        assert dialog._step_label.text() == "Cancelling…"

    def test_escape_routes_through_cancel(self, dialog, qapp):
        received = []
        dialog.cancel_requested.connect(lambda: received.append(True))
        dialog.update_progress(20, "Working")
        event = QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier)
        dialog.keyPressEvent(event)
        assert received == [True]

    def test_escape_does_nothing_when_button_disabled(self, dialog, qapp):
        received = []
        dialog.cancel_requested.connect(lambda: received.append(True))
        dialog.update_progress(20, "Working")
        dialog._cancel_btn.click()  # Disables the button.
        # Now Esc should not fire a second cancel.
        event = QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier)
        dialog.keyPressEvent(event)
        assert received == [True]  # Still just one signal.
