"""
Tests for AnnotationService.

Tests the annotation service business logic, including:
- Creating, updating, and deleting annotations
- Validation of annotation fields
- Import/export functionality (CSV and JSON)
- Template-based annotation creation
- Filtering annotations by type

Author: iEEG BrainSense Development Team
Last Updated: 2025-10-07
"""

import pytest
import csv
import json
from pathlib import Path
from datetime import datetime
from unittest.mock import Mock

from src.core.services.annotation_service import AnnotationService
from src.core.models import Annotation
from src.infrastructure.repositories.annotation_repository import AnnotationRepository


@pytest.fixture
def sample_annotation():
    """Create a sample annotation."""
    return Annotation(
        id="ann_001",
        recording_id="rec_001",
        timestamp_seconds=498.5,
        annotation_type="symptom",
        label="Tremor onset",
        description="Patient just woke up",
        severity=7,
        metadata={},
        created_at=datetime.now(),
        updated_at=datetime.now()
    )


@pytest.fixture
def mock_repository():
    """Create mock AnnotationRepository."""
    return Mock(spec=AnnotationRepository)


@pytest.fixture
def annotation_service(mock_repository):
    """Create AnnotationService instance with mocked repository."""
    return AnnotationService(mock_repository)


# ============================================================================
# Initialization Tests
# ============================================================================

def test_annotation_service_initialization(mock_repository):
    """Test AnnotationService initializes with correct dependencies."""
    service = AnnotationService(mock_repository)
    assert service.repository == mock_repository


# ============================================================================
# create_annotation Tests
# ============================================================================

def test_create_annotation_success(annotation_service, mock_repository, sample_annotation):
    """Test successful annotation creation."""
    # Setup
    mock_repository.create.return_value = sample_annotation

    # Execute
    annotation = annotation_service.create_annotation(
        patient_id="P01",
        recording_id="rec_001",
        timestamp=498.5,
        annotation_type="symptom",
        label="Tremor onset",
        description="Patient just woke up",
        severity=7
    )

    # Verify
    assert annotation.recording_id == "rec_001"
    assert annotation.timestamp_seconds == 498.5
    assert annotation.annotation_type == "symptom"
    assert annotation.label == "Tremor onset"
    assert annotation.severity == 7
    mock_repository.create.assert_called_once()


def test_create_annotation_with_metadata(annotation_service, mock_repository):
    """Test creating annotation with custom metadata."""
    # Setup
    created_ann = Mock()
    mock_repository.create.return_value = created_ann

    # Execute
    annotation = annotation_service.create_annotation(
        patient_id="P01",
        recording_id="rec_001",
        timestamp=100.0,
        annotation_type="medication",
        label="Levodopa",
        medication_type="levodopa",
        dosage="100mg"
    )

    # Verify
    assert mock_repository.create.called
    call_args = mock_repository.create.call_args[0]
    created_annotation = call_args[1]
    assert created_annotation.metadata['medication_type'] == 'levodopa'
    assert created_annotation.metadata['dosage'] == '100mg'


def test_create_annotation_invalid_type(annotation_service):
    """Test creating annotation with invalid type."""
    # Execute & Verify
    with pytest.raises(ValueError, match="Invalid annotation type"):
        annotation_service.create_annotation(
            patient_id="P01",
            recording_id="rec_001",
            timestamp=100.0,
            annotation_type="invalid_type",
            label="Test"
        )


def test_create_annotation_negative_timestamp(annotation_service):
    """Test creating annotation with negative timestamp."""
    # Execute & Verify
    with pytest.raises(ValueError, match="Timestamp must be non-negative"):
        annotation_service.create_annotation(
            patient_id="P01",
            recording_id="rec_001",
            timestamp=-10.0,
            annotation_type="symptom",
            label="Test"
        )


def test_create_annotation_invalid_severity(annotation_service):
    """Test creating annotation with severity out of range."""
    # Execute & Verify
    with pytest.raises(ValueError, match="Severity must be between 1 and 10"):
        annotation_service.create_annotation(
            patient_id="P01",
            recording_id="rec_001",
            timestamp=100.0,
            annotation_type="symptom",
            label="Test",
            severity=15
        )


