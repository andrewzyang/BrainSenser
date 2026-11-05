"""
UploadService for processing and uploading BrainSense JSON files.

This service orchestrates the complete file upload workflow:
1. File validation and duplicate detection
2. JSON parsing and record extraction
3. Data deduplication via hash calculation
4. Atomic database insertion (transaction)
5. File archiving to raw_uploads/ directory

Author: iEEG BrainSense Development Team
Last Updated: 2025-10-01
"""

import logging
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Callable

from src.core.path_resolver import PathResolver
from src.core.file_parser import FileParser
from src.core.deduplication_engine import DeduplicationEngine
from src.core.preprocessing import OvervoltagePreprocessor
from src.core.models.upload_result import UploadResult, DirectoryUploadResult
from src.core.models.uploaded_file import UploadedFile
from src.core.models.streaming_recording import StreamingRecording
from src.infrastructure.database.adapters.sqlite_adapter import SQLiteAdapter
from src.infrastructure.repositories.timeline_repository import TimelineRepository
from src.infrastructure.repositories.snapshot_repository import SnapshotRepository
from src.infrastructure.repositories.streaming_repository import StreamingRepository
from src.infrastructure.repositories.streaming_recording_repository import StreamingRecordingRepository
from src.infrastructure.repositories.processing_metadata_repository import ProcessingMetadataRepository
from src.infrastructure.repositories.patient_repository import PatientRepository

logger = logging.getLogger(__name__)


