"""
Unit tests for UploadService.upload_directory() method.

Tests cover MVVM refactoring where file discovery logic is moved from
ViewModel to Service layer. Verifies directory upload functionality including:
    - Recursive file discovery
    - Batch upload with aggregated statistics
    - Error handling and partial failures
    - Progress callback invocation
    - Edge cases (empty directories, non-existent paths, etc.)

Author: iEEG BrainSense Development Team
Last Updated: 2025-10-15
"""

import pytest
from pathlib import Path
from unittest.mock import Mock
from src.core.models.upload_result import UploadResult


class TestUploadDirectoryBasics:
    """Test basic directory upload functionality."""

    def test_upload_directory_finds_json_files_recursively(self, tmp_path, mocker):
        """Test that upload_directory discovers JSON files in nested directories."""
        # Create test directory structure with nested JSON files
        (tmp_path / "file1.json").write_text('{"test": 1}')
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        (subdir / "file2.json").write_text('{"test": 2}')
        nested = subdir / "nested"
        nested.mkdir()
        (nested / "file3.json").write_text('{"test": 3}')

        # Create non-JSON file (should be ignored)
        (tmp_path / "readme.txt").write_text("not json")

        # Mock dependencies
        mock_service = _create_mock_upload_service(mocker)
        mock_result = _create_success_upload_result()
        mocker.patch.object(mock_service, 'upload_file', return_value=mock_result)

        # Test directory upload
        result = mock_service.upload_directory("P001", tmp_path)

        # Verify: should find exactly 3 JSON files
        assert result.total_files == 3
        assert result.successful_uploads == 3
        assert result.failed_uploads == 0

        # Verify upload_file called 3 times (once per JSON file)
        assert mock_service.upload_file.call_count == 3

    def test_upload_directory_returns_empty_result_for_no_files(self, tmp_path, mocker):
        """Test that empty directory returns DirectoryUploadResult with zero counts."""
        # Create empty directory
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()

        # Mock dependencies
        mock_service = _create_mock_upload_service(mocker)

        # Test empty directory upload
        result = mock_service.upload_directory("P001", empty_dir)

        # Verify: empty result
        assert result.total_files == 0
        assert result.successful_uploads == 0
        assert result.failed_uploads == 0
        assert result.skipped_duplicates == 0
        assert len(result.file_results) == 0
        assert len(result.errors) == 0
        assert result.success_rate == 0.0

        # Verify upload_file was never called
        mock_service.upload_file.assert_not_called()

    def test_upload_directory_validates_patient_exists(self, tmp_path, mocker):
        """Test that upload_directory raises ValueError for non-existent patient."""
        # Create test files
        (tmp_path / "file1.json").write_text('{"test": 1}')

        # Mock dependencies with patient NOT found
        mock_service = _create_mock_upload_service(mocker)
        mock_service.patient_repo.get_by_id.return_value = None

        # Test: should raise ValueError
        with pytest.raises(ValueError, match="Patient not found: INVALID_ID"):
            mock_service.upload_directory("INVALID_ID", tmp_path)


