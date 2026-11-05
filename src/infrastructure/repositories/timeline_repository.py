"""
TimelineRepository for managing BrainSense time-domain recordings.

This repository provides database operations for timeline_data table in
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
from src.core.models import TimelineRecord


class TimelineRepository(BaseRepository[TimelineRecord]):
    """
    Repository for timeline_data table operations.

    This repository manages BrainSense time-domain recordings with:
    - Hash-based deduplication using INSERT OR IGNORE
    - Batch insertion for performance
    - Query operations with pagination
    - Statistics (count, date range)

    The repository operates on per-patient databases. All methods
    require patient_id to determine which database to use.

    Example:
        >>> from src.infrastructure.database.adapters import SQLiteAdapter
        >>> from src.core.path_resolver import PathResolver
        >>> from src.core.models import TimelineRecord
        >>> from datetime import datetime
        >>>
        >>> adapter = SQLiteAdapter()
        >>> resolver = PathResolver()
        >>> repo = TimelineRepository(adapter, resolver)
        >>>
        >>> # Insert batch with deduplication
        >>> records = [
        ...     TimelineRecord(
        ...         timestamp=datetime.now(),
        ...         left_hemisphere=100.5,
        ...         source_file="test.json",
        ...         data_hash="abc123"
        ...     )
        ... ]
        >>> inserted, duplicates = repo.insert_batch("PATIENT001", records)
        >>> print(f"Inserted: {inserted}, Duplicates: {duplicates}")
    """

    def __init__(self, adapter: SQLiteAdapter, path_resolver: PathResolver):
        """
        Initialize TimelineRepository.

        Args:
            adapter: SQLiteAdapter for database operations
            path_resolver: PathResolver for database paths
        """
        super().__init__(adapter, path_resolver)

    def _map_row_to_model(self, row: sqlite3.Row) -> TimelineRecord:
        """
        Convert database row to TimelineRecord.

        Args:
            row: Database row from sqlite3.Row

        Returns:
            TimelineRecord: Populated TimelineRecord instance
        """
        return TimelineRecord.from_row(dict(row))

    def insert_batch(
        self,
        patient_id: str,
        records: List[TimelineRecord],
        conn: Optional[sqlite3.Connection] = None
    ) -> Tuple[int, int]:
        """
        Insert timeline records with automatic deduplication.

        Uses INSERT OR IGNORE with data_hash UNIQUE constraint to
        automatically skip duplicates. Returns counts of inserted
        and duplicate records.

        Args:
            patient_id: Patient identifier
            records: List of TimelineRecord instances
            conn: Optional connection (for transactions)

        Returns:
            Tuple[int, int]: (inserted_count, duplicate_count)

        Raises:
            sqlite3.Error: If database operation fails

        Example:
            >>> records = [TimelineRecord(...), TimelineRecord(...)]
            >>> inserted, duplicates = repo.insert_batch("PATIENT001", records)
            >>> print(f"Inserted: {inserted}, Duplicates: {duplicates}")
        """
        if not records:
            self.logger.debug("No records to insert")
            return (0, 0)

        db_path = self.path_resolver.get_patient_db_path(patient_id)
        original_count = len(records)

        query = """
        INSERT OR IGNORE INTO timeline_data (
            timestamp, unix_timestamp,
            left_hemisphere, right_hemisphere,
            left_amplitude, right_amplitude,
            left_frequency, right_frequency,
            left_pulse_width, right_pulse_width,
            therapy_status,
            is_outlier, outlier_reason, outlier_score,
            preprocessing_applied, preprocessing_timestamp,
            original_left_hemisphere, original_right_hemisphere,
            source_file, session_id, segment_id, segment_type,
            data_hash
        ) VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
        )
        """

        try:
            # Use provided connection or create new one
            if conn is not None:
                cursor = conn.cursor()
                initial_count = cursor.execute("SELECT COUNT(*) FROM timeline_data").fetchone()[0]

                for record in records:
                    data = record.to_dict()
                    cursor.execute(query, (
                        data['timestamp'], data['unix_timestamp'],
                        data['left_hemisphere'], data['right_hemisphere'],
                        data['left_amplitude'], data['right_amplitude'],
                        data['left_frequency'], data['right_frequency'],
                        data['left_pulse_width'], data['right_pulse_width'],
                        data['therapy_status'],
                        data['is_outlier'], data['outlier_reason'], data['outlier_score'],
                        data['preprocessing_applied'], data['preprocessing_timestamp'],
                        data['original_left_hemisphere'], data['original_right_hemisphere'],
                        data['source_file'], data['session_id'], data['segment_id'], data['segment_type'],
                        data['data_hash']
                    ))

                final_count = cursor.execute("SELECT COUNT(*) FROM timeline_data").fetchone()[0]
                inserted_count = final_count - initial_count
                duplicate_count = original_count - inserted_count

            else:
                with self.adapter.get_connection(db_path) as conn:
                    cursor = conn.cursor()
                    initial_count = cursor.execute("SELECT COUNT(*) FROM timeline_data").fetchone()[0]

                    for record in records:
                        data = record.to_dict()
                        cursor.execute(query, (
                            data['timestamp'], data['unix_timestamp'],
                            data['left_hemisphere'], data['right_hemisphere'],
                            data['left_amplitude'], data['right_amplitude'],
                            data['left_frequency'], data['right_frequency'],
                            data['left_pulse_width'], data['right_pulse_width'],
                            data['therapy_status'],
                            data['is_outlier'], data['outlier_reason'], data['outlier_score'],
                            data['preprocessing_applied'], data['preprocessing_timestamp'],
                            data['original_left_hemisphere'], data['original_right_hemisphere'],
                            data['source_file'], data['session_id'], data['segment_id'], data['segment_type'],
                            data['data_hash']
                        ))

                    final_count = cursor.execute("SELECT COUNT(*) FROM timeline_data").fetchone()[0]
                    inserted_count = final_count - initial_count
                    duplicate_count = original_count - inserted_count

                    conn.commit()

            self.logger.info(f"Inserted {inserted_count} timeline records, {duplicate_count} duplicates skipped")
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
    ) -> List[TimelineRecord]:
        """
        Get timeline records for patient with pagination.

        Args:
            patient_id: Patient identifier
            limit: Maximum number of records to return (default 100)
            offset: Number of records to skip (default 0)
            conn: Optional connection (for transactions)

        Returns:
            List[TimelineRecord]: List of timeline records (empty if none found)

        Raises:
            sqlite3.Error: If database operation fails

        Example:
            >>> records = repo.get_by_patient("PATIENT001", limit=50)
            >>> for record in records:
            ...     print(record.timestamp, record.left_hemisphere)
        """
        db_path = self.path_resolver.get_patient_db_path(patient_id)
        query = """
        SELECT * FROM timeline_data
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
        Count total timeline records for patient.

        Args:
            patient_id: Patient identifier
            conn: Optional connection (for transactions)

        Returns:
            int: Number of timeline records

        Raises:
            sqlite3.Error: If database operation fails

        Example:
            >>> count = repo.get_count("PATIENT001")
            >>> print(f"Patient has {count} timeline records")
        """
        db_path = self.path_resolver.get_patient_db_path(patient_id)
        query = "SELECT COUNT(*) FROM timeline_data"

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
        Get min and max dates for patient's timeline data.

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
        query = "SELECT MIN(timestamp), MAX(timestamp) FROM timeline_data"

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
        limit: int = 100000,
        offset: int = 0,
        conn: Optional[sqlite3.Connection] = None
    ) -> List[TimelineRecord]:
        """
        Get timeline records within a time range.

        Args:
            patient_id: Patient identifier
            start_time: Start of time range (inclusive), None = no lower bound
            end_time: End of time range (inclusive), None = no upper bound
            limit: Maximum number of records to return (default 10000)
            offset: Number of records to skip (default 0)
            conn: Optional connection (for transactions)

        Returns:
            List[TimelineRecord]: List of timeline records in time range

        Raises:
            sqlite3.Error: If database operation fails

        Example:
            >>> from datetime import datetime, timedelta
            >>> end = datetime.now()
            >>> start = end - timedelta(days=7)
            >>> records = repo.get_by_time_range("PATIENT001", start, end)
            >>> print(f"Found {len(records)} records in last week")
        """
        db_path = self.path_resolver.get_patient_db_path(patient_id)

        # Build query based on time constraints
        conditions = []
        params = []

        if start_time is not None:
            conditions.append("timestamp >= ?")
            params.append(start_time.isoformat())

        if end_time is not None:
            conditions.append("timestamp <= ?")
            params.append(end_time.isoformat())

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        query = f"""
        SELECT * FROM timeline_data
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
