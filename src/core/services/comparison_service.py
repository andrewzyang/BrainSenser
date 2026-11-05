"""
Comparison service for multi-recording analysis in Streaming Spectrum.

This service provides business logic for comparing multiple streaming recordings:
- Creating and managing recording groups
- Auto-grouping by criteria (time of day, medication state)
- Group statistics calculation
- Statistical comparison between groups

Author: iEEG BrainSense Development Team
Last Updated: 2025-10-07
"""

import logging
import uuid
from typing import List, Dict, Any, Optional
from datetime import datetime, time

from src.core.models import RecordingGroup
from src.infrastructure.repositories.recording_group_repository import RecordingGroupRepository
from src.infrastructure.repositories.streaming_recording_repository import StreamingRecordingRepository

logger = logging.getLogger(__name__)


class ComparisonService:
    """
    Service for multi-recording comparison analysis.

    Orchestrates creation and management of recording groups for the Streaming Spectrum.
    Enables comparing multiple recordings through grouping, auto-grouping, and statistical
    analysis.

    Example:
        >>> from src.infrastructure.database.adapters import SQLiteAdapter
        >>> from src.core.path_resolver import PathResolver
        >>> from src.infrastructure.repositories import (
        ...     RecordingGroupRepository,
        ...     StreamingRecordingRepository
        ... )
        >>>
        >>> adapter = SQLiteAdapter()
        >>> resolver = PathResolver()
        >>> group_repo = RecordingGroupRepository(adapter, resolver)
        >>> recording_repo = StreamingRecordingRepository(adapter, resolver)
        >>> service = ComparisonService(group_repo, recording_repo)
        >>>
        >>> # Create manual group
        >>> group = service.create_group(
        ...     patient_id="P01",
        ...     name="Morning Recordings",
        ...     recording_ids=["rec_001", "rec_002", "rec_003"],
        ...     criteria="manual"
        ... )
        >>>
        >>> # Auto-group by time of day
        >>> groups = service.auto_group_by_time_of_day("P01")
    """

    def __init__(
        self,
        group_repository: RecordingGroupRepository,
        streaming_repository: StreamingRecordingRepository
    ):
        """
        Initialize ComparisonService.

        Args:
            group_repository: RecordingGroupRepository for group database operations
            streaming_repository: StreamingRecordingRepository for recording database operations
        """
        self.group_repository = group_repository
        self.streaming_repository = streaming_repository
        self.logger = logging.getLogger(__name__)

    def create_group(
        self,
        patient_id: str,
        name: str,
        recording_ids: List[str],
        criteria: str = 'manual',
        description: Optional[str] = None,
        custom_criteria: Optional[Dict[str, Any]] = None,
        color: str = '#3498db'
    ) -> RecordingGroup:
        """
        Create new recording group.

        Args:
            patient_id: Patient identifier
            name: Group name
            recording_ids: List of recording IDs to include
            criteria: Grouping criteria ('manual', 'time_of_day', 'medication_state', 'custom')
            description: Optional group description
            custom_criteria: Optional custom grouping rules
            color: Hex color code for visualization

        Returns:
            RecordingGroup: Created group

        Raises:
            ValueError: If recording_ids is empty or recordings don't exist
        """
        if not recording_ids:
            raise ValueError("Cannot create group with no recordings")

        # Validate that all recordings exist and belong to patient
        for recording_id in recording_ids:
            recording = self.streaming_repository.get_by_id(patient_id, recording_id)
            if not recording:
                raise ValueError(f"Recording {recording_id} not found for patient {patient_id}")

        group_id = f"group_{uuid.uuid4().hex[:8]}"

        group = RecordingGroup(
            id=group_id,
            patient_id=patient_id,
            name=name,
            description=description,
            recording_ids=recording_ids,
            grouping_criteria=criteria,
            custom_criteria=custom_criteria,
            color=color,
            created_at=datetime.now(),
            updated_at=datetime.now()
        )

        created_group = self.group_repository.create(patient_id, group)
        self.logger.info(
            f"Created group '{name}' with {len(recording_ids)} recordings for patient {patient_id}"
        )

        return created_group

    def update_group(
        self,
        patient_id: str,
        group_id: str,
        **kwargs
    ) -> RecordingGroup:
        """
        Update existing group.

        Args:
            patient_id: Patient identifier
            group_id: Group identifier
            **kwargs: Fields to update (name, description, recording_ids, color, etc.)

        Returns:
            RecordingGroup: Updated group

        Raises:
            ValueError: If group not found
        """
        group = self.group_repository.get_by_id(patient_id, group_id)
        if not group:
            raise ValueError(f"Group {group_id} not found")

        # Update fields
        for key, value in kwargs.items():
            if hasattr(group, key):
                setattr(group, key, value)

        updated_group = self.group_repository.update(patient_id, group)
        self.logger.info(f"Updated group {group_id} for patient {patient_id}")

        return updated_group

    def delete_group(self, patient_id: str, group_id: str) -> None:
        """
        Delete group.

        Args:
            patient_id: Patient identifier
            group_id: Group identifier

        Raises:
            ValueError: If group not found
        """
        self.group_repository.delete(patient_id, group_id)
        self.logger.info(f"Deleted group {group_id} for patient {patient_id}")

    def get_groups_for_patient(self, patient_id: str) -> List[RecordingGroup]:
        """
        Get all groups for a patient.

        Args:
            patient_id: Patient identifier

        Returns:
            List[RecordingGroup]: List of groups (may be empty)
        """
        return self.group_repository.get_by_patient(patient_id)

    def add_recording_to_group(
        self,
        patient_id: str,
        group_id: str,
        recording_id: str
    ) -> RecordingGroup:
        """
        Add recording to existing group.

        Args:
            patient_id: Patient identifier
            group_id: Group identifier
            recording_id: Recording identifier

        Returns:
            RecordingGroup: Updated group

        Raises:
            ValueError: If group or recording not found
        """
        # Validate recording exists
        recording = self.streaming_repository.get_by_id(patient_id, recording_id)
        if not recording:
            raise ValueError(f"Recording {recording_id} not found")

        updated_group = self.group_repository.add_recording_to_group(
            patient_id, group_id, recording_id
        )
        self.logger.info(f"Added recording {recording_id} to group {group_id}")

        return updated_group

    def remove_recording_from_group(
        self,
        patient_id: str,
        group_id: str,
        recording_id: str
    ) -> RecordingGroup:
        """
        Remove recording from group.

        Args:
            patient_id: Patient identifier
            group_id: Group identifier
            recording_id: Recording identifier

        Returns:
            RecordingGroup: Updated group

        Raises:
            ValueError: If group not found
        """
        updated_group = self.group_repository.remove_recording_from_group(
            patient_id, group_id, recording_id
        )
        self.logger.info(f"Removed recording {recording_id} from group {group_id}")

        return updated_group

    def auto_group_by_time_of_day(
        self,
        patient_id: str
    ) -> List[RecordingGroup]:
        """
        Automatically create groups based on recording time of day.

        Creates three groups:
        - Morning: 5am - 12pm
        - Afternoon: 12pm - 6pm
        - Evening: 6pm - 11pm
        - Night: 11pm - 5am

        Args:
            patient_id: Patient identifier

        Returns:
            List[RecordingGroup]: List of created groups
        """
        self.logger.info(f"Auto-grouping by time of day for patient {patient_id}")

        # Get all recordings for patient
        all_recordings = self.streaming_repository.get_by_patient(patient_id)

        # Categorize recordings by time of day
        morning_ids = []
        afternoon_ids = []
        evening_ids = []
        night_ids = []

        for recording in all_recordings:
            recording_time = recording.recording_date.time()

            if time(5, 0) <= recording_time < time(12, 0):
                morning_ids.append(recording.id)
            elif time(12, 0) <= recording_time < time(18, 0):
                afternoon_ids.append(recording.id)
            elif time(18, 0) <= recording_time < time(23, 0):
                evening_ids.append(recording.id)
            else:  # 11pm - 5am
                night_ids.append(recording.id)

        # Create groups for non-empty categories
        created_groups = []
        color_map = {
            'Morning': '#3498db',  # Blue
            'Afternoon': '#f39c12',  # Orange
            'Evening': '#9b59b6',  # Purple
            'Night': '#34495e'  # Dark gray
        }

        for name, recording_ids in [
            ('Morning', morning_ids),
            ('Afternoon', afternoon_ids),
            ('Evening', evening_ids),
            ('Night', night_ids)
        ]:
            if recording_ids:
                group = self.create_group(
                    patient_id=patient_id,
                    name=name,
                    recording_ids=recording_ids,
                    criteria='time_of_day',
                    description=f'Automatically grouped recordings from {name.lower()} time period',
                    color=color_map[name]
                )
                created_groups.append(group)

        self.logger.info(f"Created {len(created_groups)} time-of-day groups for patient {patient_id}")
        return created_groups

    def auto_group_by_medication_state(
        self,
        patient_id: str
    ) -> List[RecordingGroup]:
        """
        Automatically create groups based on medication state.

        Looks at recording metadata for 'medication_state' field and creates
        groups for each unique value (e.g., 'pre_med', 'post_med', 'off_med').

        Args:
            patient_id: Patient identifier

        Returns:
            List[RecordingGroup]: List of created groups

        Note:
            Requires recordings to have 'medication_state' in their metadata.
        """
        self.logger.info(f"Auto-grouping by medication state for patient {patient_id}")

        # Get all recordings for patient
        all_recordings = self.streaming_repository.get_by_patient(patient_id)

        # Categorize recordings by medication state
        state_groups: Dict[str, List[str]] = {}

        for recording in all_recordings:
            med_state = recording.metadata.get('medication_state')
            if med_state:
                if med_state not in state_groups:
                    state_groups[med_state] = []
                state_groups[med_state].append(recording.id)

        if not state_groups:
            self.logger.warning(
                f"No recordings with medication_state metadata found for patient {patient_id}"
            )
            return []

        # Create groups
        created_groups = []
        colors = ['#e74c3c', '#2ecc71', '#f39c12', '#3498db', '#9b59b6']

        for idx, (state_name, recording_ids) in enumerate(state_groups.items()):
            color = colors[idx % len(colors)]
            display_name = state_name.replace('_', ' ').title()

            group = self.create_group(
                patient_id=patient_id,
                name=display_name,
                recording_ids=recording_ids,
                criteria='medication_state',
                description=f'Recordings in {display_name} state',
                color=color
            )
            created_groups.append(group)

        self.logger.info(
            f"Created {len(created_groups)} medication state groups for patient {patient_id}"
        )
        return created_groups