class TestUploadDirectoryErrorHandling:
    """Test error handling in directory uploads."""

    def test_upload_directory_raises_file_not_found_for_nonexistent_directory(self, mocker):
        """Test that upload_directory raises FileNotFoundError for non-existent path."""
        mock_service = _create_mock_upload_service(mocker)
        nonexistent_path = Path("/nonexistent/directory")

        with pytest.raises(FileNotFoundError, match="Directory not found"):
            mock_service.upload_directory("P001", nonexistent_path)

    def test_upload_directory_raises_not_a_directory_for_file(self, tmp_path, mocker):
        """Test that upload_directory raises NotADirectoryError when path is a file."""
        # Create a file instead of directory
        test_file = tmp_path / "file.json"
        test_file.write_text('{"test": 1}')

        mock_service = _create_mock_upload_service(mocker)

        with pytest.raises(NotADirectoryError, match="Path is not a directory"):
            mock_service.upload_directory("P001", test_file)

    def test_upload_directory_handles_partial_failures(self, tmp_path, mocker):
        """Test that partial failures are aggregated correctly (some succeed, some fail)."""
        # Create 3 test files
        (tmp_path / "file1.json").write_text('{"test": 1}')
        (tmp_path / "file2.json").write_text('{"test": 2}')
        (tmp_path / "file3.json").write_text('{"test": 3}')

        # Mock dependencies
        mock_service = _create_mock_upload_service(mocker)

        # Mock upload_file to return success for first 2, failure for last
        success_result = _create_success_upload_result(
            timeline_inserted=10, snapshot_inserted=5
        )
        failure_result = UploadResult(
            success=False,
            message="Upload failed: Parse error",
            processing_time=0.5
        )

        mock_service.upload_file.side_effect = [
            success_result,
            success_result,
            failure_result
        ]

        # Test directory upload
        result = mock_service.upload_directory("P001", tmp_path)

        # Verify: 2 successes, 1 failure
        assert result.total_files == 3
        assert result.successful_uploads == 2
        assert result.failed_uploads == 1
        assert result.total_timeline_inserted == 20  # 10 + 10
        assert result.total_snapshot_inserted == 10  # 5 + 5
        assert len(result.errors) == 1

        # Verify error details
        error_path, error_msg = result.errors[0]
        assert error_path.name == "file3.json"
        assert "Parse error" in error_msg

    def test_upload_directory_handles_complete_failure(self, tmp_path, mocker):
        """Test that all files failing is handled correctly."""
        # Create test files
        (tmp_path / "file1.json").write_text('{"test": 1}')
        (tmp_path / "file2.json").write_text('{"test": 2}')

        # Mock dependencies
        mock_service = _create_mock_upload_service(mocker)

        # Mock all uploads to fail
        failure_result = UploadResult(
            success=False,
            message="Upload failed: Invalid format",
            processing_time=0.5
        )
        mock_service.upload_file.return_value = failure_result

        # Test directory upload
        result = mock_service.upload_directory("P001", tmp_path)

        # Verify: all failed
        assert result.total_files == 2
        assert result.successful_uploads == 0
        assert result.failed_uploads == 2
        assert result.success_rate == 0.0
        assert len(result.errors) == 2
        assert result.total_timeline_inserted == 0
        assert result.total_snapshot_inserted == 0

    def test_upload_directory_handles_exceptions_during_upload(self, tmp_path, mocker):
        """Test that exceptions during individual file uploads are caught and aggregated."""
        # Create test files
        (tmp_path / "file1.json").write_text('{"test": 1}')
        (tmp_path / "file2.json").write_text('{"test": 2}')

        # Mock dependencies
        mock_service = _create_mock_upload_service(mocker)

        # Mock upload_file to raise exception
        mock_service.upload_file.side_effect = RuntimeError("Unexpected database error")

        # Test directory upload (should not raise, should catch and aggregate)
        result = mock_service.upload_directory("P001", tmp_path)

        # Verify: all failed with error tracking
        assert result.total_files == 2
        assert result.successful_uploads == 0
        assert result.failed_uploads == 2
        assert len(result.errors) == 2

        # Verify errors contain exception messages
        for error_path, error_msg in result.errors:
            assert "Unexpected database error" in error_msg

    def test_upload_directory_counts_duplicate_files_as_skipped_not_failed(self, tmp_path, mocker):
        """Already-uploaded files are skipped duplicates, NOT failures.

        Regression: an is_duplicate result must increment skipped_duplicates and
        leave failed_uploads/errors empty, so a directory of already-uploaded
        files does not look like a batch failure.
        """
        (tmp_path / "file1.json").write_text('{"test": 1}')
        (tmp_path / "file2.json").write_text('{"test": 2}')
        (tmp_path / "file3.json").write_text('{"test": 3}')

        mock_service = _create_mock_upload_service(mocker)
        mock_service.upload_file.return_value = UploadResult(
            success=False,
            message="File already uploaded: file.json on 2026-06-02 13:55:17",
            file_hash="deadbeef",
            is_duplicate=True,
            processing_time=0.01,
        )

        result = mock_service.upload_directory("P001", tmp_path)

        assert result.total_files == 3
        assert result.successful_uploads == 0
        assert result.failed_uploads == 0          # NOT counted as failures
        assert result.skipped_duplicates == 3       # counted as skipped
        assert result.has_errors is False
        assert result.errors == []


