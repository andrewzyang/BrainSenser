"""
Unit tests for DataManagementViewModel.upload_file() and upload_path().

Companion to test_data_management_viewmodel_upload_directory.py. Covers the
single-file upload path added so the Data Management "Upload" button accepts
either one JSON file or a whole directory (the View hands over a Path; the
ViewModel routes it).

MVVM: the ViewModel delegates the actual upload to UploadService (mocked here)
and only validates inputs, formats the result message, and emits signals. These
tests never perform a real upload.

Author: iEEG BrainSense Development Team
Last Updated: 2026-06-03
"""

from unittest.mock import Mock

from src.ui.viewmodels.data_management_viewmodel import DataManagementViewModel
from src.core.models.upload_result import UploadResult


class TestUploadPathRouting:
    """upload_path() routes to the right handler based on the path type."""

    def test_directory_routes_to_upload_directory(self, mocker, tmp_path):
        viewmodel = _create_mock_viewmodel(mocker)
        viewmodel.upload_directory = mocker.Mock()
        viewmodel.upload_file = mocker.Mock()

        test_dir = tmp_path / "recordings"
        test_dir.mkdir()

        viewmodel.upload_path(test_dir)

        viewmodel.upload_directory.assert_called_once_with(test_dir)
        viewmodel.upload_file.assert_not_called()

    def test_file_routes_to_upload_file(self, mocker, tmp_path):
        viewmodel = _create_mock_viewmodel(mocker)
        viewmodel.upload_directory = mocker.Mock()
        viewmodel.upload_file = mocker.Mock()

        test_file = tmp_path / "session.json"
        test_file.write_text("{}")

        viewmodel.upload_path(test_file)

        viewmodel.upload_file.assert_called_once_with(test_file)
        viewmodel.upload_directory.assert_not_called()

    def test_missing_path_emits_error(self, mocker, tmp_path):
        viewmodel = _create_mock_viewmodel(mocker)
        viewmodel.upload_directory = mocker.Mock()
        viewmodel.upload_file = mocker.Mock()
        error_spy = Mock()
        viewmodel.error_occurred.connect(error_spy)

        viewmodel.upload_path(tmp_path / "does_not_exist.json")

        error_spy.assert_called_once()
        viewmodel.upload_file.assert_not_called()
        viewmodel.upload_directory.assert_not_called()


class TestUploadFileDelegation:
    """upload_file() delegates to the service and validates inputs first."""

    def test_delegates_to_service_with_patient_and_path(self, mocker, tmp_path):
        viewmodel = _create_mock_viewmodel(mocker)
        viewmodel._current_patient = _create_mock_patient("P001")
        viewmodel._refresh_after_upload = mocker.Mock()

        test_file = tmp_path / "session.json"
        test_file.write_text("{}")

        mock_upload_file = mocker.patch.object(
            viewmodel.upload_service, "upload_file",
            return_value=_create_upload_result(success=True, timeline_inserted=10),
        )

        viewmodel.upload_file(test_file)

        mock_upload_file.assert_called_once_with(
            patient_id="P001", file_path=test_file, progress_callback=None
        )

    def test_no_patient_selected_emits_error_and_skips_service(self, mocker, tmp_path):
        viewmodel = _create_mock_viewmodel(mocker)
        viewmodel._current_patient = None
        error_spy = Mock()
        viewmodel.error_occurred.connect(error_spy)

        test_file = tmp_path / "session.json"
        test_file.write_text("{}")

        viewmodel.upload_file(test_file)

        error_spy.assert_called_once()
        viewmodel.upload_service.upload_file.assert_not_called()

    def test_non_json_file_emits_error_and_skips_service(self, mocker, tmp_path):
        viewmodel = _create_mock_viewmodel(mocker)
        viewmodel._current_patient = _create_mock_patient("P001")
        error_spy = Mock()
        viewmodel.error_occurred.connect(error_spy)

        test_file = tmp_path / "session.txt"
        test_file.write_text("not json")

        viewmodel.upload_file(test_file)

        error_spy.assert_called_once()
        viewmodel.upload_service.upload_file.assert_not_called()

    def test_missing_file_emits_error_and_skips_service(self, mocker, tmp_path):
        viewmodel = _create_mock_viewmodel(mocker)
        viewmodel._current_patient = _create_mock_patient("P001")
        error_spy = Mock()
        viewmodel.error_occurred.connect(error_spy)

        viewmodel.upload_file(tmp_path / "absent.json")

        error_spy.assert_called_once()
        viewmodel.upload_service.upload_file.assert_not_called()


