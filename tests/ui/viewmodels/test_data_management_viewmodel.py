"""
Tests for DataManagementViewModel.

Tests the ViewModel logic, signal emissions, and coordination with services.
Uses mocked services to isolate ViewModel behavior.

Author: iEEG BrainSense Development Team
Last Updated: 2025-10-01
"""

import pytest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock

from src.ui.viewmodels import DataManagementViewModel
from src.core.models import Patient, PatientStatistics, UploadedFile


@pytest.fixture
def mock_patient_service():
    """Create mock PatientService."""
    service = Mock()
    service.get_all_active_patients = Mock(return_value=[])
    service.get_patient = Mock(return_value=None)
    service.create_patient = Mock(return_value=None)
    service.update_patient = Mock(return_value=None)
    service.delete_patient = Mock(return_value=False)
    return service


@pytest.fixture
def mock_statistics_service():
    """Create mock StatisticsService."""
    service = Mock()
    service.get_patient_statistics = Mock(return_value=None)
    return service


@pytest.fixture
def mock_upload_service():
    """Create mock UploadService."""
    service = Mock()
    service.get_upload_history = Mock(return_value=[])
    return service


@pytest.fixture
def mock_path_resolver():
    """Create mock PathResolver."""
    resolver = Mock()
    return resolver


@pytest.fixture
def viewmodel(mock_patient_service, mock_statistics_service, mock_upload_service, mock_path_resolver):
    """Create DataManagementViewModel with mocked services."""
    return DataManagementViewModel(
        mock_patient_service,
        mock_statistics_service,
        mock_upload_service,
        mock_path_resolver
    )


@pytest.fixture
def sample_patient():
    """Create a sample Patient object for testing."""
    return Patient(
        patient_id="PATIENT001",
        patient_name="John Doe",
        data_directory=Path("/data/patients/PATIENT001"),
        database_path=Path("/data/patients/PATIENT001/brainsense_data.db"),
        created_at=datetime.now(),
        updated_at=datetime.now(),
        is_active=True,
        metadata={"age": 65}
    )


@pytest.fixture
def sample_statistics():
    """Create sample PatientStatistics for testing."""
    return PatientStatistics(
        patient_id="PATIENT001",
        snapshots_original=100,
        snapshots_deduplicated=80,
        timeline_original=200,
        timeline_deduplicated=150,
        total_files_uploaded=5,
        total_duplicates_skipped=70,
        last_upload_date=datetime.now(),
        last_calculated=datetime.now()
    )


# ============================================================================
# Initialization Tests
# ============================================================================

def test_viewmodel_initialization(viewmodel, mock_patient_service, mock_statistics_service, mock_upload_service, mock_path_resolver):
    """Test ViewModel initializes with correct services."""
    assert viewmodel.patient_service == mock_patient_service
    assert viewmodel.statistics_service == mock_statistics_service
    assert viewmodel.upload_service == mock_upload_service
    assert viewmodel.path_resolver == mock_path_resolver
    assert viewmodel.current_patient is None


def test_viewmodel_has_all_signals(viewmodel):
    """Test ViewModel defines all required signals."""
    # Check that all signals exist
    assert hasattr(viewmodel, 'patients_loaded')
    assert hasattr(viewmodel, 'patient_selected')
    assert hasattr(viewmodel, 'patient_cleared')
    assert hasattr(viewmodel, 'statistics_updated')
    assert hasattr(viewmodel, 'upload_history_updated')
    assert hasattr(viewmodel, 'error_occurred')
    assert hasattr(viewmodel, 'success_message')


# ============================================================================
# load_patients Tests
# ============================================================================

def test_load_patients_success(viewmodel, mock_patient_service, sample_patient):
    """Test loading patients successfully."""
    # Setup
    patients = [sample_patient]
    mock_patient_service.get_all_active_patients.return_value = patients

    # Create signal spy
    signal_spy = Mock()
    viewmodel.patients_loaded.connect(signal_spy)

    # Execute
    viewmodel.load_patients()

    # Verify
    mock_patient_service.get_all_active_patients.assert_called_once()
    signal_spy.assert_called_once_with(patients)


def test_load_patients_empty_list(viewmodel, mock_patient_service):
    """Test loading patients when none exist."""
    # Setup
    mock_patient_service.get_all_active_patients.return_value = []

    # Create signal spy
    signal_spy = Mock()
    viewmodel.patients_loaded.connect(signal_spy)

    # Execute
    viewmodel.load_patients()

    # Verify
    signal_spy.assert_called_once_with([])


