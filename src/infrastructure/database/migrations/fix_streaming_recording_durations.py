"""
Database migration to fix streaming recording durations.

This migration fixes a bug where streaming recording durations were calculated
by summing sample counts across all channels instead of using the max. Since
channels are recorded simultaneously (not sequentially), this caused durations
to be multiplied by the number of channels (typically 2x for LEFT+RIGHT).

The migration:
1. Iterates through all streaming recordings in all patient databases
2. Recalculates the correct duration from the actual file
3. Updates the database with the corrected duration

Usage:
    python src/infrastructure/database/migrations/fix_streaming_recording_durations.py

Author: iEEG BrainSense Development Team
Created: 2025-10-08
"""

import json
import sqlite3
import logging
from pathlib import Path
from typing import List, Dict, Any

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def get_patient_databases(data_root: Path) -> List[Path]:
    """Find all patient databases."""
    patient_dbs = []

    if not data_root.exists():
        logger.warning(f"Data root not found: {data_root}")
        return patient_dbs

    for patient_dir in data_root.iterdir():
        if not patient_dir.is_dir():
            continue

        db_path = patient_dir / "brainsense_data.db"
        if db_path.exists():
            patient_dbs.append(db_path)
            logger.info(f"Found patient database: {db_path}")

    return patient_dbs


def calculate_correct_duration(file_path: str) -> float:
    """
    Calculate correct duration from streaming file.

    Args:
        file_path: Path to streaming recording file

    Returns:
        Correct duration in seconds, or None if cannot be calculated
    """
    try:
        file_path_obj = Path(file_path)
        if not file_path_obj.exists():
            logger.warning(f"File not found: {file_path}")
            return None

        with open(file_path_obj, 'r') as f:
            data = json.load(f)

        # Find streaming data arrays
        streaming_records = []
        for key in ['BrainSenseTimeDomain', 'IndefiniteStreaming']:
            if key in data and isinstance(data[key], list):
                streaming_records = data[key]
                break

        if not streaming_records:
            logger.warning(f"No streaming data found in {file_path}")
            return None

        # Calculate max sample count across all channels
        max_samples = 0
        sample_rate = 250.0  # default

        for record in streaming_records:
            if not isinstance(record, dict):
                continue

            # Get sample rate
            rate = record.get('SampleRateInHz') or record.get('SampleRate')
            if rate:
                sample_rate = rate

            # Get waveform data
            waveform_data = record.get('TimeDomainData') or record.get('LFPData')
            if waveform_data and isinstance(waveform_data, list):
                sample_count = len(waveform_data)
                max_samples = max(max_samples, sample_count)

        if max_samples == 0 or sample_rate == 0:
            logger.warning(f"Invalid sample count or rate for {file_path}")
            return None

        correct_duration = max_samples / sample_rate
        return correct_duration

    except Exception as e:
        logger.error(f"Error calculating duration for {file_path}: {e}")
        return None


def fix_database_durations(db_path: Path) -> Dict[str, Any]:
    """
    Fix streaming recording durations in a patient database.

    Args:
        db_path: Path to patient database

    Returns:
        Dict with migration statistics
    """
    stats = {
        'patient_id': db_path.parent.name,
        'total_recordings': 0,
        'fixed': 0,
        'skipped': 0,
        'errors': 0
    }

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # Get all streaming recordings
        cursor.execute("""
            SELECT id, file_path, duration_seconds, channel_count
            FROM streaming_recordings
        """)

        recordings = cursor.fetchall()
        stats['total_recordings'] = len(recordings)

        logger.info(f"Processing {len(recordings)} recordings in {db_path.name}")

        for rec_id, file_path, old_duration, channel_count in recordings:
            # Calculate correct duration
            correct_duration = calculate_correct_duration(file_path)

            if correct_duration is None:
                stats['errors'] += 1
                continue

            # Check if duration needs fixing (allow 1 second tolerance)
            if abs(correct_duration - old_duration) > 1.0:
                # Update duration
                cursor.execute("""
                    UPDATE streaming_recordings
                    SET duration_seconds = ?,
                        updated_at = datetime('now')
                    WHERE id = ?
                """, (correct_duration, rec_id))

                logger.info(
                    f"  Fixed {rec_id}: {old_duration:.2f}s → {correct_duration:.2f}s "
                    f"(ratio: {old_duration/correct_duration:.2f}x, likely {channel_count} channels)"
                )
                stats['fixed'] += 1
            else:
                stats['skipped'] += 1

        conn.commit()
        logger.info(
            f"Completed {db_path.name}: "
            f"{stats['fixed']} fixed, {stats['skipped']} skipped, {stats['errors']} errors"
        )

    except Exception as e:
        logger.error(f"Error processing {db_path}: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()

    return stats


def main():
    """Run the migration."""
    logger.info("Starting streaming recording duration migration")

    # Get data root from environment or use default
    import os
    data_root = Path(os.getenv('BRAINSENSE_DATA_DIR', Path.home() / '.brainsense_data'))
    patients_root = data_root / 'patients'

    logger.info(f"Scanning for patient databases in: {patients_root}")

    # Find all patient databases
    patient_dbs = get_patient_databases(patients_root)

    if not patient_dbs:
        logger.warning("No patient databases found")
        return

    # Process each database
    total_stats = {
        'total_recordings': 0,
        'fixed': 0,
        'skipped': 0,
        'errors': 0
    }

    for db_path in patient_dbs:
        try:
            stats = fix_database_durations(db_path)
            total_stats['total_recordings'] += stats['total_recordings']
            total_stats['fixed'] += stats['fixed']
            total_stats['skipped'] += stats['skipped']
            total_stats['errors'] += stats['errors']
        except Exception as e:
            logger.error(f"Failed to process {db_path}: {e}")

    # Summary
    logger.info("\n" + "="*60)
    logger.info("Migration Summary")
    logger.info("="*60)
    logger.info(f"Total recordings processed: {total_stats['total_recordings']}")
    logger.info(f"Fixed: {total_stats['fixed']}")
    logger.info(f"Skipped (already correct): {total_stats['skipped']}")
    logger.info(f"Errors: {total_stats['errors']}")
    logger.info("="*60)


if __name__ == '__main__':
    main()
