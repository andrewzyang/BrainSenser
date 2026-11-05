"""
Data loaders to bridge repository records and domain models.

This module provides functions to convert database records (TimelineRecord,
SnapshotRecord) into domain models (TimelineDataset, SnapshotDataset) for
use by analysis services.

Author: iEEG BrainSense Development Team
Last Updated: 2025-10-02
"""

import logging
from typing import List, Dict
from datetime import datetime

from src.core.models import TimelineRecord, SnapshotRecord
from src.domain.models import (
    TimelineDataset,
    SnapshotDataset,
    TimelineRecording,
    SnapshotEvent
)

logger = logging.getLogger(__name__)


def load_timeline_dataset(
    patient_id: str,
    records: List[TimelineRecord],
    frequency_band: str = "Beta"
) -> TimelineDataset:
    """
    Convert TimelineRecord list to TimelineDataset.

    Timeline records store bilateral LFP power values (microvolts) for chronic
    monitoring. The frequency_band parameter specifies which band is being analyzed
    (e.g., "Beta", "Gamma"). The actual band being recorded is determined by the
    device configuration, not stored in the database.

    Parameters
    ----------
    patient_id : str
        Patient identifier
    records : List[TimelineRecord]
        Raw timeline records from repository
    frequency_band : str
        Frequency band label (default "Beta")

    Returns
    -------
    TimelineDataset
        Domain model ready for analysis

    Example
    -------
    >>> from src.infrastructure.repositories import TimelineRepository
    >>> repo = TimelineRepository(adapter, resolver)
    >>> records = repo.get_by_patient("PT001", limit=1000)
    >>> dataset = load_timeline_dataset("PT001", records, frequency_band="Beta")
    >>> print(f"Loaded {len(dataset.recordings)} recordings")
    """
    recordings: List[TimelineRecording] = []

    for record in records:
        # Convert TimelineRecord → TimelineRecording
        # Note: left_hemisphere and right_hemisphere are power values (microvolts)
        # for the frequency band being monitored chronically
        # Accept records with at least one hemisphere present
        if record.left_hemisphere is not None or record.right_hemisphere is not None:
            recording = TimelineRecording(
                timestamp=record.timestamp,
                time_relative=0.0,  # Will be set during synchronization
                power_left=record.left_hemisphere if record.left_hemisphere is not None else 0.0,
                power_right=record.right_hemisphere if record.right_hemisphere is not None else 0.0,
                frequency_band=frequency_band,
                coverage=1.0,  # Assume full coverage unless marked as outlier
                has_overvoltage=record.is_outlier == 1
            )
            recordings.append(recording)

    logger.info(
        f"Loaded {len(recordings)} timeline recordings for patient {patient_id}, "
        f"band={frequency_band}"
    )

    return TimelineDataset(
        patient_id=patient_id,
        recordings=recordings,
        frequency_band=frequency_band
    )


def load_snapshot_dataset(
    patient_id: str,
    records: List[SnapshotRecord],
    frequency_band: str = "Beta"
) -> SnapshotDataset:
    """
    Convert SnapshotRecord list to SnapshotDataset.

    Snapshot records store patient-triggered events with frequency/power data
    as JSON. This function:
    1. Filters for patient-triggered events (patient_event == 1)
    2. Extracts event_name from the record
    3. Creates SnapshotEvent objects for the specified frequency band

    Parameters
    ----------
    patient_id : str
        Patient identifier
    records : List[SnapshotRecord]
        Raw snapshot records from repository
    frequency_band : str
        Frequency band to extract (default "Beta")

    Returns
    -------
    SnapshotDataset
        Domain model ready for analysis

    Example
    -------
    >>> from src.infrastructure.repositories import SnapshotRepository
    >>> repo = SnapshotRepository(adapter, resolver)
    >>> records = repo.get_by_patient("PT001", limit=1000)
    >>> dataset = load_snapshot_dataset("PT001", records, frequency_band="Beta")
    >>> print(f"Found {len(dataset.events)} patient-triggered events")
    """
    # Group records by timestamp and event_name to deduplicate hemispheric records
    # Each unique snapshot event may have separate records for Left and Right hemispheres
    unique_events: Dict[tuple[datetime, str], SnapshotEvent] = {}

    for record in records:
        # Only include patient-triggered events
        if record.patient_event != 1:
            continue

        # Extract event name (e.g., "Craving", "Happy", "Anxious")
        event_name = record.event_name or "Unknown"

        # Skip if no event name
        if not event_name or event_name == "Unknown":
            logger.debug(f"Skipping snapshot at {record.timestamp} - no event_name")
            continue

        # Use (timestamp, event_name) as the key to deduplicate hemispheric records
        event_key = (record.timestamp, event_name)

        # Only create one SnapshotEvent per unique (timestamp, event_name) pair
        if event_key not in unique_events:
            event = SnapshotEvent(
                timestamp=record.timestamp,
                event_name=event_name,
                patient_event_id=record.patient_event_id,
                frequency_band=frequency_band
            )
            unique_events[event_key] = event

    # Convert to list
    events = list(unique_events.values())

    logger.info(
        f"Loaded {len(events)} snapshot events for patient {patient_id}, "
        f"band={frequency_band}"
    )

    return SnapshotDataset(
        patient_id=patient_id,
        events=events,
        frequency_band=frequency_band
    )
