"""
Annotation service for managing clinical event annotations.

This service provides business logic for annotation operations including:
- Creating, updating, and deleting annotations
- Importing and exporting annotations (CSV, JSON)
- Applying annotation templates
- Filtering annotations by type and time range

Author: iEEG BrainSense Development Team
Last Updated: 2025-10-07
"""

import logging
import uuid
import csv
import json
from pathlib import Path
from typing import Optional, List
from datetime import datetime

from src.core.models import Annotation
from src.infrastructure.repositories.annotation_repository import AnnotationRepository

logger = logging.getLogger(__name__)


class AnnotationService:
    """
    Service for annotation management operations.

    Orchestrates creation, retrieval, update, and deletion of clinical annotations
    for streaming recordings. Provides import/export functionality and templates.

    Example:
        >>> from src.infrastructure.database.adapters import SQLiteAdapter
        >>> from src.core.path_resolver import PathResolver
        >>> from src.infrastructure.repositories import AnnotationRepository
        >>>
        >>> adapter = SQLiteAdapter()
        >>> resolver = PathResolver()
        >>> repo = AnnotationRepository(adapter, resolver)
        >>> service = AnnotationService(repo)
        >>>
        >>> # Create annotation
        >>> annotation = service.create_annotation(
        ...     patient_id="P01",
        ...     recording_id="rec_001",
        ...     timestamp=498.5,
        ...     annotation_type="symptom",
        ...     label="Tremor onset",
        ...     description="Patient just woke up",
        ...     severity=7
        ... )
        >>>
        >>> # Export annotations
        >>> service.export_annotations("P01", "rec_001", "annotations.csv")
    """

    def __init__(self, repository: AnnotationRepository):
        """
        Initialize AnnotationService.

        Args:
            repository: AnnotationRepository for database operations
        """
        self.repository = repository
        self.logger = logging.getLogger(__name__)

    def create_annotation(
        self,
        patient_id: str,
        recording_id: str,
        timestamp: float,
        annotation_type: str,
        label: str,
        description: Optional[str] = None,
        severity: Optional[int] = None,
        **metadata
    ) -> Annotation:
        """
        Create new annotation for a recording.

        Args:
            patient_id: Patient identifier
            recording_id: Recording identifier
            timestamp: Timestamp in seconds from start of recording
            annotation_type: Type ('symptom', 'medication', 'activity', 'other')
            label: Short label for the event
            description: Optional detailed description
            severity: Optional severity rating (1-10)
            **metadata: Additional metadata fields

        Returns:
            Annotation: Created annotation

        Raises:
            ValueError: If annotation type is invalid or timestamp is negative
        """
        # Validate annotation type
        valid_types = ['symptom', 'medication', 'activity', 'other']
        if annotation_type not in valid_types:
            raise ValueError(f"Invalid annotation type: {annotation_type}. Must be one of {valid_types}")

        # Validate timestamp
        if timestamp < 0:
            raise ValueError(f"Timestamp must be non-negative, got {timestamp}")

        # Validate severity if provided
        if severity is not None and not (1 <= severity <= 10):
            raise ValueError(f"Severity must be between 1 and 10, got {severity}")

        annotation = Annotation(
            id=str(uuid.uuid4()),
            recording_id=recording_id,
            timestamp_seconds=timestamp,
            annotation_type=annotation_type,
            label=label,
            description=description,
            severity=severity,
            metadata=metadata,
            created_at=datetime.now(),
            updated_at=datetime.now()
        )

        created = self.repository.create(patient_id, annotation)
        self.logger.info(
            f"Created annotation {created.id} at {timestamp}s: {label} ({annotation_type})"
        )

        return created

    def update_annotation(
        self,
        patient_id: str,
        annotation_id: str,
        **updates
    ) -> Annotation:
        """
        Update existing annotation.

        Args:
            patient_id: Patient identifier
            annotation_id: Annotation identifier
            **updates: Fields to update (label, description, severity, metadata, etc.)

        Returns:
            Annotation: Updated annotation

        Raises:
            ValueError: If annotation not found
        """
        # Get existing annotation
        annotation = self.repository.get_by_id(patient_id, annotation_id)
        if not annotation:
            raise ValueError(f"Annotation {annotation_id} not found")

        # Update fields
        if 'label' in updates:
            annotation.label = updates['label']
        if 'description' in updates:
            annotation.description = updates['description']
        if 'severity' in updates:
            severity = updates['severity']
            if severity is not None and not (1 <= severity <= 10):
                raise ValueError(f"Severity must be between 1 and 10, got {severity}")
            annotation.severity = severity
        if 'annotation_type' in updates:
            valid_types = ['symptom', 'medication', 'activity', 'other']
            if updates['annotation_type'] not in valid_types:
                raise ValueError(f"Invalid annotation type: {updates['annotation_type']}")
            annotation.annotation_type = updates['annotation_type']
        if 'timestamp_seconds' in updates:
            if updates['timestamp_seconds'] < 0:
                raise ValueError(f"Timestamp must be non-negative")
            annotation.timestamp_seconds = updates['timestamp_seconds']
        if 'metadata' in updates:
            annotation.metadata.update(updates['metadata'])

        updated = self.repository.update(patient_id, annotation)
        self.logger.info(f"Updated annotation {annotation_id}")

        return updated

    def delete_annotation(self, patient_id: str, annotation_id: str):
        """
        Delete annotation.

        Args:
            patient_id: Patient identifier
            annotation_id: Annotation identifier

        Raises:
            ValueError: If annotation not found
        """
        self.repository.delete(patient_id, annotation_id)
        self.logger.info(f"Deleted annotation {annotation_id}")

    def get_annotations_for_recording(
        self,
        patient_id: str,
        recording_id: str,
        annotation_type: Optional[str] = None
    ) -> List[Annotation]:
        """
        Get all annotations for a recording, optionally filtered by type.

        Args:
            patient_id: Patient identifier
            recording_id: Recording identifier
            annotation_type: Optional type filter

        Returns:
            List[Annotation]: List of annotations
        """
        if annotation_type:
            return self.repository.get_by_type(patient_id, recording_id, annotation_type)
        else:
            return self.repository.get_by_recording(patient_id, recording_id)

    def export_annotations(
        self,
        patient_id: str,
        recording_id: str,
        output_path: Path,
        format: str = 'csv'
    ):
        """
        Export annotations to file.

        Args:
            patient_id: Patient identifier
            recording_id: Recording identifier
            output_path: Path for output file
            format: Export format ('csv' or 'json')

        Raises:
            ValueError: If format is not supported
        """
        annotations = self.repository.get_by_recording(patient_id, recording_id)

        if format == 'csv':
            with open(output_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=[
                        'timestamp_seconds',
                        'timestamp_minutes',
                        'annotation_type',
                        'label',
                        'description',
                        'severity'
                    ]
                )
                writer.writeheader()
                for annotation in annotations:
                    writer.writerow(annotation.to_csv_row())

            self.logger.info(f"Exported {len(annotations)} annotations to {output_path} (CSV)")

        elif format == 'json':
            data = {
                'recording_id': recording_id,
                'export_date': datetime.now().isoformat(),
                'annotation_count': len(annotations),
                'annotations': [ann.to_dict() for ann in annotations]
            }

            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)

            self.logger.info(f"Exported {len(annotations)} annotations to {output_path} (JSON)")

        else:
            raise ValueError(f"Unsupported export format: {format}")

    def import_annotations(
        self,
        patient_id: str,
        recording_id: str,
        file_path: Path,
        format: str = 'csv'
    ) -> List[Annotation]:
        """
        Import annotations from file.

        Args:
            patient_id: Patient identifier
            recording_id: Recording identifier
            file_path: Path to input file
            format: Import format ('csv' or 'json')

        Returns:
            List[Annotation]: List of imported annotations

        Raises:
            ValueError: If format is not supported
            FileNotFoundError: If file doesn't exist
        """
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        imported_annotations = []

        if format == 'csv':
            with open(file_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    annotation = self.create_annotation(
                        patient_id=patient_id,
                        recording_id=recording_id,
                        timestamp=float(row['timestamp_seconds']),
                        annotation_type=row['annotation_type'],
                        label=row['label'],
                        description=row.get('description') or None,
                        severity=int(row['severity']) if row.get('severity') else None
                    )
                    imported_annotations.append(annotation)

            self.logger.info(f"Imported {len(imported_annotations)} annotations from {file_path} (CSV)")

        elif format == 'json':
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            for ann_data in data.get('annotations', []):
                annotation = Annotation.from_dict(ann_data)
                # Override recording_id to match target recording
                annotation.recording_id = recording_id
                # Generate new ID
                annotation.id = str(uuid.uuid4())
                # Update timestamps
                annotation.created_at = datetime.now()
                annotation.updated_at = datetime.now()

                created = self.repository.create(patient_id, annotation)
                imported_annotations.append(created)

            self.logger.info(f"Imported {len(imported_annotations)} annotations from {file_path} (JSON)")

        else:
            raise ValueError(f"Unsupported import format: {format}")

        return imported_annotations

    def create_from_template(
        self,
        patient_id: str,
        recording_id: str,
        timestamp: float,
        template_name: str,
        **kwargs
    ) -> Annotation:
        """
        Create annotation from predefined template.

        Args:
            patient_id: Patient identifier
            recording_id: Recording identifier
            timestamp: Timestamp in seconds
            template_name: Template name ('symptom_tremor', 'medication_levodopa', etc.)
            **kwargs: Additional fields to override template defaults

        Returns:
            Annotation: Created annotation

        Supported templates:
            - 'symptom_tremor': Tremor symptom with default severity
            - 'symptom_dyskinesia': Dyskinesia symptom
            - 'symptom_bradykinesia': Bradykinesia symptom
            - 'symptom_rigidity': Rigidity symptom
            - 'medication_levodopa': Levodopa administration
            - 'medication_dopamine_agonist': Dopamine agonist administration
            - 'activity_walking': Walking activity
            - 'activity_resting': Resting activity
        """
        templates = {
            'symptom_tremor': {
                'annotation_type': 'symptom',
                'label': 'Tremor',
                'severity': 5,
                'metadata': {'symptom_type': 'tremor'}
            },
            'symptom_dyskinesia': {
                'annotation_type': 'symptom',
                'label': 'Dyskinesia',
                'severity': 5,
                'metadata': {'symptom_type': 'dyskinesia'}
            },
            'symptom_bradykinesia': {
                'annotation_type': 'symptom',
                'label': 'Bradykinesia',
                'severity': 5,
                'metadata': {'symptom_type': 'bradykinesia'}
            },
            'symptom_rigidity': {
                'annotation_type': 'symptom',
                'label': 'Rigidity',
                'severity': 5,
                'metadata': {'symptom_type': 'rigidity'}
            },
            'medication_levodopa': {
                'annotation_type': 'medication',
                'label': 'Levodopa Administration',
                'metadata': {'medication_type': 'levodopa', 'route': 'oral'}
            },
            'medication_dopamine_agonist': {
                'annotation_type': 'medication',
                'label': 'Dopamine Agonist Administration',
                'metadata': {'medication_type': 'dopamine_agonist', 'route': 'oral'}
            },
            'activity_walking': {
                'annotation_type': 'activity',
                'label': 'Walking',
                'metadata': {'activity_type': 'walking'}
            },
            'activity_resting': {
                'annotation_type': 'activity',
                'label': 'Resting',
                'metadata': {'activity_type': 'resting'}
            }
        }

        if template_name not in templates:
            raise ValueError(f"Unknown template: {template_name}. Available: {list(templates.keys())}")

        template = templates[template_name].copy()
        # Override with provided kwargs
        template.update(kwargs)

        return self.create_annotation(
            patient_id=patient_id,
            recording_id=recording_id,
            timestamp=timestamp,
            **template
        )