def test_load_patients_error(viewmodel, mock_patient_service):
    """Test loading patients when service raises error."""
    # Setup
    mock_patient_service.get_all_active_patients.side_effect = Exception("Database error")

    # Create signal spies
    error_spy = Mock()
    viewmodel.error_occurred.connect(error_spy)

    # Execute
    viewmodel.load_patients()

    # Verify error signal emitted
    error_spy.assert_called_once()
    error_message = error_spy.call_args[0][0]
    assert "Failed to load patients" in error_message


# ============================================================================
# select_patient Tests
# ============================================================================

def test_select_patient_success(viewmodel, mock_patient_service, mock_statistics_service, sample_patient, sample_statistics):
    """Test selecting a patient successfully."""
    # Setup
    mock_patient_service.get_patient.return_value = sample_patient
    mock_statistics_service.get_patient_statistics.return_value = sample_statistics

    # Create signal spies
    patient_spy = Mock()
    stats_spy = Mock()
    viewmodel.patient_selected.connect(patient_spy)
    viewmodel.statistics_updated.connect(stats_spy)

    # Execute
    viewmodel.select_patient("PATIENT001")

    # Verify
    mock_patient_service.get_patient.assert_called_once_with("PATIENT001")
    mock_statistics_service.get_patient_statistics.assert_called_once_with("PATIENT001")
    patient_spy.assert_called_once_with(sample_patient)
    stats_spy.assert_called_once_with(sample_statistics)
    assert viewmodel.current_patient == sample_patient


def test_select_patient_not_found(viewmodel, mock_patient_service):
    """Test selecting a patient that doesn't exist."""
    # Setup
    mock_patient_service.get_patient.return_value = None

    # Create signal spies
    error_spy = Mock()
    patient_spy = Mock()
    viewmodel.error_occurred.connect(error_spy)
    viewmodel.patient_selected.connect(patient_spy)

    # Execute
    viewmodel.select_patient("NONEXISTENT")

    # Verify
    error_spy.assert_called_once()
    error_message = error_spy.call_args[0][0]
    assert "not found" in error_message.lower()
    patient_spy.assert_not_called()
    assert viewmodel.current_patient is None


def test_select_patient_statistics_error(viewmodel, mock_patient_service, mock_statistics_service, sample_patient):
    """Test selecting patient when statistics loading fails."""
    # Setup
    mock_patient_service.get_patient.return_value = sample_patient
    mock_statistics_service.get_patient_statistics.side_effect = Exception("Stats error")

    # Create signal spies
    error_spy = Mock()
    viewmodel.error_occurred.connect(error_spy)

    # Execute
    viewmodel.select_patient("PATIENT001")

    # Verify patient still selected but error emitted
    assert viewmodel.current_patient == sample_patient
    error_spy.assert_called()


def test_select_patient_no_statistics(viewmodel, mock_patient_service, mock_statistics_service, sample_patient):
    """Test selecting patient with no statistics (new patient)."""
    # Setup
    mock_patient_service.get_patient.return_value = sample_patient
    mock_statistics_service.get_patient_statistics.return_value = None

    # Create signal spies
    stats_spy = Mock()
    viewmodel.statistics_updated.connect(stats_spy)

    # Execute
    viewmodel.select_patient("PATIENT001")

    # Verify empty statistics created and emitted
    stats_spy.assert_called_once()
    stats = stats_spy.call_args[0][0]
    assert stats.patient_id == "PATIENT001"
    assert stats.total_files_uploaded == 0
    assert stats.snapshots_deduplicated == 0


# ============================================================================
# clear_patient_selection Tests
# ============================================================================

def test_clear_patient_selection(viewmodel, sample_patient):
    """Test clearing patient selection."""
    # Setup - select a patient first
    viewmodel._current_patient = sample_patient

    # Create signal spy
    clear_spy = Mock()
    viewmodel.patient_cleared.connect(clear_spy)

    # Execute
    viewmodel.clear_patient_selection()

    # Verify
    assert viewmodel.current_patient is None
    clear_spy.assert_called_once()


# ============================================================================
# create_patient Tests
# ============================================================================

