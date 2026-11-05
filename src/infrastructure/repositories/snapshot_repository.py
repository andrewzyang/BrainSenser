"""
SnapshotRepository for managing BrainSense frequency snapshots.

This repository provides database operations for snapshot_data table in
per-patient databases. It implements:
- Batch insertion with automatic deduplication (INSERT OR IGNORE)
- Querying records by patient with pagination
- Counting total records
- Getting date ranges

Author: iEEG BrainSense Development Team
Last Updated: 2025-10-01
"""

import sqlite3
from typing import Optional, Tuple, List
from datetime import datetime

from src.infrastructure.repositories.base_repository import BaseRepository
from src.infrastructure.database.adapters.sqlite_adapter import SQLiteAdapter
from src.core.path_resolver import PathResolver
from src.core.models import SnapshotRecord


class SnapshotRepository(BaseRepository[SnapshotRecord]):
    """
    Repository for snapshot_data table operations.

    This repository manages BrainSense frequency snapshots with:
    - Hash-based deduplication using INSERT OR IGNORE
    - Batch insertion for performance
    - JSON field storage (frequency_data, power_data, fft_output)
    - Query operations with pagination
    - Statistics (count, date range)

    The repository operates on per-patient databases. All methods
    require patient_id to determine which database to use.

    Example:
        >>> from src.infrastructure.database.adapters import SQLiteAdapter
        >>> from src.core.path_resolver import PathResolver
        >>> from src.core.models import SnapshotRecord
        >>> from datetime import datetime
        >>> import json
        >>>
        >>> adapter = SQLiteAdapter()
        >>> resolver = PathResolver()
        >>> repo = SnapshotRepository(adapter, resolver)
        >>>
        >>> # Insert batch with deduplication
        >>> records = [
        ...     SnapshotRecord(
        ...         timestamp=datetime.now(),
        ...         frequency_data=json.dumps([1.0, 2.0, 3.0]),
        ...         power_data=json.dumps([10.0, 20.0, 30.0]),
        ...         hemisphere="LEFT",
        ...         source_file="test.json",
        ...         data_hash="def456"
        ...     )
        ... ]
        >>> inserted, duplicates = repo.insert_batch("PATIENT001", records)
        >>> print(f"Inserted: {inserted}, Duplicates: {duplicates}")
    """

    def __init__(self, adapter: SQLiteAdapter, path_resolver: PathResolver):
        """
        Initialize SnapshotRepository.

        Args:
            adapter: SQLiteAdapter for database operations
            path_resolver: PathResolver for database paths
        """
        super().__init__(adapter, path_resolver)

    def _map_row_to_model(self, row: sqlite3.Row) -> SnapshotRecord:
        """
        Convert database row to SnapshotRecord.

        Args:
            row: Database row from sqlite3.Row

        Returns:
            SnapshotRecord: Populated SnapshotRecord instance
        """
        return SnapshotRecord.from_row(dict(row))

    def insert_batch(
        self,
        patient_id: str,
        records: List[SnapshotRecord],
        conn: Optional[sqlite3.Connection] = None
    ) -> Tuple[int, int]:
        """
        Insert snapshot records with automatic deduplication.

        Uses INSERT OR IGNORE with data_hash UNIQUE constraint to
        automatically skip duplicates. Returns counts of inserted
        and duplicate records.

        Args:
            patient_id: Patient identifier
            records: List of SnapshotRecord instances
            conn: Optional connection (for transactions)

        Returns:
            Tuple[int, int]: (inserted_count, duplicate_count)

        Raises:
            sqlite3.Error: If database operation fails

        Example:
            >>> records = [SnapshotRecord(...), SnapshotRecord(...)]
            >>> inserted, duplicates = repo.insert_batch("PATIENT001", records)
            >>> print(f"Inserted: {inserted}, Duplicates: {duplicates}")
        """
        if not records:
            self.logger.debug("No records to insert")
            return (0, 0)

        db_path = self.path_resolver.get_patient_db_path(patient_id)
        original_count = len(records)

        query = """
        INSERT OR IGNORE INTO snapshot_data (
            timestamp, unix_timestamp,
            event_type, event_subtype, event_name,
            frequency_data, power_data, fft_output,
            hemisphere,
            source_file, session_id, duration_seconds, sampling_rate,
            patient_event, patient_event_id, event_notes,
            therapy_amplitude_left, therapy_amplitude_right, therapy_frequency,
            data_hash
        ) VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
        )
        """

        try:
            # Use provided connection or create new one
            if conn is not None:
                cursor = conn.cursor()
                initial_count = cursor.execute("SELECT COUNT(*) FROM snapshot_data").fetchone()[0]

                for record in records:
                    data = record.to_dict()
                    cursor.execute(query, (
                        data['timestamp'], data['unix_timestamp'],
                        data['event_type'], data['event_subtype'], data['event_name'],
                        data['frequency_data'], data['power_data'], data['fft_output'],
                        data['hemisphere'],
                        data['source_file'], data['session_id'], data['duration_seconds'], data['sampling_rate'],
                        data['patient_event'], data['patient_event_id'], data['event_notes'],
                        data['therapy_amplitude_left'], data['therapy_amplitude_right'], data['therapy_frequency'],
                        data['data_hash']
                    ))

                final_count = cursor.execute("SELECT COUNT(*) FROM snapshot_data").fetchone()[0]
                inserted_count = final_count - initial_count
                duplicate_count = original_count - inserted_count

            else:
                with self.adapter.get_connection(db_path) as conn:
                    cursor = conn.cursor()
                    initial_count = cursor.execute("SELECT COUNT(*) FROM snapshot_data").fetchone()[0]

                    for record in records:
                        data = record.to_dict()
                        cursor.execute(query, (
                            data['timestamp'], data['unix_timestamp'],
                            data['event_type'], data['event_subtype'], data['event_name'],
                            data['frequency_data'], data['power_data'], data['fft_output'],
                            data['hemisphere'],
                            data['source_file'], data['session_id'], data['duration_seconds'], data['sampling_rate'],
                            data['patient_event'], data['patient_event_id'], data['event_notes'],
                            data['therapy_amplitude_left'], data['therapy_amplitude_right'], data['therapy_frequency'],
                            data['data_hash']
                        ))

                    final_count = cursor.execute("SELECT COUNT(*) FROM snapshot_data").fetchone()[0]
                    inserted_count = final_count - initial_count
                    duplicate_count = original_count - inserted_count

                    conn.commit()

            self.logger.info(f"Inserted {inserted_count} snapshot records, {duplicate_count} duplicates skipped")
            return (inserted_count, duplicate_count)

        except sqlite3.Error as e:
            self.logger.error(f"Database error in insert_batch: {e}")
            raise
        except Exception as e:
            self.logger.error(f"Unexpected error in insert_batch: {e}")
            raise

    def get_by_patient(
        self,
        patient_id: str,
        limit: int = 100,
        offset: int = 0,
        conn: Optional[sqlite3.Connection] = None
    ) -> List[SnapshotRecord]:
        """
        Get snapshot records for patient with pagination.

        Args:
            patient_id: Patient identifier
            limit: Maximum number of records to return (default 100)
            offset: Number of records to skip (default 0)
            conn: Optional connection (for transactions)

        Returns:
            List[SnapshotRecord]: List of snapshot records (empty if none found)

        Raises:
            sqlite3.Error: If database operation fails

        Example:
            >>> records = repo.get_by_patient("PATIENT001", limit=50)
            >>> for record in records:
            ...     print(record.timestamp, record.event_type)
        """
        db_path = self.path_resolver.get_patient_db_path(patient_id)
        query = """
        SELECT * FROM snapshot_data
        ORDER BY timestamp DESC
        LIMIT ? OFFSET ?
        """

        try:
            if conn is not None:
                return self._fetch_all(conn, query, (limit, offset))
            else:
                with self.adapter.get_connection(db_path) as conn:
                    return self._fetch_all(conn, query, (limit, offset))

        except sqlite3.Error as e:
            self.logger.error(f"Database error in get_by_patient: {e}")
            raise
        except Exception as e:
            self.logger.error(f"Unexpected error in get_by_patient: {e}")
            raise

    def get_count(
        self,
        patient_id: str,
        conn: Optional[sqlite3.Connection] = None
    ) -> int:
        """
        Count total snapshot records for patient.

        Args:
            patient_id: Patient identifier
            conn: Optional connection (for transactions)

        Returns:
            int: Number of snapshot records

        Raises:
            sqlite3.Error: If database operation fails

        Example:
            >>> count = repo.get_count("PATIENT001")
            >>> print(f"Patient has {count} snapshot records")
        """
        db_path = self.path_resolver.get_patient_db_path(patient_id)
        query = "SELECT COUNT(*) FROM snapshot_data"

        try:
            if conn is not None:
                cursor = conn.cursor()
                result = cursor.execute(query).fetchone()
                return result[0] if result else 0
            else:
                with self.adapter.get_connection(db_path) as conn:
                    cursor = conn.cursor()
                    result = cursor.execute(query).fetchone()
                    return result[0] if result else 0

        except sqlite3.Error as e:
            self.logger.error(f"Database error in get_count: {e}")
            raise
        except Exception as e:
            self.logger.error(f"Unexpected error in get_count: {e}")
            raise

    def get_date_range(
        self,
        patient_id: str,
        conn: Optional[sqlite3.Connection] = None
    ) -> Optional[Tuple[datetime, datetime]]:
        """
        Get min and max dates for patient's snapshot data.

        Args:
            patient_id: Patient identifier
            conn: Optional connection (for transactions)

        Returns:
            Optional[Tuple[datetime, datetime]]: (min_date, max_date) or None if no records

        Raises:
            sqlite3.Error: If database operation fails

        Example:
            >>> date_range = repo.get_date_range("PATIENT001")
            >>> if date_range:
            ...     min_date, max_date = date_range
            ...     print(f"Data from {min_date} to {max_date}")
        """
        db_path = self.path_resolver.get_patient_db_path(patient_id)
        query = "SELECT MIN(timestamp), MAX(timestamp) FROM snapshot_data"

        try:
            if conn is not None:
                cursor = conn.cursor()
                result = cursor.execute(query).fetchone()
            else:
                with self.adapter.get_connection(db_path) as conn:
                    cursor = conn.cursor()
                    result = cursor.execute(query).fetchone()

            if result and result[0] and result[1]:
                min_date = datetime.fromisoformat(result[0])
                max_date = datetime.fromisoformat(result[1])
                return (min_date, max_date)
            else:
                return None

        except sqlite3.Error as e:
            self.logger.error(f"Database error in get_date_range: {e}")
            raise
        except Exception as e:
            self.logger.error(f"Unexpected error in get_date_range: {e}")
            raise

    def get_by_time_range(
        self,
        patient_id: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        patient_events_only: bool = True,
        limit: int = 100000,
        offset: int = 0,
        conn: Optional[sqlite3.Connection] = None
    ) -> List[SnapshotRecord]:
        """
        Get snapshot records within a time range.

        Args:
            patient_id: Patient identifier
            start_time: Start of time range (inclusive), None = no lower bound
            end_time: End of time range (inclusive), None = no upper bound
            patient_events_only: If True, only return patient-triggered events (default True)
            limit: Maximum number of records to return (default 10000)
            offset: Number of records to skip (default 0)
            conn: Optional connection (for transactions)

        Returns:
            List[SnapshotRecord]: List of snapshot records in time range

        Raises:
            sqlite3.Error: If database operation fails

        Example:
            >>> from datetime import datetime, timedelta
            >>> end = datetime.now()
            >>> start = end - timedelta(days=7)
            >>> records = repo.get_by_time_range("PATIENT001", start, end)
            >>> print(f"Found {len(records)} patient events in last week")
        """
        db_path = self.path_resolver.get_patient_db_path(patient_id)

        # Build query based on constraints
        conditions = []
        params = []

        if start_time is not None:
            conditions.append("timestamp >= ?")
            params.append(start_time.isoformat())

        if end_time is not None:
            conditions.append("timestamp <= ?")
            params.append(end_time.isoformat())

        if patient_events_only:
            conditions.append("patient_event = 1")

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        query = f"""
        SELECT * FROM snapshot_data
        WHERE {where_clause}
        ORDER BY timestamp ASC
        LIMIT ? OFFSET ?
        """

        params.extend([limit, offset])

        try:
            if conn is not None:
                return self._fetch_all(conn, query, tuple(params))
            else:
                with self.adapter.get_connection(db_path) as conn:
                    return self._fetch_all(conn, query, tuple(params))

        except sqlite3.Error as e:
            self.logger.error(f"Database error in get_by_time_range: {e}")
            raise
        except Exception as e:
            self.logger.error(f"Unexpected error in get_by_time_range: {e}")
            raise