class TestUploadDirectoryStatistics:
    """Test aggregated statistics calculation."""

    def test_upload_directory_aggregates_timeline_statistics(self, tmp_path, mocker):
        """Test that timeline counts are summed across all files."""
        # Create test files
        (tmp_path / "file1.json").write_text('{"test": 1}')
        (tmp_path / "file2.json").write_text('{"test": 2}')
        (tmp_path / "file3.json").write_text('{"test": 3}')

        # Mock dependencies
        mock_service = _create_mock_upload_service(mocker)

        # Mock upload_file with different timeline counts
        results = [
            _create_success_upload_result(timeline_inserted=100, timeline_duplicates=10),
            _create_success_upload_result(timeline_inserted=200, timeline_duplicates=20),
            _create_success_upload_result(timeline_inserted=150, timeline_duplicates=15),
        ]
        mock_service.upload_file.side_effect = results

        # Test directory upload
        result = mock_service.upload_directory("P001", tmp_path)

        # Verify aggregated timeline statistics
        assert result.total_timeline_inserted == 450  # 100 + 200 + 150
        assert result.total_timeline_duplicates == 45  # 10 + 20 + 15

    def test_upload_directory_aggregates_all_data_types(self, tmp_path, mocker):
        """Test that all 4 BrainSense data types are aggregated correctly."""
        # Create test files
        (tmp_path / "file1.json").write_text('{"test": 1}')
        (tmp_path / "file2.json").write_text('{"test": 2}')

        # Mock dependencies
        mock_service = _create_mock_upload_service(mocker)

        # Mock upload_file with data from all types
        mock_result = UploadResult(
            success=True,
            message="Success",
            timeline_inserted=100,
            timeline_duplicates=10,
            snapshot_inserted=50,
            snapshot_duplicates=5,
            indefinite_streaming_inserted=25,
            indefinite_streaming_duplicates=2,
            definite_streaming_inserted=15,
            definite_streaming_duplicates=1,
            total_duplicates=18,
            processing_time=1.5
        )
        mock_service.upload_file.return_value = mock_result

        # Test directory upload
        result = mock_service.upload_directory("P001", tmp_path)

        # Verify all data types aggregated
        assert result.total_timeline_inserted == 200  # 100 * 2
        assert result.total_timeline_duplicates == 20
        assert result.total_snapshot_inserted == 100  # 50 * 2
        assert result.total_snapshot_duplicates == 10
        assert result.total_indefinite_streaming_inserted == 50  # 25 * 2
        assert result.total_indefinite_streaming_duplicates == 4
        assert result.total_definite_streaming_inserted == 30  # 15 * 2
        assert result.total_definite_streaming_duplicates == 2

    def test_upload_directory_tracks_per_file_results(self, tmp_path, mocker):
        """Test that individual file results are stored in file_results dict."""
        # Create test files
        file1 = tmp_path / "file1.json"
        file2 = tmp_path / "file2.json"
        file1.write_text('{"test": 1}')
        file2.write_text('{"test": 2}')

        # Mock dependencies
        mock_service = _create_mock_upload_service(mocker)

        # Mock different results for each file
        result1 = _create_success_upload_result(timeline_inserted=100)
        result2 = _create_success_upload_result(timeline_inserted=200)
        mock_service.upload_file.side_effect = [result1, result2]

        # Test directory upload
        result = mock_service.upload_directory("P001", tmp_path)

        # Verify file_results dict contains entries for both files
        assert len(result.file_results) == 2
        assert file1 in result.file_results or any(p.name == "file1.json" for p in result.file_results.keys())
        assert file2 in result.file_results or any(p.name == "file2.json" for p in result.file_results.keys())


class TestUploadDirectoryProgressCallback:
    """Test progress callback functionality."""

    def test_upload_directory_invokes_progress_callback(self, tmp_path, mocker):
        """Test that progress callback is invoked with correct arguments."""
        # Create test files
        (tmp_path / "file1.json").write_text('{"test": 1}')
        (tmp_path / "file2.json").write_text('{"test": 2}')
        (tmp_path / "file3.json").write_text('{"test": 3}')

        # Mock dependencies
        mock_service = _create_mock_upload_service(mocker)
        mock_service.upload_file.return_value = _create_success_upload_result()

        # Mock progress callback
        progress_callback = Mock()

        # Test directory upload with callback
        result = mock_service.upload_directory("P001", tmp_path, progress_callback=progress_callback)

        # Verify: callback called 3 times (once per file)
        assert progress_callback.call_count == 3

        # Verify callback arguments: (current, total)
        progress_callback.assert_any_call(1, 3)
        progress_callback.assert_any_call(2, 3)
        progress_callback.assert_any_call(3, 3)

    def test_upload_directory_without_progress_callback(self, tmp_path, mocker):
        """Test that upload works when no progress callback is provided."""
        # Create test files
        (tmp_path / "file1.json").write_text('{"test": 1}')

        # Mock dependencies
        mock_service = _create_mock_upload_service(mocker)
        mock_service.upload_file.return_value = _create_success_upload_result()

        # Test directory upload without callback (should not raise)
        result = mock_service.upload_directory("P001", tmp_path, progress_callback=None)

        # Verify: works correctly
        assert result.total_files == 1
        assert result.successful_uploads == 1