def test_create_patient_success(viewmodel, mock_patient_service, sample_patient):
    """Test creating a new patient successfully."""
    # Setup
    mock_patient_service.generate_patient_id.return_value = "JOHN_DOE_20251015143022"
    mock_patient_service.create_patient.return_value = sample_patient
    mock_patient_service.get_patient.return_value = sample_patient
    mock_patient_service.get_all_active_patients.return_value = [sample_patient]

    # Create signal spies
    success_spy = Mock()
    patients_spy = Mock()
    patient_spy = Mock()
    viewmodel.success_message.connect(success_spy)
    viewmodel.patients_loaded.connect(patients_spy)
    viewmodel.patient_selected.connect(patient_spy)

    # Execute
    viewmodel.create_patient("John Doe")

    # Verify ID generation delegation
    mock_patient_service.generate_patient_id.assert_called_once_with("John Doe")

    # Verify patient creation with generated ID
    mock_patient_service.create_patient.assert_called_once_with(
        patient_id="JOHN_DOE_20251015143022",
        patient_name="John Doe",
        metadata=None
    )

    success_spy.assert_called_once()
    patients_spy.assert_called_once()  # Reload patients
    patient_spy.assert_called_once()  # Auto-select new patient


def test_create_patient_empty_name(viewmodel, mock_patient_service):
    """Test creating patient with empty name."""
    # Create signal spies
    error_spy = Mock()
    viewmodel.error_occurred.connect(error_spy)

    # Execute
    viewmodel.create_patient("")

    # Verify
    error_spy.assert_called_once()
    error_message = error_spy.call_args[0][0]
    assert "empty" in error_message.lower()
    mock_patient_service.create_patient.assert_not_called()


def test_create_patient_whitespace_name(viewmodel, mock_patient_service):
    """Test creating patient with whitespace-only name."""
    # Create signal spies
    error_spy = Mock()
    viewmodel.error_occurred.connect(error_spy)

    # Execute
    viewmodel.create_patient("   ")

    # Verify
    error_spy.assert_called_once()
    mock_patient_service.create_patient.assert_not_called()


def test_create_patient_service_error(viewmodel, mock_patient_service):
    """Test creating patient when service raises error."""
    # Setup
    mock_patient_service.generate_patient_id.return_value = "JOHN_DOE_20251015143022"
    mock_patient_service.create_patient.side_effect = Exception("Creation failed")

    # Create signal spies
    error_spy = Mock()
    viewmodel.error_occurred.connect(error_spy)

    # Execute
    viewmodel.create_patient("John Doe")

    # Verify
    error_spy.assert_called_once()
    error_message = error_spy.call_args[0][0]
    assert "Failed to create patient" in error_message


def test_create_patient_delegates_id_generation(viewmodel, mock_patient_service):
    """Test ViewModel delegates ID generation to service."""
    # Setup
    generated_id = "JANE_DOE_20251015150000"
    mock_patient_service.generate_patient_id.return_value = generated_id
    mock_patient_service.create_patient.return_value = Patient(
        patient_id=generated_id,
        patient_name="Jane Doe",
        data_directory=Path("/data/patients/JANE_DOE_20251015150000"),
        database_path=Path("/data/patients/JANE_DOE_20251015150000/brainsense_data.db"),
        created_at=datetime.now(),
        updated_at=datetime.now(),
        is_active=True
    )
    mock_patient_service.get_patient.return_value = mock_patient_service.create_patient.return_value
    mock_patient_service.get_all_active_patients.return_value = [mock_patient_service.create_patient.return_value]

    # Execute
    viewmodel.create_patient("Jane Doe")

    # Verify delegation
    mock_patient_service.generate_patient_id.assert_called_once_with("Jane Doe")

    # Verify generated ID is used
    create_call_args = mock_patient_service.create_patient.call_args
    assert create_call_args.kwargs['patient_id'] == generated_id


# ============================================================================
# update_patient Tests
# ============================================================================