def test_create_annotation_valid_severity_range(annotation_service, mock_repository):
    """Test creating annotation with valid severity values."""
    # Setup
    mock_repository.create.return_value = Mock()

    # Test severity = 1
    annotation_service.create_annotation(
        patient_id="P01",
        recording_id="rec_001",
        timestamp=100.0,
        annotation_type="symptom",
        label="Test",
        severity=1
    )

    # Test severity = 10
    annotation_service.create_annotation(
        patient_id="P01",
        recording_id="rec_001",
        timestamp=100.0,
        annotation_type="symptom",
        label="Test",
        severity=10
    )

    # Verify both succeeded
    assert mock_repository.create.call_count == 2


# ============================================================================
# update_annotation Tests
# ============================================================================

def test_update_annotation_success(annotation_service, mock_repository, sample_annotation):
    """Test successful annotation update."""
    # Setup
    mock_repository.get_by_id.return_value = sample_annotation
    mock_repository.update.return_value = sample_annotation

    # Execute
    updated = annotation_service.update_annotation(
        patient_id="P01",
        annotation_id="ann_001",
        label="Updated label",
        severity=9
    )

    # Verify
    assert updated.label == "Updated label"
    assert updated.severity == 9
    mock_repository.update.assert_called_once()


def test_update_annotation_not_found(annotation_service, mock_repository):
    """Test updating non-existent annotation."""
    # Setup
    mock_repository.get_by_id.return_value = None

    # Execute & Verify
    with pytest.raises(ValueError, match="not found"):
        annotation_service.update_annotation(
            patient_id="P01",
            annotation_id="nonexistent",
            label="Test"
        )


def test_update_annotation_invalid_severity(annotation_service, mock_repository, sample_annotation):
    """Test updating annotation with invalid severity."""
    # Setup
    mock_repository.get_by_id.return_value = sample_annotation

    # Execute & Verify
    with pytest.raises(ValueError, match="Severity must be between 1 and 10"):
        annotation_service.update_annotation(
            patient_id="P01",
            annotation_id="ann_001",
            severity=15
        )


def test_update_annotation_invalid_type(annotation_service, mock_repository, sample_annotation):
    """Test updating annotation with invalid type."""
    # Setup
    mock_repository.get_by_id.return_value = sample_annotation

    # Execute & Verify
    with pytest.raises(ValueError, match="Invalid annotation type"):
        annotation_service.update_annotation(
            patient_id="P01",
            annotation_id="ann_001",
            annotation_type="invalid_type"
        )


def test_update_annotation_negative_timestamp(annotation_service, mock_repository, sample_annotation):
    """Test updating annotation with negative timestamp."""
    # Setup
    mock_repository.get_by_id.return_value = sample_annotation

    # Execute & Verify
    with pytest.raises(ValueError, match="Timestamp must be non-negative"):
        annotation_service.update_annotation(
            patient_id="P01",
            annotation_id="ann_001",
            timestamp_seconds=-10.0
        )


# ============================================================================
# delete_annotation Tests
# ============================================================================

def test_delete_annotation_success(annotation_service, mock_repository):
    """Test successful annotation deletion."""
    # Execute
    annotation_service.delete_annotation("P01", "ann_001")

    # Verify
    mock_repository.delete.assert_called_once_with("P01", "ann_001")


# ============================================================================
# get_annotations_for_recording Tests
# ============================================================================

def test_get_annotations_for_recording_all(annotation_service, mock_repository, sample_annotation):
    """Test getting all annotations for a recording."""
    # Setup
    mock_repository.get_by_recording.return_value = [sample_annotation]

    # Execute
    annotations = annotation_service.get_annotations_for_recording("P01", "rec_001")

    # Verify
    assert len(annotations) == 1
    assert annotations[0].id == "ann_001"
    mock_repository.get_by_recording.assert_called_once_with("P01", "rec_001")


