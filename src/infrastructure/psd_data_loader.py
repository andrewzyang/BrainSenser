"""
PSD data loader for Snapshot frequency-domain analysis.

This module loads and prepares snapshot PSD data from the database,
handling JSON decoding, hemisphere merging, and artifact masking.

Author: iEEG BrainSense Development Team
Last Updated: 2025-10-02
"""

import logging
import json
from typing import List, Optional, Dict, Tuple
from datetime import datetime
import numpy as np

from src.core.models import SnapshotRecord
from src.domain.psd_models import SnapshotPsdEvent, SnapshotPsdDataset

logger = logging.getLogger(__name__)

# Constants
# Note: Frequency axis is now dynamically determined from data
# Some devices use 98 bins (0.98 Hz to 96.04 Hz at 0.98 Hz)
# Others use 100 bins (0 Hz to 123.75 Hz at 1.25 Hz)
NOISE_FLOOR = 0.109  # μV²/Hz
ARTIFACT_SENTINEL = -1.0  # Medtronic's censored bin marker


def load_snapshot_psd_dataset(
    patient_id: str,
    records: List[SnapshotRecord]
) -> SnapshotPsdDataset:
    """
    Convert SnapshotRecord list to SnapshotPsdDataset with full PSD data.

    This function:
    1. Groups records by timestamp to merge hemispheres
    2. Decodes JSON frequency and power arrays
    3. Applies artifact masking (negative values become NaN)
    4. Preserves therapy settings for stimulation-state filtering

    Parameters
    ----------
    patient_id : str
        Patient identifier
    records : List[SnapshotRecord]
        Raw snapshot records from repository

    Returns
    -------
    SnapshotPsdDataset
        Dataset with PSD events ready for analysis

    Example
    -------
    >>> from src.infrastructure.repositories import SnapshotRepository
    >>> repo = SnapshotRepository(adapter, resolver)
    >>> records = repo.get_by_patient("PT001")
    >>> dataset = load_snapshot_psd_dataset("PT001", records)
    >>> print(f"Loaded {len(dataset.events)} PSD events")
    """
    # Group records by timestamp and event to merge hemispheres
    grouped_records: Dict[Tuple[datetime, str], List[SnapshotRecord]] = {}

    for record in records:
        # Only include patient-triggered events
        if record.patient_event != 1:
            continue

        event_name = record.event_name or "Unknown"
        if not event_name or event_name == "Unknown":
            continue

        key = (record.timestamp, event_name)
        if key not in grouped_records:
            grouped_records[key] = []
        grouped_records[key].append(record)

    # Process grouped records into PSD events
    psd_events = []
    detected_frequency_axis = None

    for (timestamp, event_name), group in grouped_records.items():
        psd_event = _merge_hemispheric_records(timestamp, event_name, group)
        if psd_event is not None:
            psd_events.append(psd_event)
            # Use the first event's frequency axis as the dataset axis
            if detected_frequency_axis is None:
                detected_frequency_axis = psd_event.frequency_axis

    # Use detected frequency axis or fall back to empty array
    frequency_axis = detected_frequency_axis if detected_frequency_axis is not None else np.array([])

    logger.info(
        f"Loaded {len(psd_events)} PSD events for patient {patient_id} "
        f"from {len(records)} raw records (frequency bins: {len(frequency_axis)})"
    )

    return SnapshotPsdDataset(
        patient_id=patient_id,
        events=psd_events,
        frequency_axis=frequency_axis
    )


