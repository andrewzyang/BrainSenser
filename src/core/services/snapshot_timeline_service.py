"""
Snapshot timeline service for analyzing patient snapshot patterns.

This service provides business logic for extracting and organizing snapshot
data by day, calculating temporal statistics, and generating timeline reports.
"""

import logging
from typing import List, Dict
from datetime import datetime, date
from collections import defaultdict

from src.core.models.snapshot_timeline import (
    SnapshotEvent,
    DaySnapshots,
    PatientTimeline
)
from src.infrastructure.repositories.snapshot_repository import SnapshotRepository
from src.core.services.patient_service import PatientService
from src.core.services.exceptions import PatientNotFoundError, DataNotFoundError


logger = logging.getLogger(__name__)


class SnapshotTimelineService:
    """
    Service for analyzing snapshot timelines.

    Provides methods to extract and organize patient snapshots by day,
    with temporal grouping and statistical analysis.

    Example:
        >>> from src.infrastructure.container import Container
        >>> container = Container()
        >>> service = container.snapshot_timeline_service()
        >>>
        >>> # Get timeline for specific patient
        >>> timeline = service.get_patient_timeline("PATIENT001")
        >>> print(f"Patient has {timeline.total_snapshots} snapshots")
        >>>
        >>> # Get timelines for all patients
        >>> all_timelines = service.get_all_timelines()
    """

    def __init__(
        self,
        snapshot_repository: SnapshotRepository,
        patient_service: PatientService
    ):
        """
        Initialize SnapshotTimelineService.

        Args:
            snapshot_repository: Repository for snapshot data access
            patient_service: Service for patient operations
        """
        self._snapshot_repository = snapshot_repository
        self._patient_service = patient_service
        self._cache: Dict[str, PatientTimeline] = {}
        self.logger = logging.getLogger(__name__)

    def get_patient_timeline(
        self,
        patient_id: str,
        use_cache: bool = True,
        patient_events_only: bool = False
    ) -> PatientTimeline:
        """
        Get complete timeline for a patient.

        Retrieves all snapshots for the patient, groups them by day,
        and calculates temporal statistics.

        Args:
            patient_id: Patient identifier
            use_cache: Whether to use cached results (default True)
            patient_events_only: If True, only include patient-triggered events

        Returns:
            PatientTimeline with all snapshots grouped by day

        Raises:
            PatientNotFoundError: If patient doesn't exist
            DataNotFoundError: If patient has no snapshots

        Example:
            >>> timeline = service.get_patient_timeline("PATIENT001")
            >>> print(f"Date range: {timeline.date_range[0]} to {timeline.date_range[1]}")
            >>> for day in timeline.days:
            ...     print(f"Day {day.day_of_year}: {day.count} snapshots")
        """
        # Check cache
        cache_key = f"{patient_id}_{patient_events_only}"
        if use_cache and cache_key in self._cache:
            self.logger.debug(f"Returning cached timeline for {patient_id}")
            return self._cache[cache_key]

        # Verify patient exists
        patient = self._patient_service.get_patient(patient_id)
        if not patient:
            raise PatientNotFoundError(
                f"Patient {patient_id} not found",
                user_message=f"Patient {patient_id} does not exist"
            )

        # Fetch all snapshots (no limit)
        self.logger.info(f"Fetching snapshots for patient {patient_id}")
        try:
            count = self._snapshot_repository.get_count(patient_id)
            if count == 0:
                raise DataNotFoundError(
                    f"No snapshots found for patient {patient_id}",
                    user_message=f"Patient {patient_id} has no recorded snapshots"
                )

            # Fetch all snapshots
            snapshots = self._snapshot_repository.get_by_patient(
                patient_id,
                limit=count,
                offset=0
            )
        except Exception as e:
            self.logger.error(f"Error fetching snapshots for {patient_id}: {e}")
            raise

        # Filter by patient events if requested
        if patient_events_only:
            snapshots = [s for s in snapshots if s.patient_event == 1]
            if not snapshots:
                raise DataNotFoundError(
                    f"No patient-triggered snapshots found for {patient_id}",
                    user_message=f"Patient {patient_id} has no patient-triggered snapshots"
                )

        # Group by day
        days_map: Dict[date, List[SnapshotEvent]] = defaultdict(list)

        for snapshot in snapshots:
            try:
                # Get timestamp (already a datetime object)
                dt = snapshot.timestamp
                if isinstance(dt, str):
                    # Handle case where timestamp is still a string
                    dt = datetime.fromisoformat(dt)
                day = dt.date()

                # Create event
                event = SnapshotEvent(
                    timestamp=dt,
                    time_of_day=dt.time(),
                    event_name=snapshot.event_name,
                    event_type=snapshot.event_type,
                    hemisphere=snapshot.hemisphere,
                    patient_triggered=bool(snapshot.patient_event),
                    source_file=snapshot.source_file
                )

                days_map[day].append(event)

            except (ValueError, AttributeError, TypeError) as e:
                self.logger.warning(
                    f"Skipping snapshot with invalid timestamp: {snapshot.timestamp} - {e}"
                )
                continue

        if not days_map:
            raise DataNotFoundError(
                f"No valid snapshots found for patient {patient_id}",
                user_message=f"Patient {patient_id} has no valid snapshot data"
            )

        # Create DaySnapshots objects
        days = []
        for day_date in sorted(days_map.keys()):
            events = sorted(days_map[day_date], key=lambda e: e.timestamp)
            day_snapshots = DaySnapshots(
                date=day_date,
                day_of_year=day_date.timetuple().tm_yday,
                events=tuple(events)
            )
            days.append(day_snapshots)

        # Create timeline
        timeline = PatientTimeline(
            patient_id=patient_id,
            days=tuple(days),
            total_snapshots=sum(day.count for day in days),
            date_range=(days[0].date, days[-1].date) if days else None
        )

        # Cache result
        if use_cache:
            self._cache[cache_key] = timeline

        self.logger.info(
            f"Created timeline for {patient_id}: "
            f"{timeline.total_snapshots} snapshots across {timeline.total_days} days"
        )

        return timeline

    def get_all_timelines(
        self,
        patient_events_only: bool = False
    ) -> List[PatientTimeline]:
        """
        Get timelines for all active patients.

        Retrieves timeline data for all patients that have snapshot data.
        Patients without snapshots are logged and skipped.

        Args:
            patient_events_only: If True, only include patient-triggered events

        Returns:
            List[PatientTimeline]: List of patient timelines (may be empty)

        Example:
            >>> timelines = service.get_all_timelines()
            >>> for timeline in timelines:
            ...     print(f"{timeline.patient_id}: {timeline.total_snapshots} snapshots")
        """
        patients = self._patient_service.get_all_active_patients()
        self.logger.info(f"Processing timelines for {len(patients)} patients")

        timelines = []

        for patient in patients:
            try:
                timeline = self.get_patient_timeline(
                    patient.patient_id,
                    patient_events_only=patient_events_only
                )
                timelines.append(timeline)
                self.logger.debug(f"Added timeline for {patient.patient_id}")

            except DataNotFoundError as e:
                self.logger.warning(f"No snapshots for patient {patient.patient_id}: {e}")
                continue

            except Exception as e:
                self.logger.error(
                    f"Failed to process patient {patient.patient_id}: {e}",
                    exc_info=True
                )
                continue

        self.logger.info(f"Created {len(timelines)} timelines from {len(patients)} patients")
        return timelines

    def clear_cache(self) -> None:
        """
        Clear the timeline cache.

        Useful when snapshot data has been updated and cached timelines
        need to be regenerated.

        Example:
            >>> service.clear_cache()
            >>> timeline = service.get_patient_timeline("PATIENT001")  # Fresh data
        """
        self._cache.clear()
        self.logger.debug("Timeline cache cleared")

    def get_cache_size(self) -> int:
        """
        Get number of cached timelines.

        Returns:
            int: Number of timelines in cache

        Example:
            >>> size = service.get_cache_size()
            >>> print(f"Cache contains {size} timelines")
        """
        return len(self._cache)
