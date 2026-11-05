"""
Unit tests for DataManagementViewModel.upload_directory() method.

Tests cover MVVM compliance after refactoring where file discovery logic
was moved from ViewModel to Service layer. Verifies that ViewModel:
    - Delegates entirely to UploadService (no file system operations)
    - Properly handles DirectoryUploadResult from service
    - Emits appropriate signals based on results
    - Handles error cases gracefully

CRITICAL: ViewModel tests should NOT touch the file system. All file
operations are mocked at the service level.

Author: iEEG BrainSense Development Team
Last Updated: 2025-10-15
"""

from pathlib import Path
from unittest.mock import Mock
from src.ui.viewmodels.data_management_viewmodel import DataManagementViewModel
from src.core.models.upload_result import DirectoryUploadResult


class TestUploadDirectoryDelegation:
    """Test that ViewModel properly delegates to service."""

    def test_upload_directory_delegates_to_service(self, mocker, tmp_path):
        """Test that ViewModel delegates to service without file operations."""
        # Create ViewModel with mocked dependencies
        viewmodel = _create_mock_viewmodel(mocker)

        # Set up current patient
        mock_patient = Mock()
        mock_patient.patient_id = "P001"
        viewmodel._current_patient = mock_patient

        # Create test directory
        test_dir = tmp_path / "test_dir"
        test_dir.mkdir()

        # Mock service method to return successful result
        mock_result = _create_directory_upload_result(
            total_files=5,
            successful_uploads=5,
            failed_uploads=0,
            total_timeline_inserted=500,
            total_timeline_duplicates=50
        )
        mock_upload_directory = mocker.patch.object(
            viewmodel.upload_service,
            'upload_directory',
            return_value=mock_result
        )

        # Test ViewModel method
        viewmodel.upload_directory(test_dir)

        # Verify delegation to service (NO file operations in ViewModel!)
        mock_upload_directory.assert_called_once_with(
            patient_id="P001",
            directory_path=test_dir,
            progress_callback=None
        )

    def test_upload_directory_passes_correct_patient_id(self, mocker, tmp_path):
        """Test that ViewModel passes current patient ID to service."""
        viewmodel = _create_mock_viewmodel(mocker)

        # Set up different patient
        mock_patient = Mock()
        mock_patient.patient_id = "PATIENT_XYZ"
        viewmodel._current_patient = mock_patient

        # Create test directory
        test_dir = tmp_path / "test_dir"
        test_dir.mkdir()

        # Mock service
        mock_result = _create_directory_upload_result(total_files=1, successful_uploads=1)
        mock_upload_directory = mocker.patch.object(
            viewmodel.upload_service,
            'upload_directory',
            return_value=mock_result
        )

        # Test
        viewmodel.upload_directory(test_dir)

        # Verify correct patient ID passed
        call_args = mock_upload_directory.call_args
        assert call_args[1]['patient_id'] == "PATIENT_XYZ"


