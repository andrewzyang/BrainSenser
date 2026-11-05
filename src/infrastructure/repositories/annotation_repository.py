"""
Repository for annotations table operations.

This module provides CRUD operations for the Annotation model, managing
clinical event annotations for streaming recordings.

Features:
- Create/read/update/delete annotations
- Query by recording, time range, annotation type
- Retrieve annotations sorted by timestamp
- Transaction support
- Cascade deletion when recording is deleted

Author: iEEG BrainSense Development Team
Last Updated: 2025-10-07
"""

import sqlite3
from datetime import datetime
from typing import Optional, List

from .base_repository import BaseRepository
from src.core.models import Annotation
from src.infrastructure.database.schema.patient_schema import TABLE_ANNOTATIONS


class AnnotationRepository(BaseRepository[Annotation]):
    """
    Repository for Annotation model / annotations table.

    Provides CRUD operations for clinical annotations on streaming recordings.
    All operations use per-patient databases (brainsense_data.db).

    Example:
        >>> adapter = SQLiteAdapter()
        >>> resolver = PathResolver()
        >>> repo = AnnotationRepository(adapter, resolver)
        >>>
        >>> # Create annotation
        >>> annotation = repo.create(
        ...     patient_id="P01",
        ...     annotation=Annotation(
        ...         id="ann_001",
        ...         recording_id="rec_001",
        ...         timestamp_seconds=498.5,
        ...         annotation_type="symptom",
        ...         label="Tremor onset",
        ...         description="Patient just woke up",
        ...         severity=7
        ...     )
        ... )
        >>>
        >>> # Get annotations for recording
        >>> annotations = repo.get_by_recording("P01", "rec_001")
    """

    def _map_row_to_model(self, row: sqlite3.Row) -> Annotation:
        """
        Convert database row to Annotation model.

        Args:
            row: Database row with annotations columns

        Returns:
            Annotation: Annotation model instance
        """
        row_dict = dict(row)
        return Annotation.from_dict(row_dict)

    def create(self, patient_id: str, annotation: Annotation) -> Annotation:
        """
        Create new annotation.

        Args:
            patient_id: Patient identifier
            annotation: Annotation instance to create

        Returns:
            Annotation: Created annotation

        Raises:
            sqlite3.IntegrityError: If annotation ID already exists
        """
        db_path = self.path_resolver.get_patient_db_path(patient_id)

        query = f"""
            INSERT INTO {TABLE_ANNOTATIONS}
            (id, recording_id, timestamp_seconds, annotation_type, label,
             description, severity, metadata, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """

        data = annotation.to_dict()

        try:
            with self.adapter.transaction(db_path) as conn:
                self._execute_query(conn, query, (
                    data['id'],
                    data['recording_id'],
                    data['timestamp_seconds'],
                    data['annotation_type'],
                    data['label'],
                    data['description'],
                    data['severity'],
                    data['metadata'],
                    data['created_at'],
                    data['updated_at']
                ))

            self.logger.info(f"Created annotation: {annotation.id} for recording {annotation.recording_id}")
            return self.get_by_id(patient_id, annotation.id)

        except sqlite3.IntegrityError as e:
            self.logger.error(f"Failed to create annotation {annotation.id}: {e}")
            raise

    def get_by_id(self, patient_id: str, annotation_id: str) -> Optional[Annotation]:
        """
        Get annotation by ID.

        Args:
            patient_id: Patient identifier
            annotation_id: Annotation identifier

        Returns:
            Optional[Annotation]: Annotation or None if not found
        """
        db_path = self.path_resolver.get_patient_db_path(patient_id)

        query = f"SELECT * FROM {TABLE_ANNOTATIONS} WHERE id = ?"

        with self.adapter.get_connection(db_path) as conn:
            return self._fetch_one(conn, query, (annotation_id,))

    def get_by_recording(self, patient_id: str, recording_id: str) -> List[Annotation]:
        """
        Get all annotations for a recording.

        Args:
            patient_id: Patient identifier
            recording_id: Recording identifier

        Returns:
            List[Annotation]: List of annotations sorted by timestamp
        """
        db_path = self.path_resolver.get_patient_db_path(patient_id)

        query = f"""
            SELECT * FROM {TABLE_ANNOTATIONS}
            WHERE recording_id = ?
            ORDER BY timestamp_seconds ASC
        """

        with self.adapter.get_connection(db_path) as conn:
            return self._fetch_all(conn, query, (recording_id,))

    def get_by_time_range(
        self,
        patient_id: str,
        recording_id: str,
        start_sec: float,
        end_sec: float
    ) -> List[Annotation]:
        """
        Get annotations within a time range.

        Args:
            patient_id: Patient identifier
            recording_id: Recording identifier
            start_sec: Start time in seconds
            end_sec: End time in seconds

        Returns:
            List[Annotation]: List of annotations in range
        """
        db_path = self.path_resolver.get_patient_db_path(patient_id)

        query = f"""
            SELECT * FROM {TABLE_ANNOTATIONS}
            WHERE recording_id = ?
            AND timestamp_seconds >= ?
            AND timestamp_seconds <= ?
            ORDER BY timestamp_seconds ASC
        """

        with self.adapter.get_connection(db_path) as conn:
            return self._fetch_all(conn, query, (recording_id, start_sec, end_sec))

    def get_by_type(
        self,
        patient_id: str,
        recording_id: str,
        annotation_type: str
    ) -> List[Annotation]:
        """
        Get annotations of a specific type.

        Args:
            patient_id: Patient identifier
            recording_id: Recording identifier
            annotation_type: Type of annotation ('symptom', 'medication', 'activity', 'other')

        Returns:
            List[Annotation]: List of annotations of specified type
        """
        db_path = self.path_resolver.get_patient_db_path(patient_id)

        query = f"""
            SELECT * FROM {TABLE_ANNOTATIONS}
            WHERE recording_id = ?
            AND annotation_type = ?
            ORDER BY timestamp_seconds ASC
        """

        with self.adapter.get_connection(db_path) as conn:
            return self._fetch_all(conn, query, (recording_id, annotation_type))

    def get_all_by_type(
        self,
        patient_id: str,
        annotation_type: str
    ) -> List[Annotation]:
        """
        Get all annotations of a specific type across all recordings.

        Args:
            patient_id: Patient identifier
            annotation_type: Type of annotation ('symptom', 'medication', 'activity', 'other')

        Returns:
            List[Annotation]: List of annotations of specified type
        """
        db_path = self.path_resolver.get_patient_db_path(patient_id)

        query = f"""
            SELECT * FROM {TABLE_ANNOTATIONS}
            WHERE annotation_type = ?
            ORDER BY created_at DESC
        """

        with self.adapter.get_connection(db_path) as conn:
            return self._fetch_all(conn, query, (annotation_type,))

    def update(self, patient_id: str, annotation: Annotation) -> Annotation:
        """
        Update existing annotation.

        Args:
            patient_id: Patient identifier
            annotation: Annotation with updated values

        Returns:
            Annotation: Updated annotation

        Raises:
            ValueError: If annotation not found
        """
        db_path = self.path_resolver.get_patient_db_path(patient_id)

        # Update the updated_at timestamp
        annotation.updated_at = datetime.now()

        query = f"""
            UPDATE {TABLE_ANNOTATIONS}
            SET recording_id = ?,
                timestamp_seconds = ?,
                annotation_type = ?,
                label = ?,
                description = ?,
                severity = ?,
                metadata = ?,
                updated_at = ?
            WHERE id = ?
        """

        data = annotation.to_dict()

        try:
            with self.adapter.transaction(db_path) as conn:
                rows_affected = self._execute_query(conn, query, (
                    data['recording_id'],
                    data['timestamp_seconds'],
                    data['annotation_type'],
                    data['label'],
                    data['description'],
                    data['severity'],
                    data['metadata'],
                    data['updated_at'],
                    data['id']
                ))

                if rows_affected == 0:
                    raise ValueError(f"Annotation {annotation.id} not found")

            self.logger.info(f"Updated annotation: {annotation.id}")
            return self.get_by_id(patient_id, annotation.id)

        except sqlite3.Error as e:
            self.logger.error(f"Failed to update annotation {annotation.id}: {e}")
            raise

    def delete(self, patient_id: str, annotation_id: str) -> None:
        """
        Delete annotation.

        Args:
            patient_id: Patient identifier
            annotation_id: Annotation identifier

        Raises:
            ValueError: If annotation not found
        """
        db_path = self.path_resolver.get_patient_db_path(patient_id)

        query = f"DELETE FROM {TABLE_ANNOTATIONS} WHERE id = ?"

        try:
            with self.adapter.transaction(db_path) as conn:
                rows_affected = self._execute_query(conn, query, (annotation_id,))

                if rows_affected == 0:
                    raise ValueError(f"Annotation {annotation_id} not found")

            self.logger.info(f"Deleted annotation: {annotation_id}")

        except sqlite3.Error as e:
            self.logger.error(f"Failed to delete annotation {annotation_id}: {e}")
            raise

    def delete_by_recording(self, patient_id: str, recording_id: str) -> int:
        """
        Delete all annotations for a recording.

        Args:
            patient_id: Patient identifier
            recording_id: Recording identifier

        Returns:
            int: Number of annotations deleted
        """
        db_path = self.path_resolver.get_patient_db_path(patient_id)

        query = f"DELETE FROM {TABLE_ANNOTATIONS} WHERE recording_id = ?"

        try:
            with self.adapter.transaction(db_path) as conn:
                rows_affected = self._execute_query(conn, query, (recording_id,))

            self.logger.info(f"Deleted {rows_affected} annotations for recording {recording_id}")
            return rows_affected

        except sqlite3.Error as e:
            self.logger.error(f"Failed to delete annotations for recording {recording_id}: {e}")
            raise

    def count_by_recording(self, patient_id: str, recording_id: str) -> int:
        """
        Count annotations for a recording.

        Args:
            patient_id: Patient identifier
            recording_id: Recording identifier

        Returns:
            int: Number of annotations
        """
        db_path = self.path_resolver.get_patient_db_path(patient_id)

        query = f"""
            SELECT COUNT(*) as count
            FROM {TABLE_ANNOTATIONS}
            WHERE recording_id = ?
        """

        with self.adapter.get_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(query, (recording_id,))
            row = cursor.fetchone()
            return row['count'] if row else 0

    def count_by_type(self, patient_id: str, recording_id: str, annotation_type: str) -> int:
        """
        Count annotations of a specific type for a recording.

        Args:
            patient_id: Patient identifier
            recording_id: Recording identifier
            annotation_type: Type of annotation

        Returns:
            int: Number of annotations of specified type
        """
        db_path = self.path_resolver.get_patient_db_path(patient_id)

        query = f"""
            SELECT COUNT(*) as count
            FROM {TABLE_ANNOTATIONS}
            WHERE recording_id = ?
            AND annotation_type = ?
        """

        with self.adapter.get_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(query, (recording_id, annotation_type))
            row = cursor.fetchone()
            return row['count'] if row else 0