def test_get_annotations_for_recording_filtered(annotation_service, mock_repository, sample_annotation):
    """Test getting annotations filtered by type."""
    # Setup
    mock_repository.get_by_type.return_value = [sample_annotation]

    # Execute
    annotations = annotation_service.get_annotations_for_recording(
        "P01",
        "rec_001",
        annotation_type="symptom"
    )

    # Verify
    assert len(annotations) == 1
    assert annotations[0].annotation_type == "symptom"
    mock_repository.get_by_type.assert_called_once_with("P01", "rec_001", "symptom")


# ============================================================================
# export_annotations Tests
# ============================================================================

def test_export_annotations_csv(annotation_service, mock_repository, sample_annotation, tmp_path):
    """Test exporting annotations to CSV."""
    # Setup
    mock_repository.get_by_recording.return_value = [sample_annotation]
    output_file = tmp_path / "annotations.csv"

    # Execute
    annotation_service.export_annotations("P01", "rec_001", output_file, format='csv')

    # Verify file created
    assert output_file.exists()

    # Verify content
    with open(output_file) as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        assert len(rows) == 1
        assert rows[0]['label'] == 'Tremor onset'
        assert rows[0]['annotation_type'] == 'symptom'


def test_export_annotations_json(annotation_service, mock_repository, sample_annotation, tmp_path):
    """Test exporting annotations to JSON."""
    # Setup
    mock_repository.get_by_recording.return_value = [sample_annotation]
    output_file = tmp_path / "annotations.json"

    # Execute
    annotation_service.export_annotations("P01", "rec_001", output_file, format='json')

    # Verify file created
    assert output_file.exists()

    # Verify content
    with open(output_file) as f:
        data = json.load(f)
        assert data['recording_id'] == 'rec_001'
        assert data['annotation_count'] == 1
        assert len(data['annotations']) == 1
        assert data['annotations'][0]['label'] == 'Tremor onset'


def test_export_annotations_invalid_format(annotation_service, mock_repository, tmp_path):
    """Test exporting with invalid format."""
    # Setup
    mock_repository.get_by_recording.return_value = []
    output_file = tmp_path / "annotations.xyz"

    # Execute & Verify
    with pytest.raises(ValueError, match="Unsupported export format"):
        annotation_service.export_annotations("P01", "rec_001", output_file, format='xyz')


# ============================================================================
# import_annotations Tests
# ============================================================================

def test_import_annotations_csv(annotation_service, mock_repository, tmp_path):
    """Test importing annotations from CSV."""
    # Setup - create CSV file
    csv_file = tmp_path / "import.csv"
    with open(csv_file, 'w', newline='') as f:
        writer = csv.DictWriter(
            f,
            fieldnames=['timestamp_seconds', 'annotation_type', 'label', 'description', 'severity']
        )
        writer.writeheader()
        writer.writerow({
            'timestamp_seconds': '100.0',
            'annotation_type': 'symptom',
            'label': 'Test symptom',
            'description': 'Test description',
            'severity': '5'
        })

    mock_repository.create.return_value = Mock()

    # Execute
    imported = annotation_service.import_annotations("P01", "rec_001", csv_file, format='csv')

    # Verify
    assert len(imported) == 1
    assert mock_repository.create.called


def test_import_annotations_json(annotation_service, mock_repository, tmp_path):
    """Test importing annotations from JSON."""
    # Setup - create JSON file
    json_file = tmp_path / "import.json"
    data = {
        'recording_id': 'old_rec',
        'annotations': [
            {
                'id': 'old_id',
                'recording_id': 'old_rec',
                'timestamp_seconds': 100.0,
                'annotation_type': 'symptom',
                'label': 'Test',
                'description': None,
                'severity': 5,
                'metadata': {},
                'created_at': datetime.now().isoformat(),
                'updated_at': datetime.now().isoformat()
            }
        ]
    }
    with open(json_file, 'w') as f:
        json.dump(data, f)

    mock_repository.create.return_value = Mock()

    # Execute
    imported = annotation_service.import_annotations("P01", "rec_001", json_file, format='json')

    # Verify
    assert len(imported) == 1
    assert mock_repository.create.called