class TestUploadDirectorySignalEmission:
    """Test signal emission based on upload results."""

    def test_upload_directory_emits_success_signal_on_complete_success(self, mocker, tmp_path):
        """Test that success_message signal is emitted with correct content."""
        viewmodel = _create_mock_viewmodel(mocker)
        viewmodel._current_patient = _create_mock_patient("P001")

        # Create test directory
        test_dir = tmp_path / "test_dir"
        test_dir.mkdir()

        # Mock service to return successful result
        mock_result = _create_directory_upload_result(
            total_files=5,
            successful_uploads=5,
            failed_uploads=0,
            total_timeline_inserted=500,
            total_timeline_duplicates=50,
            total_snapshot_inserted=250,
            total_snapshot_duplicates=25
        )
        mocker.patch.object(viewmodel.upload_service, 'upload_directory', return_value=mock_result)

        # Mock signal spy
        success_spy = Mock()
        viewmodel.success_message.connect(success_spy)

        # Test
        viewmodel.upload_directory(test_dir)

        # Verify success signal emitted
        success_spy.assert_called_once()
        success_msg = success_spy.call_args[0][0]

        # Verify message content
        assert "5 of 5 files" in success_msg or "5/5 files" in success_msg
        assert "500" in success_msg  # Timeline count
        assert "250" in success_msg  # Snapshot count

    def test_upload_directory_emits_success_with_warnings_on_partial_success(self, mocker, tmp_path):
        """Test that success message includes warnings for partial success."""
        viewmodel = _create_mock_viewmodel(mocker)
        viewmodel._current_patient = _create_mock_patient("P001")

        # Create test directory
        test_dir = tmp_path / "test_dir"
        test_dir.mkdir()

        # Mock service to return partial success
        mock_result = _create_directory_upload_result(
            total_files=10,
            successful_uploads=7,
            failed_uploads=3,
            skipped_duplicates=2,
            has_errors=True
        )
        mocker.patch.object(viewmodel.upload_service, 'upload_directory', return_value=mock_result)

        # Mock signal spy
        success_spy = Mock()
        viewmodel.success_message.connect(success_spy)

        # Test
        viewmodel.upload_directory(test_dir)

        # Verify success signal emitted (even with warnings)
        success_spy.assert_called_once()
        success_msg = success_spy.call_args[0][0]

        # Verify warnings in message
        assert "7" in success_msg and "10" in success_msg  # 7 of 10
        assert "Warnings" in success_msg or "Failed uploads: 3" in success_msg

    def test_upload_directory_emits_error_signal_on_no_files(self, mocker, tmp_path):
        """Test that error_occurred signal is emitted when no JSON files found."""
        viewmodel = _create_mock_viewmodel(mocker)
        viewmodel._current_patient = _create_mock_patient("P001")

        # Create test directory
        test_dir = tmp_path / "test_dir"
        test_dir.mkdir()

        # Mock service to return empty result (no files found)
        mock_result = _create_directory_upload_result(
            total_files=0,
            successful_uploads=0,
            failed_uploads=0
        )
        mocker.patch.object(viewmodel.upload_service, 'upload_directory', return_value=mock_result)

        # Mock signal spy
        error_spy = Mock()
        viewmodel.error_occurred.connect(error_spy)

        # Test
        viewmodel.upload_directory(test_dir)

        # Verify error signal emitted
        error_spy.assert_called_once()
        error_msg = error_spy.call_args[0][0]
        assert "No JSON Files Found" in error_msg

    def test_upload_directory_emits_error_signal_on_all_failures(self, mocker, tmp_path):
        """Test that error_occurred signal is emitted when all files fail."""
        viewmodel = _create_mock_viewmodel(mocker)
        viewmodel._current_patient = _create_mock_patient("P001")

        # Create test directory
        test_dir = tmp_path / "test_dir"
        test_dir.mkdir()

        # Mock service to return complete failure
        mock_result = _create_directory_upload_result(
            total_files=5,
            successful_uploads=0,
            failed_uploads=5
        )
        mocker.patch.object(viewmodel.upload_service, 'upload_directory', return_value=mock_result)

        # Mock signal spy
        error_spy = Mock()
        viewmodel.error_occurred.connect(error_spy)

        # Test
        viewmodel.upload_directory(test_dir)

        # Verify error signal emitted
        error_spy.assert_called_once()
        error_msg = error_spy.call_args[0][0]
        assert "Batch Upload Failed" in error_msg or "failed to upload" in error_msg

    def test_upload_directory_all_duplicates_emits_info_not_error(self, mocker, tmp_path):
        """All files already uploaded -> informational success, NOT a failure error.

        Regression: previously duplicate files were counted as failed_uploads,
        so a directory of already-uploaded files showed "Batch Upload Failed".
        """
        viewmodel = _create_mock_viewmodel(mocker)
        viewmodel._current_patient = _create_mock_patient("P001")

        test_dir = tmp_path / "test_dir"
        test_dir.mkdir()

        # 15 files, none new, none failed -> all skipped as duplicates
        mock_result = _create_directory_upload_result(
            total_files=15,
            successful_uploads=0,
            failed_uploads=0,
            skipped_duplicates=15,
        )
        mocker.patch.object(viewmodel.upload_service, 'upload_directory', return_value=mock_result)

        success_spy, error_spy = Mock(), Mock()
        viewmodel.success_message.connect(success_spy)
        viewmodel.error_occurred.connect(error_spy)

        viewmodel.upload_directory(test_dir)

        error_spy.assert_not_called()
        success_spy.assert_called_once()
        msg = success_spy.call_args[0][0]
        assert "Already Uploaded" in msg
        assert "15" in msg

    def test_upload_directory_emits_error_signal_on_no_patient_selected(self, mocker):
        """Test that error is emitted when no patient is selected."""
        viewmodel = _create_mock_viewmodel(mocker)
        viewmodel._current_patient = None  # No patient selected

        # Mock signal spy
        error_spy = Mock()
        viewmodel.error_occurred.connect(error_spy)

        # Test
        viewmodel.upload_directory(Path("/test"))

        # Verify error signal emitted
        error_spy.assert_called_once()
        error_msg = error_spy.call_args[0][0]
        assert "No patient selected" in error_msg


