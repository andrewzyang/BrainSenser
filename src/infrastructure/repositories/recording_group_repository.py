"""
Repository for recording_groups table operations.

This module provides CRUD operations for the RecordingGroup model, managing
groups of streaming recordings for multi-recording comparison analysis in the
Streaming Spectrum.

Features:
- Create/read/update/delete recording groups
- Query by patient, grouping criteria
- Add/remove recordings from groups
- Transaction support

Author: iEEG BrainSense Development Team
Last Updated: 2025-10-07
"""

import sqlite3
from datetime import datetime
from typing import Optional, List

from .base_repository import BaseRepository
from src.core.models import RecordingGroup
from src.infrastructure.database.schema.patient_schema import TABLE_RECORDING_GROUPS


class RecordingGroupRepository(BaseRepository[RecordingGroup]):
    """
    Repository for RecordingGroup model / recording_groups table.

    Provides CRUD operations for recording groups used in the Streaming Spectrum.
    All operations use per-patient databases (brainsense_data.db).

    Example:
        >>> adapter = SQLiteAdapter()
        >>> resolver = PathResolver()
        >>> repo = RecordingGroupRepository(adapter, resolver)
        >>>
        >>> # Create group
        >>> group = RecordingGroup(
        ...     id="group_001",
        ...     patient_id="P01",
        ...     name="Morning Recordings",
        ...     recording_ids=["rec_001", "rec_002"],
        ...     grouping_criteria="time_of_day",
        ...     color="#3498db",
        ...     created_at=datetime.now(),
        ...     updated_at=datetime.now()
        ... )
        >>> repo.create("P01", group)
        >>>
        >>> # Get group
        >>> group = repo.get_by_id("P01", "group_001")
        >>>
        >>> # Get all groups for patient
        >>> groups = repo.get_by_patient("P01")
    """

    def _map_row_to_model(self, row: sqlite3.Row) -> RecordingGroup:
        """
        Convert database row to RecordingGroup model.

        Args:
            row: Database row with recording_groups columns

        Returns:
            RecordingGroup: RecordingGroup model instance
        """
        row_dict = dict(row)
        return RecordingGroup.from_dict(row_dict)

    def create(self, patient_id: str, group: RecordingGroup) -> RecordingGroup:
        """
        Create new recording group.

        Args:
            patient_id: Patient identifier
            group: RecordingGroup instance to create

        Returns:
            RecordingGroup: Created group

        Raises:
            sqlite3.IntegrityError: If group ID already exists
        """
        db_path = self.path_resolver.get_patient_db_path(patient_id)

        query = f"""
            INSERT INTO {TABLE_RECORDING_GROUPS}
            (id, patient_id, name, description, recording_ids, grouping_criteria,
             custom_criteria, color, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """

        data = group.to_dict()

        try:
            with self.adapter.transaction(db_path) as conn:
                self._execute_query(conn, query, (
                    data['id'],
                    data['patient_id'],
                    data['name'],
                    data['description'],
                    data['recording_ids'],
                    data['grouping_criteria'],
                    data['custom_criteria'],
                    data['color'],
                    data['created_at'],
                    data['updated_at']
                ))

            self.logger.info(f"Created recording group: {group.id} for patient {patient_id}")
            return self.get_by_id(patient_id, group.id)

        except sqlite3.IntegrityError as e:
            self.logger.error(f"Failed to create group {group.id}: {e}")
            raise

    def get_by_id(self, patient_id: str, group_id: str) -> Optional[RecordingGroup]:
        """
        Get recording group by ID.

        Args:
            patient_id: Patient identifier
            group_id: Group identifier

        Returns:
            Optional[RecordingGroup]: Group or None if not found
        """
        db_path = self.path_resolver.get_patient_db_path(patient_id)

        query = f"SELECT * FROM {TABLE_RECORDING_GROUPS} WHERE id = ?"

        with self.adapter.get_connection(db_path) as conn:
            return self._fetch_one(conn, query, (group_id,))

    def get_by_patient(self, patient_id: str) -> List[RecordingGroup]:
        """
        Get all groups for a patient.

        Args:
            patient_id: Patient identifier

        Returns:
            List[RecordingGroup]: List of groups (may be empty)
        """
        db_path = self.path_resolver.get_patient_db_path(patient_id)

        query = f"""
            SELECT * FROM {TABLE_RECORDING_GROUPS}
            WHERE patient_id = ?
            ORDER BY created_at DESC
        """

        with self.adapter.get_connection(db_path) as conn:
            return self._fetch_all(conn, query, (patient_id,))

    def get_by_criteria(self, patient_id: str, criteria: str) -> List[RecordingGroup]:
        """
        Get groups with specific grouping criteria.

        Args:
            patient_id: Patient identifier
            criteria: Grouping criteria ('manual', 'time_of_day', 'medication_state', 'custom')

        Returns:
            List[RecordingGroup]: List of groups with matching criteria
        """
        db_path = self.path_resolver.get_patient_db_path(patient_id)

        query = f"""
            SELECT * FROM {TABLE_RECORDING_GROUPS}
            WHERE patient_id = ?
            AND grouping_criteria = ?
            ORDER BY created_at DESC
        """

        with self.adapter.get_connection(db_path) as conn:
            return self._fetch_all(conn, query, (patient_id, criteria))

    def update(self, patient_id: str, group: RecordingGroup) -> RecordingGroup:
        """
        Update existing group.

        Args:
            patient_id: Patient identifier
            group: RecordingGroup with updated values

        Returns:
            RecordingGroup: Updated group

        Raises:
            ValueError: If group not found
        """
        db_path = self.path_resolver.get_patient_db_path(patient_id)

        # Update the updated_at timestamp
        group.updated_at = datetime.now()

        query = f"""
            UPDATE {TABLE_RECORDING_GROUPS}
            SET name = ?,
                description = ?,
                recording_ids = ?,
                grouping_criteria = ?,
                custom_criteria = ?,
                color = ?,
                updated_at = ?
            WHERE id = ?
        """

        data = group.to_dict()

        try:
            with self.adapter.transaction(db_path) as conn:
                rows_affected = self._execute_query(conn, query, (
                    data['name'],
                    data['description'],
                    data['recording_ids'],
                    data['grouping_criteria'],
                    data['custom_criteria'],
                    data['color'],
                    data['updated_at'],
                    data['id']
                ))

                if rows_affected == 0:
                    raise ValueError(f"Group {group.id} not found")

            self.logger.info(f"Updated group: {group.id}")
            return self.get_by_id(patient_id, group.id)

        except sqlite3.Error as e:
            self.logger.error(f"Failed to update group {group.id}: {e}")
            raise

    def delete(self, patient_id: str, group_id: str) -> None:
        """
        Delete group.

        Args:
            patient_id: Patient identifier
            group_id: Group identifier

        Raises:
            ValueError: If group not found
        """
        db_path = self.path_resolver.get_patient_db_path(patient_id)

        query = f"DELETE FROM {TABLE_RECORDING_GROUPS} WHERE id = ?"

        try:
            with self.adapter.transaction(db_path) as conn:
                rows_affected = self._execute_query(conn, query, (group_id,))

                if rows_affected == 0:
                    raise ValueError(f"Group {group_id} not found")

            self.logger.info(f"Deleted group: {group_id}")

        except sqlite3.Error as e:
            self.logger.error(f"Failed to delete group {group_id}: {e}")
            raise

    def add_recording_to_group(self, patient_id: str, group_id: str, recording_id: str) -> RecordingGroup:
        """
        Add recording to group.

        Args:
            patient_id: Patient identifier
            group_id: Group identifier
            recording_id: Recording identifier to add

        Returns:
            RecordingGroup: Updated group

        Raises:
            ValueError: If group not found
        """
        group = self.get_by_id(patient_id, group_id)
        if not group:
            raise ValueError(f"Group {group_id} not found")

        group.add_recording(recording_id)
        return self.update(patient_id, group)

    def remove_recording_from_group(self, patient_id: str, group_id: str, recording_id: str) -> RecordingGroup:
        """
        Remove recording from group.

        Args:
            patient_id: Patient identifier
            group_id: Group identifier
            recording_id: Recording identifier to remove

        Returns:
            RecordingGroup: Updated group

        Raises:
            ValueError: If group not found
        """
        group = self.get_by_id(patient_id, group_id)
        if not group:
            raise ValueError(f"Group {group_id} not found")

        group.remove_recording(recording_id)
        return self.update(patient_id, group)

    def count_by_patient(self, patient_id: str) -> int:
        """
        Count total groups for a patient.

        Args:
            patient_id: Patient identifier

        Returns:
            int: Total number of groups
        """
        db_path = self.path_resolver.get_patient_db_path(patient_id)

        query = f"""
            SELECT COUNT(*) as count
            FROM {TABLE_RECORDING_GROUPS}
            WHERE patient_id = ?
        """

        with self.adapter.get_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(query, (patient_id,))
            row = cursor.fetchone()
            return row['count'] if row else 0
