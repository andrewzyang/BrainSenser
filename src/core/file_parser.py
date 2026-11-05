"""
FileParser for BrainSense JSON files.

This module provides parsing functionality for BrainSense JSON files exported
from Medtronic DBS systems. It classifies records by type and extracts timeline
and snapshot data into structured dataclasses.

Author: iEEG BrainSense Development Team
Last Updated: 2025-10-01
"""

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import List, Optional, Dict, Any

from src.core.models.timeline_record import TimelineRecord
from src.core.models.snapshot_record import SnapshotRecord
from src.core.models.streaming_record import StreamingRecord
from src.core.deduplication_engine import DeduplicationEngine

logger = logging.getLogger(__name__)


class RecordType(Enum):
    """
    BrainSense record types.

    Based on BrainSense JSON export format from Medtronic DBS systems.
    """
    TIMELINE = "BrainSenseTimeDomain"  # LFP time-domain data
    SNAPSHOT = "BrainSenseLfp"  # Frequency snapshot (PSD)
    INDEFINITE_STREAM = "IndefiniteStreaming"  # Continuous streaming
    UNKNOWN = "Unknown"  # Unrecognized record type


@dataclass
class ParsedFileData:
    """
    Result of parsing a BrainSense JSON file.

    Contains lists of parsed records organized by type, along with
    file metadata and parsing statistics.

    Attributes:
        timeline_records: List of TimelineRecord instances
        snapshot_records: List of SnapshotRecord instances
        streaming_records: List of StreamingRecord instances
        file_hash: SHA256 hash of source file
        file_name: Original filename
        total_records: Total number of records in file
        skipped_records: Number of records skipped (unknown types)
        parse_errors: Number of records that failed to parse
    """
    timeline_records: List[TimelineRecord]
    snapshot_records: List[SnapshotRecord]
    streaming_records: List['StreamingRecord']
    file_hash: str
    file_name: str
    total_records: int
    skipped_records: int
    parse_errors: int