class TestUploadDirectoryResultProperties:
    """Test DirectoryUploadResult helper properties."""

    def test_directory_upload_result_success_rate(self, tmp_path, mocker):
        """Test success_rate property calculation."""
        # Create test files
        (tmp_path / "file1.json").write_text('{"test": 1}')
        (tmp_path / "file2.json").write_text('{"test": 2}')
        (tmp_path / "file3.json").write_text('{"test": 3}')
        (tmp_path / "file4.json").write_text('{"test": 4}')

        # Mock dependencies
        mock_service = _create_mock_upload_service(mocker)

        # Mock 3 successes, 1 failure
        success = _create_success_upload_result()
        failure = UploadResult(success=False, message="Failed", processing_time=0.5)
        mock_service.upload_file.side_effect = [success, success, success, failure]

        # Test directory upload
        result = mock_service.upload_directory("P001", tmp_path)

        # Verify success rate: 3/4 = 75%
        assert result.success_rate == 75.0
        assert result.has_errors is True

    def test_directory_upload_result_has_errors_property(self, tmp_path, mocker):
        """Test has_errors property."""
        # Create test files
        (tmp_path / "file1.json").write_text('{"test": 1}')

        # Mock dependencies
        mock_service = _create_mock_upload_service(mocker)

        # Test 1: All success (no errors)
        mock_service.upload_file.return_value = _create_success_upload_result()
        result_success = mock_service.upload_directory("P001", tmp_path)
        assert result_success.has_errors is False

        # Test 2: With errors
        mock_service.upload_file.return_value = UploadResult(
            success=False, message="Failed", processing_time=0.5
        )
        result_error = mock_service.upload_directory("P001", tmp_path)
        assert result_error.has_errors is True


# Helper functions for creating mocks


def _create_mock_upload_service(mocker):
    """Create a mock UploadService with basic dependencies."""
    from src.core.services.upload_service import UploadService as UploadServiceClass

    mock_service = mocker.Mock(spec=UploadServiceClass)

    # Mock patient_repo
    mock_patient_repo = mocker.Mock()
    mock_patient = mocker.Mock()
    mock_patient.patient_id = "P001"
    mock_patient_repo.get_by_id.return_value = mock_patient
    mock_service.patient_repo = mock_patient_repo

    # Bind the real upload_directory method to the mock
    # (We want to test the real method, just with mocked dependencies)
    mock_service.upload_directory = UploadServiceClass.upload_directory.__get__(mock_service, UploadServiceClass)

    return mock_service


def _create_success_upload_result(
    timeline_inserted=10,
    timeline_duplicates=2,
    snapshot_inserted=5,
    snapshot_duplicates=1,
    indefinite_streaming_inserted=0,
    indefinite_streaming_duplicates=0,
    definite_streaming_inserted=0,
    definite_streaming_duplicates=0
):
    """Create a successful UploadResult for testing."""
    return UploadResult(
        success=True,
        message="Upload successful",
        timeline_inserted=timeline_inserted,
        timeline_duplicates=timeline_duplicates,
        snapshot_inserted=snapshot_inserted,
        snapshot_duplicates=snapshot_duplicates,
        indefinite_streaming_inserted=indefinite_streaming_inserted,
        indefinite_streaming_duplicates=indefinite_streaming_duplicates,
        definite_streaming_inserted=definite_streaming_inserted,
        definite_streaming_duplicates=definite_streaming_duplicates,
        total_duplicates=timeline_duplicates + snapshot_duplicates +
                        indefinite_streaming_duplicates + definite_streaming_duplicates,
        processing_time=1.0
    )
