"""
ProcessingMetadataRepository for managing file upload tracking.

This repository provides database operations for processing_metadata table in
per-patient databases. It implements:
- Creating processing metadata records (tracking file uploads)
- Querying upload history by patient
- Checking for duplicate file uploads by hash
- Getting upload statistics

Author: iEEG BrainSense Development Team
Last Updated: 2025-10-01
"""

import sqlite3
from typing import Optional, List, Dict, Any
from pathlib import Path

from src.infrastructure.repositories.base_repository import BaseRepository
from src.infrastructure.database.adapters.sqlite_adapter import SQLiteAdapter
from src.core.path_resolver import PathResolver
from src.core.models import UploadedFile


class ProcessingMetadataRepository(BaseRepository[UploadedFile]):
    """
    Repository for processing_metadata table operations.

    This repository manages file upload tracking and statistics with:
    - Creating processing metadata records after file processing
    - Querying upload history by patient
    - Duplicate file detection via file_hash
    - Upload statistics retrieval

    The repository operates on per-patient databases. All methods
    require patient_id to determine which database to use.

    Example:
        >>> from src.infrastructure.database.adapters import SQLiteAdapter
        >>> from src.core.path_resolver import PathResolver
        >>> from pathlib import Path
        >>>
        >>> adapter = SQLiteAdapter()
        >>> resolver = PathResolver()
        >>> repo = ProcessingMetadataRepository(adapter, resolver)
        >>>
        >>> # Create processing metadata record
        >>> file_info = {
        ...     'file_name': 'test.json',
        ...     'file_path': Path('/data/test.json'),
        ...     'file_hash': 'abc123',
        ...     'file_size_bytes': 1024
        ... }
        >>> counts = {
        ...     'timeline_count': 100,
        ...     'timeline_original_count': 120,
        ...     'snapshot_count': 50,
        ...     'snapshot_original_count': 60,
        ...     'duplicates_skipped': 30
        ... }
        >>> metadata = repo.create("PATIENT001", file_info, counts)
        >>> print(f"Created file ID: {metadata.file_id}")
    """

    def __init__(self, adapter: SQLiteAdapter, path_resolver: PathResolver):
        """
        Initialize ProcessingMetadataRepository.

        Args:
            adapter: SQLiteAdapter for database operations
            path_resolver: PathResolver for database paths
        """
        super().__init__(adapter, path_resolver)

    def _map_row_to_model(self, row: sqlite3.Row) -> UploadedFile:
        """
        Convert database row to UploadedFile.

        Args:
            row: Database row from sqlite3.Row

        Returns:
            UploadedFile: Populated UploadedFile instance
        """
        from datetime import datetime
        import json

        row_dict = dict(row)

        return UploadedFile(
            file_id=row_dict['id'],
            patient_id=row_dict['patient_id'],
            file_name=row_dict['file_name'],
            file_path=Path(row_dict['file_path']),
            file_hash=row_dict['file_hash'],
            file_size_bytes=row_dict.get('file_size_bytes') or 0,
            timeline_count=row_dict.get('timeline_count') or 0,
            timeline_original_count=row_dict.get('timeline_original_count') or 0,
            snapshot_count=row_dict.get('snapshot_count') or 0,
            snapshot_original_count=row_dict.get('snapshot_original_count') or 0,
            indefinite_streaming_count=row_dict.get('indefinite_streaming_count') or 0,
            indefinite_streaming_original_count=row_dict.get('indefinite_streaming_original_count') or 0,
            definite_streaming_count=row_dict.get('definite_streaming_count') or 0,
            definite_streaming_original_count=row_dict.get('definite_streaming_original_count') or 0,
            duplicates_skipped=row_dict.get('duplicates_skipped') or 0,
            outliers_detected=row_dict.get('outliers_detected') or 0,
            processing_time_seconds=row_dict.get('processing_time_seconds') or 0.0,
            extractor_version=row_dict.get('extractor_version') or "unknown",
            processing_settings=json.loads(row_dict['processing_settings']) if row_dict.get('processing_settings') else None,
            errors_encountered=row_dict.get('errors_encountered') or 0,
            error_details=row_dict.get('error_details'),
            processed_at=datetime.fromisoformat(row_dict['processed_at']) if row_dict.get('processed_at') else datetime.now()
        )

    def create(
        self,
        patient_id: str,
        file_info: Dict[str, Any],
        counts: Dict[str, int],
        processing_info: Optional[Dict[str, Any]] = None,
        conn: Optional[sqlite3.Connection] = None
    ) -> UploadedFile:
        """
        Create processing metadata record for uploaded file.

        Records file upload with processing statistics. This is typically
        called after a file has been parsed and inserted into timeline_data
        and snapshot_data tables.

        Args:
            patient_id: Patient identifier
            file_info: Dict with file_name, file_path, file_hash, file_size_bytes
            counts: Dict with timeline_count, timeline_original_count, snapshot_count,
                    snapshot_original_count, duplicates_skipped, outliers_detected
            processing_info: Optional dict with processing_time_seconds, extractor_version,
                            processing_settings, errors_encountered, error_details
            conn: Optional connection (for transactions)

        Returns:
            UploadedFile: Created UploadedFile instance with file_id

        Raises:
            sqlite3.Error: If database operation fails

        Example:
            >>> file_info = {
            ...     'file_name': 'test.json',
            ...     'file_path': Path('/data/test.json'),
            ...     'file_hash': 'abc123',
            ...     'file_size_bytes': 1024
            ... }
            >>> counts = {
            ...     'timeline_count': 100,
            ...     'timeline_original_count': 120,
            ...     'snapshot_count': 50,
            ...     'snapshot_original_count': 60,
            ...     'duplicates_skipped': 30,
            ...     'outliers_detected': 0
            ... }
            >>> metadata = repo.create("PATIENT001", file_info, counts)
        """
        import json

        db_path = self.path_resolver.get_patient_db_path(patient_id)

        # Merge processing_info with defaults
        proc_info = processing_info or {}
        processing_time = proc_info.get('processing_time_seconds', 0.0)
        extractor_version = proc_info.get('extractor_version', '1.0.0')
        processing_settings = proc_info.get('processing_settings')
        errors_encountered = proc_info.get('errors_encountered', 0)
        error_details = proc_info.get('error_details')

        # Convert processing_settings to JSON if it's a dict
        if processing_settings and isinstance(processing_settings, dict):
            processing_settings_json = json.dumps(processing_settings)
        else:
            processing_settings_json = processing_settings

        query = """
        INSERT INTO processing_metadata (
            patient_id,
            file_name, file_path, file_hash, file_size_bytes,
            timeline_count, timeline_original_count,
            snapshot_count, snapshot_original_count,
            indefinite_streaming_count, indefinite_streaming_original_count,
            definite_streaming_count, definite_streaming_original_count,
            duplicates_skipped, outliers_detected,
            processing_time_seconds, extractor_version, processing_settings,
            errors_encountered, error_details
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """

        params = (
            patient_id,
            file_info['file_name'],
            str(file_info['file_path']),
            file_info['file_hash'],
            file_info['file_size_bytes'],
            counts.get('timeline_count', 0),
            counts.get('timeline_original_count', 0),
            counts.get('snapshot_count', 0),
            counts.get('snapshot_original_count', 0),
            counts.get('indefinite_streaming_count', 0),
            counts.get('indefinite_streaming_original_count', 0),
            counts.get('definite_streaming_count', 0),
            counts.get('definite_streaming_original_count', 0),
            counts.get('duplicates_skipped', 0),
            counts.get('outliers_detected', 0),
            processing_time,
            extractor_version,
            processing_settings_json,
            errors_encountered,
            error_details
        )

        try:
            if conn is not None:
                cursor = conn.cursor()
                cursor.execute(query, params)
                file_id = cursor.lastrowid

                # Fetch the created record
                fetch_query = "SELECT * FROM processing_metadata WHERE id = ?"
                return self._fetch_one(conn, fetch_query, (file_id,))
            else:
                with self.adapter.get_connection(db_path) as conn:
                    cursor = conn.cursor()
                    cursor.execute(query, params)
                    file_id = cursor.lastrowid
                    conn.commit()

                    # Fetch the created record
                    fetch_query = "SELECT * FROM processing_metadata WHERE id = ?"
                    return self._fetch_one(conn, fetch_query, (file_id,))

        except sqlite3.Error as e:
            self.logger.error(f"Database error in create: {e}")
            raise
        except Exception as e:
            self.logger.error(f"Unexpected error in create: {e}")
            raise

    def get_by_patient(
        self,
        patient_id: str,
        limit: Optional[int] = None,
        conn: Optional[sqlite3.Connection] = None
    ) -> List[UploadedFile]:
        """
        Get upload history for patient sorted by processed_at descending.

        Args:
            patient_id: Patient identifier
            limit: Optional maximum number of records to return
            conn: Optional connection (for transactions)

        Returns:
            List[UploadedFile]: List of uploaded files (empty if none found)

        Raises:
            sqlite3.Error: If database operation fails

        Example:
            >>> uploads = repo.get_by_patient("PATIENT001", limit=10)
            >>> for upload in uploads:
            ...     print(upload.file_name, upload.processed_at)
        """
        db_path = self.path_resolver.get_patient_db_path(patient_id)

        if limit:
            query = """
            SELECT * FROM processing_metadata
            WHERE patient_id = ?
            ORDER BY processed_at DESC
            LIMIT ?
            """
            params = (patient_id, limit)
        else:
            query = """
            SELECT * FROM processing_metadata
            WHERE patient_id = ?
            ORDER BY processed_at DESC
            """
            params = (patient_id,)

        try:
            if conn is not None:
                return self._fetch_all(conn, query, params)
            else:
                with self.adapter.get_connection(db_path) as conn:
                    return self._fetch_all(conn, query, params)

        except sqlite3.Error as e:
            self.logger.error(f"Database error in get_by_patient: {e}")
            raise
        except Exception as e:
            self.logger.error(f"Unexpected error in get_by_patient: {e}")
            raise

    def get_by_file_hash(
        self,
        patient_id: str,
        file_hash: str,
        conn: Optional[sqlite3.Connection] = None
    ) -> Optional[UploadedFile]:
        """
        Check if file already uploaded by hash.

        Used for duplicate file detection before processing.

        Args:
            patient_id: Patient identifier
            file_hash: SHA256 hash of file
            conn: Optional connection (for transactions)

        Returns:
            Optional[UploadedFile]: UploadedFile if hash exists, None otherwise

        Raises:
            sqlite3.Error: If database operation fails

        Example:
            >>> existing = repo.get_by_file_hash("PATIENT001", "abc123...")
            >>> if existing:
            ...     print(f"File already uploaded: {existing.file_name}")
        """
        db_path = self.path_resolver.get_patient_db_path(patient_id)
        query = """
        SELECT * FROM processing_metadata
        WHERE patient_id = ? AND file_hash = ?
        LIMIT 1
        """

        try:
            if conn is not None:
                return self._fetch_one(conn, query, (patient_id, file_hash))
            else:
                with self.adapter.get_connection(db_path) as conn:
                    return self._fetch_one(conn, query, (patient_id, file_hash))

        except sqlite3.Error as e:
            self.logger.error(f"Database error in get_by_file_hash: {e}")
            raise
        except Exception as e:
            self.logger.error(f"Unexpected error in get_by_file_hash: {e}")
            raise

    def get_total_files_count(
        self,
        patient_id: str,
        conn: Optional[sqlite3.Connection] = None
    ) -> int:
        """
        Count total number of uploaded files for patient.

        Args:
            patient_id: Patient identifier
            conn: Optional connection (for transactions)

        Returns:
            int: Number of uploaded files

        Raises:
            sqlite3.Error: If database operation fails

        Example:
            >>> count = repo.get_total_files_count("PATIENT001")
            >>> print(f"Patient has {count} uploaded files")
        """
        db_path = self.path_resolver.get_patient_db_path(patient_id)
        query = "SELECT COUNT(*) FROM processing_metadata WHERE patient_id = ?"

        try:
            if conn is not None:
                cursor = conn.cursor()
                result = cursor.execute(query, (patient_id,)).fetchone()
                return result[0] if result else 0
            else:
                with self.adapter.get_connection(db_path) as conn:
                    cursor = conn.cursor()
                    result = cursor.execute(query, (patient_id,)).fetchone()
                    return result[0] if result else 0

        except sqlite3.Error as e:
            self.logger.error(f"Database error in get_total_files_count: {e}")
            raise
        except Exception as e:
            self.logger.error(f"Unexpected error in get_total_files_count: {e}")
            raise
