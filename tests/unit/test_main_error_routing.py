"""
Regression tests for main.py error signal routing.

Background
----------
MainWindow._show_error displays a QMessageBox.critical. Each view
(SnapshotsPsdView, Snapshots5HzBandView) already has
its own _on_error slot that shows a QMessageBox.critical AND resets
view-specific state (progress bar, export buttons, stale markers).

If main.py also wires those viewmodels' error_occurred signals to
MainWindow._show_error, every failure pops two stacked dialogs for the
same error. Only app_viewmodel.error_occurred — which has no view-level
handler — should be routed through MainWindow._show_error.

These tests parse main.py statically so they cannot be accidentally
satisfied by patching at runtime.
"""

import re
from pathlib import Path

import pytest


MAIN_PY = Path(__file__).resolve().parents[2] / "main.py"


@pytest.fixture(scope="module")
def main_py_source() -> str:
    return MAIN_PY.read_text(encoding="utf-8")


def test_show_error_only_wired_to_app_viewmodel(main_py_source: str):
    """
    Only app_viewmodel.error_occurred should connect to self._show_error.

    Timeline/PSD/ML viewmodel errors have view-level _on_error handlers;
    duplicating them through MainWindow causes stacked QMessageBox dialogs.
    """
    pattern = re.compile(
        r"self\.(?P<owner>[\w_.]+?)\.error_occurred\.connect\(\s*self\._show_error\s*\)"
    )
    owners = pattern.findall(main_py_source)

    assert owners == ["app_viewmodel"], (
        "Expected MainWindow._show_error to be connected to "
        "self.app_viewmodel.error_occurred only. "
        f"Found connections from: {owners}. "
        "Timeline/PSD/ML viewmodel error signals are already handled by "
        "their respective views' _on_error slots — routing them through "
        "MainWindow as well will display two stacked QMessageBox dialogs "
        "for every error."
    )


def test_snapshots_psd_page_error_not_routed_through_main_window(main_py_source: str):
    assert "snapshots_psd_page.viewmodel.error_occurred.connect(self._show_error)" \
        not in main_py_source, (
        "Snapshots PSD viewmodel error is already handled by "
        "snapshots_psd_view.SnapshotsPsdView._on_error; remove the "
        "MainWindow-level connection to avoid stacked dialogs."
    )


def test_snapshots_5hz_band_page_error_not_routed_through_main_window(main_py_source: str):
    assert "snapshots_5hz_band_page.viewmodel.error_occurred.connect(self._show_error)" \
        not in main_py_source, (
        "Snapshots 5 Hz Band viewmodel error is already handled by "
        "snapshots_5hz_band_view.Snapshots5HzBandView._on_error; remove the "
        "MainWindow-level connection to avoid stacked dialogs."
    )


def test_app_viewmodel_still_connected_to_show_error(main_py_source: str):
    """
    app_viewmodel errors (patient load/create/update/delete failures)
    have no view-level handler — MainWindow must still show them.
    """
    assert "self.app_viewmodel.error_occurred.connect(self._show_error)" \
        in main_py_source, (
        "AppViewModel error_occurred must remain connected to "
        "MainWindow._show_error: it is the only handler for patient "
        "lifecycle failures and removing it would silently swallow "
        "user-facing errors."
    )
