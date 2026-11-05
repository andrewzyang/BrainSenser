"""
StreamingRepository for managing BrainSense streaming waveform data.

This repository provides database operations for indefinite_streaming and
definite_streaming tables in per-patient streaming databases. It implements:
- Batch insertion with automatic deduplication (INSERT OR IGNORE)
- Querying records by patient with pagination
- Counting total records by type
- Getting date ranges

Author: iEEG BrainSense Development Team
Last Updated: 2025-10-02
"""

import sqlite3
from typing import Optional, Tuple, List
from datetime import datetime

from src.infrastructure.repositories.base_repository import BaseRepository
from src.infrastructure.database.adapters.sqlite_adapter import SQLiteAdapter
from src.core.path_resolver import PathResolver
from src.core.models import StreamingRecord


class StreamingRepository(BaseRepository[StreamingRecord]):
    """
    Repository for streaming data table operations.

    This repository manages BrainSense streaming waveform recordings with:
    - Hash-based deduplication using INSERT OR IGNORE
    - Batch insertion for performance
    - Separate tables for indefinite and definite streaming
    - Query operations with pagination

    The repository operates on per-patient streaming databases. All methods
    require patient_id to determine which database to use.

    Example:
        >>> from src.infrastructure.database.adapters import SQLiteAdapter
        >>> from src.core.path_resolver import PathResolver
        >>> from src.core.models import StreamingRecord
        >>> from datetime import datetime
        >>>
        >>> adapter = SQLiteAdapter()
        >>> resolver = PathResolver()
        >>> repo = StreamingRepository(adapter, resolver)
        >>>
        >>> # Insert batch with deduplication
        >>> records = [
        ...     StreamingRecord(
        ...         timestamp=datetime.now(),
        ...         channel="ZERO_THREE_LEFT",
        ...         waveform_data='[20.4, 20.1, ...]',
        ...         sample_count=3563,
        ...         sample_rate=250,
        ...         source_file="test.json",
        ...         data_hash="abc123",
        ...         streaming_type="indefinite"
        ...     )
        ... ]
        >>> inserted, duplicates = repo.insert_batch("PATIENT001", records)
        >>> print(f"Inserted: {inserted}, Duplicates: {duplicates}")
    """

    def __init__(self, adapter: SQLiteAdapter, path_resolver: PathResolver):
        """
        Initialize StreamingRepository.

        Args:
            adapter: SQLiteAdapter for database operations
            path_resolver: PathResolver for database paths
        """
        super().__init__(adapter, path_resolver)

    def _map_row_to_model(self, row: sqlite3.Row) -> StreamingRecord:
        """
        Convert database row to StreamingRecord.

        Args:
            row: Database row from sqlite3.Row

        Returns:
            StreamingRecord: Populated StreamingRecord instance
        """
        row_dict = dict(row)

        return StreamingRecord(
            timestamp=datetime.fromisoformat(row_dict['timestamp']) if row_dict.get('timestamp') else datetime.now(),
            unix_timestamp=row_dict.get('unix_timestamp'),
            channel=row_dict.get('channel') or "",
            hemisphere=row_dict.get('hemisphere'),
            waveform_data=row_dict.get('waveform_data') or "",
            sample_count=row_dict.get('sample_count') or 0,
            sample_rate=row_dict.get('sample_rate') or 0,
            duration_seconds=row_dict.get('duration_seconds'),
            gain=row_dict.get('gain'),
            global_sequences=row_dict.get('global_sequences'),
            global_packet_sizes=row_dict.get('global_packet_sizes'),
            ticks_in_mses=row_dict.get('ticks_in_mses'),
            pass_info=row_dict.get('pass_info'),
            source_file=row_dict.get('source_file') or "",
            session_id=row_dict.get('session_id'),
            data_hash=row_dict.get('data_hash') or "",
            streaming_type=row_dict.get('streaming_type') or "indefinite"
        )

    def insert_batch(
        self,
        patient_id: str,
        records: List[StreamingRecord],
        conn: Optional[sqlite3.Connection] = None
    ) -> Tuple[int, int]:
        """
        Insert streaming records with automatic deduplication.

        Uses INSERT OR IGNORE with data_hash UNIQUE constraint to
        automatically skip duplicates. Returns counts of inserted
        and duplicate records.

        Records are routed to appropriate table based on streaming_type:
        - "indefinite" → indefinite_streaming table
        - "definite" → definite_streaming table

        Args:
            patient_id: Patient identifier
            records: List of StreamingRecord instances
            conn: Optional connection (for transactions)

        Returns:
            Tuple[int, int]: (inserted_count, duplicate_count)

        Raises:
            sqlite3.Error: If database operation fails

        Example:
            >>> records = [StreamingRecord(...), StreamingRecord(...)]
            >>> inserted, duplicates = repo.insert_batch("PATIENT001", records)
            >>> print(f"Inserted: {inserted}, Duplicates: {duplicates}")
        """
        if not records:
            self.logger.debug("No records to insert")
            return (0, 0)

        # Use patient database - NOT a separate streaming database
        db_path = self.path_resolver.get_patient_db_path(patient_id)
        original_count = len(records)

        # Separate records by type
        indefinite_records = [r for r in records if r.streaming_type == "indefinite"]
        definite_records = [r for r in records if r.streaming_type == "definite"]

        total_inserted = 0
        total_duplicates = 0

        try:
            # Use provided connection (for transactions) or create new one
            should_close = False
            if conn is None:
                conn = self.adapter.get_connection(db_path)
                should_close = True

            # Insert indefinite streaming records
            if indefinite_records:
                inserted, duplicates = self._insert_indefinite_batch(conn, indefinite_records)
                total_inserted += inserted
                total_duplicates += duplicates

            # Insert definite streaming records
            if definite_records:
                inserted, duplicates = self._insert_definite_batch(conn, definite_records)
                total_inserted += inserted
                total_duplicates += duplicates

            if should_close:
                conn.commit()
                conn.close()

            self.logger.info(
                f"Inserted {total_inserted}/{original_count} streaming records "
                f"({total_duplicates} duplicates) for patient {patient_id}"
            )

            return (total_inserted, total_duplicates)

        except sqlite3.Error as e:
            self.logger.error(f"Database error in insert_batch: {e}")
            if should_close and conn:
                conn.close()
            raise

    def _insert_indefinite_batch(
        self,
        conn: sqlite3.Connection,
        records: List[StreamingRecord]
    ) -> Tuple[int, int]:
        """Insert indefinite streaming records."""
        query = """
        INSERT OR IGNORE INTO indefinite_streaming (
            timestamp, unix_timestamp,
            channel, hemisphere,
            waveform_data, sample_count, sample_rate, duration_seconds,
            gain,
            global_sequences, global_packet_sizes, ticks_in_mses, pass_info,
            source_file, session_id,
            data_hash
        ) VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
        )
        """

        cursor = conn.cursor()
        rows_before = cursor.execute("SELECT COUNT(*) FROM indefinite_streaming").fetchone()[0]

        for record in records:
            cursor.execute(query, (
                record.timestamp.isoformat() if record.timestamp else None,
                record.unix_timestamp,
                record.channel,
                record.hemisphere,
                record.waveform_data,
                record.sample_count,
                record.sample_rate,
                record.duration_seconds,
                record.gain,
                record.global_sequences,
                record.global_packet_sizes,
                record.ticks_in_mses,
                record.pass_info,
                record.source_file,
                record.session_id,
                record.data_hash
            ))

        rows_after = cursor.execute("SELECT COUNT(*) FROM indefinite_streaming").fetchone()[0]
        inserted = rows_after - rows_before
        duplicates = len(records) - inserted

        return (inserted, duplicates)

    def _insert_definite_batch(
        self,
        conn: sqlite3.Connection,
        records: List[StreamingRecord]
    ) -> Tuple[int, int]:
        """Insert definite streaming records."""
        query = """
        INSERT OR IGNORE INTO definite_streaming (
            timestamp, unix_timestamp,
            channel, hemisphere,
            waveform_data, sample_count, sample_rate, duration_seconds,
            gain,
            trigger_type, trigger_timestamp,
            global_sequences, global_packet_sizes, ticks_in_mses, pass_info,
            source_file, session_id,
            data_hash
        ) VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?, ?, ?, ?, ?, ?
        )
        """

        cursor = conn.cursor()
        rows_before = cursor.execute("SELECT COUNT(*) FROM definite_streaming").fetchone()[0]

        for record in records:
            cursor.execute(query, (
                record.timestamp.isoformat() if record.timestamp else None,
                record.unix_timestamp,
                record.channel,
                record.hemisphere,
                record.waveform_data,
                record.sample_count,
                record.sample_rate,
                record.duration_seconds,
                record.gain,
                record.global_sequences,
                record.global_packet_sizes,
                record.ticks_in_mses,
                record.pass_info,
                record.source_file,
                record.session_id,
                record.data_hash
            ))

        rows_after = cursor.execute("SELECT COUNT(*) FROM definite_streaming").fetchone()[0]
        inserted = rows_after - rows_before
        duplicates = len(records) - inserted

        return (inserted, duplicates)

    def count_by_type(
        self,
        patient_id: str,
        streaming_type: str = "indefinite",
        conn: Optional[sqlite3.Connection] = None
    ) -> int:
        """
        Count streaming records by type.

        Args:
            patient_id: Patient identifier
            streaming_type: "indefinite" or "definite"
            conn: Optional connection (for transactions)

        Returns:
            int: Number of records

        Raises:
            sqlite3.Error: If database operation fails
        """
        # Use patient database - NOT a separate streaming database
        db_path = self.path_resolver.get_patient_db_path(patient_id)
        table_name = f"{streaming_type}_streaming"
        query = f"SELECT COUNT(*) FROM {table_name}"

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
            self.logger.error(f"Database error in count_by_type: {e}")
            raise

    def get_all_by_patient(
        self,
        patient_id: str,
        streaming_type: str = "indefinite",
        conn: Optional[sqlite3.Connection] = None
    ) -> List[StreamingRecord]:
        """
        Get all streaming records for a patient.

        Args:
            patient_id: Patient identifier
            streaming_type: "indefinite" or "definite"
            conn: Optional connection (for transactions)

        Returns:
            List[StreamingRecord]: All streaming records for the patient

        Raises:
            sqlite3.Error: If database operation fails
        """
        db_path = self.path_resolver.get_patient_db_path(patient_id)
        table_name = f"{streaming_type}_streaming"
        query = f"SELECT * FROM {table_name} ORDER BY timestamp ASC"

        try:
            if conn is not None:
                return self._fetch_all(conn, query)
            else:
                with self.adapter.get_connection(db_path) as conn:
                    return self._fetch_all(conn, query)

        except sqlite3.Error as e:
            self.logger.error(f"Database error in get_all_by_patient: {e}")
            raise
