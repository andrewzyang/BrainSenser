"""Fixtures for the Data page layout tests: the shipped stylesheet and a stub ViewModel."""

from unittest.mock import MagicMock, Mock

import pytest
from PySide6.QtWidgets import QApplication

from src.ui.app_style import apply_app_stylesheet
from src.ui.viewmodels.data_management_viewmodel import DataManagementViewModel

VM_SIGNALS = ("patient_selected", "patient_cleared", "metadata_updated", "statistics_updated",
              "upload_history_updated", "error_occurred", "success_message")


@pytest.fixture(scope="module")
def app_stylesheet(qapp):
    """The shipped stylesheet, applied once per module and then restored.

    Re-styling the application repolishes every widget, so doing it per test
    would dominate these tests; the per-test restore fixture of the UI conftest
    sees no change while this is applied.
    """
    app = QApplication.instance()
    previous = app.styleSheet()
    apply_app_stylesheet(app)
    yield
    app.setStyleSheet(previous)


@pytest.fixture
def stub_viewmodel():
    """A DataManagementViewModel stand-in whose seven signals accept connections."""
    viewmodel = Mock(spec=DataManagementViewModel)
    for name in VM_SIGNALS:
        setattr(viewmodel, name, MagicMock())
    return viewmodel
