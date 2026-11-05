"""
RecordingLoaderWorker - Background worker for loading streaming recordings.

This worker loads recording data asynchronously using QRunnable and QThreadPool
to prevent UI blocking during large file I/O operations.

Per the project threading guidelines:
- Uses QRunnable with QThreadPool for CPU-intensive tasks
- Never updates UI from background thread - uses signals instead
- Implements proper thread cleanup

Author: iEEG BrainSense Development Team
Last Updated: 2025-10-08
"""

import logging
from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from src.core.services.streaming_service import StreamingService


class RecordingLoaderSignals(QObject):
    """
    Signals for RecordingLoaderWorker.

    QRunnable can't have signals directly, so we use a separate QObject.
    All signals are emitted from the worker thread and must be connected
    to UI updates on the main thread.
    """

    # Progress signal (percentage: 0-100)
    progress = Signal(int, str)  # progress_percent, status_message

    # Success signal (waveform_data, recording)
    finished = Signal(object, object)  # np.ndarray, StreamingRecording

    # Error signal (error_message)
    error = Signal(str)


class RecordingLoaderWorker(QRunnable):
    """
    Background worker for loading streaming recording files.

    This worker loads recording data from disk without blocking the UI thread.
    Designed for large files (100MB+) that may take multiple seconds to load.

    Architecture:
    - Runs in QThreadPool background thread
    - Uses StreamingService for actual loading
    - Emits signals for progress, completion, and errors
    - Never accesses UI components directly

    Example usage:
        >>> # In ViewModel or View
        >>> worker = RecordingLoaderWorker(service, "P01", "rec_001")
        >>> worker.signals.progress.connect(self._on_load_progress)
        >>> worker.signals.finished.connect(self._on_load_finished)
        >>> worker.signals.error.connect(self._on_load_error)
        >>> QThreadPool.globalInstance().start(worker)

    Signals:
        progress(int, str): Loading progress (0-100) and status message
        finished(np.ndarray, StreamingRecording): Success with data and metadata
        error(str): Error message if loading fails
    """

    def __init__(
        self,
        streaming_service: StreamingService,
        patient_id: str,
        recording_id: str
    ):
        """
        Initialize RecordingLoaderWorker.

        Args:
            streaming_service: StreamingService instance for loading
            patient_id: Patient identifier
            recording_id: Recording identifier
        """
        super().__init__()
        self.streaming_service = streaming_service
        self.patient_id = patient_id
        self.recording_id = recording_id
        self.signals = RecordingLoaderSignals()
        self.logger = logging.getLogger(__name__)

        # Worker state
        self._is_cancelled = False

    @Slot()
    def run(self):
        """
        Execute the loading task in a background thread.

        This method runs in a QThreadPool worker thread.
        Never call UI methods directly - use signals instead.
        """
        try:
            self.logger.info(
                f"Starting async load: patient={self.patient_id}, "
                f"recording={self.recording_id}"
            )

            # Emit initial progress
            self.signals.progress.emit(0, "Loading recording metadata...")

            if self._is_cancelled:
                self.logger.info("Load cancelled before metadata retrieval")
                return

            # Load recording data (this is the slow operation)
            # Note: We can't easily report fine-grained progress for file I/O,
            # so we just update at key milestones
            self.signals.progress.emit(25, "Reading file from disk...")

            waveform_data, recording = self.streaming_service.load_recording(
                self.patient_id,
                self.recording_id
            )

            if self._is_cancelled:
                self.logger.info("Load cancelled after file read")
                return

            self.signals.progress.emit(75, "Validating data...")

            # Quick validation
            if waveform_data is None or recording is None:
                raise ValueError("Loaded data is None")

            if waveform_data.size == 0:
                raise ValueError("Loaded waveform data is empty")

            self.signals.progress.emit(100, "Load complete")

            # Emit success signal with loaded data
            self.logger.info(
                f"Successfully loaded recording: shape={waveform_data.shape}, "
                f"duration={recording.duration_seconds:.1f}s"
            )
            self.signals.finished.emit(waveform_data, recording)

        except FileNotFoundError as e:
            error_msg = f"Recording file not found: {str(e)}"
            self.logger.error(error_msg)
            self.signals.error.emit(error_msg)

        except ValueError as e:
            error_msg = f"Invalid recording data: {str(e)}"
            self.logger.error(error_msg)
            self.signals.error.emit(error_msg)

        except Exception as e:
            error_msg = f"Failed to load recording: {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            self.signals.error.emit(error_msg)

    def cancel(self):
        """
        Request cancellation of the loading operation.

        Note: This is a cooperative cancellation - the worker checks
        self._is_cancelled at safe points. If the file I/O is in progress,
        it may not cancel immediately.
        """
        self.logger.info(f"Cancellation requested for recording {self.recording_id}")
        self._is_cancelled = True