class UploadService:
    """
    Service for uploading and processing BrainSense JSON files.

    Orchestrates the complete upload workflow including:
    - File validation and duplicate detection
    - JSON parsing (FileParser)
    - Data hash calculation (DeduplicationEngine)
    - Atomic database insertion with transaction
    - File archiving to patient's raw_uploads/ directory

    All database operations are atomic (all-or-nothing) using transactions.
    If any step fails, the entire upload is rolled back.

    Example:
        >>> from src.core.path_resolver import PathResolver
        >>> from src.infrastructure.database.adapters import SQLiteAdapter
        >>>
        >>> adapter = SQLiteAdapter()
        >>> resolver = PathResolver()
        >>> service = UploadService(adapter, resolver)
        >>>
        >>> result = service.upload_file("PATIENT001", Path("data.json"))
        >>> if result.success:
        ...     print(f"Inserted {result.total_inserted} records")
    """

    def __init__(
        self,
        adapter: SQLiteAdapter,
        path_resolver: PathResolver,
        timeline_repo: Optional[TimelineRepository] = None,
        snapshot_repo: Optional[SnapshotRepository] = None,
        streaming_repo: Optional[StreamingRepository] = None,
        streaming_recording_repo: Optional[StreamingRecordingRepository] = None,
        processing_repo: Optional[ProcessingMetadataRepository] = None,
        patient_repo: Optional[PatientRepository] = None,
        enable_overvoltage_preprocessing: bool = True,
    ):
        """
        Initialize UploadService.

        Args:
            adapter: SQLiteAdapter for database operations
            path_resolver: PathResolver for file paths
            timeline_repo: Optional TimelineRepository (created if None)
            snapshot_repo: Optional SnapshotRepository (created if None)
            streaming_repo: Optional StreamingRepository (created if None)
            streaming_recording_repo: Optional StreamingRecordingRepository (created if None)
            processing_repo: Optional ProcessingMetadataRepository (created if None)
            patient_repo: Optional PatientRepository (created if None)
            enable_overvoltage_preprocessing: Enable OvER preprocessing (default: True)
        """
        self.adapter = adapter
        self.path_resolver = path_resolver

        # Initialize repositories (use provided or create new)
        self.timeline_repo = timeline_repo or TimelineRepository(adapter, path_resolver)
        self.snapshot_repo = snapshot_repo or SnapshotRepository(adapter, path_resolver)
        self.streaming_repo = streaming_repo or StreamingRepository(adapter, path_resolver)
        self.streaming_recording_repo = streaming_recording_repo or StreamingRecordingRepository(adapter, path_resolver)
        self.processing_repo = processing_repo or ProcessingMetadataRepository(adapter, path_resolver)
        self.patient_repo = patient_repo or PatientRepository(adapter, path_resolver)

        # Initialize preprocessor
        self.overvoltage_preprocessor = OvervoltagePreprocessor(enabled=enable_overvoltage_preprocessing)

        logger.info(f"UploadService initialized (OvER preprocessing: {enable_overvoltage_preprocessing})")

    def upload_file(
        self,
        patient_id: str,
        file_path: Path,
        progress_callback: Optional[Callable[[str], None]] = None
    ) -> UploadResult:
        """
        Upload and process BrainSense JSON file.

        Complete workflow:
        1. Validate file exists and patient exists
        2. Calculate file hash and check for duplicates
        3. Parse JSON file (FileParser)
        4. Calculate data hashes (DeduplicationEngine)
        5. Archive file to patient's raw_uploads/ directory (BEFORE DB transaction)
        6. Begin database transaction
        7. Insert timeline records (TimelineRepository.insert_batch)
        8. Insert snapshot records (SnapshotRepository.insert_batch)
        9. Record processing metadata (ProcessingMetadataRepository.create)
        10. Commit transaction
        11. Return UploadResult

        All operations are atomic. If the database transaction fails after file
        archiving, the archived file is automatically cleaned up. This ensures
        consistency: either both the file and database records exist, or neither do.

        Args:
            patient_id: Patient identifier
            file_path: Path to BrainSense JSON file
            progress_callback: Optional callback for progress updates

        Returns:
            UploadResult: Upload status and statistics

        Example:
            >>> result = service.upload_file("PATIENT001", Path("data.json"))
            >>> if result.success:
            ...     print(f"Uploaded {result.total_inserted} records")
            >>> else:
            ...     print(f"Error: {result.message}")
        """
        start_time = time.time()

        def report_progress(message: str):
            """Helper to report progress via callback."""
            logger.info(f"[{patient_id}] {message}")
            if progress_callback:
                progress_callback(message)

        try:
            # Step 1: Validate file exists
            report_progress("Validating file...")
            if not file_path.exists():
                return UploadResult(
                    success=False,
                    message=f"File not found: {file_path}",
                    processing_time=time.time() - start_time
                )

            if not file_path.is_file():
                return UploadResult(
                    success=False,
                    message=f"Not a file: {file_path}",
                    processing_time=time.time() - start_time
                )

            # Step 2: Validate patient exists
            report_progress("Validating patient...")
            patient = self.patient_repo.get_by_id(patient_id)
            if not patient:
                return UploadResult(
                    success=False,
                    message=f"Patient not found: {patient_id}",
                    processing_time=time.time() - start_time
                )

            # Step 3: Calculate file hash and check for duplicates
            report_progress("Checking for duplicate file...")
            file_hash = DeduplicationEngine.calculate_file_hash(file_path)

            existing_upload = self.processing_repo.get_by_file_hash(patient_id, file_hash)
            if existing_upload:
                return UploadResult(
                    success=False,
                    message=f"File already uploaded: {existing_upload.file_name} on {existing_upload.processed_at}",
                    file_hash=file_hash,
                    is_duplicate=True,  # benign skip, not a failure
                    processing_time=time.time() - start_time
                )

            # Step 4: Parse JSON file
            report_progress("Parsing JSON file...")
            parsed_data = FileParser.parse_json(file_path, patient_id=patient_id)

            if parsed_data.parse_errors > 0:
                logger.warning(
                    f"Parsed {file_path.name} with {parsed_data.parse_errors} errors"
                )

            # Step 4.5: Apply OvER preprocessing to timeline records
            preprocessing_stats = None
            if parsed_data.timeline_records:
                report_progress("Applying overvoltage preprocessing...")
                parsed_data.timeline_records, preprocessing_stats = (
                    self.overvoltage_preprocessor.preprocess_timeline_records(
                        parsed_data.timeline_records
                    )
                )
                if preprocessing_stats.get('total_corrected', 0) > 0:
                    logger.info(f"OvER preprocessing corrected {preprocessing_stats['total_corrected']} overvoltage events")

            # Step 5: Archive file to raw_uploads/ directory BEFORE database transaction
            # This ensures atomicity: if DB transaction fails, we clean up the archived file
            report_progress("Archiving file...")
            raw_uploads_dir = self.path_resolver.get_patient_uploads_directory(patient_id)
            raw_uploads_dir.mkdir(parents=True, exist_ok=True)

            # Generate unique filename if file already exists
            dest_path = raw_uploads_dir / file_path.name
            counter = 1
            while dest_path.exists():
                dest_path = raw_uploads_dir / f"{file_path.stem}_{counter}{file_path.suffix}"
                counter += 1

            try:
                shutil.copy2(file_path, dest_path)
                logger.info(f"File archived to: {dest_path}")
            except Exception as e:
                logger.error(f"Failed to archive file: {e}")
                return UploadResult(
                    success=False,
                    message=f"Failed to archive file: {str(e)}",
                    processing_time=time.time() - start_time
                )

            # Step 6: Begin transaction and insert data
            report_progress(f"Inserting {len(parsed_data.timeline_records)} timeline records...")

            # Initialize streaming counters
            indefinite_streaming_inserted = 0
            indefinite_streaming_duplicates = 0
            definite_streaming_inserted = 0
            definite_streaming_duplicates = 0

            try:
                # Step 7: Insert ALL data into brainsense_data.db (single database, single transaction)
                with self.adapter.transaction(self.path_resolver.get_patient_db_path(patient_id)) as conn:
                    # Insert timeline records
                    timeline_inserted, timeline_duplicates = self.timeline_repo.insert_batch(
                        patient_id,
                        parsed_data.timeline_records,
                        conn=conn
                    )

                    # Insert snapshot records
                    report_progress(f"Inserting {len(parsed_data.snapshot_records)} snapshot records...")
                    snapshot_inserted, snapshot_duplicates = self.snapshot_repo.insert_batch(
                        patient_id,
                        parsed_data.snapshot_records,
                        conn=conn
                    )

                    # Step 8: Insert streaming records into SAME database (using same connection/transaction!)
                    if parsed_data.streaming_records:
                        report_progress(f"Inserting {len(parsed_data.streaming_records)} streaming records...")
                        # Now streaming uses the SAME database and transaction
                        streaming_inserted, streaming_duplicates = self.streaming_repo.insert_batch(
                            patient_id,
                            parsed_data.streaming_records,
                            conn=conn  # Pass connection for same transaction!
                        )

                        # Separate indefinite vs definite for statistics
                        indefinite_count = sum(1 for r in parsed_data.streaming_records if r.streaming_type == "indefinite")
                        definite_count = len(parsed_data.streaming_records) - indefinite_count

                        indefinite_streaming_inserted = streaming_inserted if indefinite_count > 0 else 0
                        indefinite_streaming_duplicates = streaming_duplicates if indefinite_count > 0 else 0
                        definite_streaming_inserted = streaming_inserted if definite_count > 0 else 0
                        definite_streaming_duplicates = streaming_duplicates if definite_count > 0 else 0

                        # Step 8.5: Create StreamingRecording entry for data management
                        # This consolidates all streaming records into a single recording file entry
                        if streaming_inserted > 0:
                            report_progress("Creating streaming recording entry...")
                            try:
                                self._create_streaming_recording_entry(
                                    patient_id=patient_id,
                                    file_path=dest_path,
                                    streaming_records=parsed_data.streaming_records,
                                    conn=conn
                                )
                            except Exception as streaming_error:
                                # Don't fail the entire upload if streaming recording entry creation fails
                                # The streaming records are already inserted into the database
                                logger.warning(
                                    f"Failed to create streaming recording entry: {streaming_error}. "
                                    f"Streaming records were saved, but file may not appear in streaming data views. "
                                    f"File: {file_path.name}"
                                )

                    # Step 9: Record processing metadata
                    report_progress("Recording upload metadata...")
                    total_duplicates = (timeline_duplicates + snapshot_duplicates +
                                      indefinite_streaming_duplicates + definite_streaming_duplicates)

                    file_info = {
                        'file_name': file_path.name,
                        'file_path': str(dest_path),  # Store archived path instead of original
                        'file_hash': file_hash,
                        'file_size_bytes': file_path.stat().st_size,
                    }

                    # Note: Snapshots and streaming are stored per-hemisphere in database (correct),
                    # but we report counts as "events" where each event = hemisphere pair.
                    # Timeline already stores both hemispheres in a single record.
                    # Use ceiling division to handle odd numbers (some formats may have unpaired records)
                    import math
                    snapshot_count_orig = len(parsed_data.snapshot_records)
                    indefinite_count_orig = sum(1 for r in parsed_data.streaming_records if r.streaming_type == "indefinite")
                    definite_count_orig = sum(1 for r in parsed_data.streaming_records if r.streaming_type == "definite")

                    counts = {
                        'timeline_count': timeline_inserted,
                        'timeline_original_count': len(parsed_data.timeline_records),
                        # Snapshots: divide by 2 to show event count (each event has Left+Right hemispheres)
                        'snapshot_count': math.ceil(snapshot_inserted / 2) if snapshot_inserted > 0 else 0,
                        'snapshot_original_count': math.ceil(snapshot_count_orig / 2) if snapshot_count_orig > 0 else 0,
                        # Streaming: divide by 2 to show event count (each event has Left+Right hemispheres)
                        'indefinite_streaming_count': math.ceil(indefinite_streaming_inserted / 2) if indefinite_streaming_inserted > 0 else 0,
                        'indefinite_streaming_original_count': math.ceil(indefinite_count_orig / 2) if indefinite_count_orig > 0 else 0,
                        'definite_streaming_count': math.ceil(definite_streaming_inserted / 2) if definite_streaming_inserted > 0 else 0,
                        'definite_streaming_original_count': math.ceil(definite_count_orig / 2) if definite_count_orig > 0 else 0,
                        'duplicates_skipped': total_duplicates,
                        'outliers_detected': preprocessing_stats.get('total_corrected', 0) if preprocessing_stats else 0,
                    }

                    processing_info = {
                        'processing_time_seconds': 0.0,  # Will be calculated at end
                        'extractor_version': 'v1.0',
                        'processing_settings': preprocessing_stats if preprocessing_stats else None,
                        'errors_encountered': parsed_data.parse_errors,
                        'error_details': None,
                    }

                    self.processing_repo.create(
                        patient_id=patient_id,
                        file_info=file_info,
                        counts=counts,
                        processing_info=processing_info,
                        conn=conn
                    )

                    # Transaction commits automatically on exit from context manager

                # Step 11: Extract and store patient metadata (after successful upload)
                try:
                    report_progress("Extracting patient metadata...")
                    self._extract_and_store_metadata(patient_id, file_path)
                except Exception as metadata_error:
                    # Don't fail the entire upload if metadata extraction fails
                    logger.warning(f"Failed to extract metadata: {metadata_error}")

            except Exception as transaction_error:
                # If database transaction failed, clean up the archived file
                logger.error(f"Database transaction failed: {transaction_error}")
                try:
                    if dest_path.exists():
                        dest_path.unlink()
                        logger.info(f"Cleaned up archived file after transaction failure: {dest_path}")
                except Exception as cleanup_error:
                    logger.error(f"Failed to clean up archived file: {cleanup_error}")

                # Re-raise the original error
                raise transaction_error

            # Step 10: Return success result
            processing_time = time.time() - start_time
            report_progress(f"Upload complete in {processing_time:.2f}s")

            # Return counts as "events" (hemisphere pairs counted as 1)
            # Note: Database stores per-hemisphere (correct for queries), but UI shows event counts
            # Use ceiling division to handle odd numbers (some formats may have unpaired records)
            import math
            snapshot_inserted_events = math.ceil(snapshot_inserted / 2) if snapshot_inserted > 0 else 0
            snapshot_duplicates_events = math.ceil(snapshot_duplicates / 2) if snapshot_duplicates > 0 else 0
            indefinite_inserted_events = math.ceil(indefinite_streaming_inserted / 2) if indefinite_streaming_inserted > 0 else 0
            indefinite_duplicates_events = math.ceil(indefinite_streaming_duplicates / 2) if indefinite_streaming_duplicates > 0 else 0
            definite_inserted_events = math.ceil(definite_streaming_inserted / 2) if definite_streaming_inserted > 0 else 0
            definite_duplicates_events = math.ceil(definite_streaming_duplicates / 2) if definite_streaming_duplicates > 0 else 0

            # Recalculate total duplicates with event-based counts
            total_duplicates_events = (timeline_duplicates + snapshot_duplicates_events +
                                      indefinite_duplicates_events + definite_duplicates_events)

            return UploadResult(
                success=True,
                message=f"Successfully uploaded {file_path.name}",
                timeline_inserted=timeline_inserted,
                timeline_duplicates=timeline_duplicates,
                snapshot_inserted=snapshot_inserted_events,
                snapshot_duplicates=snapshot_duplicates_events,
                indefinite_streaming_inserted=indefinite_inserted_events,
                indefinite_streaming_duplicates=indefinite_duplicates_events,
                definite_streaming_inserted=definite_inserted_events,
                definite_streaming_duplicates=definite_duplicates_events,
                total_duplicates=total_duplicates_events,
                file_hash=file_hash,
                processing_time=processing_time
            )

        except Exception as e:
            logger.error(f"Upload failed: {e}", exc_info=True)
            return UploadResult(
                success=False,
                message=f"Upload failed: {str(e)}",
                processing_time=time.time() - start_time
            )

    def upload_directory(
        self,
        patient_id: str,
        directory_path: Path,
        progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> DirectoryUploadResult:
        """
        Upload all JSON files from a directory for a patient.

        Discovers all *.json files recursively in the directory, uploads each file
        using upload_file(), and aggregates the results into a DirectoryUploadResult.

        Args:
            patient_id: Target patient ID
            directory_path: Directory to scan for JSON files (recursive search)
            progress_callback: Optional callback(current, total) for progress updates

        Returns:
            DirectoryUploadResult with comprehensive statistics and error details

        Raises:
            FileNotFoundError: If directory doesn't exist
            NotADirectoryError: If path is not a directory
            ValueError: If patient doesn't exist

        Example:
            >>> result = service.upload_directory("P001", Path("/data/recordings"))
            >>> print(f"Uploaded {result.successful_uploads}/{result.total_files} files")
            >>> print(f"Success rate: {result.success_rate:.1f}%")
            >>> if result.has_errors:
            ...     for path, error in result.errors:
            ...         print(f"Failed: {path.name} - {error}")
        """
        # Validate directory
        if not directory_path.exists():
            raise FileNotFoundError(f"Directory not found: {directory_path}")

        if not directory_path.is_dir():
            raise NotADirectoryError(f"Path is not a directory: {directory_path}")

        # Validate patient exists
        patient = self.patient_repo.get_by_id(patient_id)
        if not patient:
            raise ValueError(f"Patient not found: {patient_id}")

        logger.info(f"Starting directory upload for patient {patient_id} from {directory_path}")

        # Discover JSON files recursively
        json_files = sorted(directory_path.rglob("*.json"))
        total_files = len(json_files)

        logger.info(f"Found {total_files} JSON files in {directory_path}")

        if total_files == 0:
            # Return empty result for no files
            return DirectoryUploadResult(
                total_files=0,
                successful_uploads=0,
                failed_uploads=0,
                skipped_duplicates=0,
                file_results={},
                errors=[]
            )

        # Initialize aggregated statistics
        file_results = {}
        errors = []
        stats = {
            'successful_uploads': 0,
            'failed_uploads': 0,
            'skipped_duplicates': 0,
            'timeline_inserted': 0,
            'timeline_duplicates': 0,
            'snapshot_inserted': 0,
            'snapshot_duplicates': 0,
            'indefinite_streaming_inserted': 0,
            'indefinite_streaming_duplicates': 0,
            'definite_streaming_inserted': 0,
            'definite_streaming_duplicates': 0,
        }

        # Process each file
        for index, file_path in enumerate(json_files, start=1):
            try:
                # Report progress if callback provided
                if progress_callback:
                    progress_callback(index, total_files)

                logger.info(f"Uploading file {index}/{total_files}: {file_path.name}")

                # Upload individual file using existing method
                result = self.upload_file(patient_id, file_path)
                file_results[file_path] = result

                # Aggregate statistics
                if result.success:
                    stats['successful_uploads'] += 1
                    stats['timeline_inserted'] += result.timeline_inserted
                    stats['timeline_duplicates'] += result.timeline_duplicates
                    stats['snapshot_inserted'] += result.snapshot_inserted
                    stats['snapshot_duplicates'] += result.snapshot_duplicates
                    stats['indefinite_streaming_inserted'] += result.indefinite_streaming_inserted
                    stats['indefinite_streaming_duplicates'] += result.indefinite_streaming_duplicates
                    stats['definite_streaming_inserted'] += result.definite_streaming_inserted
                    stats['definite_streaming_duplicates'] += result.definite_streaming_duplicates

                    # Check if this file was a duplicate (all records were duplicates)
                    if (result.timeline_duplicates > 0 and result.timeline_inserted == 0 and
                        result.snapshot_duplicates > 0 and result.snapshot_inserted == 0):
                        stats['skipped_duplicates'] += 1

                elif result.is_duplicate:
                    # This exact file was already uploaded - skipped, NOT a failure.
                    stats['skipped_duplicates'] += 1
                    logger.info(f"Skipped duplicate file {file_path.name}: {result.message}")

                else:
                    stats['failed_uploads'] += 1
                    errors.append((file_path, result.message))
                    logger.warning(f"Upload failed for {file_path.name}: {result.message}")

            except Exception as e:
                # Handle unexpected errors
                stats['failed_uploads'] += 1
                error_msg = str(e)
                errors.append((file_path, error_msg))
                logger.error(f"Unexpected error uploading {file_path.name}: {e}", exc_info=True)

                # Create failed result for this file
                file_results[file_path] = UploadResult(
                    success=False,
                    message=error_msg,
                    timeline_inserted=0,
                    timeline_duplicates=0,
                    snapshot_inserted=0,
                    snapshot_duplicates=0,
                    indefinite_streaming_inserted=0,
                    indefinite_streaming_duplicates=0,
                    definite_streaming_inserted=0,
                    definite_streaming_duplicates=0,
                    processing_time=0.0
                )

        # Log summary
        logger.info(
            f"Directory upload complete for {patient_id}: "
            f"{stats['successful_uploads']}/{total_files} successful, "
            f"{stats['failed_uploads']} failed, "
            f"{stats['timeline_inserted']} timeline records, "
            f"{stats['snapshot_inserted']} snapshot records"
        )

        # Return aggregated result
        return DirectoryUploadResult(
            total_files=total_files,
            successful_uploads=stats['successful_uploads'],
            failed_uploads=stats['failed_uploads'],
            skipped_duplicates=stats['skipped_duplicates'],
            file_results=file_results,
            total_timeline_inserted=stats['timeline_inserted'],
            total_timeline_duplicates=stats['timeline_duplicates'],
            total_snapshot_inserted=stats['snapshot_inserted'],
            total_snapshot_duplicates=stats['snapshot_duplicates'],
            total_indefinite_streaming_inserted=stats['indefinite_streaming_inserted'],
            total_indefinite_streaming_duplicates=stats['indefinite_streaming_duplicates'],
            total_definite_streaming_inserted=stats['definite_streaming_inserted'],
            total_definite_streaming_duplicates=stats['definite_streaming_duplicates'],
            errors=errors
        )

    def get_upload_history(self, patient_id: str, limit: Optional[int] = None) -> List[UploadedFile]:
        """
        Get upload history for patient.

        Returns list of all uploaded files for the patient, sorted by upload date
        (most recent first).

        Args:
            patient_id: Patient identifier
            limit: Optional limit on number of results

        Returns:
            List[UploadedFile]: List of uploaded files

        Example:
            >>> history = service.get_upload_history("PATIENT001")
            >>> for upload in history:
            ...     print(f"{upload.file_name}: {upload.timeline_count} records")
        """
        try:
            return self.processing_repo.get_by_patient(patient_id, limit=limit)
        except Exception as e:
            logger.error(f"Failed to get upload history for {patient_id}: {e}")
            return []

    def check_file_uploaded(self, patient_id: str, file_hash: str) -> bool:
        """
        Check if file has already been uploaded.

        Uses file hash to detect duplicate uploads. Returns True if a file
        with the same hash has been uploaded for this patient.

        Args:
            patient_id: Patient identifier
            file_hash: SHA256 hash of file

        Returns:
            bool: True if file already uploaded, False otherwise

        Example:
            >>> file_hash = DeduplicationEngine.calculate_file_hash(Path("data.json"))
            >>> if service.check_file_uploaded("PATIENT001", file_hash):
            ...     print("File already uploaded")
        """
        try:
            existing = self.processing_repo.get_by_file_hash(patient_id, file_hash)
            return existing is not None
        except Exception as e:
            logger.error(f"Failed to check file upload status: {e}")
            return False

    def _create_streaming_recording_entry(
        self,
        patient_id: str,
        file_path: Path,
        streaming_records: List,
        conn
    ):
        """
        Create a StreamingRecording entry for uploaded streaming data.

        This creates a consolidated recording entry in the streaming_recordings table
        to enable detection and loading of the uploaded streaming file in data views.

        Args:
            patient_id: Patient identifier
            file_path: Path to uploaded file
            streaming_records: List of StreamingRecord instances
            conn: Database connection for transaction
        """
        import uuid

        if not streaming_records:
            return

        # Extract metadata from streaming records
        # Get unique channels and hemispheres
        channels = sorted(set(r.channel for r in streaming_records if r.channel))
        hemispheres = sorted(set(r.hemisphere for r in streaming_records if r.hemisphere))

        # Calculate duration from maximum sample count across channels
        # NOTE: All channels are recorded simultaneously (not sequentially),
        # so we use max (not sum) to get the recording duration
        max_samples = max(r.sample_count for r in streaming_records)
        sample_rate = streaming_records[0].sample_rate if streaming_records else 250.0

        # Get recording date from first record
        recording_date = streaming_records[0].timestamp if streaming_records else datetime.now()

        # Calculate duration from single channel (all channels same length)
        duration_seconds = max_samples / sample_rate if sample_rate > 0 else 0

        # Build channel labels (e.g., ["Ch0_Left", "Ch0_Right"])
        channel_labels = []
        for channel in channels:
            for hemisphere in hemispheres:
                if any(r.channel == channel and r.hemisphere == hemisphere for r in streaming_records):
                    channel_labels.append(f"{channel}_{hemisphere}")

        # If no proper channel labels, use generic names
        if not channel_labels:
            channel_count = len(set((r.channel, r.hemisphere) for r in streaming_records))
            channel_labels = [f"Ch{i}" for i in range(channel_count)]

        # Create StreamingRecording instance
        recording = StreamingRecording(
            id=str(uuid.uuid4()),
            patient_id=patient_id,
            file_path=str(file_path),
            original_file_path=None,
            recording_date=recording_date,
            duration_seconds=duration_seconds,
            start_time=recording_date,
            end_time=None,
            is_trimmed=False,
            file_size_bytes=file_path.stat().st_size if file_path.exists() else 0,
            sampling_rate=sample_rate,
            channel_count=len(channel_labels),
            channel_labels=channel_labels,
            metadata={
                'source': 'upload',
                'streaming_type': streaming_records[0].streaming_type if streaming_records else 'indefinite',
                'total_segments': len(streaming_records),
            },
            processing_applied=[],
            created_at=datetime.now(),
            updated_at=datetime.now()
        )

        # Insert into streaming_recordings table
        query = f"""
            INSERT OR IGNORE INTO streaming_recordings
            (id, patient_id, file_path, original_file_path, recording_date,
             duration_seconds, start_time, end_time, is_trimmed, file_size_bytes,
             sampling_rate, channel_count, channel_labels, metadata,
             processing_applied, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """

        data = recording.to_dict()

        cursor = conn.cursor()
        cursor.execute(query, (
            data['id'],
            data['patient_id'],
            data['file_path'],
            data['original_file_path'],
            data['recording_date'],
            data['duration_seconds'],
            data['start_time'],
            data['end_time'],
            data['is_trimmed'],
            data['file_size_bytes'],
            data['sampling_rate'],
            data['channel_count'],
            data['channel_labels'],
            data['metadata'],
            data['processing_applied'],
            data['created_at'],
            data['updated_at']
        ))

        logger.info(
            f"Created streaming recording entry: {recording.id} "
            f"(duration: {duration_seconds:.1f}s, channels: {len(channel_labels)})"
        )

    def _extract_and_store_metadata(self, patient_id: str, file_path: Path):
        """
        Extract patient metadata from BrainSense JSON and store in patient record.

        This extracts metadata from the uploaded JSON file and merges it with
        existing patient metadata. Only updates if new data is available.

        Args:
            patient_id: Patient identifier
            file_path: Path to the uploaded JSON file
        """
        import json

        # Read JSON file
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                json_data = json.load(f)
        except Exception as e:
            logger.warning(f"Failed to read JSON for metadata extraction: {e}")
            return

        # Extract metadata from JSON
        metadata = self._extract_metadata_from_json(json_data)

        if not metadata:
            logger.debug(f"No metadata extracted from {file_path.name}")
            return

        # Get current patient
        patient = self.patient_repo.get_by_id(patient_id)
        if not patient:
            logger.warning(f"Patient not found for metadata update: {patient_id}")
            return

        # Merge with existing metadata (keep existing, add new)
        existing_metadata = patient.metadata or {}
        merged_metadata = {**existing_metadata, **metadata}

        # Only update if metadata changed
        if merged_metadata != existing_metadata:
            try:
                self.patient_repo.update(
                    patient_id=patient_id,
                    patient_name=patient.patient_name,
                    metadata=merged_metadata
                )
                logger.info(f"Updated patient metadata for {patient_id}")
            except Exception as e:
                logger.error(f"Failed to update patient metadata: {e}")
        else:
            logger.debug(f"No metadata changes for {patient_id}")

    def _extract_metadata_from_json(self, json_data: dict) -> dict:
        """
        Extract metadata fields from BrainSense JSON structure.

        Args:
            json_data: Parsed JSON data from BrainSense file

        Returns:
            dict: Extracted metadata fields
        """
        metadata = {}

        # Extract Patient Information (use "Final" state)
        try:
            patient_info = json_data.get("PatientInformation", {}).get("Final", {})
            if patient_info:
                if first_name := patient_info.get("PatientFirstName"):
                    metadata["first_name"] = first_name
                if last_name := patient_info.get("PatientLastName"):
                    metadata["last_name"] = last_name
                if dob := patient_info.get("PatientDateOfBirth"):
                    metadata["date_of_birth"] = dob
                if gender := patient_info.get("PatientGender"):
                    metadata["gender"] = self._clean_gender(gender)
                if device_patient_id := patient_info.get("PatientId"):
                    metadata["device_patient_id"] = device_patient_id
                if diagnosis := patient_info.get("Diagnosis"):
                    metadata["diagnosis"] = self._clean_diagnosis(diagnosis)
        except Exception as e:
            logger.debug(f"Failed to extract patient info: {e}")

        # Extract Device Information (use "Final" state)
        try:
            device_info = json_data.get("DeviceInformation", {}).get("Final", {})
            if device_info:
                if neurostimulator := device_info.get("Neurostimulator"):
                    metadata["neurostimulator"] = neurostimulator
                if model := device_info.get("NeurostimulatorModel"):
                    metadata["neurostimulator_model"] = model
                if serial := device_info.get("NeurostimulatorSerialNumber"):
                    metadata["serial_number"] = serial
                if implant_date := device_info.get("ImplantDate"):
                    metadata["implant_date"] = implant_date
                if location := device_info.get("NeurostimulatorLocation"):
                    metadata["device_location"] = self._clean_location(location)
        except Exception as e:
            logger.debug(f"Failed to extract device info: {e}")

        # Extract Battery Information
        try:
            battery_info = json_data.get("BatteryInformation", {})
            if battery_info:
                if battery_pct := battery_info.get("BatteryPercentage"):
                    metadata["battery_percentage"] = battery_pct
                if battery_life := battery_info.get("EstimatedBatteryLifeMonths"):
                    metadata["battery_life_months"] = battery_life
        except Exception as e:
            logger.debug(f"Failed to extract battery info: {e}")

        # Extract Session Information
        try:
            if session_date := json_data.get("SessionDate"):
                metadata["last_session_date"] = session_date
            if programmer_version := json_data.get("ProgrammerVersion"):
                metadata["programmer_version"] = programmer_version
        except Exception as e:
            logger.debug(f"Failed to extract session info: {e}")

        return metadata

    @staticmethod
    def _clean_gender(gender: str) -> str:
        """Clean gender field by removing enum prefix."""
        if not gender:
            return ""
        # Remove "PatientGenderDef." prefix
        if gender.startswith("PatientGenderDef."):
            gender = gender.replace("PatientGenderDef.", "")
        return gender.replace("_", " ").title()

    @staticmethod
    def _clean_diagnosis(diagnosis: str) -> str:
        """Clean diagnosis field by removing enum prefix."""
        if not diagnosis:
            return ""
        # Remove "DiagnosisTypeDef." prefix
        if diagnosis.startswith("DiagnosisTypeDef."):
            diagnosis = diagnosis.replace("DiagnosisTypeDef.", "")
        return diagnosis.replace("_", " ").title()

    @staticmethod
    def _clean_location(location: str) -> str:
        """Clean device location field by removing enum prefix."""
        if not location:
            return ""
        # Remove "InsLocation." prefix
        if location.startswith("InsLocation."):
            location = location.replace("InsLocation.", "")
        return location.replace("_", " ").title()