def test_import_annotations_file_not_found(annotation_service):
    """Test importing from non-existent file."""
    # Execute & Verify
    with pytest.raises(FileNotFoundError):
        annotation_service.import_annotations(
            "P01",
            "rec_001",
            Path("/nonexistent/file.csv"),
            format='csv'
        )


def test_import_annotations_invalid_format(annotation_service, tmp_path):
    """Test importing with invalid format."""
    # Setup
    test_file = tmp_path / "test.txt"
    test_file.write_text("dummy")

    # Execute & Verify
    with pytest.raises(ValueError, match="Unsupported import format"):
        annotation_service.import_annotations("P01", "rec_001", test_file, format='xyz')


# ============================================================================
# create_from_template Tests
# ============================================================================

def test_create_from_template_tremor(annotation_service, mock_repository):
    """Test creating annotation from tremor template."""
    # Setup
    mock_repository.create.return_value = Mock()

    # Execute
    annotation_service.create_from_template(
        patient_id="P01",
        recording_id="rec_001",
        timestamp=100.0,
        template_name="symptom_tremor"
    )

    # Verify
    assert mock_repository.create.called
    call_args = mock_repository.create.call_args[0]
    created_annotation = call_args[1]
    assert created_annotation.annotation_type == 'symptom'
    assert created_annotation.label == 'Tremor'
    assert created_annotation.severity == 5


def test_create_from_template_medication(annotation_service, mock_repository):
    """Test creating annotation from medication template."""
    # Setup
    mock_repository.create.return_value = Mock()

    # Execute
    annotation_service.create_from_template(
        patient_id="P01",
        recording_id="rec_001",
        timestamp=200.0,
        template_name="medication_levodopa"
    )

    # Verify
    assert mock_repository.create.called
    call_args = mock_repository.create.call_args[0]
    created_annotation = call_args[1]
    assert created_annotation.annotation_type == 'medication'
    assert created_annotation.label == 'Levodopa Administration'


def test_create_from_template_with_override(annotation_service, mock_repository):
    """Test creating template annotation with field override."""
    # Setup
    mock_repository.create.return_value = Mock()

    # Execute - override default severity
    annotation_service.create_from_template(
        patient_id="P01",
        recording_id="rec_001",
        timestamp=100.0,
        template_name="symptom_tremor",
        severity=9,
        description="Custom description"
    )

    # Verify
    assert mock_repository.create.called
    call_args = mock_repository.create.call_args[0]
    created_annotation = call_args[1]
    assert created_annotation.severity == 9
    assert created_annotation.description == "Custom description"


def test_create_from_template_invalid_template(annotation_service):
    """Test creating annotation from non-existent template."""
    # Execute & Verify
    with pytest.raises(ValueError, match="Unknown template"):
        annotation_service.create_from_template(
            patient_id="P01",
            recording_id="rec_001",
            timestamp=100.0,
            template_name="nonexistent_template"
        )


def test_create_from_template_all_symptom_templates(annotation_service, mock_repository):
    """Test all symptom templates are valid."""
    # Setup
    mock_repository.create.return_value = Mock()

    symptom_templates = [
        "symptom_tremor",
        "symptom_dyskinesia",
        "symptom_bradykinesia",
        "symptom_rigidity"
    ]

    for template in symptom_templates:
        annotation_service.create_from_template(
            patient_id="P01",
            recording_id="rec_001",
            timestamp=100.0,
            template_name=template
        )

    # Verify all created
    assert mock_repository.create.call_count == len(symptom_templates)


def test_create_from_template_all_activity_templates(annotation_service, mock_repository):
    """Test all activity templates are valid."""
    # Setup
    mock_repository.create.return_value = Mock()

    activity_templates = [
        "activity_walking",
        "activity_resting"
    ]

    for template in activity_templates:
        annotation_service.create_from_template(
            patient_id="P01",
            recording_id="rec_001",
            timestamp=100.0,
            template_name=template
        )

    # Verify all created
    assert mock_repository.create.call_count == len(activity_templates)
