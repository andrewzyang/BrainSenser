"""
Utility for loading streaming recording data from files.

This module provides file-based loading for streaming recordings, replacing
the previous database-based waveform loading approach. Supports multiple
file formats and includes data validation.

Supported formats:
- Standard JSON format (metadata + channels)
- Legacy TimeDomain format
- Raw Medtronic format (IndefiniteStreaming, BrainSenseTimeDomain)
- NumPy binary format (.npy)

Author: iEEG BrainSense Development Team
Created: 2025-10-08
"""

import json
import hashlib
import logging
import numpy as np
from pathlib import Path
from typing import Tuple, Dict, Any, List

logger = logging.getLogger(__name__)


class StreamingFileLoader:
    """
    Loads streaming recording waveform data from files.

    Provides robust file loading with validation, multiple format support,
    and integrity checking via checksums.

    Supports multiple file formats:
    - Standard JSON format (metadata + channels)
    - Legacy TimeDomain format (old processed files)
    - Raw Medtronic format (IndefiniteStreaming, BrainSenseTimeDomain)
    - NumPy binary format (.npy)

    Example:
        >>> loader = StreamingFileLoader()
        >>> waveform, metadata = loader.load_from_file(
        ...     file_path=Path("recording.json"),
        ...     expected_channels=["Ch0_LEFT", "Ch1_RIGHT"],
        ...     expected_duration=10.0,
        ...     expected_sampling_rate=250.0
        ... )
    """

    def __init__(self):
        """Initialize StreamingFileLoader."""
        self.logger = logging.getLogger(__name__)

    def load_from_file(
        self,
        file_path: Path,
        expected_channels: List[str],
        expected_duration: float,
        expected_sampling_rate: float
    ) -> Tuple[np.ndarray, Dict[str, Any]]:
        """
        Load waveform data from file.

        Args:
            file_path: Path to recording file
            expected_channels: Expected channel labels (from DB metadata)
            expected_duration: Expected duration in seconds (validation)
            expected_sampling_rate: Expected sampling rate in Hz (validation)

        Returns:
            Tuple[np.ndarray, Dict]:
                - Waveform array (n_samples, n_channels)
                - File metadata dict

        Raises:
            FileNotFoundError: If file doesn't exist
            ValueError: If file format invalid or data mismatched
            RuntimeError: If data loading fails
        """
        if not file_path.exists():
            raise FileNotFoundError(f"Recording file not found: {file_path}")

        self.logger.debug(f"Loading waveform data from {file_path}")

        # Detect format by extension
        if file_path.suffix == '.json':
            waveform, metadata = self._load_json(
                file_path,
                expected_channels,
                expected_duration,
                expected_sampling_rate
            )
        elif file_path.suffix == '.npy':
            waveform, metadata = self._load_numpy(
                file_path,
                expected_channels,
                expected_duration,
                expected_sampling_rate
            )
        else:
            raise ValueError(f"Unsupported file format: {file_path.suffix}")

        # Compute file checksum for integrity validation
        checksum = self.compute_file_checksum(file_path)
        metadata['file_checksum'] = checksum

        self.logger.debug(
            f"Loaded waveform with shape {waveform.shape}, "
            f"checksum: {checksum[:8]}..."
        )

        return waveform, metadata

    def _load_json(
        self,
        file_path: Path,
        expected_channels: List[str],
        expected_duration: float,
        expected_sampling_rate: float
    ) -> Tuple[np.ndarray, Dict[str, Any]]:
        """Load from JSON format (standard, legacy, or raw Medtronic)."""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON file: {e}")

        # Try standard format first (processed files)
        if 'data' in data and 'channels' in data['data']:
            return self._load_standard_format(
                data,
                expected_channels,
                expected_duration,
                expected_sampling_rate
            )

        # Try legacy TimeDomain format (old processed files)
        elif 'TimeDomain' in data and isinstance(data.get('TimeDomain'), list):
            return self._load_legacy_format(
                data,
                expected_channels,
                expected_duration,
                expected_sampling_rate
            )

        # Try raw Medtronic format (unprocessed uploads)
        elif self._is_raw_medtronic_format(data):
            return self._load_raw_medtronic_format(
                data,
                expected_channels,
                expected_duration,
                expected_sampling_rate
            )

        else:
            raise ValueError(
                f"Unrecognized JSON structure in {file_path}. "
                f"Expected 'data.channels', 'TimeDomain', or raw Medtronic format. "
                f"Found: {list(data.keys())}"
            )

    def _load_standard_format(
        self,
        data: Dict,
        expected_channels: List[str],
        expected_duration: float,
        expected_sampling_rate: float
    ) -> Tuple[np.ndarray, Dict[str, Any]]:
        """Load from standard format: {metadata: {...}, data: {channels: {...}}}"""
        metadata = data.get('metadata', {})
        channels_data = data['data']['channels']

        # Build channel arrays in expected order
        channel_arrays = []
        missing_channels = []

        for label in expected_channels:
            if label not in channels_data:
                missing_channels.append(label)
                # Use zeros for missing channels (with warning)
                if len(channel_arrays) > 0:
                    # Match length of first channel
                    channel_arrays.append(np.zeros(len(channel_arrays[0])))
                else:
                    # Estimate length from duration and sampling rate
                    expected_samples = int(expected_duration * expected_sampling_rate)
                    channel_arrays.append(np.zeros(expected_samples))
            else:
                channel_array = np.array(channels_data[label], dtype=np.float64)
                channel_arrays.append(channel_array)

        if missing_channels:
            self.logger.warning(
                f"Channels {missing_channels} not found in file, using zeros"
            )

        # Stack into 2D array (samples, channels)
        waveform_array = np.column_stack(channel_arrays)

        # Validate shape
        n_samples, n_channels = waveform_array.shape
        expected_samples = int(expected_duration * expected_sampling_rate)

        # Allow 1 second tolerance
        if abs(n_samples - expected_samples) > expected_sampling_rate:
            self.logger.warning(
                f"Sample count mismatch: expected ~{expected_samples}, got {n_samples} "
                f"(difference: {abs(n_samples - expected_samples)} samples)"
            )

        if n_channels != len(expected_channels):
            raise ValueError(
                f"Channel count mismatch: expected {len(expected_channels)}, got {n_channels}"
            )

        return waveform_array, metadata

    def _load_legacy_format(
        self,
        data: Dict,
        expected_channels: List[str],
        expected_duration: float,
        expected_sampling_rate: float
    ) -> Tuple[np.ndarray, Dict[str, Any]]:
        """
        Load from legacy TimeDomain format.

        Expected structure:
            {
                "TimeDomain": [
                    {
                        "Channel": "ZERO_THREE_LEFT_LEFT",
                        "SampleRate": 250,
                        "Timestamp": "2024-03-15T09:30:00",
                        "LFPData": [0.123, -0.456, ...]
                    },
                    ...
                ]
            }
        """
        self.logger.info("Loading legacy TimeDomain format")
        time_domain = data['TimeDomain']

        # Group data by channel
        channel_data_map = {}
        for record in time_domain:
            channel = record.get('Channel', '')
            lfp_data = record.get('LFPData', [])

            if channel not in channel_data_map:
                channel_data_map[channel] = []
            channel_data_map[channel].extend(lfp_data)

        # Build arrays in expected order
        channel_arrays = []
        missing_channels = []

        for label in expected_channels:
            if label not in channel_data_map:
                missing_channels.append(label)
                # Use zeros
                if len(channel_arrays) > 0:
                    channel_arrays.append(np.zeros(len(channel_arrays[0])))
                else:
                    expected_samples = int(expected_duration * expected_sampling_rate)
                    channel_arrays.append(np.zeros(expected_samples))
            else:
                channel_array = np.array(channel_data_map[label], dtype=np.float64)
                channel_arrays.append(channel_array)

        if missing_channels:
            self.logger.warning(
                f"Legacy format: channels {missing_channels} not found, using zeros"
            )

        waveform_array = np.column_stack(channel_arrays)

        # Extract metadata from first record
        first_record = time_domain[0] if time_domain else {}
        metadata = {
            'sampling_rate': first_record.get('SampleRate', expected_sampling_rate),
            'recording_date': first_record.get('Timestamp', None),
            'format': 'legacy_time_domain'
        }

        return waveform_array, metadata

    def _load_numpy(
        self,
        file_path: Path,
        expected_channels: List[str],
        expected_duration: float,
        expected_sampling_rate: float
    ) -> Tuple[np.ndarray, Dict[str, Any]]:
        """Load from NumPy binary format."""
        self.logger.debug("Loading NumPy binary format")

        waveform_array = np.load(file_path)

        # Validate shape
        if waveform_array.ndim != 2:
            raise ValueError(
                f"Expected 2D array, got shape {waveform_array.shape}"
            )

        n_samples, n_channels = waveform_array.shape
        expected_samples = int(expected_duration * expected_sampling_rate)

        if abs(n_samples - expected_samples) > expected_sampling_rate:
            self.logger.warning(
                f"Sample count mismatch: expected ~{expected_samples}, got {n_samples}"
            )

        if n_channels != len(expected_channels):
            raise ValueError(
                f"Channel count mismatch: expected {len(expected_channels)}, got {n_channels}"
            )

        # No metadata in .npy files
        metadata = {'format': 'numpy_binary'}
        return waveform_array, metadata

    def _is_raw_medtronic_format(self, data: Dict) -> bool:
        """
        Detect if JSON contains raw Medtronic streaming data.

        Returns True if:
        - Has 'BrainSenseTimeDomain' or 'IndefiniteStreaming' arrays
        - Arrays contain records with 'TimeDomainData' or 'LFPData' field

        Args:
            data: Parsed JSON data

        Returns:
            bool: True if raw Medtronic format detected
        """
        # Check for raw Medtronic array keys
        for key in ['BrainSenseTimeDomain', 'IndefiniteStreaming']:
            if key in data and isinstance(data[key], list):
                # Check if array has the key (even if empty, it's raw format)
                # Or verify at least one record has TimeDomainData/LFPData
                if len(data[key]) == 0:
                    # Empty array with raw key is still raw format
                    return True

                # Check any record for TimeDomainData or LFPData
                for record in data[key]:
                    if isinstance(record, dict):
                        if 'TimeDomainData' in record or 'LFPData' in record:
                            return True

        return False

    def _channels_match_hemisphere(self, raw_channel: str, expected_label: str) -> bool:
        """
        Check if raw channel name matches expected label by hemisphere.

        Examples:
            "ZERO_THREE_LEFT", "Ch0_LEFT" → True
            "ZERO_THREE_RIGHT", "Ch1_RIGHT" → True
            "ZERO_THREE_LEFT", "Ch1_RIGHT" → False

        Args:
            raw_channel: Raw Medtronic channel name (e.g., "ZERO_THREE_LEFT")
            expected_label: Expected channel label (e.g., "Ch0_LEFT")

        Returns:
            bool: True if channels match by hemisphere
        """
        raw_upper = raw_channel.upper()
        expected_upper = expected_label.upper()

        if 'LEFT' in raw_upper and 'LEFT' in expected_upper:
            return True
        if 'RIGHT' in raw_upper and 'RIGHT' in expected_upper:
            return True

        return False

    def _load_raw_medtronic_format(
        self,
        data: Dict,
        expected_channels: List[str],
        expected_duration: float,
        expected_sampling_rate: float
    ) -> Tuple[np.ndarray, Dict[str, Any]]:
        """
        Load from raw Medtronic format (IndefiniteStreaming or BrainSenseTimeDomain).

        Format structure:
            {
                "IndefiniteStreaming": [
                    {
                        "Channel": "ZERO_THREE_LEFT",
                        "SampleRateInHz": 250,
                        "TimeDomainData": [20.4, 20.1, ...],
                        "FirstPacketDateTime": "2020-03-01T13:48:43.000Z",
                        "Gain": 230
                    },
                    {
                        "Channel": "ZERO_THREE_RIGHT",
                        "SampleRateInHz": 250,
                        "TimeDomainData": [15.2, 14.8, ...]
                    }
                ]
            }

        Args:
            data: Parsed JSON data
            expected_channels: Expected channel labels (from DB)
            expected_duration: Expected duration in seconds
            expected_sampling_rate: Expected sampling rate in Hz

        Returns:
            Tuple[np.ndarray, Dict]:
                - Waveform array (n_samples, n_channels) in expected channel order
                - Metadata dict (sampling_rate, timestamp, format, etc.)

        Raises:
            ValueError: If no streaming records found or data invalid
        """
        self.logger.info("Loading raw Medtronic format")

        # Extract raw streaming records
        streaming_records = []
        source_key = None
        for key in ['BrainSenseTimeDomain', 'IndefiniteStreaming']:
            if key in data and isinstance(data[key], list):
                streaming_records = data[key]
                source_key = key
                break

        if not streaming_records:
            raise ValueError("No streaming records found in raw Medtronic file")

        # Build channel_name → waveform_array mapping
        channel_data_map = {}
        metadata_by_channel = {}

        for record in streaming_records:
            if not isinstance(record, dict):
                continue

            # Extract channel name (required)
            channel = record.get('Channel') or record.get('channel')
            if not channel:
                self.logger.warning("Skipping record without Channel field")
                continue

            # Extract TimeDomainData (required)
            waveform_data_raw = record.get('TimeDomainData') or record.get('LFPData')
            if not waveform_data_raw or not isinstance(waveform_data_raw, list):
                self.logger.warning(f"Skipping channel {channel}: no TimeDomainData")
                continue

            # Convert to numpy array
            waveform_array = np.array(waveform_data_raw, dtype=np.float64)
            channel_data_map[channel] = waveform_array

            # Store metadata for this channel
            metadata_by_channel[channel] = {
                'sample_rate': record.get('SampleRateInHz') or record.get('SampleRate'),
                'timestamp': record.get('FirstPacketDateTime') or record.get('Timestamp'),
                'gain': record.get('Gain'),
                'sample_count': len(waveform_array)
            }

        # Map raw channel names to expected channel labels
        channel_arrays = []
        missing_channels = []
        matched_channels = []

        for expected_label in expected_channels:
            # Find matching channel in raw data
            matched_channel = None

            # Strategy: Match by hemisphere
            for raw_channel_name in channel_data_map.keys():
                if expected_label in raw_channel_name or \
                   self._channels_match_hemisphere(raw_channel_name, expected_label):
                    matched_channel = raw_channel_name
                    break

            if matched_channel:
                channel_arrays.append(channel_data_map[matched_channel])
                matched_channels.append(f"{expected_label} ← {matched_channel}")
            else:
                # Use zeros for missing channel
                missing_channels.append(expected_label)
                if len(channel_arrays) > 0:
                    # Match length of first channel
                    channel_arrays.append(np.zeros(len(channel_arrays[0])))
                else:
                    # Estimate length from duration and sampling rate
                    expected_samples = int(expected_duration * expected_sampling_rate)
                    channel_arrays.append(np.zeros(expected_samples))

        if missing_channels:
            self.logger.warning(
                f"Raw format: channels {missing_channels} not found in file, using zeros"
            )

        if matched_channels:
            self.logger.info(f"Matched channels: {matched_channels}")

        # Stack into 2D array (samples, channels)
        waveform_array = np.column_stack(channel_arrays)

        # Validate shape
        n_samples, n_channels = waveform_array.shape
        expected_samples = int(expected_duration * expected_sampling_rate)

        # Allow 1 second tolerance
        if abs(n_samples - expected_samples) > expected_sampling_rate:
            self.logger.warning(
                f"Sample count mismatch: expected ~{expected_samples}, got {n_samples} "
                f"(difference: {abs(n_samples - expected_samples)} samples)"
            )

        if n_channels != len(expected_channels):
            raise ValueError(
                f"Channel count mismatch: expected {len(expected_channels)}, got {n_channels}"
            )

        # Extract metadata from first available channel
        first_metadata = next(iter(metadata_by_channel.values())) if metadata_by_channel else {}

        metadata = {
            'sampling_rate': first_metadata.get('sample_rate', expected_sampling_rate),
            'recording_date': first_metadata.get('timestamp'),
            'format': f'raw_medtronic_{source_key}',
            'channel_count': n_channels,
            'sample_count': n_samples
        }

        return waveform_array, metadata

    def compute_file_checksum(self, file_path: Path) -> str:
        """
        Compute SHA-256 checksum of file.

        Args:
            file_path: Path to file

        Returns:
            str: Hex digest of SHA-256 hash
        """
        sha256 = hashlib.sha256()
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                sha256.update(chunk)
        return sha256.hexdigest()