def _merge_hemispheric_records(
    timestamp: datetime,
    event_name: str,
    records: List[SnapshotRecord]
) -> Optional[SnapshotPsdEvent]:
    """
    Merge hemisphere-specific records into a single PSD event.

    Parameters
    ----------
    timestamp : datetime
        Event timestamp
    event_name : str
        Event type name
    records : List[SnapshotRecord]
        Records to merge (may have LEFT, RIGHT, or BOTH hemispheres)

    Returns
    -------
    Optional[SnapshotPsdEvent]
        Merged event or None if no valid PSD data
    """
    # Initialize containers
    frequency_axis = None
    psd_left = None
    psd_right = None
    artifact_mask_left = None
    artifact_mask_right = None
    therapy_amplitude_left = None
    therapy_amplitude_right = None
    therapy_frequency = None
    patient_event_id = None
    hemisphere = "BOTH"

    # Process each record
    for record in records:
        # Decode JSON arrays
        try:
            if record.frequency_data and record.power_data:
                freqs = json.loads(record.frequency_data)
                powers = json.loads(record.power_data)

                if not isinstance(freqs, list) or not isinstance(powers, list):
                    continue

                if len(freqs) != len(powers):
                    logger.warning(
                        f"Mismatched frequency/power array lengths at {timestamp}: "
                        f"{len(freqs)} vs {len(powers)}"
                    )
                    continue

                # Convert to numpy arrays
                freq_array = np.array(freqs, dtype=np.float64)
                power_array = np.array(powers, dtype=np.float64)

                # Create artifact mask (negative values are censored)
                artifact_mask = power_array < 0

                # Replace censored values with NaN
                power_array[artifact_mask] = np.nan

                # Store the first frequency axis we encounter
                if frequency_axis is None:
                    frequency_axis = freq_array
                else:
                    # Validate subsequent records match the first one
                    if len(freq_array) != len(frequency_axis):
                        logger.warning(
                            f"Inconsistent frequency array length at {timestamp}: "
                            f"{len(freq_array)} vs {len(frequency_axis)}, skipping this hemisphere"
                        )
                        continue

                    # Check frequency values match (with tolerance)
                    freq_diff = np.abs(freq_array - frequency_axis)
                    if np.max(freq_diff) > 0.1:
                        logger.warning(
                            f"Frequency axis mismatch at {timestamp}, max diff: {np.max(freq_diff)}, skipping this hemisphere"
                        )
                        continue

                # Assign to appropriate hemisphere (case-insensitive comparison)
                hemisphere_upper = record.hemisphere.upper() if record.hemisphere else ""
                if hemisphere_upper == "LEFT":
                    psd_left = power_array
                    artifact_mask_left = artifact_mask
                elif hemisphere_upper == "RIGHT":
                    psd_right = power_array
                    artifact_mask_right = artifact_mask
                elif hemisphere_upper == "BOTH":
                    # For BOTH, duplicate to both arrays
                    psd_left = power_array.copy()
                    psd_right = power_array.copy()
                    artifact_mask_left = artifact_mask.copy()
                    artifact_mask_right = artifact_mask.copy()

        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"Failed to decode JSON at {timestamp}: {e}")
            continue

        # Extract therapy settings (use first non-null values)
        if therapy_amplitude_left is None and record.therapy_amplitude_left is not None:
            therapy_amplitude_left = record.therapy_amplitude_left
        if therapy_amplitude_right is None and record.therapy_amplitude_right is not None:
            therapy_amplitude_right = record.therapy_amplitude_right
        if therapy_frequency is None and record.therapy_frequency is not None:
            therapy_frequency = record.therapy_frequency

        # Extract patient event ID
        if patient_event_id is None and record.patient_event_id:
            patient_event_id = record.patient_event_id

        # Update hemisphere info (normalize to uppercase for consistency)
        if record.hemisphere:
            record_hemi_upper = record.hemisphere.upper()
            if hemisphere == "BOTH":
                hemisphere = record_hemi_upper
            elif hemisphere != record_hemi_upper and record_hemi_upper != "BOTH":
                hemisphere = "BOTH"

    # Check if we have valid data
    if frequency_axis is None or (psd_left is None and psd_right is None):
        return None

    # Create PSD event
    return SnapshotPsdEvent(
        timestamp=timestamp,
        event_name=event_name,
        patient_event_id=patient_event_id,
        frequency_axis=frequency_axis,
        psd_left=psd_left,
        psd_right=psd_right,
        artifact_mask_left=artifact_mask_left,
        artifact_mask_right=artifact_mask_right,
        therapy_amplitude_left=therapy_amplitude_left,
        therapy_amplitude_right=therapy_amplitude_right,
        therapy_frequency=therapy_frequency,
        hemisphere=hemisphere
    )


def apply_noise_floor_flagging(
    psd_array: np.ndarray,
    noise_floor: float = NOISE_FLOOR
) -> np.ndarray:
    """
    Flag but do not filter noise floor values.

    Parameters
    ----------
    psd_array : np.ndarray
        Power spectral density array
    noise_floor : float
        Noise floor threshold (default 0.109 μV²/Hz)

    Returns
    -------
    np.ndarray
        Boolean mask where True indicates noise floor values
    """
    return np.abs(psd_array - noise_floor) < 1e-9


def validate_frequency_coverage(
    psd_event: SnapshotPsdEvent,
    min_valid_fraction: float = 0.8
) -> bool:
    """
    Validate that event has sufficient frequency coverage.

    Parameters
    ----------
    psd_event : SnapshotPsdEvent
        Event to validate
    min_valid_fraction : float
        Minimum fraction of valid (non-NaN) bins required

    Returns
    -------
    bool
        True if event has sufficient coverage
    """
    has_valid = False

    if psd_event.has_left_data:
        valid_fraction = np.sum(~np.isnan(psd_event.psd_left)) / len(psd_event.psd_left)
        if valid_fraction >= min_valid_fraction:
            has_valid = True

    if psd_event.has_right_data:
        valid_fraction = np.sum(~np.isnan(psd_event.psd_right)) / len(psd_event.psd_right)
        if valid_fraction >= min_valid_fraction:
            has_valid = True

    return has_valid