class TestUploadDirectoryPostOperations:
    """Test post-upload operations (statistics refresh, history reload, etc.)."""

    def test_upload_directory_refreshes_statistics_after_success(self, mocker, tmp_path):
        """Test that statistics are refreshed after successful upload."""
        viewmodel = _create_mock_viewmodel(mocker)
        viewmodel._current_patient = _create_mock_patient("P001")

        # Create test directory
        test_dir = tmp_path / "test_dir"
        test_dir.mkdir()

        # Mock service
        mock_result = _create_directory_upload_result(total_files=3, successful_uploads=3)
        mocker.patch.object(viewmodel.upload_service, 'upload_directory', return_value=mock_result)

        # Spy on refresh_statistics method
        refresh_spy = mocker.spy(viewmodel, 'refresh_statistics')

        # Test
        viewmodel.upload_directory(test_dir)

        # Verify refresh_statistics was called
        refresh_spy.assert_called_once()

    def test_upload_directory_refreshes_upload_history_after_success(self, mocker, tmp_path):
        """Test that upload history is refreshed after successful upload."""
        viewmodel = _create_mock_viewmodel(mocker)
        viewmodel._current_patient = _create_mock_patient("P001")

        # Create test directory
        test_dir = tmp_path / "test_dir"
        test_dir.mkdir()

        # Mock service
        mock_result = _create_directory_upload_result(total_files=3, successful_uploads=3)
        mocker.patch.object(viewmodel.upload_service, 'upload_directory', return_value=mock_result)

        # Spy on _load_upload_history method
        history_spy = mocker.spy(viewmodel, '_load_upload_history')

        # Test
        viewmodel.upload_directory(test_dir)

        # Verify _load_upload_history was called with correct patient ID
        history_spy.assert_called_once_with("P001")

    def test_upload_directory_emits_data_uploaded_signal(self, mocker, tmp_path):
        """Test that data_uploaded signal is emitted after successful upload."""
        viewmodel = _create_mock_viewmodel(mocker)
        viewmodel._current_patient = _create_mock_patient("P001")

        # Create test directory
        test_dir = tmp_path / "test_dir"
        test_dir.mkdir()

        # Mock service
        mock_result = _create_directory_upload_result(total_files=3, successful_uploads=3)
        mocker.patch.object(viewmodel.upload_service, 'upload_directory', return_value=mock_result)

        # Mock signal spy
        data_uploaded_spy = Mock()
        viewmodel.data_uploaded.connect(data_uploaded_spy)

        # Test
        viewmodel.upload_directory(test_dir)

        # Verify data_uploaded signal emitted with patient ID
        data_uploaded_spy.assert_called_once_with("P001")


