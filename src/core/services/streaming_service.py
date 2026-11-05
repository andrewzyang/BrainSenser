"""
Streaming service for managing streaming recording files.

This service provides business logic for streaming recording operations including:
- Loading recording data from files
- Trimming recordings to specific time ranges
- Applying signal processing filters
- Calculating recording statistics
- Exporting recordings in various formats

Author: iEEG BrainSense Development Team
Last Updated: 2025-10-07
"""

import logging
import json
import uuid
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime
import numpy as np

from src.core.models import StreamingRecording
from src.infrastructure.repositories.streaming_recording_repository import StreamingRecordingRepository
from src.core.path_resolver import PathResolver
from src.core.utils.atomic_file_writer import AtomicFileWriter
from src.core.preprocessing import CardiacArtifactRemoval, SignalIntegrityCleaner

logger = logging.getLogger(__name__)


class FileIntegrityError(Exception):
    """Raised when file checksum validation fails."""


class StreamingService:
    """
    Service for streaming recording file operations.

    Orchestrates loading, trimming, filtering, and exporting of streaming recordings.
    **Loads waveform data directly from JSON files on disk** (not from database).

    Architecture (Updated 2025-10-08):
        - Metadata stored in `streaming_recordings` table (database)
        - Waveform data stored in JSON files (file system)
        - File path resolution supports absolute and relative paths
        - Checksum validation for data integrity

    Benefits of file-based loading:
        - Faster loading (no database overhead)
        - Smaller database size (no duplicate waveform storage)
        - Simpler data pipeline (single source of truth)
        - Easier testing and debugging

    Example:
        >>> from src.infrastructure.database.adapters import SQLiteAdapter
        >>> from src.core.path_resolver import PathResolver
        >>> from src.infrastructure.repositories import StreamingRecordingRepository
        >>>
        >>> adapter = SQLiteAdapter()
        >>> resolver = PathResolver()
        >>> repo = StreamingRecordingRepository(adapter, resolver)
        >>> service = StreamingService(repo, resolver)
        >>>
        >>> # Load recording (from file, not database)
        >>> data, recording = service.load_recording("P01", "rec_001")
        >>> # Waveform data loaded from file at recording.file_path
        >>>
        >>> # Trim recording
        >>> trimmed = service.trim_recording(
        ...     patient_id="P01",
        ...     recording_id="rec_001",
        ...     start_sec=300.0,
        ...     end_sec=1500.0,
        ...     filters=['highpass_0.5Hz', 'dc_offset_removal'],
        ...     output_name="trimmed_recording.json"
        ... )
        >>> # Trimmed data saved to new JSON file
    """

    def __init__(
        self,
        repository: StreamingRecordingRepository,
        path_resolver: PathResolver
    ):
        """
        Initialize StreamingService.

        Args:
            repository: StreamingRecordingRepository for database operations
            path_resolver: PathResolver for file path management
        """
        self.repository = repository
        self.path_resolver = path_resolver
        self.logger = logging.getLogger(__name__)

        # Initialize cardiac preprocessor (reusable instance for performance)
        self._cardiac_preprocessor = CardiacArtifactRemoval(enabled=True, fs=250)
        # Integrity cleaner repairs NaNs/frozen segments prior to spectral filters
        self._integrity_cleaner = SignalIntegrityCleaner()

    def get_recordings_for_patient(self, patient_id: str) -> List[StreamingRecording]:
        """
        Get all recordings for a patient.

        Automatically cleans up orphaned database records (files that don't exist).

        Args:
            patient_id: Patient identifier

        Returns:
            List[StreamingRecording]: All recordings for the patient
        """
        # Clean up orphaned records before returning
        self.cleanup_orphaned_recordings(patient_id)

        return self.repository.get_by_patient(patient_id)

    def get_recording_metadata(self, patient_id: str, recording_id: str) -> Optional[StreamingRecording]:
        """
        Get recording metadata without loading the full waveform data.

        Args:
            patient_id: Patient identifier
            recording_id: Recording identifier

        Returns:
            StreamingRecording: Recording metadata, or None if not found
        """
        return self.repository.get_by_id(patient_id, recording_id)

    def load_recording(
        self,
        patient_id: str,
        recording_id: str
    ) -> Tuple[np.ndarray, StreamingRecording]:
        """
        Load recording data and metadata.

        Now loads waveform data directly from source files instead of database.
        This provides faster loading, smaller database size, and simpler data pipeline.

        Args:
            patient_id: Patient identifier
            recording_id: Recording identifier

        Returns:
            Tuple[np.ndarray, StreamingRecording]:
                - Waveform array of shape (n_samples, n_channels)
                - Recording metadata

        Raises:
            ValueError: If recording not found in database
            FileNotFoundError: If recording file not found on disk
            RuntimeError: If waveform data cannot be loaded
        """
        self.logger.info(f"Loading recording {recording_id} for patient {patient_id}")

        # Get recording metadata from database
        recording = self.repository.get_by_id(patient_id, recording_id)
        if not recording:
            raise ValueError(f"Recording {recording_id} not found in database")

        try:
            # Resolve file path (handles absolute, relative, subdirectories)
            file_path = self._resolve_file_path(recording, patient_id)

            self.logger.debug(f"Loading waveform data from {file_path}")

            # Load waveform data from file
            from src.core.services.streaming_file_loader import StreamingFileLoader
            loader = StreamingFileLoader()

            # Validate checksum if stored (before loading full file)
            if recording.file_checksum:
                computed_checksum = loader.compute_file_checksum(file_path)
                if computed_checksum != recording.file_checksum:
                    raise FileIntegrityError(
                        f"File checksum mismatch for {recording_id}:\n"
                        f"  Expected: {recording.file_checksum}\n"
                        f"  Computed: {computed_checksum}\n"
                        f"  File may be corrupted or modified.\n"
                        f"  Location: {file_path}"
                    )
                self.logger.debug(f"Checksum validated for {recording_id}")

            # Load waveform data from file
            waveform_array, file_metadata = loader.load_from_file(
                file_path=file_path,
                expected_channels=recording.channel_labels,
                expected_duration=recording.duration_seconds,
                expected_sampling_rate=recording.sampling_rate
            )

            self.logger.info(
                f"Loaded recording with shape {waveform_array.shape} "
                f"({recording.duration_seconds:.1f}s @ {recording.sampling_rate}Hz)"
            )

            # Store checksum if not already stored
            if not recording.file_checksum and 'file_checksum' in file_metadata:
                recording.file_checksum = file_metadata['file_checksum']
                self.repository.update(patient_id, recording)
                self.logger.debug(f"Stored checksum for {recording_id}: {recording.file_checksum[:8]}...")

            return waveform_array, recording

        except FileNotFoundError:
            patient_dir = self.path_resolver.get_patient_directory(patient_id)
            error_msg = (
                f"Recording file not found for {recording_id}\n"
                f"Expected file: {recording.file_path}\n"
                f"Patient directory: {patient_dir}\n"
                f"\n"
                f"Troubleshooting:\n"
                f"1. Check if file exists in patient directory\n"
                f"2. Verify file_path in database is correct\n"
                f"3. Check file permissions\n"
                f"4. Run database integrity check"
            )
            self.logger.error(error_msg)
            raise FileNotFoundError(error_msg)

        except json.JSONDecodeError as e:
            error_msg = (
                f"Invalid JSON format in {recording.file_path}\n"
                f"Error: {e}\n"
                f"\n"
                f"Possible causes:\n"
                f"1. File is corrupted\n"
                f"2. File is incomplete (interrupted upload)\n"
                f"3. File format is not JSON\n"
                f"\n"
                f"Try:\n"
                f"1. Re-upload the recording\n"
                f"2. Check file integrity with 'cat' or 'jq'\n"
                f"3. Contact support if issue persists"
            )
            self.logger.error(error_msg)
            raise ValueError(error_msg)

        except ValueError as e:
            error_msg = (
                f"Invalid recording data in {recording.file_path}\n"
                f"Error: {e}\n"
                f"\n"
                f"This usually indicates:\n"
                f"1. File format mismatch\n"
                f"2. Channel labels don't match expected\n"
                f"3. Duration or sample count mismatch\n"
                f"\n"
                f"Check database metadata matches file content"
            )
            self.logger.error(error_msg)
            raise RuntimeError(error_msg)

        except Exception as e:
            self.logger.error(f"Unexpected error loading recording {recording_id}: {e}")
            raise RuntimeError(f"Failed to load recording: {e}")

    def _resolve_file_path(self, recording: StreamingRecording, patient_id: str) -> Path:
        """
        Resolve recording file path, trying multiple locations.

        Handles absolute paths, relative paths, and searches common subdirectories.

        Args:
            recording: Recording metadata with file_path
            patient_id: Patient identifier

        Returns:
            Path: Resolved absolute path to recording file

        Raises:
            FileNotFoundError: If file cannot be found in any location
        """
        file_path = Path(recording.file_path)

        # 1. Try absolute path as-is
        if file_path.is_absolute() and file_path.exists():
            self.logger.debug(f"Resolved file path (absolute): {file_path}")
            return file_path

        # 2. Try relative to patient directory
        patient_dir = self.path_resolver.get_patient_directory(patient_id)
        candidate = patient_dir / file_path.name
        if candidate.exists():
            self.logger.debug(f"Resolved file path (patient dir): {candidate}")
            return candidate

        # 3. Try common subdirectories
        for subdir in ['streaming', 'recordings', 'data', 'raw']:
            candidate = patient_dir / subdir / file_path.name
            if candidate.exists():
                self.logger.debug(f"Resolved file path ({subdir}): {candidate}")
                return candidate

        # 4. Try alternate naming (with/without .json extension)
        if not file_path.suffix:
            candidate = patient_dir / f"{file_path.name}.json"
            if candidate.exists():
                self.logger.debug(f"Resolved file path (added .json): {candidate}")
                return candidate

        # 5. Try the file_path as given, relative to patient directory
        if not file_path.is_absolute():
            candidate = patient_dir / file_path
            if candidate.exists():
                self.logger.debug(f"Resolved file path (relative): {candidate}")
                return candidate

        # 6. Not found - raise with helpful message
        searched_locations = [
            str(file_path) if file_path.is_absolute() else str(patient_dir / file_path.name),
            str(patient_dir / 'streaming' / file_path.name),
            str(patient_dir / 'recordings' / file_path.name),
            str(patient_dir / 'data' / file_path.name),
            str(patient_dir / 'raw' / file_path.name),
        ]

        raise FileNotFoundError(
            f"Recording file not found: {file_path}\n"
            f"Searched locations:\n" + "\n".join(f"  - {loc}" for loc in searched_locations)
        )

    def trim_recording(
        self,
        patient_id: str,
        recording_id: str,
        start_sec: float,
        end_sec: float,
        filters: List[str],
        output_name: str
    ) -> StreamingRecording:
        """
        Trim recording to specified time range and apply filters.

        Creates a new trimmed recording file and database entry.
        The original recording is not modified.

        Args:
            patient_id: Patient identifier
            recording_id: Original recording identifier
            start_sec: Start time in seconds
            end_sec: End time in seconds
            filters: List of filter names to apply (e.g., ['highpass_0.5Hz'])
            output_name: Name for output file

        Returns:
            StreamingRecording: New trimmed recording metadata

        Raises:
            ValueError: If time range is invalid
            FileNotFoundError: If original recording file doesn't exist
        """
        self.logger.info(
            f"Trimming recording {recording_id} from {start_sec}s to {end_sec}s"
        )

        # Validate time range
        if start_sec >= end_sec:
            raise ValueError(f"Invalid time range: start ({start_sec}) must be < end ({end_sec})")

        # Load original recording
        waveform_data, original_recording = self.load_recording(patient_id, recording_id)

        # Validate time range against recording duration
        if end_sec > original_recording.duration_seconds:
            raise ValueError(
                f"End time ({end_sec}s) exceeds recording duration "
                f"({original_recording.duration_seconds}s)"
            )

        # Calculate sample indices
        start_sample = int(start_sec * original_recording.sampling_rate)
        end_sample = int(end_sec * original_recording.sampling_rate)

        # Trim waveform data
        trimmed_data = waveform_data[start_sample:end_sample, :]

        # Apply filters
        if filters:
            trimmed_data = self.apply_filters(
                trimmed_data,
                filters,
                original_recording.sampling_rate
            )

        # Calculate new duration after filtering (filters may drop samples)
        if trimmed_data.size == 0:
            new_duration = 0.0
        else:
            new_duration = trimmed_data.shape[0] / original_recording.sampling_rate

        # Prepare output file path
        patient_dir = self.path_resolver.get_patient_directory(patient_id)
        output_path = patient_dir / output_name

        # Build JSON structure for atomic write
        n_samples = trimmed_data.shape[0]
        timestamps = [i / original_recording.sampling_rate for i in range(n_samples)]

        channels = {}
        for i, label in enumerate(original_recording.channel_labels):
            channels[label] = trimmed_data[:, i].tolist()

        output_data = {
            'metadata': {
                'recording_date': original_recording.recording_date.isoformat(),
                'duration_seconds': new_duration,
                'sampling_rate': original_recording.sampling_rate,
                'channel_count': original_recording.channel_count,
                'channel_labels': original_recording.channel_labels,
                'trim_start_sec': start_sec,
                'trim_end_sec': end_sec
            },
            'data': {
                'timestamps': timestamps,
                'channels': channels
            }
        }

        # Extract display name from output_name (remove .json extension if present)
        display_name = output_name.replace('.json', '') if output_name else ''

        # Create trimmed recording metadata (will be populated in pre-commit hook)
        trimmed_recording = StreamingRecording(
            id=str(uuid.uuid4()),
            patient_id=patient_id,
            file_path=str(output_path),
            original_file_path=original_recording.file_path,
            recording_date=original_recording.recording_date,
            duration_seconds=new_duration,
            start_time=original_recording.recording_date,
            end_time=None,
            is_trimmed=True,
            file_size_bytes=0,  # Will be set in pre-commit hook
            sampling_rate=original_recording.sampling_rate,
            channel_count=original_recording.channel_count,
            channel_labels=original_recording.channel_labels.copy(),
            metadata={
                **original_recording.metadata,
                'trim_start_sec': start_sec,
                'trim_end_sec': end_sec,
                'display_name': display_name  # Save user's annotation for dropdown display
            },
            processing_applied=filters.copy(),
            file_checksum=None,  # Will be set in pre-commit hook
            created_at=datetime.now(),
            updated_at=datetime.now()
        )

        # Use atomic file writer with pre-commit hook
        writer = AtomicFileWriter()

        def pre_commit_hook(temp_file_path: Path):
            """
            Called after file is written but before rename.
            Computes checksum and creates database entry.
            If this raises an exception, temp file is cleaned up.
            """
            # Compute checksum from temp file
            from src.core.services.streaming_file_loader import StreamingFileLoader
            loader = StreamingFileLoader()
            file_checksum = loader.compute_file_checksum(temp_file_path)
            trimmed_recording.file_checksum = file_checksum
            self.logger.debug(f"Computed checksum for trimmed file: {file_checksum[:8]}...")

            # Get file size
            file_size = temp_file_path.stat().st_size
            trimmed_recording.file_size_bytes = file_size

            # Create database entry
            # If this fails, exception propagates and temp file is cleaned up
            self.repository.create(patient_id, trimmed_recording)
            self.logger.debug("Created database entry for trimmed recording")

        try:
            # Write file atomically with database creation
            writer.write_json_atomic(
                target_path=output_path,
                data=output_data,
                pre_commit_hook=pre_commit_hook
            )

            self.logger.info(
                f"Created trimmed recording {trimmed_recording.id} "
                f"(duration: {new_duration:.1f}s, filters: {filters})"
            )

            return trimmed_recording

        except Exception as e:
            # If anything failed, temp file is already cleaned up
            # But ensure database entry is rolled back if partially created
            try:
                self.repository.delete(patient_id, trimmed_recording.id)
            except:
                pass  # Delete might fail if entry wasn't created

            error_msg = (
                f"Failed to create trimmed recording: {e}\n"
                f"No files or database entries were created."
            )
            self.logger.error(error_msg)
            raise Exception(error_msg) from e

    def apply_filters(
        self,
        data: np.ndarray,
        filters: List[str],
        sampling_rate: float
    ) -> np.ndarray:
        """
        Apply signal processing filters to waveform data.

        Args:
            data: Waveform data of shape (n_samples, n_channels)
            filters: List of filter names to apply
            sampling_rate: Sample rate in Hz

        Returns:
            np.ndarray: Filtered data with same shape as input

        Raises:
            ImportError: If scipy is required but not available
            ValueError: If filter parameters are invalid

        Supported filters:
            - 'dc_offset_removal': Subtract mean from each channel
            - 'signal_integrity_cleaner': Repair NaNs/frozen segments before other filters
            - 'cardiac_removal': Time-domain ECG artifact removal (Sanger 2025 method)
            - 'highpass_0.5Hz': Butterworth high-pass filter at 0.5 Hz
            - 'lowpass_100Hz': Butterworth low-pass filter at 100 Hz
            - 'notch_60Hz': IIR notch filter at 60 Hz (power line fundamental)
            - 'notch_120Hz': IIR notch filter at 120 Hz (power line 2nd harmonic)

        Note:
            - Filter cutoff frequencies must be less than Nyquist frequency (sampling_rate / 2)
            - Cardiac removal requires at least 3 R-waves and 1000+ samples per channel
            - Filters are applied in the order specified
        """
        filtered_data = data.copy()

        for filter_name in filters:
            if filter_name == 'dc_offset_removal':
                # Subtract mean from each channel
                filtered_data = filtered_data - np.mean(filtered_data, axis=0, keepdims=True)
                self.logger.debug("Applied DC offset removal")

            elif filter_name == 'signal_integrity_cleaner':
                cleaned_data, stats = self._integrity_cleaner.clean(
                    filtered_data,
                    sampling_rate=sampling_rate
                )
                filtered_data = cleaned_data
                self.logger.info(
                    "Applied signal integrity cleaner "
                    f"(interpolated_segments={stats.get('total_interpolated_segments', 0)}, "
                    f"dropped_segments={stats.get('total_dropped_segments', 0)}, "
                    f"dropped_samples={stats.get('total_dropped_samples', 0)})"
                )

            elif filter_name.startswith('highpass_'):
                # High-pass filter (requires scipy)
                from scipy.signal import butter, filtfilt
                cutoff_hz = float(filter_name.split('_')[1].replace('Hz', ''))
                nyquist = sampling_rate / 2

                # Validate cutoff frequency
                if cutoff_hz <= 0 or cutoff_hz >= nyquist:
                    raise ValueError(
                        f"High-pass filter cutoff ({cutoff_hz} Hz) must be between 0 and "
                        f"Nyquist frequency ({nyquist:.1f} Hz). "
                        f"For {sampling_rate} Hz sampling rate, use cutoff < {nyquist:.1f} Hz."
                    )

                b, a = butter(4, cutoff_hz / nyquist, btype='high')
                # Apply per channel
                for ch in range(filtered_data.shape[1]):
                    filtered_data[:, ch] = filtfilt(b, a, filtered_data[:, ch])
                self.logger.debug(f"Applied high-pass filter at {cutoff_hz} Hz")

            elif filter_name.startswith('lowpass_'):
                # Low-pass filter (requires scipy)
                from scipy.signal import butter, filtfilt
                cutoff_hz = float(filter_name.split('_')[1].replace('Hz', ''))
                nyquist = sampling_rate / 2

                # Validate cutoff frequency
                if cutoff_hz <= 0 or cutoff_hz >= nyquist:
                    raise ValueError(
                        f"Low-pass filter cutoff ({cutoff_hz} Hz) must be between 0 and "
                        f"Nyquist frequency ({nyquist:.1f} Hz). "
                        f"For {sampling_rate} Hz sampling rate, use cutoff < {nyquist:.1f} Hz."
                    )

                b, a = butter(4, cutoff_hz / nyquist, btype='low')
                # Apply per channel
                for ch in range(filtered_data.shape[1]):
                    filtered_data[:, ch] = filtfilt(b, a, filtered_data[:, ch])
                self.logger.debug(f"Applied low-pass filter at {cutoff_hz} Hz")

            elif filter_name.startswith('notch_'):
                # Notch filter (requires scipy)
                from scipy.signal import iirnotch, filtfilt
                notch_hz = float(filter_name.split('_')[1].replace('Hz', ''))
                nyquist = sampling_rate / 2

                # Validate notch frequency
                if notch_hz <= 0 or notch_hz >= nyquist:
                    raise ValueError(
                        f"Notch filter frequency ({notch_hz} Hz) must be between 0 and "
                        f"Nyquist frequency ({nyquist:.1f} Hz). "
                        f"For {sampling_rate} Hz sampling rate, use frequency < {nyquist:.1f} Hz."
                    )

                quality_factor = 30
                b, a = iirnotch(notch_hz, quality_factor, sampling_rate)
                # Apply per channel
                for ch in range(filtered_data.shape[1]):
                    filtered_data[:, ch] = filtfilt(b, a, filtered_data[:, ch])
                self.logger.debug(f"Applied notch filter at {notch_hz} Hz")

            elif filter_name == 'cardiac_removal':
                # Cardiac artifact removal operates on 1D signals (per channel)
                # Need to process each channel separately
                n_samples, n_channels = filtered_data.shape
                self.logger.info(f"Applying cardiac artifact removal to {n_channels} channels")

                for ch_idx in range(n_channels):
                    channel_data = filtered_data[:, ch_idx]

                    try:
                        # Apply cardiac removal to this channel
                        cleaned_channel, stats = self._cardiac_preprocessor.remove_cardiac_artifact(
                            channel_data,
                            fs=sampling_rate
                        )

                        # Check if removal was successful or if there was an error
                        if 'error' in stats:
                            # Insufficient R-waves or other processing issue
                            self.logger.warning(
                                f"Channel {ch_idx}: Cardiac removal skipped - {stats['error']}"
                            )
                            # Leave channel unchanged (cleaned_channel is original signal)
                        else:
                            # Successful removal - update channel data
                            filtered_data[:, ch_idx] = cleaned_channel

                            # Log results
                            self.logger.debug(
                                f"Channel {ch_idx}: {stats['r_waves_detected']} R-waves, "
                                f"{stats['heart_rate_bpm']:.1f} BPM, "
                                f"{stats['power_reduction_theta']:.1f}% theta reduction"
                            )

                    except ValueError as e:
                        # Handle validation errors (signal too short, no valid QRS segments)
                        if "too short" in str(e) or "No valid QRS" in str(e):
                            self.logger.warning(
                                f"Channel {ch_idx}: Cardiac removal skipped - {str(e)}"
                            )
                            # Leave channel unchanged
                        else:
                            # Re-raise unexpected ValueError
                            raise

                    except Exception as e:
                        # Unexpected error - log and skip this channel
                        self.logger.error(
                            f"Channel {ch_idx}: Cardiac removal failed - {str(e)}",
                            exc_info=True
                        )
                        # Leave channel unchanged

                self.logger.info("Cardiac artifact removal complete")

            else:
                self.logger.warning(f"Unknown filter: {filter_name}")

        return filtered_data

    def get_recording_statistics(
        self,
        patient_id: str,
        recording_id: str
    ) -> Dict[str, Any]:
        """
        Calculate basic statistics for a recording.

        Args:
            patient_id: Patient identifier
            recording_id: Recording identifier

        Returns:
            Dict with statistics:
                - mean, std, min, max per channel
                - total power per channel
                - duration, sampling rate, channel count
        """
        waveform_data, recording = self.load_recording(patient_id, recording_id)

        stats = {
            'duration_seconds': recording.duration_seconds,
            'sampling_rate': recording.sampling_rate,
            'channel_count': recording.channel_count,
            'channels': {}
        }

        for i, label in enumerate(recording.channel_labels):
            channel_data = waveform_data[:, i]
            stats['channels'][label] = {
                'mean': float(np.mean(channel_data)),
                'std': float(np.std(channel_data)),
                'min': float(np.min(channel_data)),
                'max': float(np.max(channel_data)),
                'total_power': float(np.sum(channel_data ** 2))
            }

        return stats

    def export_recording(
        self,
        patient_id: str,
        recording_id: str,
        output_path: Path,
        format: str = 'json'
    ):
        """
        Export recording in specified format.

        Args:
            patient_id: Patient identifier
            recording_id: Recording identifier
            output_path: Path for output file
            format: Export format ('json', 'csv', 'npy')

        Raises:
            ValueError: If format is not supported
        """
        waveform_data, recording = self.load_recording(patient_id, recording_id)

        if format == 'json':
            self._save_recording_to_file(
                output_path,
                waveform_data,
                recording.channel_labels,
                recording.sampling_rate,
                recording.recording_date,
                0,
                recording.duration_seconds
            )
        elif format == 'csv':
            # Save as CSV with headers
            import csv
            with open(output_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(['time_sec'] + recording.channel_labels)
                for i in range(waveform_data.shape[0]):
                    time_sec = i / recording.sampling_rate
                    row = [time_sec] + waveform_data[i, :].tolist()
                    writer.writerow(row)
        elif format == 'npy':
            # Save as numpy array
            np.save(output_path, waveform_data)
        else:
            raise ValueError(f"Unsupported export format: {format}")

        self.logger.info(f"Exported recording to {output_path} ({format})")

    def delete_recording(
        self,
        patient_id: str,
        recording_id: str,
        delete_file: bool = True
    ) -> None:
        """
        Delete a recording (database record and file if no other references).

        Smart file deletion: Only deletes the file if no other recordings
        reference it. This prevents orphaning recordings when multiple records
        point to the same file (e.g., when trimming from trimmed files).

        Args:
            patient_id: Patient identifier
            recording_id: Recording identifier
            delete_file: If True, delete file if it's the last reference (default: True)

        Raises:
            ValueError: If recording not found
        """
        self.logger.info(f"Deleting recording {recording_id} for patient {patient_id}")

        # Get recording metadata first (to get file path)
        recording = self.repository.get_by_id(patient_id, recording_id)
        if not recording:
            raise ValueError(f"Recording {recording_id} not found")

        # Check if file should be deleted
        should_delete_file = False
        if delete_file:
            try:
                file_path = self._resolve_file_path(recording, patient_id)

                # Check if any other recordings reference this file
                other_refs = self._count_file_references(patient_id, file_path, exclude_id=recording_id)

                if other_refs > 0:
                    self.logger.info(
                        f"File {file_path.name} is referenced by {other_refs} other recording(s), "
                        f"keeping file and only deleting database record"
                    )
                    should_delete_file = False
                else:
                    should_delete_file = True

            except Exception as e:
                self.logger.error(f"Failed to check file references: {e}")
                should_delete_file = False  # Err on the side of caution

        # Delete file from disk if it's the last reference
        if should_delete_file:
            try:
                file_path = self._resolve_file_path(recording, patient_id)
                if file_path.exists():
                    file_path.unlink()
                    self.logger.info(f"Deleted file: {file_path} (last reference)")
                else:
                    self.logger.warning(f"File not found (already deleted?): {file_path}")
            except Exception as e:
                self.logger.error(f"Failed to delete file: {e}")
                # Continue with database deletion even if file deletion fails

        # Delete database record (cascade deletes annotations)
        self.repository.delete(patient_id, recording_id)
        self.logger.info(f"Deleted recording from database: {recording_id}")

    def _count_file_references(self, patient_id: str, file_path: Path, exclude_id: str = None) -> int:
        """
        Count how many recordings reference a given file path.

        Args:
            patient_id: Patient identifier
            file_path: File path to check
            exclude_id: Recording ID to exclude from count (typically the one being deleted)

        Returns:
            int: Number of other recordings referencing this file
        """
        try:
            all_recordings = self.repository.get_by_patient(patient_id)

            count = 0
            for recording in all_recordings:
                # Skip the recording we're excluding
                if exclude_id and recording.id == exclude_id:
                    continue

                # Check if this recording references the same file
                try:
                    rec_file_path = self._resolve_file_path(recording, patient_id)
                    if rec_file_path == file_path:
                        count += 1
                except Exception:
                    # Skip recordings with unresolvable paths
                    continue

            return count

        except Exception as e:
            self.logger.error(f"Error counting file references: {e}")
            return 0

    def cleanup_orphaned_recordings(self, patient_id: str) -> int:
        """
        Clean up orphaned database records (recordings where file doesn't exist).

        This happens when:
        - A trimmed file is deleted but the database record remains
        - A child trimmed file's parent is deleted
        - Files are manually deleted from disk

        Args:
            patient_id: Patient identifier

        Returns:
            int: Number of orphaned records cleaned up
        """
        try:
            # Get all recordings from database
            recordings = self.repository.get_by_patient(patient_id)

            orphaned_ids = []
            for recording in recordings:
                try:
                    # Try to resolve file path
                    file_path = self._resolve_file_path(recording, patient_id)

                    # Check if file exists
                    if not file_path.exists():
                        self.logger.warning(
                            f"Orphaned record detected: {recording.id} "
                            f"(file not found: {file_path})"
                        )
                        orphaned_ids.append(recording.id)

                except Exception as e:
                    # If we can't even resolve the path, it's orphaned
                    self.logger.warning(
                        f"Orphaned record detected: {recording.id} "
                        f"(path resolution failed: {e})"
                    )
                    orphaned_ids.append(recording.id)

            # Delete orphaned records from database
            for recording_id in orphaned_ids:
                try:
                    self.repository.delete(patient_id, recording_id)
                    self.logger.info(f"Cleaned up orphaned record: {recording_id}")
                except Exception as e:
                    self.logger.error(f"Failed to delete orphaned record {recording_id}: {e}")

            if orphaned_ids:
                self.logger.info(
                    f"Cleaned up {len(orphaned_ids)} orphaned recording(s) for patient {patient_id}"
                )

            return len(orphaned_ids)

        except Exception as e:
            self.logger.error(f"Error during orphan cleanup for patient {patient_id}: {e}")
            return 0

    def _save_recording_to_file(
        self,
        output_path: Path,
        waveform_data: np.ndarray,
        channel_labels: List[str],
        sampling_rate: float,
        recording_date: datetime,
        start_sec: float,
        end_sec: float
    ):
        """
        Save waveform data to JSON file.

        Args:
            output_path: Output file path
            waveform_data: Waveform array (n_samples, n_channels)
            channel_labels: List of channel labels
            sampling_rate: Sample rate in Hz
            recording_date: Recording date/time
            start_sec: Start time in seconds
            end_sec: End time in seconds
        """
        # Build JSON structure
        n_samples = waveform_data.shape[0]
        duration = n_samples / sampling_rate

        # Create timestamps array
        timestamps = [i / sampling_rate for i in range(n_samples)]

        # Create channels dict
        channels = {}
        for i, label in enumerate(channel_labels):
            channels[label] = waveform_data[:, i].tolist()

        data = {
            'metadata': {
                'recording_date': recording_date.isoformat(),
                'duration_seconds': duration,
                'sampling_rate': sampling_rate,
                'channel_count': len(channel_labels),
                'channel_labels': channel_labels,
                'trim_start_sec': start_sec,
                'trim_end_sec': end_sec
            },
            'data': {
                'timestamps': timestamps,
                'channels': channels
            }
        }

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)

        self.logger.debug(f"Saved recording to {output_path}")
