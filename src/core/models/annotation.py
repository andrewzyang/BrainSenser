"""
Annotation data model for clinical event annotations in streaming recordings.

This module defines the Annotation dataclass representing clinical annotations
for specific timestamps in streaming recordings. Used by streaming data analysis
tools to mark events like symptoms, medications, activities, etc.

Author: iEEG BrainSense Development Team
Last Updated: 2025-10-07
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict, Any
import json


@dataclass
class Annotation:
    """
    Clinical annotation for a specific timestamp in a streaming recording.

    Annotations allow clinicians and researchers to mark clinical events within
    recordings, such as symptom onset, medication administration, or peak effects.
    Each annotation has a type, label, and flexible metadata for event-specific details.

    Attributes:
        id: Unique identifier for the annotation
        recording_id: ID of the recording this annotation belongs to
        timestamp_seconds: Time within recording in seconds from start
        annotation_type: Type of annotation ('symptom', 'medication', 'activity', 'other')
        label: Short label for the event (e.g., "Tremor onset")
        description: Optional detailed description
        severity: Optional severity rating (1-10 scale for symptoms)
        metadata: Additional flexible metadata (medication dose, symptom details, etc.)
        created_at: When this annotation was created
        updated_at: When this annotation was last updated

    Example:
        >>> annotation = Annotation(
        ...     id="ann_001",
        ...     recording_id="rec_001",
        ...     timestamp_seconds=498.5,
        ...     annotation_type="symptom",
        ...     label="Tremor onset",
        ...     description="Patient just woke up",
        ...     severity=7,
        ...     metadata={"body_part": "right_hand", "frequency": "4-6Hz"},
        ...     created_at=datetime.now(),
        ...     updated_at=datetime.now()
        ... )
    """

    # Identifiers
    id: str
    recording_id: str

    # Timing
    timestamp_seconds: float

    # Event classification
    annotation_type: str  # 'symptom', 'medication', 'activity', 'other'
    label: str

    # Event details
    description: Optional[str] = None
    severity: Optional[int] = None  # 1-10 scale for symptoms

    # Additional metadata
    metadata: Dict[str, Any] = field(default_factory=dict)

    # Database timestamps
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    @property
    def is_symptom(self) -> bool:
        """Whether this is a symptom annotation."""
        return self.annotation_type == 'symptom'

    @property
    def is_medication(self) -> bool:
        """Whether this is a medication annotation."""
        return self.annotation_type == 'medication'

    @property
    def is_activity(self) -> bool:
        """Whether this is an activity annotation."""
        return self.annotation_type == 'activity'

    @property
    def has_severity(self) -> bool:
        """Whether this annotation has a severity rating."""
        return self.severity is not None

    @property
    def timestamp_minutes(self) -> float:
        """Timestamp in minutes."""
        return self.timestamp_seconds / 60.0

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert to dictionary for database storage.

        Returns:
            Dictionary with all fields, converting complex types to JSON strings
        """
        return {
            'id': self.id,
            'recording_id': self.recording_id,
            'timestamp_seconds': self.timestamp_seconds,
            'annotation_type': self.annotation_type,
            'label': self.label,
            'description': self.description,
            'severity': self.severity,
            'metadata': json.dumps(self.metadata),
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat()
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Annotation':
        """
        Create Annotation from dictionary (database row).

        Args:
            data: Dictionary with database fields

        Returns:
            Annotation instance
        """
        # Parse JSON metadata
        metadata = json.loads(data['metadata']) if isinstance(data['metadata'], str) else data['metadata']

        # Parse datetime fields
        created_at = datetime.fromisoformat(data['created_at']) if isinstance(data['created_at'], str) else data['created_at']
        updated_at = datetime.fromisoformat(data['updated_at']) if isinstance(data['updated_at'], str) else data['updated_at']

        return cls(
            id=data['id'],
            recording_id=data['recording_id'],
            timestamp_seconds=data['timestamp_seconds'],
            annotation_type=data['annotation_type'],
            label=data['label'],
            description=data.get('description'),
            severity=data.get('severity'),
            metadata=metadata,
            created_at=created_at,
            updated_at=updated_at
        )

    def to_csv_row(self) -> Dict[str, Any]:
        """
        Convert to CSV export format.

        Returns:
            Dictionary suitable for CSV export
        """
        return {
            'timestamp_seconds': self.timestamp_seconds,
            'timestamp_minutes': f"{self.timestamp_minutes:.2f}",
            'annotation_type': self.annotation_type,
            'label': self.label,
            'description': self.description or '',
            'severity': self.severity if self.severity is not None else ''
        }