class TestUploadDirectoryValidation:
    """Test input validation in ViewModel."""

    def test_upload_directory_validates_directory_exists(self, mocker, tmp_path):
        """Test that ViewModel validates directory exists before calling service."""
        viewmodel = _create_mock_viewmodel(mocker)
        viewmodel._current_patient = _create_mock_patient("P001")

        # Mock service (should not be called)
        mock_upload_directory = mocker.patch.object(viewmodel.upload_service, 'upload_directory')

        # Mock signal spy
        error_spy = Mock()
        viewmodel.error_occurred.connect(error_spy)

        # Test with non-existent directory
        nonexistent_dir = tmp_path / "nonexistent"
        viewmodel.upload_directory(nonexistent_dir)

        # Verify: service was NOT called (validation failed early)
        mock_upload_directory.assert_not_called()

        # Verify: error signal was emitted
        error_spy.assert_called_once()
        error_msg = error_spy.call_args[0][0]
        assert "Invalid directory" in error_msg

    def test_upload_directory_validates_path_is_directory(self, mocker, tmp_path):
        """Test that ViewModel validates path is a directory (not a file)."""
        viewmodel = _create_mock_viewmodel(mocker)
        viewmodel._current_patient = _create_mock_patient("P001")

        # Create a file instead of directory
        test_file = tmp_path / "file.json"
        test_file.write_text('{"test": 1}')

        # Mock service (should not be called)
        mock_upload_directory = mocker.patch.object(viewmodel.upload_service, 'upload_directory')

        # Mock signal spy
        error_spy = Mock()
        viewmodel.error_occurred.connect(error_spy)

        # Test with file path
        viewmodel.upload_directory(test_file)

        # Verify: service was NOT called
        mock_upload_directory.assert_not_called()

        # Verify: error signal was emitted
        error_spy.assert_called_once()


class TestUploadDirectoryExceptionHandling:
    """Test exception handling in ViewModel."""

    def test_upload_directory_handles_service_exceptions(self, mocker, tmp_path):
        """Test that ViewModel handles exceptions from service gracefully."""
        viewmodel = _create_mock_viewmodel(mocker)
        viewmodel._current_patient = _create_mock_patient("P001")

        # Create test directory
        test_dir = tmp_path / "test_dir"
        test_dir.mkdir()

        # Mock service to raise exception
        mocker.patch.object(
            viewmodel.upload_service,
            'upload_directory',
            side_effect=Exception("Unexpected database error")
        )

        # Mock signal spy
        error_spy = Mock()
        viewmodel.error_occurred.connect(error_spy)

        # Test (should not raise exception)
        viewmodel.upload_directory(test_dir)

        # Verify: error signal was emitted with error details
        error_spy.assert_called_once()
        error_msg = error_spy.call_args[0][0]
        assert "Unexpected Error" in error_msg or "error occurred" in error_msg
        assert "database error" in error_msg.lower()

    def test_upload_directory_handles_file_not_found_from_service(self, mocker, tmp_path):
        """Test that ViewModel handles FileNotFoundError from service."""
        viewmodel = _create_mock_viewmodel(mocker)
        viewmodel._current_patient = _create_mock_patient("P001")

        # Create test directory
        test_dir = tmp_path / "test_dir"
        test_dir.mkdir()

        # Mock service to raise FileNotFoundError
        mocker.patch.object(
            viewmodel.upload_service,
            'upload_directory',
            side_effect=FileNotFoundError("Directory not found: /missing")
        )

        # Mock signal spy
        error_spy = Mock()
        viewmodel.error_occurred.connect(error_spy)

        # Test
        viewmodel.upload_directory(test_dir)

        # Verify: error signal emitted with appropriate message
        error_spy.assert_called_once()
        error_msg = error_spy.call_args[0][0]
        assert "Directory not found" in error_msg


