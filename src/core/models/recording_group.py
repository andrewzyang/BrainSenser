"""
RecordingGroup data model for grouping streaming recordings for comparison.

This module defines the RecordingGroup dataclass representing a group of
streaming recordings that can be analyzed together in the Streaming Spectrum.
Groups can be manually created or automatically generated based on criteria
like time of day or medication state.

Author: iEEG BrainSense Development Team
Last Updated: 2025-10-07
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict, Any
import json


@dataclass
class RecordingGroup:
    """
    Represents a group of streaming recordings for comparison analysis.

    This model enables multi-recording comparison in the Streaming Spectrum.
    Groups can be manually created by the user or automatically generated
    based on grouping criteria (time of day, medication state, custom rules).

    Attributes:
        id: Unique identifier for the group
        patient_id: Patient identifier (foreign key to patients table)
        name: Human-readable name for the group (e.g., "Morning Recordings")
        description: Optional detailed description of the group
        recording_ids: List of streaming_recording IDs in this group
        grouping_criteria: How the group was created ('manual', 'time_of_day',
                          'medication_state', 'custom')
        custom_criteria: Optional dict with custom grouping rules
        color: Hex color code for visualization (e.g., '#3498db')
        created_at: When this group was created
        updated_at: When this group was last updated

    Example:
        >>> group = RecordingGroup(
        ...     id="group_001",
        ...     patient_id="P01",
        ...     name="Morning Recordings",
        ...     description="All recordings taken in the morning before medication",
        ...     recording_ids=["rec_001", "rec_002", "rec_003"],
        ...     grouping_criteria="time_of_day",
        ...     custom_criteria=None,
        ...     color="#3498db",
        ...     created_at=datetime.now(),
        ...     updated_at=datetime.now()
        ... )
    """

    # Identifiers
    id: str
    patient_id: str

    # Group metadata
    name: str
    description: Optional[str] = None

    # Group composition
    recording_ids: List[str] = field(default_factory=list)

    # Grouping information
    grouping_criteria: str = 'manual'  # 'manual', 'time_of_day', 'medication_state', 'custom'
    custom_criteria: Optional[Dict[str, Any]] = None

    # Visualization
    color: str = '#3498db'  # Default blue

    # Database timestamps
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    @property
    def recording_count(self) -> int:
        """Number of recordings in this group."""
        return len(self.recording_ids)

    @property
    def is_manual(self) -> bool:
        """Whether this is a manually created group."""
        return self.grouping_criteria == 'manual'

    @property
    def is_auto_grouped(self) -> bool:
        """Whether this group was automatically generated."""
        return self.grouping_criteria in ['time_of_day', 'medication_state', 'custom']

    def add_recording(self, recording_id: str) -> None:
        """
        Add recording to group if not already present.

        Args:
            recording_id: Recording ID to add
        """
        if recording_id not in self.recording_ids:
            self.recording_ids.append(recording_id)
            self.updated_at = datetime.now()

    def remove_recording(self, recording_id: str) -> None:
        """
        Remove recording from group.

        Args:
            recording_id: Recording ID to remove
        """
        if recording_id in self.recording_ids:
            self.recording_ids.remove(recording_id)
            self.updated_at = datetime.now()

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert to dictionary for database storage.

        Returns:
            Dictionary with all fields, converting complex types to JSON strings
        """
        return {
            'id': self.id,
            'patient_id': self.patient_id,
            'name': self.name,
            'description': self.description,
            'recording_ids': json.dumps(self.recording_ids),
            'grouping_criteria': self.grouping_criteria,
            'custom_criteria': json.dumps(self.custom_criteria) if self.custom_criteria else None,
            'color': self.color,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat()
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'RecordingGroup':
        """
        Create RecordingGroup from dictionary (database row).

        Args:
            data: Dictionary with database fields

        Returns:
            RecordingGroup instance
        """
        # Parse JSON fields
        recording_ids = json.loads(data['recording_ids']) if isinstance(data['recording_ids'], str) else data['recording_ids']
        custom_criteria = None
        if data.get('custom_criteria'):
            custom_criteria = json.loads(data['custom_criteria']) if isinstance(data['custom_criteria'], str) else data['custom_criteria']

        # Parse datetime fields
        created_at = datetime.fromisoformat(data['created_at']) if isinstance(data['created_at'], str) else data['created_at']
        updated_at = datetime.fromisoformat(data['updated_at']) if isinstance(data['updated_at'], str) else data['updated_at']

        return cls(
            id=data['id'],
            patient_id=data['patient_id'],
            name=data['name'],
            description=data.get('description'),
            recording_ids=recording_ids,
            grouping_criteria=data['grouping_criteria'],
            custom_criteria=custom_criteria,
            color=data.get('color', '#3498db'),
            created_at=created_at,
            updated_at=updated_at
        )
