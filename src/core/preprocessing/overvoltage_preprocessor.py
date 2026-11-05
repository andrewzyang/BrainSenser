"""
Overvoltage Event Removal (OvER) Preprocessor for BrainSense Timeline Data.

Implements automatic detection and correction of overvoltage events in timeline
recordings based on Hanish et al. 2025 methodology. Integrates with the upload
workflow to preprocess data before database insertion.

This preprocessor:
1. Detects overvoltage events (>71.58M threshold) in timeline LFP data
2. Applies OvER correction formula to recalculate affected values
3. Preserves original values for auditability
4. Updates preprocessing metadata

Author: iEEG BrainSense Development Team
Last Updated: 2025-10-02
"""

import json
import logging
from datetime import datetime
from typing import List, Dict, Optional, Tuple
import numpy as np

from src.core.models.timeline_record import TimelineRecord

logger = logging.getLogger(__name__)

# Constants from Hanish et al. 2025 paper
MAX_32BIT_INT = 2**32 - 1  # Maximum 32-bit unsigned integer
SAMPLES_PER_BIN = 60  # BrainSense averages 60 samples per 10-minute bin
THRESHOLD_VALUE = MAX_32BIT_INT / SAMPLES_PER_BIN  # Detection threshold (~71.58M)


class OvervoltagePreprocessor:
    """
    Preprocessor for detecting and correcting overvoltage events in timeline data.

    Based on the Overvoltage Event Removal (OvER) method from Hanish et al. 2025,
    this preprocessor automatically detects and corrects artifactual high-power
    values caused by 32-bit integer overflow in BrainSense recordings.

    The preprocessor:
    - Detects values exceeding 71.58M (overflow threshold)
    - Applies OvER correction to recalculate true power values
    - Preserves original values in dedicated fields
    - Updates preprocessing metadata for traceability
    """

    def __init__(self, enabled: bool = True):
        """
        Initialize the overvoltage preprocessor.

        Args:
            enabled: Whether preprocessing is enabled (default: True)
        """
        self.enabled = enabled
        self.detection_stats = {
            'left': {'total': 0, 'corrected': 0, 'failed': 0},
            'right': {'total': 0, 'corrected': 0, 'failed': 0}
        }

        logger.info(f"OvervoltagePreprocessor initialized (enabled={enabled})")

    def preprocess_timeline_records(self, records: List[TimelineRecord]) -> Tuple[List[TimelineRecord], Dict]:
        """
        Preprocess timeline records to detect and correct overvoltage events.

        This is the main entry point for the preprocessing pipeline. It processes
        all timeline records, applying OvER correction where needed.

        Args:
            records: List of TimelineRecord instances to preprocess

        Returns:
            Tuple of:
                - List[TimelineRecord]: Preprocessed records with corrections applied
                - Dict: Preprocessing statistics and summary

        Example:
            >>> preprocessor = OvervoltagePreprocessor()
            >>> corrected_records, stats = preprocessor.preprocess_timeline_records(timeline_records)
            >>> print(f"Corrected {stats['total_corrected']} overvoltage events")
        """
        if not self.enabled:
            logger.info("OvER preprocessing is disabled")
            return records, {'enabled': False, 'message': 'Preprocessing disabled'}

        logger.info(f"Starting OvER preprocessing for {len(records)} timeline records")

        # Reset statistics
        self.detection_stats = {
            'left': {'total': 0, 'corrected': 0, 'failed': 0},
            'right': {'total': 0, 'corrected': 0, 'failed': 0}
        }

        preprocessing_timestamp = datetime.now().isoformat()
        corrected_records = []

        for record in records:
            corrected_record = self._process_single_record(record, preprocessing_timestamp)
            corrected_records.append(corrected_record)

        # Generate summary statistics
        summary = self._generate_summary()

        logger.info(f"OvER preprocessing complete: {summary['total_corrected']} corrections applied")

        return corrected_records, summary

    def _process_single_record(self, record: TimelineRecord, preprocessing_timestamp: str) -> TimelineRecord:
        """
        Process a single timeline record for overvoltage events.

        Args:
            record: TimelineRecord to process
            preprocessing_timestamp: ISO timestamp for preprocessing metadata

        Returns:
            TimelineRecord: Processed record (modified in-place if corrections applied)
        """
        corrections_applied = []

        # Check left hemisphere
        if record.left_hemisphere is not None:
            self.detection_stats['left']['total'] += 1

            if record.left_hemisphere > THRESHOLD_VALUE:
                corrected_value = self._apply_over_correction(record.left_hemisphere)

                if corrected_value is not None and not np.isnan(corrected_value):
                    # Store original value before correction
                    record.original_left_hemisphere = record.left_hemisphere
                    record.left_hemisphere = corrected_value
                    self.detection_stats['left']['corrected'] += 1
                    corrections_applied.append('left_overvoltage')

                    logger.debug(f"Left hemisphere corrected at {record.timestamp}: "
                               f"{record.original_left_hemisphere:.0f} → {corrected_value:.2f}")
                else:
                    self.detection_stats['left']['failed'] += 1
                    # Mark as NaN if correction fails
                    record.original_left_hemisphere = record.left_hemisphere
                    record.left_hemisphere = None
                    corrections_applied.append('left_overvoltage_nan')

        # Check right hemisphere
        if record.right_hemisphere is not None:
            self.detection_stats['right']['total'] += 1

            if record.right_hemisphere > THRESHOLD_VALUE:
                corrected_value = self._apply_over_correction(record.right_hemisphere)

                if corrected_value is not None and not np.isnan(corrected_value):
                    # Store original value before correction
                    record.original_right_hemisphere = record.right_hemisphere
                    record.right_hemisphere = corrected_value
                    self.detection_stats['right']['corrected'] += 1
                    corrections_applied.append('right_overvoltage')

                    logger.debug(f"Right hemisphere corrected at {record.timestamp}: "
                               f"{record.original_right_hemisphere:.0f} → {corrected_value:.2f}")
                else:
                    self.detection_stats['right']['failed'] += 1
                    # Mark as NaN if correction fails
                    record.original_right_hemisphere = record.right_hemisphere
                    record.right_hemisphere = None
                    corrections_applied.append('right_overvoltage_nan')

        # Update preprocessing metadata if corrections were applied
        if corrections_applied:
            preprocessing_info = {
                'method': 'OvER',
                'version': '1.0',
                'corrections': corrections_applied,
                'threshold': THRESHOLD_VALUE,
                'reference': 'Hanish et al. 2025'
            }

            # Merge with existing preprocessing if any
            if record.preprocessing_applied:
                try:
                    existing = json.loads(record.preprocessing_applied)
                    if isinstance(existing, list):
                        existing.append(preprocessing_info)
                        record.preprocessing_applied = json.dumps(existing)
                    else:
                        record.preprocessing_applied = json.dumps([existing, preprocessing_info])
                except json.JSONDecodeError:
                    record.preprocessing_applied = json.dumps([preprocessing_info])
            else:
                record.preprocessing_applied = json.dumps([preprocessing_info])

            record.preprocessing_timestamp = preprocessing_timestamp

        return record

    def _apply_over_correction(self, original_value: float) -> Optional[float]:
        """
        Apply OvER correction formula to an overvoltage value.

        Based on Equations 6-7 from Hanish et al. 2025:
        - Calculates number of invalid samples that caused overflow
        - Recalculates average from valid samples only

        Args:
            original_value: The detected overvoltage value

        Returns:
            Optional[float]: Corrected value, or None if all samples were invalid
        """
        try:
            # Calculate number of invalid samples (Eq. 6)
            n_invalid = np.floor(original_value / (MAX_32BIT_INT / SAMPLES_PER_BIN))

            # Apply correction if there are valid samples (Eq. 7)
            if SAMPLES_PER_BIN - n_invalid > 0:
                s_valid = (SAMPLES_PER_BIN * original_value - n_invalid * MAX_32BIT_INT)
                corrected_value = s_valid / (SAMPLES_PER_BIN - n_invalid)
                return float(corrected_value)
            else:
                # All samples were invalid, return None (will be stored as NULL)
                return None

        except Exception as e:
            logger.error(f"OvER correction failed for value {original_value}: {e}")
            return None

    def _generate_summary(self) -> Dict:
        """
        Generate preprocessing summary statistics.

        Returns:
            Dict: Summary of preprocessing results
        """
        total_corrected = (self.detection_stats['left']['corrected'] +
                          self.detection_stats['right']['corrected'])
        total_failed = (self.detection_stats['left']['failed'] +
                       self.detection_stats['right']['failed'])
        total_processed = (self.detection_stats['left']['total'] +
                          self.detection_stats['right']['total'])

        summary = {
            'enabled': True,
            'method': 'OvER (Overvoltage Event Removal)',
            'reference': 'Hanish et al. 2025',
            'threshold': THRESHOLD_VALUE,
            'total_processed': total_processed,
            'total_corrected': total_corrected,
            'total_failed': total_failed,
            'left_hemisphere': {
                'total': self.detection_stats['left']['total'],
                'corrected': self.detection_stats['left']['corrected'],
                'failed': self.detection_stats['left']['failed'],
                'correction_rate': (self.detection_stats['left']['corrected'] /
                                   self.detection_stats['left']['total'] * 100
                                   if self.detection_stats['left']['total'] > 0 else 0)
            },
            'right_hemisphere': {
                'total': self.detection_stats['right']['total'],
                'corrected': self.detection_stats['right']['corrected'],
                'failed': self.detection_stats['right']['failed'],
                'correction_rate': (self.detection_stats['right']['corrected'] /
                                   self.detection_stats['right']['total'] * 100
                                   if self.detection_stats['right']['total'] > 0 else 0)
            },
            'overall_correction_rate': (total_corrected / total_processed * 100
                                       if total_processed > 0 else 0)
        }

        return summary

    def validate_correction(self, original_value: float, corrected_value: float) -> bool:
        """
        Validate that a correction is reasonable.

        Performs sanity checks on corrected values to ensure they are
        within expected ranges for BrainSense LFP data.

        Args:
            original_value: Original overvoltage value
            corrected_value: Corrected value after OvER

        Returns:
            bool: True if correction appears valid
        """
        # Corrected value should be significantly smaller
        if corrected_value >= original_value:
            return False

        # Corrected value should be positive (power values are always positive)
        if corrected_value < 0:
            return False

        # Corrected value should be below threshold
        if corrected_value >= THRESHOLD_VALUE:
            return False

        # Typical BrainSense LFP power values are < 1000000 (1M)
        # Allow up to 10M for edge cases but flag anything higher
        if corrected_value > 10_000_000:
            logger.warning(f"Unusually high corrected value: {corrected_value:.2f}")

        return True