def test_update_patient_success(viewmodel, mock_patient_service, sample_patient):
    """Test updating a patient successfully."""
    # Setup
    updated_patient = Patient(
        patient_id="PATIENT001",
        patient_name="Jane Doe",  # Updated name
        data_directory=sample_patient.data_directory,
        database_path=sample_patient.database_path,
        created_at=sample_patient.created_at,
        updated_at=datetime.now(),
        is_active=True
    )
    mock_patient_service.update_patient.return_value = updated_patient
    mock_patient_service.get_patient.return_value = updated_patient
    mock_patient_service.get_all_active_patients.return_value = [updated_patient]

    # Create signal spies
    success_spy = Mock()
    patients_spy = Mock()
    patient_spy = Mock()
    viewmodel.success_message.connect(success_spy)
    viewmodel.patients_loaded.connect(patients_spy)
    viewmodel.patient_selected.connect(patient_spy)

    # Execute
    viewmodel.update_patient("PATIENT001", "Jane Doe")

    # Verify
    mock_patient_service.update_patient.assert_called_once_with(
        patient_id="PATIENT001",
        patient_name="Jane Doe",
        metadata=None
    )
    success_spy.assert_called_once()
    patients_spy.assert_called_once()  # Reload patients
    patient_spy.assert_called_once()  # Re-select patient


def test_update_patient_empty_name(viewmodel, mock_patient_service):
    """Test updating patient with empty name."""
    # Create signal spies
    error_spy = Mock()
    viewmodel.error_occurred.connect(error_spy)

    # Execute
    viewmodel.update_patient("PATIENT001", "")

    # Verify
    error_spy.assert_called_once()
    mock_patient_service.update_patient.assert_not_called()


def test_update_patient_not_found(viewmodel, mock_patient_service):
    """Test updating patient that doesn't exist."""
    # Setup
    mock_patient_service.update_patient.return_value = None

    # Create signal spies
    error_spy = Mock()
    viewmodel.error_occurred.connect(error_spy)

    # Execute
    viewmodel.update_patient("NONEXISTENT", "Jane Doe")

    # Verify
    error_spy.assert_called_once()
    error_message = error_spy.call_args[0][0]
    assert "not found" in error_message.lower()


# ============================================================================
# delete_patient Tests
# ============================================================================

def test_delete_patient_success(viewmodel, mock_patient_service):
    """Test deleting a patient successfully."""
    # Setup
    mock_patient_service.delete_patient.return_value = True
    mock_patient_service.get_all_active_patients.return_value = []

    # Create signal spies
    success_spy = Mock()
    patients_spy = Mock()
    viewmodel.success_message.connect(success_spy)
    viewmodel.patients_loaded.connect(patients_spy)

    # Execute
    viewmodel.delete_patient("PATIENT001")

    # Verify
    mock_patient_service.delete_patient.assert_called_once_with("PATIENT001")
    success_spy.assert_called_once()
    patients_spy.assert_called_once()  # Reload patients


def test_delete_patient_not_found(viewmodel, mock_patient_service):
    """Test deleting patient that doesn't exist."""
    # Setup
    mock_patient_service.delete_patient.return_value = False

    # Create signal spies
    error_spy = Mock()
    viewmodel.error_occurred.connect(error_spy)

    # Execute
    viewmodel.delete_patient("NONEXISTENT")

    # Verify
    error_spy.assert_called_once()
    error_message = error_spy.call_args[0][0]
    assert "not found" in error_message.lower()


def test_delete_patient_clears_current_selection(viewmodel, sample_patient):
    """Test deleting the currently selected patient clears selection."""
    # Setup - select a patient first
    viewmodel._current_patient = sample_patient
    viewmodel.patient_service.delete_patient.return_value = True

    # Create signal spies
    clear_spy = Mock()
    viewmodel.patient_cleared.connect(clear_spy)

    # Execute
    viewmodel.delete_patient("PATIENT001")

    # Verify
    assert viewmodel.current_patient is None
    clear_spy.assert_called_once()


def test_delete_patient_different_from_selection(viewmodel, sample_patient):
    """Test deleting a different patient doesn't clear selection."""
    # Setup - select a patient
    viewmodel._current_patient = sample_patient
    viewmodel.patient_service.delete_patient.return_value = True

    # Create signal spies
    clear_spy = Mock()
    viewmodel.patient_cleared.connect(clear_spy)

    # Execute - delete a different patient
    viewmodel.delete_patient("PATIENT002")

    # Verify current patient unchanged
    assert viewmodel.current_patient == sample_patient
    clear_spy.assert_not_called()


# ============================================================================
# refresh_statistics Tests
# ============================================================================