class TestUploadFileSignalEmission:
    """upload_file() emits the right signal for each result kind."""

    def test_success_emits_breakdown_and_refreshes(self, mocker, tmp_path):
        viewmodel = _create_mock_viewmodel(mocker)
        viewmodel._current_patient = _create_mock_patient("P001")
        refresh = mocker.patch.object(viewmodel, "_refresh_after_upload")

        test_file = tmp_path / "session.json"
        test_file.write_text("{}")

        result = _create_upload_result(
            success=True,
            timeline_inserted=100, timeline_duplicates=5,
            snapshot_inserted=20, snapshot_duplicates=2,
        )
        mocker.patch.object(viewmodel.upload_service, "upload_file", return_value=result)

        success_spy, error_spy = Mock(), Mock()
        viewmodel.success_message.connect(success_spy)
        viewmodel.error_occurred.connect(error_spy)

        viewmodel.upload_file(test_file)

        success_spy.assert_called_once()
        msg = success_spy.call_args[0][0]
        assert "session.json" in msg
        assert "Timeline: 100" in msg
        assert "Snapshots: 20" in msg
        error_spy.assert_not_called()
        refresh.assert_called_once()

    def test_duplicate_emits_info_not_error(self, mocker, tmp_path):
        viewmodel = _create_mock_viewmodel(mocker)
        viewmodel._current_patient = _create_mock_patient("P001")
        refresh = mocker.patch.object(viewmodel, "_refresh_after_upload")

        test_file = tmp_path / "session.json"
        test_file.write_text("{}")

        result = _create_upload_result(
            success=False,
            message="File already uploaded: session.json on 2026-06-03",
            file_hash="abc123",
            is_duplicate=True,
        )
        mocker.patch.object(viewmodel.upload_service, "upload_file", return_value=result)

        success_spy, error_spy = Mock(), Mock()
        viewmodel.success_message.connect(success_spy)
        viewmodel.error_occurred.connect(error_spy)

        viewmodel.upload_file(test_file)

        success_spy.assert_called_once()
        assert "Already Uploaded" in success_spy.call_args[0][0]
        error_spy.assert_not_called()
        refresh.assert_not_called()  # nothing changed, no refresh needed

    def test_failure_emits_error_and_no_refresh(self, mocker, tmp_path):
        viewmodel = _create_mock_viewmodel(mocker)
        viewmodel._current_patient = _create_mock_patient("P001")
        refresh = mocker.patch.object(viewmodel, "_refresh_after_upload")

        test_file = tmp_path / "session.json"
        test_file.write_text("{}")

        result = _create_upload_result(
            success=False,
            message="Upload failed: corrupt JSON",
            file_hash="",
        )
        mocker.patch.object(viewmodel.upload_service, "upload_file", return_value=result)

        success_spy, error_spy = Mock(), Mock()
        viewmodel.success_message.connect(success_spy)
        viewmodel.error_occurred.connect(error_spy)

        viewmodel.upload_file(test_file)

        error_spy.assert_called_once()
        assert "corrupt JSON" in error_spy.call_args[0][0]
        success_spy.assert_not_called()
        refresh.assert_not_called()


# Helpers (local; mirror the upload_directory test module) -------------------

def _create_mock_viewmodel(mocker):
    """Create a DataManagementViewModel with mocked dependencies."""
    viewmodel = DataManagementViewModel(
        patient_service=mocker.Mock(),
        statistics_service=mocker.Mock(),
        upload_service=mocker.Mock(),
        path_resolver=mocker.Mock(),
    )
    # Stub these so the shared refresh path can't touch real internals.
    viewmodel.refresh_statistics = mocker.Mock()
    viewmodel._load_upload_history = mocker.Mock()
    return viewmodel


def _create_mock_patient(patient_id: str):
    """Create a mock Patient object."""
    patient = Mock()
    patient.patient_id = patient_id
    patient.metadata = {}
    return patient


def _create_upload_result(
    success=True,
    message="OK",
    timeline_inserted=0,
    timeline_duplicates=0,
    snapshot_inserted=0,
    snapshot_duplicates=0,
    indefinite_streaming_inserted=0,
    indefinite_streaming_duplicates=0,
    definite_streaming_inserted=0,
    definite_streaming_duplicates=0,
    file_hash="",
    is_duplicate=False,
):
    """Create a single-file UploadResult for testing."""
    return UploadResult(
        success=success,
        message=message,
        timeline_inserted=timeline_inserted,
        timeline_duplicates=timeline_duplicates,
        snapshot_inserted=snapshot_inserted,
        snapshot_duplicates=snapshot_duplicates,
        indefinite_streaming_inserted=indefinite_streaming_inserted,
        indefinite_streaming_duplicates=indefinite_streaming_duplicates,
        definite_streaming_inserted=definite_streaming_inserted,
        definite_streaming_duplicates=definite_streaming_duplicates,
        file_hash=file_hash,
        is_duplicate=is_duplicate,
    )
