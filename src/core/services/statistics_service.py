"""
Statistics service for calculating patient and system statistics.

This service aggregates data from multiple tables (processing_metadata,
timeline_data, snapshot_data) to compute statistics for individual patients
and the system as a whole.

Author: iEEG BrainSense Development Team
Last Updated: 2025-10-01
"""

import logging
from datetime import datetime
from typing import Optional, Dict, Any

from src.core.path_resolver import PathResolver
from src.core.models import PatientStatistics
from src.infrastructure.database.adapters.sqlite_adapter import SQLiteAdapter
from src.infrastructure.repositories.patient_repository import PatientRepository

logger = logging.getLogger(__name__)


class StatisticsService:
    """
    Service for calculating aggregated statistics.

    Computes statistics by querying multiple tables across patient databases
    and the global database. Provides both per-patient and system-wide statistics.

    Example:
        >>> adapter = SQLiteAdapter()
        >>> resolver = PathResolver()
        >>> repo = PatientRepository(adapter, resolver)
        >>> service = StatisticsService(adapter, resolver, repo)
        >>>
        >>> # Get statistics for a specific patient
        >>> stats = service.get_patient_statistics("PATIENT001")
        >>> print(f"Files uploaded: {stats.total_files_uploaded}")
        >>>
        >>> # Get statistics for all patients
        >>> all_stats = service.get_all_patient_statistics(active_only=True)
        >>> for patient_id, stats in all_stats.items():
        ...     print(f"{patient_id}: {stats.total_files_uploaded} files")
        >>>
        >>> # Get system-wide statistics
        >>> sys_stats = service.get_system_statistics()
        >>> print(f"Total patients: {sys_stats['total_patients']}")
    """

    def __init__(
        self,
        adapter: SQLiteAdapter,
        path_resolver: PathResolver,
        patient_repository: PatientRepository
    ):
        """
        Initialize StatisticsService.

        Args:
            adapter: SQLiteAdapter for database connections
            path_resolver: PathResolver for database paths
            patient_repository: PatientRepository for patient queries
        """
        self.adapter = adapter
        self.path_resolver = path_resolver
        self.patient_repository = patient_repository
        self.logger = logging.getLogger(__name__)

    def get_patient_statistics(self, patient_id: str) -> Optional[PatientStatistics]:
        """
        Calculate statistics for a specific patient.

        Aggregates data from the patient's database:
        - processing_metadata: file counts, upload dates, deduplication stats
        - timeline_data: record counts
        - snapshot_data: record counts

        Args:
            patient_id: Patient identifier

        Returns:
            Optional[PatientStatistics]: Statistics or None if patient not found

        Example:
            >>> stats = service.get_patient_statistics("PATIENT001")
            >>> if stats:
            ...     print(f"Snapshots: {stats.snapshots_deduplicated}")
            ...     print(f"Timeline: {stats.timeline_deduplicated}")
            ...     print(f"Reduction: {stats.snapshots_reduction_percent:.1f}%")
        """
        self.logger.debug(f"Calculating statistics for patient: {patient_id}")

        # Check if patient exists
        patient = self.patient_repository.get_by_id(patient_id)
        if not patient:
            self.logger.warning(f"Patient not found: {patient_id}")
            return None

        # Get patient database path
        patient_db = self.path_resolver.get_patient_db_path(patient_id)

        # Check if database exists
        if not patient_db.exists():
            self.logger.warning(f"Patient database not found: {patient_db}")
            # Return empty statistics
            return PatientStatistics(
                patient_id=patient_id,
                snapshots_original=0,
                snapshots_deduplicated=0,
                timeline_original=0,
                timeline_deduplicated=0,
                indefinite_streaming_original=0,
                indefinite_streaming_deduplicated=0,
                definite_streaming_original=0,
                definite_streaming_deduplicated=0,
                total_files_uploaded=0,
                total_duplicates_skipped=0,
                last_upload_date=None,
                last_calculated=datetime.now()
            )

        try:
            with self.adapter.get_connection(patient_db) as conn:
                cursor = conn.cursor()

                # Query processing_metadata for aggregated statistics
                cursor.execute("""
                    SELECT
                        COUNT(*) as file_count,
                        SUM(snapshot_original_count) as snapshot_orig,
                        SUM(timeline_original_count) as timeline_orig,
                        SUM(timeline_count) as timeline_dedup,
                        SUM(indefinite_streaming_original_count) as indefinite_streaming_orig,
                        SUM(indefinite_streaming_count) as indefinite_streaming_dedup,
                        SUM(definite_streaming_original_count) as definite_streaming_orig,
                        SUM(definite_streaming_count) as definite_streaming_dedup,
                        SUM(duplicates_skipped) as total_duplicates,
                        MAX(processed_at) as last_upload
                    FROM processing_metadata
                """)

                metadata_row = cursor.fetchone()

                # Extract values from processing_metadata (handle NULL for empty tables)
                file_count = metadata_row['file_count'] if metadata_row['file_count'] else 0
                snapshot_orig = metadata_row['snapshot_orig'] if metadata_row['snapshot_orig'] else 0

                # Query snapshot_data directly to count unique events
                # Each event can have Left, Right, or both hemispheres
                # We count unique (timestamp, event_name, patient_event_id) combinations
                # If snapshot_data is empty (e.g., in tests), fall back to processing_metadata sum
                cursor.execute("""
                    SELECT COUNT(*) FROM snapshot_data
                """)
                snapshot_table_count = cursor.fetchone()[0] or 0

                if snapshot_table_count > 0:
                    # Use actual snapshot_data table for accurate event counting
                    # Count only patient events (patient_event = 1)
                    cursor.execute("""
                        SELECT COUNT(DISTINCT timestamp || COALESCE(event_name, 'NULL') || COALESCE(patient_event_id, 'NULL'))
                        FROM snapshot_data
                        WHERE patient_event = 1
                    """)
                    snapshot_dedup = cursor.fetchone()[0] or 0
                else:
                    # Fall back to processing_metadata (for tests or empty databases)
                    # This uses the pre-calculated counts from upload service
                    snapshot_dedup = sum(
                        row['snapshot_count'] or 0
                        for row in cursor.execute("SELECT snapshot_count FROM processing_metadata").fetchall()
                    )
                timeline_orig = metadata_row['timeline_orig'] if metadata_row['timeline_orig'] else 0
                timeline_dedup = metadata_row['timeline_dedup'] if metadata_row['timeline_dedup'] else 0
                indefinite_streaming_orig = metadata_row['indefinite_streaming_orig'] if metadata_row['indefinite_streaming_orig'] else 0
                indefinite_streaming_dedup = metadata_row['indefinite_streaming_dedup'] if metadata_row['indefinite_streaming_dedup'] else 0
                definite_streaming_orig = metadata_row['definite_streaming_orig'] if metadata_row['definite_streaming_orig'] else 0
                definite_streaming_dedup = metadata_row['definite_streaming_dedup'] if metadata_row['definite_streaming_dedup'] else 0
                total_duplicates = metadata_row['total_duplicates'] if metadata_row['total_duplicates'] else 0
                last_upload_str = metadata_row['last_upload']

                # Parse last_upload timestamp
                last_upload = None
                if last_upload_str:
                    try:
                        last_upload = datetime.fromisoformat(last_upload_str)
                    except (ValueError, TypeError):
                        self.logger.warning(f"Invalid upload timestamp: {last_upload_str}")

                # Create statistics object
                stats = PatientStatistics(
                    patient_id=patient_id,
                    snapshots_original=int(snapshot_orig),
                    snapshots_deduplicated=int(snapshot_dedup),
                    timeline_original=int(timeline_orig),
                    timeline_deduplicated=int(timeline_dedup),
                    indefinite_streaming_original=int(indefinite_streaming_orig),
                    indefinite_streaming_deduplicated=int(indefinite_streaming_dedup),
                    definite_streaming_original=int(definite_streaming_orig),
                    definite_streaming_deduplicated=int(definite_streaming_dedup),
                    total_files_uploaded=int(file_count),
                    total_duplicates_skipped=int(total_duplicates),
                    last_upload_date=last_upload,
                    last_calculated=datetime.now()
                )

                self.logger.debug(
                    f"Statistics for {patient_id}: "
                    f"{stats.total_files_uploaded} files, "
                    f"{stats.snapshots_deduplicated} snapshots, "
                    f"{stats.timeline_deduplicated} timeline"
                )

                return stats

        except Exception as e:
            self.logger.error(
                f"Failed to calculate statistics for {patient_id}: {e}",
                exc_info=True
            )
            return None

    def get_all_patient_statistics(
        self,
        active_only: bool = True
    ) -> Dict[str, PatientStatistics]:
        """
        Calculate statistics for all patients.

        Args:
            active_only: If True, include only active patients.
                        If False, include all patients.

        Returns:
            Dict[str, PatientStatistics]: Dictionary mapping patient_id to statistics

        Example:
            >>> all_stats = service.get_all_patient_statistics(active_only=True)
            >>> for patient_id, stats in all_stats.items():
            ...     print(f"{patient_id}: {stats.total_files_uploaded} files")
        """
        self.logger.debug(f"Calculating statistics for all patients (active_only={active_only})")

        # Get patients
        if active_only:
            patients = self.patient_repository.get_all_active()
        else:
            patients = self.patient_repository.get_all()

        # Calculate statistics for each patient
        all_statistics = {}

        for patient in patients:
            stats = self.get_patient_statistics(patient.patient_id)
            if stats:
                all_statistics[patient.patient_id] = stats

        self.logger.debug(f"Calculated statistics for {len(all_statistics)} patients")

        return all_statistics

    def get_system_statistics(self) -> Dict[str, Any]:
        """
        Calculate system-wide statistics.

        Aggregates statistics across all patients to provide system-level metrics.

        Returns:
            Dict[str, Any]: Dictionary with system statistics:
                - total_patients: Total number of patients
                - active_patients: Number of active patients
                - total_files_uploaded: Total files across all patients
                - total_snapshots: Total snapshot records
                - total_timeline: Total timeline records
                - total_duplicates_skipped: Total duplicates removed
                - total_storage_files: Total number of patient databases

        Example:
            >>> sys_stats = service.get_system_statistics()
            >>> print(f"Total patients: {sys_stats['total_patients']}")
            >>> print(f"Total files: {sys_stats['total_files_uploaded']}")
            >>> print(f"Total duplicates removed: {sys_stats['total_duplicates_skipped']}")
        """
        self.logger.debug("Calculating system statistics")

        # Get all patients
        all_patients = self.patient_repository.get_all()
        active_patients = self.patient_repository.get_all_active()

        # Get statistics for all patients
        all_stats = self.get_all_patient_statistics(active_only=False)

        # Aggregate system-wide metrics
        total_files = 0
        total_snapshots = 0
        total_timeline = 0
        total_duplicates = 0

        for stats in all_stats.values():
            total_files += stats.total_files_uploaded
            total_snapshots += stats.snapshots_deduplicated
            total_timeline += stats.timeline_deduplicated
            total_duplicates += stats.total_duplicates_skipped

        system_stats = {
            'total_patients': len(all_patients),
            'active_patients': len(active_patients),
            'inactive_patients': len(all_patients) - len(active_patients),
            'total_files_uploaded': total_files,
            'total_snapshots': total_snapshots,
            'total_timeline': total_timeline,
            'total_duplicates_skipped': total_duplicates,
            'calculated_at': datetime.now().isoformat()
        }

        self.logger.debug(
            f"System statistics: {system_stats['total_patients']} patients, "
            f"{system_stats['total_files_uploaded']} files"
        )

        return system_stats