def test_refresh_statistics_success(viewmodel, mock_statistics_service, sample_patient, sample_statistics):
    """Test refreshing statistics for selected patient."""
    # Setup - select a patient first
    viewmodel._current_patient = sample_patient
    mock_statistics_service.get_patient_statistics.return_value = sample_statistics

    # Create signal spy
    stats_spy = Mock()
    viewmodel.statistics_updated.connect(stats_spy)

    # Execute
    viewmodel.refresh_statistics()

    # Verify
    mock_statistics_service.get_patient_statistics.assert_called_once_with("PATIENT001")
    stats_spy.assert_called_once_with(sample_statistics)


def test_refresh_statistics_no_patient_selected(viewmodel):
    """Test refreshing statistics when no patient selected."""
    # Create signal spies
    error_spy = Mock()
    viewmodel.error_occurred.connect(error_spy)

    # Execute
    viewmodel.refresh_statistics()

    # Verify
    error_spy.assert_called_once()
    error_message = error_spy.call_args[0][0]
    assert "No patient selected" in error_message


# ============================================================================
# Integration Tests
# ============================================================================

def test_complete_workflow_create_select_update_delete(viewmodel, mock_patient_service, mock_statistics_service, sample_patient):
    """Test complete workflow: create -> select -> update -> delete."""
    # Setup mocks
    mock_patient_service.create_patient.return_value = sample_patient
    mock_patient_service.get_patient.return_value = sample_patient
    mock_patient_service.get_all_active_patients.return_value = [sample_patient]
    mock_patient_service.update_patient.return_value = sample_patient
    mock_patient_service.delete_patient.return_value = True

    # Step 1: Create patient
    viewmodel.create_patient("John Doe")
    assert viewmodel.current_patient is not None

    # Step 2: Update patient
    viewmodel.update_patient("PATIENT001", "Jane Doe")
    assert viewmodel.current_patient is not None

    # Step 3: Delete patient
    viewmodel.delete_patient("PATIENT001")
    assert viewmodel.current_patient is None


def test_signal_emission_sequence(viewmodel, mock_patient_service, sample_patient):
    """Test that signals are emitted in correct sequence."""
    # Setup
    mock_patient_service.create_patient.return_value = sample_patient
    mock_patient_service.get_patient.return_value = sample_patient
    mock_patient_service.get_all_active_patients.return_value = [sample_patient]

    # Track signal emissions
    signal_order = []

    def track_signal(signal_name):
        signal_order.append(signal_name)

    viewmodel.success_message.connect(lambda msg: track_signal('success'))
    viewmodel.patients_loaded.connect(lambda p: track_signal('patients_loaded'))
    viewmodel.patient_selected.connect(lambda p: track_signal('patient_selected'))

    # Execute
    viewmodel.create_patient("John Doe")

    # Verify signal order: success -> patients_loaded -> patient_selected
    assert signal_order == ['success', 'patients_loaded', 'patient_selected']


def test_select_patient_loads_upload_history(viewmodel, mock_patient_service, mock_statistics_service, mock_upload_service, sample_patient, sample_statistics, qtbot):
    """Test selecting a patient loads their upload history."""
    # Setup
    mock_patient_service.get_patient.return_value = sample_patient
    mock_statistics_service.get_patient_statistics.return_value = sample_statistics

    sample_upload = UploadedFile(
        file_id=1,
        patient_id="PATIENT001",
        file_name="test.json",
        file_path=Path("/data/test.json"),
        file_hash="abc123",
        file_size_bytes=1024,
        timeline_count=100,
        timeline_original_count=110,
        snapshot_count=50,
        snapshot_original_count=55,
        indefinite_streaming_count=0,
        indefinite_streaming_original_count=0,
        definite_streaming_count=0,
        definite_streaming_original_count=0,
        duplicates_skipped=15,
        outliers_detected=0,
        processing_time_seconds=1.5,
        extractor_version="1.0.0",
        processing_settings=None,
        errors_encountered=0,
        error_details=None,
        processed_at=datetime.now()
    )
    mock_upload_service.get_upload_history.return_value = [sample_upload]

    # Track signals
    history_signals = []
    viewmodel.upload_history_updated.connect(history_signals.append)

    # Execute
    viewmodel.select_patient("PATIENT001")

    # Verify upload history loaded
    mock_upload_service.get_upload_history.assert_called_once_with("PATIENT001")
    assert len(history_signals) == 1
    assert len(history_signals[0]) == 1
    assert history_signals[0][0].file_name == "test.json"
