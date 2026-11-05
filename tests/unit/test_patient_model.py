"""
Unit tests for Patient model.

Tests the Patient dataclass including immutability, properties,
and type correctness.
"""

import pytest
from pathlib import Path
from datetime import datetime
from dataclasses import FrozenInstanceError

from src.core.models.patient import Patient


@pytest.fixture
def sample_patient_data():
    """Sample patient data for testing."""
    return {
        'patient_id': 'PATIENT001',
        'patient_name': 'John Doe',
        'data_directory': Path('/data/patients/PATIENT001'),
        'database_path': Path('/data/patients/PATIENT001/brainsense_data.db'),
        'created_at': datetime(2025, 9, 30, 12, 0, 0),
        'updated_at': datetime(2025, 9, 30, 12, 0, 0),
        'is_active': True,
        'metadata': {'diagnosis': 'Parkinson\'s Disease'}
    }


@pytest.fixture
def sample_patient(sample_patient_data):
    """Sample Patient instance for testing."""
    return Patient(**sample_patient_data)


class TestPatientModel:
    """Test Patient model functionality."""

    def test_patient_creation(self, sample_patient_data):
        """Test creating a Patient instance with all fields."""
        patient = Patient(**sample_patient_data)

        assert patient.patient_id == 'PATIENT001'
        assert patient.patient_name == 'John Doe'
        assert patient.data_directory == Path('/data/patients/PATIENT001')
        assert patient.database_path == Path('/data/patients/PATIENT001/brainsense_data.db')
        assert patient.created_at == datetime(2025, 9, 30, 12, 0, 0)
        assert patient.updated_at == datetime(2025, 9, 30, 12, 0, 0)
        assert patient.is_active is True
        assert patient.metadata == {'diagnosis': 'Parkinson\'s Disease'}

    def test_patient_immutability(self, sample_patient):
        """Test that Patient instances are immutable (frozen=True)."""
        with pytest.raises(FrozenInstanceError):
            sample_patient.patient_name = "Jane Doe"

        with pytest.raises(FrozenInstanceError):
            sample_patient.is_active = False

    def test_patient_str_representation(self, sample_patient):
        """Test __str__() format."""
        result = str(sample_patient)
        assert result == "Patient(PATIENT001: John Doe)"
        assert "PATIENT001" in result
        assert "John Doe" in result

    def test_patient_display_name(self, sample_patient):
        """Test display_name property returns patient_name."""
        assert sample_patient.display_name == "John Doe"
        assert sample_patient.display_name == sample_patient.patient_name

    def test_patient_with_metadata(self):
        """Test creating patient with metadata dict."""
        metadata = {
            'diagnosis': 'Essential Tremor',
            'age': 65,
            'notes': 'Sample notes'
        }
        patient = Patient(
            patient_id='TEST001',
            patient_name='Test Patient',
            data_directory=Path('/data/test'),
            database_path=Path('/data/test/db.db'),
            created_at=datetime.now(),
            updated_at=datetime.now(),
            metadata=metadata
        )

        assert patient.metadata == metadata
        assert patient.metadata['diagnosis'] == 'Essential Tremor'

    def test_patient_without_metadata(self):
        """Test creating patient without metadata (defaults to None)."""
        patient = Patient(
            patient_id='TEST002',
            patient_name='Test Patient 2',
            data_directory=Path('/data/test2'),
            database_path=Path('/data/test2/db.db'),
            created_at=datetime.now(),
            updated_at=datetime.now()
        )

        assert patient.metadata is None

    def test_patient_inactive(self):
        """Test creating inactive patient (soft delete flag)."""
        patient = Patient(
            patient_id='INACTIVE001',
            patient_name='Inactive Patient',
            data_directory=Path('/data/inactive'),
            database_path=Path('/data/inactive/db.db'),
            created_at=datetime.now(),
            updated_at=datetime.now(),
            is_active=False
        )

        assert patient.is_active is False

    def test_patient_active_default(self):
        """Test that is_active defaults to True."""
        patient = Patient(
            patient_id='DEFAULT001',
            patient_name='Default Patient',
            data_directory=Path('/data/default'),
            database_path=Path('/data/default/db.db'),
            created_at=datetime.now(),
            updated_at=datetime.now()
        )

        assert patient.is_active is True

    def test_patient_equality(self):
        """Test that two patients with same data are equal."""
        data = {
            'patient_id': 'EQUAL001',
            'patient_name': 'Equal Patient',
            'data_directory': Path('/data/equal'),
            'database_path': Path('/data/equal/db.db'),
            'created_at': datetime(2025, 1, 1, 0, 0, 0),
            'updated_at': datetime(2025, 1, 1, 0, 0, 0),
        }

        patient1 = Patient(**data)
        patient2 = Patient(**data)

        assert patient1 == patient2

    def test_patient_hashing(self):
        """Test that Patient without metadata can be used in sets and dicts (hashable)."""
        # Patient without metadata (None) is hashable
        patient = Patient(
            patient_id='HASH001',
            patient_name='Hash Patient',
            data_directory=Path('/data/hash'),
            database_path=Path('/data/hash/db.db'),
            created_at=datetime(2025, 1, 1, 0, 0, 0),
            updated_at=datetime(2025, 1, 1, 0, 0, 0),
            metadata=None  # None is hashable
        )

        # Should be able to add to set
        patient_set = {patient}
        assert patient in patient_set

        # Should be able to use as dict key
        patient_dict = {patient: "some_value"}
        assert patient_dict[patient] == "some_value"

    def test_patient_type_hints(self, sample_patient):
        """Test that types are correct."""
        assert isinstance(sample_patient.patient_id, str)
        assert isinstance(sample_patient.patient_name, str)
        assert isinstance(sample_patient.data_directory, Path)
        assert isinstance(sample_patient.database_path, Path)
        assert isinstance(sample_patient.created_at, datetime)
        assert isinstance(sample_patient.updated_at, datetime)
        assert isinstance(sample_patient.is_active, bool)
        assert sample_patient.metadata is None or isinstance(sample_patient.metadata, dict)

    def test_patient_repr(self, sample_patient):
        """Test __repr__() (auto-generated by dataclass)."""
        repr_str = repr(sample_patient)
        assert 'Patient' in repr_str
        assert 'PATIENT001' in repr_str