class TestUploadDirectoryMessageFormatting:
    """Test message formatting for different data types."""

    def test_upload_directory_includes_all_data_types_in_success_message(self, mocker, tmp_path):
        """Test that success message includes all 4 BrainSense data types."""
        viewmodel = _create_mock_viewmodel(mocker)
        viewmodel._current_patient = _create_mock_patient("P001")

        # Create test directory
        test_dir = tmp_path / "test_dir"
        test_dir.mkdir()

        # Mock service with all data types
        mock_result = _create_directory_upload_result(
            total_files=5,
            successful_uploads=5,
            total_timeline_inserted=500,
            total_timeline_duplicates=50,
            total_snapshot_inserted=250,
            total_snapshot_duplicates=25,
            total_indefinite_streaming_inserted=100,
            total_indefinite_streaming_duplicates=10,
            total_definite_streaming_inserted=75,
            total_definite_streaming_duplicates=7
        )
        mocker.patch.object(viewmodel.upload_service, 'upload_directory', return_value=mock_result)

        # Mock signal spy
        success_spy = Mock()
        viewmodel.success_message.connect(success_spy)

        # Test
        viewmodel.upload_directory(test_dir)

        # Verify message includes all data types
        success_msg = success_spy.call_args[0][0]
        assert "Timeline" in success_msg
        assert "Snapshots" in success_msg
        assert "Indefinite Streaming" in success_msg
        assert "Definite Streaming" in success_msg

    def test_upload_directory_formats_counts_with_commas(self, mocker, tmp_path):
        """Test that large numbers are formatted with thousand separators."""
        viewmodel = _create_mock_viewmodel(mocker)
        viewmodel._current_patient = _create_mock_patient("P001")

        # Create test directory
        test_dir = tmp_path / "test_dir"
        test_dir.mkdir()

        # Mock service with large numbers
        mock_result = _create_directory_upload_result(
            total_files=100,
            successful_uploads=100,
            total_timeline_inserted=10000,
            total_timeline_duplicates=1234
        )
        mocker.patch.object(viewmodel.upload_service, 'upload_directory', return_value=mock_result)

        # Mock signal spy
        success_spy = Mock()
        viewmodel.success_message.connect(success_spy)

        # Test
        viewmodel.upload_directory(test_dir)

        # Verify numbers are formatted with commas
        success_msg = success_spy.call_args[0][0]
        assert "10,000" in success_msg
        assert "1,234" in success_msg


# Helper functions


def _create_mock_viewmodel(mocker):
    """Create a DataManagementViewModel with mocked dependencies."""
    # Mock services
    mock_patient_service = mocker.Mock()
    mock_statistics_service = mocker.Mock()
    mock_upload_service = mocker.Mock()
    mock_path_resolver = mocker.Mock()

    # Create ViewModel
    viewmodel = DataManagementViewModel(
        patient_service=mock_patient_service,
        statistics_service=mock_statistics_service,
        upload_service=mock_upload_service,
        path_resolver=mock_path_resolver
    )

    # Mock refresh_statistics and _load_upload_history to avoid errors
    viewmodel.refresh_statistics = mocker.Mock()
    viewmodel._load_upload_history = mocker.Mock()

    return viewmodel


def _create_mock_patient(patient_id: str):
    """Create a mock Patient object."""
    mock_patient = Mock()
    mock_patient.patient_id = patient_id
    return mock_patient


def _create_directory_upload_result(
    total_files=0,
    successful_uploads=0,
    failed_uploads=0,
    skipped_duplicates=0,
    total_timeline_inserted=0,
    total_timeline_duplicates=0,
    total_snapshot_inserted=0,
    total_snapshot_duplicates=0,
    total_indefinite_streaming_inserted=0,
    total_indefinite_streaming_duplicates=0,
    total_definite_streaming_inserted=0,
    total_definite_streaming_duplicates=0,
    has_errors=False
):
    """Create a DirectoryUploadResult for testing."""
    result = DirectoryUploadResult(
        total_files=total_files,
        successful_uploads=successful_uploads,
        failed_uploads=failed_uploads,
        skipped_duplicates=skipped_duplicates,
        file_results={},
        total_timeline_inserted=total_timeline_inserted,
        total_timeline_duplicates=total_timeline_duplicates,
        total_snapshot_inserted=total_snapshot_inserted,
        total_snapshot_duplicates=total_snapshot_duplicates,
        total_indefinite_streaming_inserted=total_indefinite_streaming_inserted,
        total_indefinite_streaming_duplicates=total_indefinite_streaming_duplicates,
        total_definite_streaming_inserted=total_definite_streaming_inserted,
        total_definite_streaming_duplicates=total_definite_streaming_duplicates,
        errors=[]
    )

    # Override has_errors property if needed
    if has_errors:
        result.errors = [(Path("/fake/file.json"), "Test error")]

    return result