class FileParser:
    """
    Parser for BrainSense JSON files.

    Parses JSON files exported from Medtronic DBS systems, extracting timeline
    and snapshot records. Automatically calculates data hashes for deduplication.

    Example:
        >>> from pathlib import Path
        >>> file_path = Path("patient_data.json")
        >>> parsed = FileParser.parse_json(file_path)
        >>> print(f"Timeline records: {len(parsed.timeline_records)}")
        >>> print(f"Snapshot records: {len(parsed.snapshot_records)}")
    """

    @staticmethod
    def parse_json(file_path: Path, patient_id: Optional[str] = None) -> ParsedFileData:
        """
        Parse BrainSense JSON file.

        Reads JSON file, classifies records, and extracts timeline and snapshot data.
        Automatically calculates data hashes for deduplication.

        Args:
            file_path: Path to BrainSense JSON file
            patient_id: Optional patient ID (used for setting patient_id in records)

        Returns:
            ParsedFileData: Parsed records and metadata

        Raises:
            FileNotFoundError: If file does not exist
            json.JSONDecodeError: If file is not valid JSON
            ValueError: If file format is invalid

        Example:
            >>> file_path = Path("data.json")
            >>> parsed = FileParser.parse_json(file_path, patient_id="PATIENT001")
            >>> for record in parsed.timeline_records:
            ...     print(f"Timestamp: {record.timestamp}")
        """
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        # Calculate file hash for duplicate detection
        file_hash = DeduplicationEngine.calculate_file_hash(file_path)

        # Read JSON file
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # Initialize counters
        timeline_records = []
        snapshot_records = []
        streaming_records = []
        total_records = 0
        skipped_records = 0
        parse_errors = 0

        # Determine the root structure
        # BrainSense JSON can be:
        # 1. Array of records at root
        # 2. Object with "BrainSenseTimeDomain" and "BrainSenseLfp" arrays
        # 3. Object with other nested structures

        records_to_process = []

        if isinstance(data, list):
            # Case 1: Array at root
            records_to_process = data
        elif isinstance(data, dict):
            # Case 2: Object with named arrays

            # FIRST: Check for DiagnosticData (standard Medtronic structure)
            if 'DiagnosticData' in data:
                diagnostic = data['DiagnosticData']

                # Extract LfpFrequencySnapshotEvents (BrainSense Events/Snapshots)
                if 'LfpFrequencySnapshotEvents' in diagnostic and isinstance(diagnostic['LfpFrequencySnapshotEvents'], list):
                    for event in diagnostic['LfpFrequencySnapshotEvents']:
                        if isinstance(event, dict):
                            event['_array_source'] = 'LfpFrequencySnapshotEvents'
                            records_to_process.append(event)
                    logger.info(f"Found {len(diagnostic['LfpFrequencySnapshotEvents'])} snapshot events in DiagnosticData")

                # Also check for LFPTrendLogs (Timeline data) - supports two formats
                if 'LFPTrendLogs' in diagnostic:
                    trend_logs = diagnostic['LFPTrendLogs']

                    # Format 1: List of log entries (each with LfpData array)
                    if isinstance(trend_logs, list):
                        for log in trend_logs:
                            if isinstance(log, dict) and 'LfpData' in log:
                                # Similar to BrainSenseLfp handling
                                therapy_snapshot = log.get('TherapySnapshot', {})
                                base_timestamp = log.get('FirstPacketDateTime')
                                sample_rate = log.get('SampleRateInHz', 2)
                                channel = log.get('Channel', '')

                                for lfp_sample in log.get('LfpData', []):
                                    if isinstance(lfp_sample, dict):
                                        sample_record = {
                                            '_array_source': 'LFPTrendLogs',
                                            '_lfp_sample': lfp_sample,
                                            '_therapy_snapshot': therapy_snapshot,
                                            '_base_timestamp': base_timestamp,
                                            '_sample_rate': sample_rate,
                                            '_channel': channel
                                        }
                                        records_to_process.append(sample_record)

                    # Format 2: Dict with hemisphere keys containing timestamp-indexed samples (longitudinal files)
                    elif isinstance(trend_logs, dict):
                        for hem_key in ['HemisphereLocationDef.Left', 'HemisphereLocationDef.Right']:
                            if hem_key in trend_logs:
                                hemisphere = 'Left' if 'Left' in hem_key else 'Right'
                                hem_data = trend_logs[hem_key]

                                # Each key is a date, each value is a list of LFP samples
                                for date_key, samples in hem_data.items():
                                    if isinstance(samples, list):
                                        for sample in samples:
                                            if isinstance(sample, dict):
                                                # Each sample has DateTime, LFP, AmplitudeInMilliAmps
                                                sample_record = {
                                                    '_array_source': 'LFPTrendLogs',
                                                    '_timeline_sample': sample,
                                                    '_hemisphere': hemisphere,
                                                }
                                                records_to_process.append(sample_record)

            # ALSO: Check for PatientEvents at root level (patient event metadata)
            if 'PatientEvents' in data:
                patient_events = data['PatientEvents']
                if 'Initial' in patient_events and isinstance(patient_events['Initial'], list):
                    for event in patient_events['Initial']:
                        if isinstance(event, dict):
                            event['_array_source'] = 'PatientEvents'
                            records_to_process.append(event)

            # THEN: Look for common BrainSense keys at root level (legacy/alternative formats)
            for key in ['BrainSenseTimeDomain', 'BrainSenseLfp', 'IndefiniteStreaming', 'records', 'data']:
                if key in data and isinstance(data[key], list):
                    # Special handling for BrainSenseLfp (can be Timeline data or direct snapshot records)
                    if key == 'BrainSenseLfp':
                        for parent_record in data[key]:
                            if isinstance(parent_record, dict):
                                # Check if this record has LfpData array (timeline format)
                                if 'LfpData' in parent_record:
                                    # Extract therapy settings and metadata from parent
                                    therapy_snapshot = parent_record.get('TherapySnapshot', {})
                                    base_timestamp = parent_record.get('FirstPacketDateTime')
                                    sample_rate = parent_record.get('SampleRateInHz', 2)
                                    channel = parent_record.get('Channel', '')

                                    # Explode LfpData array into individual timeline samples
                                    for lfp_sample in parent_record.get('LfpData', []):
                                        if isinstance(lfp_sample, dict):
                                            # Create individual record for each sample
                                            sample_record = {
                                                '_array_source': 'BrainSenseLfp',
                                                '_lfp_sample': lfp_sample,
                                                '_therapy_snapshot': therapy_snapshot,
                                                '_base_timestamp': base_timestamp,
                                                '_sample_rate': sample_rate,
                                                '_channel': channel
                                            }
                                            records_to_process.append(sample_record)
                                else:
                                    # Direct snapshot record (has frequency/power data directly)
                                    parent_record['_array_source'] = 'BrainSenseLfp'
                                    records_to_process.append(parent_record)
                    else:
                        # Standard handling for other array types
                        for record in data[key]:
                            if isinstance(record, dict):
                                # Add _array_source tag if not present
                                if '_array_source' not in record:
                                    record['_array_source'] = key
                        records_to_process.extend(data[key])

            # If no arrays found, treat entire dict as single record
            if not records_to_process:
                records_to_process = [data]

        total_records = len(records_to_process)

        # Process each record
        for record_data in records_to_process:
            try:
                # Classify record type
                record_type = FileParser.classify_record(record_data)

                if record_type == RecordType.TIMELINE:
                    # Extract timeline record
                    timeline_record = FileParser.extract_timeline_record(
                        record_data,
                        source_file=file_path.name,
                        patient_id=patient_id
                    )
                    timeline_records.append(timeline_record)

                elif record_type == RecordType.SNAPSHOT:
                    # Extract snapshot record(s) - can be multiple per event (one per hemisphere)
                    extracted_snapshots = FileParser.extract_snapshot_record(
                        record_data,
                        source_file=file_path.name,
                        patient_id=patient_id
                    )
                    # Handle both single record and list of records
                    # None = skip this record (metadata-only with no FFT data)
                    if extracted_snapshots is None:
                        skipped_records += 1
                    elif isinstance(extracted_snapshots, list):
                        snapshot_records.extend(extracted_snapshots)
                    else:
                        snapshot_records.append(extracted_snapshots)

                elif record_type == RecordType.INDEFINITE_STREAM:
                    # Extract streaming record
                    # Note: Despite the enum name, BrainSense files are task-based recordings
                    # with defined start/end times, making them "definite" streaming
                    streaming_record = FileParser.extract_streaming_record(
                        record_data,
                        source_file=file_path.name,
                        patient_id=patient_id,
                        streaming_type="definite"
                    )
                    streaming_records.append(streaming_record)

                else:
                    # Unknown or unsupported record type
                    skipped_records += 1
                    logger.debug(f"Skipped record of type: {record_type}")

            except Exception as e:
                parse_errors += 1
                logger.warning(f"Failed to parse record: {e}")

        logger.info(
            f"Parsed {file_path.name}: "
            f"{len(timeline_records)} timeline, "
            f"{len(snapshot_records)} snapshots, "
            f"{len(streaming_records)} streaming, "
            f"{skipped_records} skipped, "
            f"{parse_errors} errors"
        )

        return ParsedFileData(
            timeline_records=timeline_records,
            snapshot_records=snapshot_records,
            streaming_records=streaming_records,
            file_hash=file_hash,
            file_name=file_path.name,
            total_records=total_records,
            skipped_records=skipped_records,
            parse_errors=parse_errors
        )

    @staticmethod
    def classify_record(record: Dict[str, Any]) -> RecordType:
        """
        Classify record by type based on BrainSense data structure.

        Four BrainSense modalities (per Swinnen et al. 2025):
        1. Survey: Not in session reports (separate recording)
        2. Streaming: High-res waveforms (IndefiniteStreaming, BrainSenseTimeDomain)
        3. Timeline: Low-freq power tracking (BrainSenseLfp with LfpData array)
        4. Events: Patient-triggered snapshots (PatientEvents)

        Args:
            record: Dictionary representing a single record

        Returns:
            RecordType: Classified record type

        Example:
            >>> record = {"Channel": "ZERO_TWO_LEFT", "TimeDomainData": [...]}
            >>> record_type = FileParser.classify_record(record)
            >>> print(record_type)
            RecordType.INDEFINITE_STREAM
        """
        # FIRST: Check for explicit RecordingType field (most reliable)
        recording_type = record.get('RecordingType') or record.get('recordingType')
        if recording_type:
            # Map Medtronic RecordingType values to our RecordType enum
            if recording_type == "BrainSenseTimeDomain":
                return RecordType.TIMELINE
            elif recording_type == "BrainSenseLfp":
                return RecordType.SNAPSHOT
            elif recording_type == "IndefiniteStreaming":
                return RecordType.INDEFINITE_STREAM

        # SECOND: Check for definitive structural markers
        # Streaming: TimeDomainData array (high-frequency waveform data)
        if 'TimeDomainData' in record and isinstance(record.get('TimeDomainData'), list):
            return RecordType.INDEFINITE_STREAM

        # Timeline: LfpData array (low-frequency power tracking samples)
        if 'LfpData' in record and isinstance(record.get('LfpData'), list):
            return RecordType.TIMELINE

        # THIRD: Content-based heuristics (look at actual data fields)
        # Timeline records have hemisphere LFP values
        has_hemisphere_data = any(key in record for key in [
            'left_hemisphere', 'LeftHemisphere', 'right_hemisphere', 'RightHemisphere',
            'LFP_Left', 'lfp_left', 'LFP_Right', 'lfp_right'
        ])
        if has_hemisphere_data:
            return RecordType.TIMELINE

        # Snapshot records have frequency/power spectral data
        has_frequency = any(key in record for key in ['frequency_data', 'frequencies', 'fft', 'power_data', 'powers'])
        has_event = any(key in record for key in ['event', 'Event', 'event_type', 'EventType'])
        if has_frequency or has_event:
            return RecordType.SNAPSHOT

        # FOURTH: Check _array_source tag (fallback for nested structures)
        # Note: This is last because array names can be ambiguous without content
        if '_array_source' in record:
            source = record['_array_source']
            # LfpFrequencySnapshotEvents = Snapshots (Medtronic standard)
            if 'LfpFrequencySnapshotEvents' in source:
                return RecordType.SNAPSHOT
            # PatientEvents = Snapshots
            elif 'PatientEvents' in source or 'Event' in source or 'Snapshot' in source:
                return RecordType.SNAPSHOT
            # BrainSenseLfp or LFPTrendLogs = Timeline (chronic LFP power tracking)
            elif 'BrainSenseLfp' in source or 'Lfp' in source or 'LFPTrendLogs' in source:
                return RecordType.TIMELINE
            # BrainSenseTimeDomain = Streaming (definite streaming variant)
            elif 'BrainSenseTimeDomain' in source or 'TimeDomain' in source:
                return RecordType.INDEFINITE_STREAM
            # IndefiniteStreaming = Streaming
            elif 'IndefiniteStreaming' in source or 'Streaming' in source:
                return RecordType.INDEFINITE_STREAM

        return RecordType.UNKNOWN

    @staticmethod
    def extract_timeline_record(
        record: Dict[str, Any],
        source_file: str = "",
        patient_id: Optional[str] = None
    ) -> TimelineRecord:
        """
        Extract timeline data from JSON record.

        Handles two timeline data formats:
        1. BrainSenseLfp: Low-frequency (2 Hz) LFP power tracking with therapy amplitude
           Structure: {_lfp_sample: {Left: {LFP, mA}, Right: {LFP, mA}, TicksInMs}, _therapy_snapshot: {...}}
        2. Legacy: Direct LFP hemisphere values with therapy settings

        Args:
            record: Dictionary representing timeline record
            source_file: Name of source file
            patient_id: Optional patient ID

        Returns:
            TimelineRecord: Populated timeline record with data_hash

        Raises:
            ValueError: If required fields are missing

        Example:
            >>> record_data = {
            ...     "_lfp_sample": {"Left": {"LFP": 769, "mA": 0.0}, "Right": {"LFP": 508, "mA": 0.0}, "TicksInMs": 701050}
            ... }
            >>> record = FileParser.extract_timeline_record(record_data)
            >>> print(record.left_hemisphere)
            769
        """
        # Check if this is a longitudinal LFPTrendLogs sample (new format)
        if '_timeline_sample' in record:
            # Extract from longitudinal LFPTrendLogs format
            # Format: {DateTime, LFP, AmplitudeInMilliAmps}
            sample = record['_timeline_sample']
            hemisphere = record.get('_hemisphere', 'Unknown')

            # Extract timestamp
            timestamp_str = sample.get('DateTime')
            if timestamp_str:
                try:
                    timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                except (ValueError, AttributeError):
                    timestamp = datetime.now()
            else:
                timestamp = datetime.now()

            unix_timestamp = timestamp.timestamp()

            # Extract LFP value and amplitude for the specific hemisphere
            lfp_value = float(sample.get('LFP', 0)) if sample.get('LFP') is not None else None
            amplitude = float(sample.get('AmplitudeInMilliAmps', 0)) if sample.get('AmplitudeInMilliAmps') is not None else None

            # Assign to correct hemisphere (this record represents ONE hemisphere only)
            if hemisphere == 'Left':
                left_hemisphere = lfp_value
                right_hemisphere = None
                left_amplitude = amplitude
                right_amplitude = None
            else:  # Right
                left_hemisphere = None
                right_hemisphere = lfp_value
                left_amplitude = None
                right_amplitude = amplitude

            # No therapy settings available in this format
            left_frequency = None
            right_frequency = None
            left_pulse_width = None
            right_pulse_width = None
            therapy_status = "ON" if amplitude and amplitude > 0 else "UNKNOWN"
            session_id = None
            segment_id = None
            segment_type = "LFPTrendLogs"

        # Check if this is a BrainSenseLfp sample (existing format)
        elif '_lfp_sample' in record:
            # Extract from BrainSenseLfp format
            lfp_sample = record['_lfp_sample']
            therapy_snapshot = record.get('_therapy_snapshot', {})
            base_timestamp = record.get('_base_timestamp')

            # Convert TicksInMs to timestamp
            lfp_sample.get('TicksInMs', 0)
            # TicksInMs is milliseconds since device boot - use as offset from base timestamp
            if base_timestamp:
                try:
                    base_dt = datetime.fromisoformat(base_timestamp.replace('Z', '+00:00'))
                    # Use ticks as relative offset (approximate)
                    timestamp = base_dt
                except (ValueError, AttributeError):
                    timestamp = datetime.now()
            else:
                timestamp = datetime.now()

            unix_timestamp = timestamp.timestamp()

            # Extract LFP power values
            left_data = lfp_sample.get('Left', {})
            right_data = lfp_sample.get('Right', {})
            left_hemisphere = float(left_data.get('LFP', 0)) if left_data.get('LFP') is not None else None
            right_hemisphere = float(right_data.get('LFP', 0)) if right_data.get('LFP') is not None else None

            # Extract stimulation amplitudes from sample
            left_amplitude = float(left_data.get('mA', 0)) if left_data.get('mA') is not None else None
            right_amplitude = float(right_data.get('mA', 0)) if right_data.get('mA') is not None else None

            # Extract therapy settings from TherapySnapshot
            left_therapy = therapy_snapshot.get('Left', {})
            right_therapy = therapy_snapshot.get('Right', {})
            left_frequency = FileParser._extract_float(left_therapy, ['FrequencyInHertz', 'RateInHertz'])
            right_frequency = FileParser._extract_float(right_therapy, ['FrequencyInHertz', 'RateInHertz'])
            left_pulse_width = FileParser._extract_float(left_therapy, ['PulseWidthInMicroSecond'])
            right_pulse_width = FileParser._extract_float(right_therapy, ['PulseWidthInMicroSecond'])

            therapy_status = "ON" if left_amplitude or right_amplitude else "OFF"
            session_id = None
            segment_id = str(lfp_sample.get('Seq', ''))
            segment_type = "BrainSenseLfp"

        else:
            # Legacy format - direct extraction
            # Extract timestamp (required)
            timestamp = FileParser._extract_timestamp(record)

            # Extract unix timestamp if available
            unix_timestamp = record.get('unix_timestamp') or record.get('UnixTimestamp')
            if unix_timestamp is None and timestamp:
                unix_timestamp = timestamp.timestamp()

            # Extract LFP values
            left_hemisphere = FileParser._extract_float(record, ['left_hemisphere', 'LeftHemisphere', 'LFP_Left', 'lfp_left'])
            right_hemisphere = FileParser._extract_float(record, ['right_hemisphere', 'RightHemisphere', 'LFP_Right', 'lfp_right'])

            # Extract therapy settings
            left_amplitude = FileParser._extract_float(record, ['left_amplitude', 'LeftAmplitude', 'AmplitudeLeft'])
            right_amplitude = FileParser._extract_float(record, ['right_amplitude', 'RightAmplitude', 'AmplitudeRight'])
            left_frequency = FileParser._extract_float(record, ['left_frequency', 'LeftFrequency', 'FrequencyLeft'])
            right_frequency = FileParser._extract_float(record, ['right_frequency', 'RightFrequency', 'FrequencyRight'])
            left_pulse_width = FileParser._extract_float(record, ['left_pulse_width', 'LeftPulseWidth', 'PulseWidthLeft'])
            right_pulse_width = FileParser._extract_float(record, ['right_pulse_width', 'RightPulseWidth', 'PulseWidthRight'])
            therapy_status = FileParser._extract_string(record, ['therapy_status', 'TherapyStatus', 'Status'])

            # Extract metadata
            session_id = FileParser._extract_string(record, ['session_id', 'SessionID', 'SessionId'])
            segment_id = FileParser._extract_string(record, ['segment_id', 'SegmentID', 'SegmentId'])
            segment_type = FileParser._extract_string(record, ['segment_type', 'SegmentType', 'Type'])

        # Create record (without hash first)
        timeline_record = TimelineRecord(
            timestamp=timestamp,
            unix_timestamp=unix_timestamp,
            left_hemisphere=left_hemisphere,
            right_hemisphere=right_hemisphere,
            left_amplitude=left_amplitude,
            right_amplitude=right_amplitude,
            left_frequency=left_frequency,
            right_frequency=right_frequency,
            left_pulse_width=left_pulse_width,
            right_pulse_width=right_pulse_width,
            therapy_status=therapy_status,
            source_file=source_file,
            session_id=session_id,
            segment_id=segment_id,
            segment_type=segment_type,
        )

        # Calculate and set data hash
        timeline_record.data_hash = DeduplicationEngine.calculate_timeline_hash(timeline_record)

        return timeline_record

    @staticmethod
    def extract_snapshot_record(
        record: Dict[str, Any],
        source_file: str = "",
        patient_id: Optional[str] = None
    ) -> SnapshotRecord:
        """
        Extract snapshot data from JSON record.

        Parses a BrainSense snapshot record and creates a SnapshotRecord instance
        with calculated data hash.

        Args:
            record: Dictionary representing snapshot record
            source_file: Name of source file
            patient_id: Optional patient ID

        Returns:
            SnapshotRecord: Populated snapshot record with data_hash

        Raises:
            ValueError: If required fields are missing

        Example:
            >>> record_data = {
            ...     "timestamp": "2024-01-01T12:00:00",
            ...     "frequency_data": [1.0, 2.0, 3.0],
            ...     "power_data": [10.0, 20.0, 30.0]
            ... }
            >>> record = FileParser.extract_snapshot_record(record_data)
            >>> print(record.data_hash)
        """
        # Check if this is a Medtronic LfpFrequencySnapshotEvent with nested structure
        if 'LfpFrequencySnapshotEvents' in record and isinstance(record['LfpFrequencySnapshotEvents'], dict):
            # Handle nested structure (e.g., from DiagnosticData.LfpFrequencySnapshotEvents)
            nested_data = record['LfpFrequencySnapshotEvents']

            # Extract timestamp from outer record
            timestamp = FileParser._extract_timestamp(record)
            event_name = FileParser._extract_string(record, ['EventName', 'event_name', 'Name'])
            event_type = "LfpFrequencySnapshot"

            # Process each hemisphere separately
            snapshots = []
            for hem_key in ['HemisphereLocationDef.Left', 'HemisphereLocationDef.Right']:
                if hem_key in nested_data:
                    hem_data = nested_data[hem_key]

                    # Extract FFTBinData as frequency/power arrays
                    fft_data = hem_data.get('FFTBinData', [])
                    freq_array = hem_data.get('Frequency') or hem_data.get('frequencies')

                    if fft_data:
                        power_data = json.dumps(fft_data)

                        # Use actual frequency bins if available (0.98 Hz resolution from device)
                        if freq_array:
                            frequency_data = json.dumps(freq_array)
                        else:
                            # Fallback: generate frequency bins (0-125 Hz range)
                            # Note: This should rarely happen as modern data includes Frequency array
                            freq_bins = [i * (125.0 / len(fft_data)) for i in range(len(fft_data))]
                            frequency_data = json.dumps(freq_bins)
                    else:
                        frequency_data = FileParser._extract_json_array(hem_data, ['Frequency', 'frequencies'])
                        power_data = FileParser._extract_json_array(hem_data, ['Power', 'powers'])

                    hemisphere = 'Left' if 'Left' in hem_key else 'Right'

                    # Extract therapy state from hemisphere data
                    therapy_amp = hem_data.get('StimulationAmplitude', 0.0)

                    # Extract sampling rate (ensure it's a scalar float, not an array)
                    sampling_rate_value = hem_data.get('SamplingRate') or hem_data.get('SampleRateInHz')
                    if sampling_rate_value is None or isinstance(sampling_rate_value, (list, tuple)):
                        sampling_rate_value = 250.0  # Default for BrainSense

                    # Create snapshot for this hemisphere
                    snapshot_record = SnapshotRecord(
                        timestamp=timestamp,
                        unix_timestamp=timestamp.timestamp() if timestamp else None,
                        event_type=event_type,
                        event_subtype="Hemisphere",
                        event_name=event_name,
                        frequency_data=frequency_data,
                        power_data=power_data,
                        hemisphere=hemisphere,
                        source_file=source_file,
                        session_id=hem_data.get('GroupId'),
                        duration_seconds=30.0,
                        sampling_rate=sampling_rate_value,
                        patient_event=1,  # These are patient-triggered events
                        patient_event_id=record.get('EventID'),
                        event_notes=None,
                        therapy_amplitude_left=therapy_amp if hemisphere == 'Left' else None,
                        therapy_amplitude_right=therapy_amp if hemisphere == 'Right' else None,
                        therapy_frequency=None,
                    )
                    snapshot_record.data_hash = DeduplicationEngine.calculate_snapshot_hash(snapshot_record)
                    snapshots.append(snapshot_record)  # Add to list instead of returning immediately

            # Return all hemisphere snapshots if we found any
            if snapshots:
                return snapshots  # Return list of all hemispheres

        # Standard extraction for flat structure (metadata-only events)
        # Extract timestamp (required)
        timestamp = FileParser._extract_timestamp(record)

        # Extract unix timestamp if available
        unix_timestamp = record.get('unix_timestamp') or record.get('UnixTimestamp')
        if unix_timestamp is None and timestamp:
            unix_timestamp = timestamp.timestamp()

        # Extract event information
        event_type = FileParser._extract_string(record, ['event_type', 'EventType', 'Type'])
        event_subtype = FileParser._extract_string(record, ['event_subtype', 'EventSubtype', 'Subtype'])
        event_name = FileParser._extract_string(record, ['event_name', 'EventName', 'Name'])

        # Extract frequency and power data (stored as JSON)
        frequency_data = FileParser._extract_json_array(record, ['frequency_data', 'FrequencyData', 'frequencies', 'Frequencies', 'FFTBinData'])
        power_data = FileParser._extract_json_array(record, ['power_data', 'PowerData', 'powers', 'Powers'])

        # Skip metadata-only events (no FFT data)
        # These are cross-file duplicates where the same event appears in multiple session exports
        # but only the original session has the FFT data. We only want to store events with actual data.
        if frequency_data == '[]' and power_data == '[]':
            logger.debug(f"Skipping metadata-only snapshot event: {timestamp} {event_name} (no FFT data)")
            return None  # Signal to skip this record

        # Extract hemisphere
        hemisphere = FileParser._extract_string(record, ['hemisphere', 'Hemisphere', 'Side'])

        # Extract metadata
        session_id = FileParser._extract_string(record, ['session_id', 'SessionID', 'SessionId'])
        duration_seconds = FileParser._extract_float(record, ['duration_seconds', 'Duration', 'DurationSeconds']) or 30.0
        sampling_rate = FileParser._extract_float(record, ['sampling_rate', 'SamplingRate', 'SampleRate'])

        # Extract patient event info
        patient_event = 1 if record.get('patient_event') or record.get('PatientEvent') else 0
        patient_event_id = FileParser._extract_string(record, ['patient_event_id', 'PatientEventID'])
        event_notes = FileParser._extract_string(record, ['event_notes', 'EventNotes', 'Notes'])

        # Extract therapy state
        therapy_amplitude_left = FileParser._extract_float(record, ['therapy_amplitude_left', 'TherapyAmplitudeLeft'])
        therapy_amplitude_right = FileParser._extract_float(record, ['therapy_amplitude_right', 'TherapyAmplitudeRight'])
        therapy_frequency = FileParser._extract_float(record, ['therapy_frequency', 'TherapyFrequency'])

        # Create record (without hash first)
        snapshot_record = SnapshotRecord(
            timestamp=timestamp,
            unix_timestamp=unix_timestamp,
            event_type=event_type,
            event_subtype=event_subtype,
            event_name=event_name,
            frequency_data=frequency_data,
            power_data=power_data,
            hemisphere=hemisphere,
            source_file=source_file,
            session_id=session_id,
            duration_seconds=duration_seconds,
            sampling_rate=sampling_rate,
            patient_event=patient_event,
            patient_event_id=patient_event_id,
            event_notes=event_notes,
            therapy_amplitude_left=therapy_amplitude_left,
            therapy_amplitude_right=therapy_amplitude_right,
            therapy_frequency=therapy_frequency,
        )

        # Calculate and set data hash
        snapshot_record.data_hash = DeduplicationEngine.calculate_snapshot_hash(snapshot_record)

        return snapshot_record

    @staticmethod
    def extract_streaming_record(
        record: Dict[str, Any],
        source_file: str = "",
        patient_id: Optional[str] = None,
        streaming_type: str = "indefinite"
    ) -> StreamingRecord:
        """
        Extract streaming data from JSON record.

        Parses an IndefiniteStreaming or DefiniteStreaming record and creates
        a StreamingRecord instance with calculated data hash.

        Args:
            record: Dictionary representing streaming record
            source_file: Name of source file
            patient_id: Optional patient ID
            streaming_type: "indefinite" or "definite"

        Returns:
            StreamingRecord: Populated streaming record with data_hash

        Raises:
            ValueError: If required fields are missing

        Example:
            >>> record_data = {
            ...     "FirstPacketDateTime": "2020-03-01T23:21:21.000Z",
            ...     "Channel": "ZERO_THREE_LEFT",
            ...     "SampleRateInHz": 250,
            ...     "TimeDomainData": [20.4, 20.1, 20.0, ...],
            ...     "Gain": 228
            ... }
            >>> record = FileParser.extract_streaming_record(record_data)
            >>> print(record.data_hash)
        """
        # Extract timestamp (required)
        timestamp_str = record.get('FirstPacketDateTime') or record.get('timestamp')
        if timestamp_str:
            try:
                timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
            except (ValueError, AttributeError):
                timestamp = datetime.now()
        else:
            timestamp = datetime.now()

        # Extract unix timestamp
        unix_timestamp = record.get('unix_timestamp')
        if unix_timestamp is None and timestamp:
            unix_timestamp = timestamp.timestamp()

        # Extract channel information (required)
        channel = record.get('Channel') or record.get('channel') or ""

        # Derive hemisphere from channel name
        hemisphere = None
        if 'LEFT' in channel.upper():
            hemisphere = "LEFT"
        elif 'RIGHT' in channel.upper():
            hemisphere = "RIGHT"

        # Extract waveform data (required - large array!)
        waveform_data_raw = record.get('TimeDomainData') or record.get('waveform_data') or []
        if isinstance(waveform_data_raw, list):
            waveform_data = json.dumps(waveform_data_raw)
            sample_count = len(waveform_data_raw)
        elif isinstance(waveform_data_raw, str):
            waveform_data = waveform_data_raw
            try:
                sample_count = len(json.loads(waveform_data_raw))
            except:
                sample_count = 0
        else:
            waveform_data = "[]"
            sample_count = 0

        # Extract sample rate
        sample_rate = record.get('SampleRateInHz') or record.get('sample_rate') or 0

        # Calculate duration (seconds = samples / sample_rate)
        duration_seconds = None
        if sample_count > 0 and sample_rate > 0:
            duration_seconds = sample_count / sample_rate

        # Extract gain
        gain = record.get('Gain') or record.get('gain')

        # Extract packet reconstruction metadata
        global_sequences = record.get('GlobalSequences')
        global_packet_sizes = record.get('GlobalPacketSizes')
        ticks_in_mses = record.get('TicksInMses')
        pass_info = record.get('Pass')

        # Extract metadata
        session_id = FileParser._extract_string(record, ['session_id', 'SessionID', 'SessionId'])

        # Create record (without hash first)
        streaming_record = StreamingRecord(
            timestamp=timestamp,
            unix_timestamp=unix_timestamp,
            channel=channel,
            hemisphere=hemisphere,
            waveform_data=waveform_data,
            sample_count=sample_count,
            sample_rate=sample_rate,
            duration_seconds=duration_seconds,
            gain=gain,
            global_sequences=global_sequences,
            global_packet_sizes=global_packet_sizes,
            ticks_in_mses=ticks_in_mses,
            pass_info=pass_info,
            source_file=source_file,
            session_id=session_id,
            streaming_type=streaming_type,
        )

        # Calculate and set data hash
        streaming_record.data_hash = DeduplicationEngine.calculate_streaming_hash(streaming_record)

        return streaming_record

    # ========================================================================
    # Helper Methods
    # ========================================================================

    @staticmethod
    def _extract_timestamp(record: Dict[str, Any]) -> datetime:
        """Extract timestamp from record (required field)."""
        for key in ['timestamp', 'Timestamp', 'DateTime', 'EventDateTime', 'dateTime', 'time', 'Time']:
            if key in record:
                value = record[key]
                if isinstance(value, str):
                    # Try ISO format first
                    try:
                        return datetime.fromisoformat(value.replace('Z', '+00:00'))
                    except ValueError:
                        pass
                    # Try common formats
                    for fmt in ['%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S', '%m/%d/%Y %H:%M:%S']:
                        try:
                            return datetime.strptime(value, fmt)
                        except ValueError:
                            continue
                elif isinstance(value, (int, float)):
                    # Unix timestamp. An out-of-range value raises OverflowError or
                    # ValueError (OSError on Windows); treat it like a bad string.
                    try:
                        return datetime.fromtimestamp(value)
                    except (OverflowError, OSError, ValueError):
                        pass

        raise ValueError("No valid timestamp found in record")

    @staticmethod
    def _extract_float(record: Dict[str, Any], keys: List[str]) -> Optional[float]:
        """Extract float value from record using multiple possible keys."""
        for key in keys:
            if key in record:
                value = record[key]
                if value is not None:
                    try:
                        return float(value)
                    except (ValueError, TypeError):
                        pass
        return None

    @staticmethod
    def _extract_string(record: Dict[str, Any], keys: List[str]) -> Optional[str]:
        """Extract string value from record using multiple possible keys."""
        for key in keys:
            if key in record:
                value = record[key]
                if value is not None:
                    return str(value)
        return None

    @staticmethod
    def _extract_json_array(record: Dict[str, Any], keys: List[str]) -> str:
        """Extract array from record and convert to JSON string."""
        for key in keys:
            if key in record:
                value = record[key]
                if value is not None:
                    if isinstance(value, str):
                        # Already JSON string
                        return value
                    elif isinstance(value, (list, tuple)):
                        # Convert to JSON
                        return json.dumps(value)
        return "[]"
