"""
Repository for streaming_recordings table operations.

This module provides CRUD operations for the StreamingRecording model, managing
complete streaming recording files (original or trimmed) for streaming data management.
This is different from StreamingRepository which manages individual waveform segments.

Features:
- Create/read/update/delete streaming recordings
- Query by patient, date range, trimmed status
- Retrieve original and trimmed recordings
- Transaction support

Author: iEEG BrainSense Development Team
Last Updated: 2025-10-07
"""

import sqlite3
from datetime import datetime
from typing import Optional, List

from .base_repository import BaseRepository
from src.core.models import StreamingRecording
from src.infrastructure.database.schema.patient_schema import TABLE_STREAMING_RECORDINGS


class StreamingRecordingRepository(BaseRepository[StreamingRecording]):
    """
    Repository for StreamingRecording model / streaming_recordings table.

    Provides CRUD operations for complete streaming recording files.
    All operations use per-patient databases (brainsense_data.db).

    Example:
        >>> adapter = SQLiteAdapter()
        >>> resolver = PathResolver()
        >>> repo = StreamingRecordingRepository(adapter, resolver)
        >>>
        >>> # Create recording
        >>> recording = repo.create(
        ...     patient_id="P01",
        ...     recording_id="rec_001",
        ...     file_path="/data/P01/recording.json",
        ...     duration_seconds=2732.5,
        ...     sampling_rate=250.0,
        ...     channel_count=4,
        ...     channel_labels=["Ch0_Left_STN", "Ch1_Left_STN", "Ch2_Right_STN", "Ch3_Right_STN"]
        ... )
        >>>
        >>> # Get recording
        >>> recording = repo.get_by_id("P01", "rec_001")
        >>>
        >>> # Get all recordings for patient
        >>> recordings = repo.get_by_patient("P01")
    """

    def _map_row_to_model(self, row: sqlite3.Row) -> StreamingRecording:
        """
        Convert database row to StreamingRecording model.

        Args:
            row: Database row with streaming_recordings columns

        Returns:
            StreamingRecording: StreamingRecording model instance
        """
        row_dict = dict(row)
        return StreamingRecording.from_dict(row_dict)

    def create(self, patient_id: str, recording: StreamingRecording) -> StreamingRecording:
        """
        Create new streaming recording.

        Args:
            patient_id: Patient identifier
            recording: StreamingRecording instance to create

        Returns:
            StreamingRecording: Created recording

        Raises:
            sqlite3.IntegrityError: If recording ID already exists
        """
        db_path = self.path_resolver.get_patient_db_path(patient_id)

        query = f"""
            INSERT INTO {TABLE_STREAMING_RECORDINGS}
            (id, patient_id, file_path, original_file_path, recording_date,
             duration_seconds, start_time, end_time, is_trimmed, file_size_bytes,
             sampling_rate, channel_count, channel_labels, metadata,
             processing_applied, file_checksum, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """

        data = recording.to_dict()

        try:
            with self.adapter.transaction(db_path) as conn:
                self._execute_query(conn, query, (
                    data['id'],
                    data['patient_id'],
                    data['file_path'],
                    data['original_file_path'],
                    data['recording_date'],
                    data['duration_seconds'],
                    data['start_time'],
                    data['end_time'],
                    data['is_trimmed'],
                    data['file_size_bytes'],
                    data['sampling_rate'],
                    data['channel_count'],
                    data['channel_labels'],
                    data['metadata'],
                    data['processing_applied'],
                    data['file_checksum'],
                    data['created_at'],
                    data['updated_at']
                ))

            self.logger.info(f"Created streaming recording: {recording.id} for patient {patient_id}")
            return self.get_by_id(patient_id, recording.id)

        except sqlite3.IntegrityError as e:
            self.logger.error(f"Failed to create recording {recording.id}: {e}")
            raise

    def get_by_id(self, patient_id: str, recording_id: str) -> Optional[StreamingRecording]:
        """
        Get streaming recording by ID.

        Args:
            patient_id: Patient identifier
            recording_id: Recording identifier

        Returns:
            Optional[StreamingRecording]: Recording or None if not found
        """
        db_path = self.path_resolver.get_patient_db_path(patient_id)

        query = f"SELECT * FROM {TABLE_STREAMING_RECORDINGS} WHERE id = ?"

        with self.adapter.get_connection(db_path) as conn:
            return self._fetch_one(conn, query, (recording_id,))

    def get_by_patient(self, patient_id: str) -> List[StreamingRecording]:
        """
        Get all recordings for a patient.

        Args:
            patient_id: Patient identifier

        Returns:
            List[StreamingRecording]: List of recordings (may be empty)
        """
        db_path = self.path_resolver.get_patient_db_path(patient_id)

        query = f"""
            SELECT * FROM {TABLE_STREAMING_RECORDINGS}
            WHERE patient_id = ?
            ORDER BY recording_date DESC
        """

        with self.adapter.get_connection(db_path) as conn:
            return self._fetch_all(conn, query, (patient_id,))

    def get_by_date_range(
        self,
        patient_id: str,
        start_date: datetime,
        end_date: datetime
    ) -> List[StreamingRecording]:
        """
        Get recordings within a date range.

        Args:
            patient_id: Patient identifier
            start_date: Start of date range (inclusive)
            end_date: End of date range (inclusive)

        Returns:
            List[StreamingRecording]: List of recordings in range
        """
        db_path = self.path_resolver.get_patient_db_path(patient_id)

        query = f"""
            SELECT * FROM {TABLE_STREAMING_RECORDINGS}
            WHERE patient_id = ?
            AND recording_date >= ?
            AND recording_date <= ?
            ORDER BY recording_date DESC
        """

        with self.adapter.get_connection(db_path) as conn:
            return self._fetch_all(conn, query, (
                patient_id,
                start_date.isoformat(),
                end_date.isoformat()
            ))

    def get_trimmed_recordings(self, patient_id: str) -> List[StreamingRecording]:
        """
        Get only trimmed recordings.

        Args:
            patient_id: Patient identifier

        Returns:
            List[StreamingRecording]: List of trimmed recordings
        """
        db_path = self.path_resolver.get_patient_db_path(patient_id)

        query = f"""
            SELECT * FROM {TABLE_STREAMING_RECORDINGS}
            WHERE patient_id = ?
            AND is_trimmed = 1
            ORDER BY recording_date DESC
        """

        with self.adapter.get_connection(db_path) as conn:
            return self._fetch_all(conn, query, (patient_id,))

    def get_original_recordings(self, patient_id: str) -> List[StreamingRecording]:
        """
        Get only original (non-trimmed) recordings.

        Args:
            patient_id: Patient identifier

        Returns:
            List[StreamingRecording]: List of original recordings
        """
        db_path = self.path_resolver.get_patient_db_path(patient_id)

        query = f"""
            SELECT * FROM {TABLE_STREAMING_RECORDINGS}
            WHERE patient_id = ?
            AND is_trimmed = 0
            ORDER BY recording_date DESC
        """

        with self.adapter.get_connection(db_path) as conn:
            return self._fetch_all(conn, query, (patient_id,))

    def update(self, patient_id: str, recording: StreamingRecording) -> StreamingRecording:
        """
        Update existing recording.

        Args:
            patient_id: Patient identifier
            recording: StreamingRecording with updated values

        Returns:
            StreamingRecording: Updated recording

        Raises:
            ValueError: If recording not found
        """
        db_path = self.path_resolver.get_patient_db_path(patient_id)

        # Update the updated_at timestamp
        recording.updated_at = datetime.now()

        query = f"""
            UPDATE {TABLE_STREAMING_RECORDINGS}
            SET file_path = ?,
                original_file_path = ?,
                recording_date = ?,
                duration_seconds = ?,
                start_time = ?,
                end_time = ?,
                is_trimmed = ?,
                file_size_bytes = ?,
                sampling_rate = ?,
                channel_count = ?,
                channel_labels = ?,
                metadata = ?,
                processing_applied = ?,
                file_checksum = ?,
                updated_at = ?
            WHERE id = ?
        """

        data = recording.to_dict()

        try:
            with self.adapter.transaction(db_path) as conn:
                rows_affected = self._execute_query(conn, query, (
                    data['file_path'],
                    data['original_file_path'],
                    data['recording_date'],
                    data['duration_seconds'],
                    data['start_time'],
                    data['end_time'],
                    data['is_trimmed'],
                    data['file_size_bytes'],
                    data['sampling_rate'],
                    data['channel_count'],
                    data['channel_labels'],
                    data['metadata'],
                    data['processing_applied'],
                    data['file_checksum'],
                    data['updated_at'],
                    data['id']
                ))

                if rows_affected == 0:
                    raise ValueError(f"Recording {recording.id} not found")

            self.logger.info(f"Updated recording: {recording.id}")
            return self.get_by_id(patient_id, recording.id)

        except sqlite3.Error as e:
            self.logger.error(f"Failed to update recording {recording.id}: {e}")
            raise

    def delete(self, patient_id: str, recording_id: str) -> None:
        """
        Delete recording (and cascade delete annotations).

        Args:
            patient_id: Patient identifier
            recording_id: Recording identifier

        Raises:
            ValueError: If recording not found
        """
        db_path = self.path_resolver.get_patient_db_path(patient_id)

        query = f"DELETE FROM {TABLE_STREAMING_RECORDINGS} WHERE id = ?"

        try:
            with self.adapter.transaction(db_path) as conn:
                rows_affected = self._execute_query(conn, query, (recording_id,))

                if rows_affected == 0:
                    raise ValueError(f"Recording {recording_id} not found")

            self.logger.info(f"Deleted recording: {recording_id}")

        except sqlite3.Error as e:
            self.logger.error(f"Failed to delete recording {recording_id}: {e}")
            raise

    def count_by_patient(self, patient_id: str) -> int:
        """
        Count total recordings for a patient.

        Args:
            patient_id: Patient identifier

        Returns:
            int: Total number of recordings
        """
        db_path = self.path_resolver.get_patient_db_path(patient_id)

        query = f"""
            SELECT COUNT(*) as count
            FROM {TABLE_STREAMING_RECORDINGS}
            WHERE patient_id = ?
        """

        with self.adapter.get_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(query, (patient_id,))
            row = cursor.fetchone()
            return row['count'] if row else 0
