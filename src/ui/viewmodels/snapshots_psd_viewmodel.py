"""
SnapshotsPsdViewModel for coordinating Snapshots PSD analysis page.

This ViewModel implements the MVVM pattern, managing state and coordinating
between the UI and service layer for snapshot PSD analysis.

Author: iEEG BrainSense Development Team
Last Updated: 2025-10-02
"""

import logging
from dataclasses import dataclass
from typing import Optional, List, Dict, Tuple, Union
from PySide6.QtCore import QObject, Qt, QThreadPool, Signal
import numpy as np

from src.domain.psd_models import SnapshotPsdDataset
from src.core.services.snapshot_psd_analysis_service import (
    SnapshotPsdAnalysisService,
    BandComparisonResult
)
from src.infrastructure.repositories import SnapshotRepository
from src.infrastructure.psd_data_loader import load_snapshot_psd_dataset
from src.domain.models import EffectSizeType
from src.domain.effect_size_preference import EffectSizePreference
from src.ui.workers.snapshots_psd_worker import SnapshotsPsdWorker

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BandStatisticsDisplayRow:
    """
    Lightweight row of formatted statistics ready for UI consumption.
    """
    band_label: str
    freq_range: str
    group1_median_text: str
    group2_median_text: str
    p_value_text: str
    p_value_highlight: bool
    q_value_text: str
    q_value_highlight: bool
    effect_size_value_text: str
    central_tendency_ci_text: str
    effect_size_ci_text: str


class SnapshotsPsdViewModel(QObject):
    """
    ViewModel for Snapshots PSD analysis page.

    Responsibilities:
    - Load patient snapshot data with PSD
    - Manage craving vs non-craving groups
    - Coordinate statistical analysis
    - Manage analysis state
    - Emit signals for UI updates

    Signals:
        patient_changed: Emitted when patient selection changes (patient_id)
        data_loaded: Emitted when patient data is loaded (n_events)
        analysis_complete: Emitted when PSD analysis completes
        psd_curves_ready: Emitted when PSD curves are computed
        band_statistics_ready: Emitted when band statistics are ready
        error_occurred: Emitted when an error occurs (error_message)
        progress_updated: Emitted during long operations (percentage, message)
        effect_size_changed: Emitted when effect size preference changes (effect_type_value)
    """

    # Signals for UI updates
    patient_changed = Signal(str)           # patient_id
    data_loaded = Signal(int)               # n_events
    analysis_complete = Signal()            # No args
    analysis_started = Signal()             # analysis run begins (drives popup show)
    psd_curves_ready = Signal()             # No args
    band_statistics_ready = Signal()        # No args
    error_occurred = Signal(str)            # error_message
    progress_updated = Signal(int, str)     # (percentage, message)
    effect_size_changed = Signal(str)       # effect_type value
    analysis_refresh_required = Signal(str) # effect_type value causing invalidation
    analysis_refresh_cleared = Signal()     # emitted when results are current

    def __init__(
        self,
        snapshot_repo: SnapshotRepository,
        analysis_service: Optional[SnapshotPsdAnalysisService] = None
    ):
        """
        Initialize SnapshotsPsdViewModel.

        Parameters
        ----------
        snapshot_repo : SnapshotRepository
            Repository for loading snapshot data
        analysis_service : Optional[SnapshotPsdAnalysisService]
            Service for PSD analysis (creates default if None)
        """
        super().__init__()

        # Dependencies
        self._snapshot_repo = snapshot_repo
        self._analysis_service = analysis_service or SnapshotPsdAnalysisService()

        # State
        self._current_patient: Optional[str] = None
        self._dataset: Optional[SnapshotPsdDataset] = None
        self._hemisphere: str = "LEFT"
        self._filter_stimulation: bool = True
        self._timeline_band_center: Optional[float] = None

        # Event groups (predefined for craving analysis)
        self._craving_group = ["Craving", "Drinking", "Drinking/Craving"]
        self._non_craving_group = ["Anxious", "Happy", "Neutral", "Sad", "Depressed"]

        # Analysis results - store for both hemispheres
        self._band_results: Dict[str, BandComparisonResult] = {}
        self._band_results_left: Dict[str, BandComparisonResult] = {}
        self._band_results_right: Dict[str, BandComparisonResult] = {}
        self._psd_curves: Dict[str, Tuple[np.ndarray, np.ndarray, int]] = {}
        self._psd_curves_left: Dict[str, Tuple[np.ndarray, np.ndarray, int]] = {}
        self._psd_curves_right: Dict[str, Tuple[np.ndarray, np.ndarray, int]] = {}
        self._band_statistics_rows: List[BandStatisticsDisplayRow] = []
        self._effect_size_header_text: str = "Effect Size"
        self._central_tendency_header_text: str = "Median Δ 95% CI"
        self._analysis_requires_refresh: bool = False

        # Available event types from loaded data
        self._available_event_types: List[str] = []
        self._event_counts: Dict[str, int] = {}

        # Worker lifecycle tracking. ``_active_worker`` is the single
        # in-flight worker, if any. ``_worker_signal_connections`` records
        # ``(signal, slot)`` pairs so we can disconnect by pair on patient
        # change / new analyze / cancel — preventing a stale ``finished``
        # from a previous run from stomping new state.
        self._active_worker: Optional[SnapshotsPsdWorker] = None
        self._worker_signal_connections: List[Tuple[Signal, object]] = []

        # Effect size preference (singleton)
        self._effect_size_preference = EffectSizePreference()
        # Connect to preference changes to re-analyze if data is loaded
        self._effect_size_preference.effect_size_changed.connect(
            self._on_effect_size_preference_changed
        )

    def _reset_analysis_outputs(self):
        """
        Clear cached analysis results without altering loaded datasets.
        """
        self._band_results = {}
        self._band_results_left = {}
        self._band_results_right = {}
        self._psd_curves = {}
        self._psd_curves_left = {}
        self._psd_curves_right = {}
        self._band_statistics_rows = []
        self._effect_size_header_text = "Effect Size"
        self._central_tendency_header_text = "Median Δ 95% CI"

    def clear_analysis_results(
        self,
        *,
        clear_groups: bool = False,
        clear_timeline_band: bool = False
    ):
        """
        Public helper for resetting analysis state.

        Parameters
        ----------
        clear_groups : bool, optional
            When True, also forget current group selections.
        clear_timeline_band : bool, optional
            When True, clear the cached timeline band center.
        """
        self._reset_analysis_outputs()
        self._clear_analysis_refresh_state()
        if clear_groups:
            self._craving_group = []
            self._non_craving_group = []
        if clear_timeline_band:
            self._timeline_band_center = None
        logger.info(
            "Snapshots PSD analysis state cleared "
            f"(clear_groups={clear_groups}, clear_timeline_band={clear_timeline_band})"
        )

    # ========================================================================
    # Private Methods - Data Transformation
    # ========================================================================

    def _format_frequency_range(self, result: BandComparisonResult) -> str:
        """Format `[min, max]` frequency range for display."""
        min_str = f"{result.min_freq:.2f}".rstrip("0").rstrip(".")
        max_str = f"{result.max_freq:.2f}".rstrip("0").rstrip(".")
        return f"{min_str}-{max_str} Hz"

    def _cache_band_statistics_rows(self):
        """
        Build pre-formatted statistics rows for UI rendering.

        Populates `_band_statistics_rows` and updates the effect-size header text
        based on the first available unified effect size result.
        """
        rows: List[BandStatisticsDisplayRow] = []
        effect_header: Optional[str] = None
        central_header: Optional[str] = None

        def append_result_rows(
            band_results: Dict[str, BandComparisonResult],
            hemisphere_suffix: str
        ):
            nonlocal effect_header
            nonlocal central_header
            for result in band_results.values():
                effect_result = result.effect_size_result
                if effect_result is not None:
                    effect_value_text = f"{effect_result.value:.3f}"
                    effect_ci_text = self._format_ci_text(
                        effect_result.ci_lower,
                        effect_result.ci_upper
                    )
                    if effect_header is None:
                        effect_header = effect_result.display_name
                else:
                    effect_value_text = f"{result.rosenthal_r:.3f}"
                    effect_ci_text = self._format_ci_text(
                        result.ci_lower,
                        result.ci_upper
                    )
                    if effect_header is None:
                        effect_header = "Rosenthal's r"

                central_label = result.central_tendency_label or "Median"
                central_ci_text = self._format_ci_text(
                    result.central_tendency_ci_lower,
                    result.central_tendency_ci_upper
                )
                if central_header is None:
                    central_header = f"{central_label} Δ 95% CI"

                rows.append(
                    BandStatisticsDisplayRow(
                        band_label=f"{result.band_name} ({hemisphere_suffix})",
                        freq_range=self._format_frequency_range(result),
                        group1_median_text=f"{result.median_group1:.3f}",
                        group2_median_text=f"{result.median_group2:.3f}",
                        p_value_text=f"{result.p_value:.4f}",
                        p_value_highlight=result.p_value < 0.05,
                        q_value_text=f"{result.q_value:.4f}",
                        q_value_highlight=result.q_value < 0.05,
                        effect_size_value_text=effect_value_text,
                        central_tendency_ci_text=central_ci_text,
                        effect_size_ci_text=effect_ci_text,
                    )
                )

        append_result_rows(self._band_results_left, "L")
        append_result_rows(self._band_results_right, "R")

        self._band_statistics_rows = rows
        self._effect_size_header_text = effect_header or "Effect Size"
        self._central_tendency_header_text = central_header or "Median Δ 95% CI"

    @staticmethod
    def _format_ci_text(lower: float, upper: float) -> str:
        """Format confidence interval values, handling NaNs."""
        if np.isnan(lower) or np.isnan(upper):
            return "-"
        return f"[{lower:.3f}, {upper:.3f}]"

    # ========================================================================
    # Public Methods - Data Loading
    # ========================================================================

    def load_patient_data(self, patient_id: str):
        """
        Load snapshot PSD data for a patient.

        Parameters
        ----------
        patient_id : str
            Patient ID to load

        Emits
        -----
        patient_changed : When patient selection changes
        progress_updated : During loading
        data_loaded : When loading completes with event count
        error_occurred : If loading fails
        """
        try:
            logger.info(f"Loading snapshot PSD data for patient: {patient_id}")

            # Cancel + disconnect any in-flight worker BEFORE we mutate
            # state. A late-arriving ``finished`` from a previous patient
            # would otherwise stomp the new patient's results.
            self._disconnect_and_cancel_active_worker()

            self._current_patient = patient_id
            self.patient_changed.emit(patient_id)

            # Clear previous data
            self._dataset = None
            self._reset_analysis_outputs()
            self._clear_analysis_refresh_state()

            # Load raw snapshot records
            records = self._snapshot_repo.get_by_patient(
                patient_id=patient_id,
                limit=10000
            )

            # Convert to PSD dataset
            self._dataset = load_snapshot_psd_dataset(patient_id, records)

            # Update available event types
            self._available_event_types = self._dataset.get_event_types()
            self._event_counts = self._dataset.get_event_counts()

            # Log summary
            n_events = len(self._dataset.events)
            logger.info(
                f"Loaded {n_events} PSD events for {patient_id}: "
                f"{self._event_counts}"
            )

            self.data_loaded.emit(n_events)

        except Exception as e:
            logger.error(f"Failed to load patient data: {e}")
            self.error_occurred.emit(f"Failed to load data: {str(e)}")

    def clear_patient_data(self):
        """Clear current patient data and reset state."""
        self._disconnect_and_cancel_active_worker()
        self._current_patient = None
        self._dataset = None
        self._reset_analysis_outputs()
        self._clear_analysis_refresh_state()
        self._available_event_types.clear()
        self._event_counts.clear()
        self._timeline_band_center = None
        logger.info("Patient data cleared")

    # ========================================================================
    # Public Methods - Analysis
    # ========================================================================

    def analyze_craving_vs_non_craving(self):
        """
        Perform craving vs non-craving analysis using default groups.

        Computes:
        - PSD curves for each group
        - Band-wise statistical comparisons
        - Multiple comparison correction

        Emits
        -----
        progress_updated : During analysis
        psd_curves_ready : When curves are computed
        band_statistics_ready : When statistics are ready
        analysis_complete : When all analysis completes
        error_occurred : If analysis fails
        """
        # Panel convention: Group 1 (Jade) = non-craving, Group 2 (Rose) = craving.
        self.analyze_event_groups(
            group1_event_types=self._non_craving_group,
            group2_event_types=self._craving_group,
            group1_name="Non-Craving",
            group2_name="Craving"
        )

    def analyze_event_groups(
        self,
        group1_event_types: List[str],
        group2_event_types: List[str],
        group1_name: str = "Group 1",
        group2_name: str = "Group 2",
        test_method: str = "Mann-Whitney U",
        correction_method: str = "FDR (Benjamini-Hochberg)",
        timeline_band_center: Optional[float] = None
    ):
        """
        Perform analysis comparing two arbitrary groups of event types.

        Parameters
        ----------
        group1_event_types : List[str]
            Event types for first group
        group2_event_types : List[str]
            Event types for second group
        group1_name : str
            Display name for first group
        group2_name : str
            Display name for second group
        test_method : str
            Statistical test method (currently only Mann-Whitney U supported)
        correction_method : str
            Multiple comparison correction method
        timeline_band_center : Optional[float]
            Optional 5 Hz band center frequency (Hz) to include alongside canonical bands

        Emits
        -----
        progress_updated : During analysis
        psd_curves_ready : When curves are computed
        band_statistics_ready : When statistics are ready
        analysis_complete : When all analysis completes
        error_occurred : If analysis fails
        """
        if not self._dataset:
            self.error_occurred.emit("No data loaded")
            return

        if timeline_band_center is not None:
            effective_band_center = timeline_band_center
        else:
            effective_band_center = self._timeline_band_center

        # Pre-checks passed — now it is safe to discard prior worker + results.
        # Cancel + signal-disconnect any in-flight worker so a stale
        # finished / error from the previous run cannot apply on top of the
        # new run.
        self._disconnect_and_cancel_active_worker()

        # Forget cached analysis so reruns start clean.
        self._reset_analysis_outputs()

        # Panel convention: Group 1 (Jade) = non-craving, Group 2 (Rose) = craving.
        # Field names retain the manuscript classification, not the group ordinal.
        self._non_craving_group = group1_event_types
        self._craving_group = group2_event_types
        self._timeline_band_center = effective_band_center

        # Construct + wire the worker.
        worker = SnapshotsPsdWorker(
            self._analysis_service,
            self._dataset,
            group1_event_types=group1_event_types,
            group2_event_types=group2_event_types,
            group1_name=group1_name,
            group2_name=group2_name,
            filter_stimulation=self._filter_stimulation,
            timeline_band_center=effective_band_center,
        )
        self._connect_worker_signals(worker)
        self._active_worker = worker

        self.analysis_started.emit()
        self.progress_updated.emit(0, "Starting PSD analysis…")

        QThreadPool.globalInstance().start(worker)

    def cancel_analysis(self) -> None:
        """Cancel any in-flight analysis. Idempotent: a no-op if no worker
        is currently running. Mirrors
        :meth:`Snapshots5HzBandViewModel.cancel_analysis`."""
        if self._active_worker is None:
            return
        logger.info("User-requested cancellation of snapshots PSD analysis")
        self._disconnect_and_cancel_active_worker()
        # The View hides the popup directly in its cancel slot; the VM no
        # longer drives dialog visibility through a progress emission.

    # ========================================================================
    # Public Methods - Settings
    # ========================================================================

    def set_hemisphere(self, hemisphere: str):
        """
        Set hemisphere for analysis.

        Parameters
        ----------
        hemisphere : str
            "LEFT", "RIGHT", or "BOTH"
        """
        if hemisphere in ["LEFT", "RIGHT", "BOTH"]:
            self._hemisphere = hemisphere
            logger.info(f"Hemisphere set to: {hemisphere}")
        else:
            logger.warning(f"Invalid hemisphere: {hemisphere}")

    def set_stimulation_filter(self, filter_stim: bool):
        """
        Set whether to filter for matching stimulation states.

        Parameters
        ----------
        filter_stim : bool
            True to require matching stimulation
        """
        self._filter_stimulation = filter_stim
        logger.info(f"Stimulation filter set to: {filter_stim}")

    def set_timeline_band_center(self, center: Optional[float]):
        """
        Set the optional timeline-style band center frequency.

        Parameters
        ----------
        center : Optional[float]
            Frequency in Hz, or None to disable
        """
        self._timeline_band_center = center
        if center is None:
            logger.info("Timeline band disabled for snapshot analysis")
        else:
            logger.info(f"Timeline band center set to {center:.2f} Hz")

    def get_timeline_band_center(self) -> Optional[float]:
        """Return the configured timeline-style band center frequency."""
        return self._timeline_band_center

    def update_craving_group(self, event_types: List[str]):
        """
        Update the event types in the craving group.

        Parameters
        ----------
        event_types : List[str]
            Event types to include in craving group
        """
        self._craving_group = event_types
        logger.info(f"Craving group updated: {event_types}")

    def update_non_craving_group(self, event_types: List[str]):
        """
        Update the event types in the non-craving group.

        Parameters
        ----------
        event_types : List[str]
            Event types to include in non-craving group
        """
        self._non_craving_group = event_types
        logger.info(f"Non-craving group updated: {event_types}")

    # ========================================================================
    # Public Properties - State Access
    # ========================================================================

    @property
    def current_patient(self) -> Optional[str]:
        """Get current patient ID."""
        return self._current_patient

    @property
    def has_data(self) -> bool:
        """Check if data is loaded."""
        return self._dataset is not None

    @property
    def available_event_types(self) -> List[str]:
        """Get list of available event types."""
        return self._available_event_types

    @property
    def event_counts(self) -> Dict[str, int]:
        """Get event counts by type."""
        return self._event_counts

    @property
    def band_results(self) -> Dict[str, BandComparisonResult]:
        """Get band comparison results."""
        return self._band_results

    @property
    def psd_curves(self) -> Dict[str, Tuple[np.ndarray, np.ndarray, np.ndarray, int]]:
        """
        Get PSD curves for groups with 95% bootstrap confidence intervals.

        Returns
        -------
        Dict with 'craving' and 'non_craving' keys, each containing:
            (median_psd, lower_ci, upper_ci, n_events)

        Note: The CI bounds are calculated using bootstrap percentile method,
        which is appropriate for medians and consistent with Mann-Whitney U testing.
        """
        return self._psd_curves

    @property
    def psd_curves_left(self) -> Dict[str, Tuple[np.ndarray, np.ndarray, np.ndarray, int]]:
        """
        Get PSD curves for left hemisphere with 95% confidence intervals.

        Returns
        -------
        Dict with 'craving' and 'non_craving' keys, each containing:
            (median_psd, lower_ci, upper_ci, n_events)
        """
        return self._psd_curves_left

    @property
    def psd_curves_right(self) -> Dict[str, Tuple[np.ndarray, np.ndarray, np.ndarray, int]]:
        """
        Get PSD curves for right hemisphere with 95% confidence intervals.

        Returns
        -------
        Dict with 'craving' and 'non_craving' keys, each containing:
            (median_psd, lower_ci, upper_ci, n_events)
        """
        return self._psd_curves_right

    @property
    def band_results_left(self) -> Dict[str, BandComparisonResult]:
        """Get band comparison results for left hemisphere."""
        return self._band_results_left

    @property
    def band_results_right(self) -> Dict[str, BandComparisonResult]:
        """Get band comparison results for right hemisphere."""
        return self._band_results_right

    @property
    def band_statistics_table_rows(self) -> List[BandStatisticsDisplayRow]:
        """Rows of formatted statistics for UI tables."""
        return self._band_statistics_rows

    @property
    def effect_size_header_text(self) -> str:
        """Header label for the effect size column."""
        return self._effect_size_header_text or "Effect Size"

    @property
    def central_tendency_header_text(self) -> str:
        """Header label for the central tendency CI column."""
        return self._central_tendency_header_text or "Median Δ 95% CI"

    @property
    def frequency_axis(self) -> Optional[np.ndarray]:
        """Get frequency axis for PSD plots."""
        if self._dataset:
            return self._dataset.frequency_axis
        return None

    @property
    def hemisphere(self) -> str:
        """Get current hemisphere setting."""
        return self._hemisphere

    @property
    def craving_group(self) -> List[str]:
        """Get event types in craving group."""
        return self._craving_group

    @property
    def non_craving_group(self) -> List[str]:
        """Get event types in non-craving group."""
        return self._non_craving_group

    def get_significant_bands(self) -> List[str]:
        """
        Get list of bands with significant differences.

        Returns
        -------
        List[str]
            Band names with q < 0.05
        """
        return [
            band for band, result in self._band_results.items()
            if result.is_significant
        ]

    def has_analysis_results(self) -> bool:
        """
        Check if analysis results are available for export.

        Returns
        -------
        bool
            True if any PSD curves or band statistics are available
        """
        # Check the merged results (source of truth for exports)
        # Don't check left/right individually to avoid stale data issues
        has_curves = (
            self._psd_curves is not None and
            len(self._psd_curves) > 0
        )

        has_stats = len(self._band_results) > 0

        result = has_curves or has_stats

        # Debug logging
        logger.debug(
            f"has_analysis_results check: "
            f"has_curves={has_curves} "
            f"(psd_curves={'dict' if isinstance(self._psd_curves, dict) else 'other'}, len={len(self._psd_curves) if self._psd_curves else 0}), "
            f"has_stats={has_stats} "
            f"(band_results len={len(self._band_results)}), "
            f"result={result}"
        )

        return result

    # ========================================================================
    # Effect Size Management
    # ========================================================================

    def get_effect_size_type(self) -> EffectSizeType:
        """
        Get current effect size preference.

        Returns
        -------
        EffectSizeType
            Current effect size type
        """
        return self._effect_size_preference.get_effect_size()

    def get_effect_size_value(self) -> str:
        """
        Get current effect size preference as value string.

        Returns
        -------
        str
            Current effect size type value (e.g., "cohens_d")
        """
        return self._effect_size_preference.get_effect_size_value()

    def set_effect_size_type(self, effect_type: Union[str, EffectSizeType]):
        """
        Update effect size preference.

        Parameters
        ----------
        effect_type : Union[str, EffectSizeType]
            New effect size type to use (enum instance or value string). Updates
            preference without automatically recomputing current results.
        """
        if isinstance(effect_type, str):
            try:
                effect_type_enum = EffectSizeType(effect_type)
            except ValueError as exc:
                logger.warning(f"Ignoring invalid effect size type: {effect_type}")
                raise exc
        else:
            effect_type_enum = effect_type

        self._effect_size_preference.set_effect_size(effect_type_enum)
        # Note: The preference will emit effect_size_changed signal,
        # which we're connected to via _on_effect_size_preference_changed

    def _on_effect_size_preference_changed(self, effect_type_value: str):
        """Handle effect size preference change."""
        logger.info(f"Effect size preference changed to: {effect_type_value}")

        # Emit signal for UI
        self.effect_size_changed.emit(effect_type_value)

        # Mark existing results as stale until user re-runs analysis
        if self.has_analysis_results():
            logger.info("Effect size change invalidated current PSD analysis results")
            self._analysis_requires_refresh = True
            self.analysis_refresh_required.emit(effect_type_value)
        else:
            self._clear_analysis_refresh_state()

    # ========================================================================
    # Internal Helpers - Analysis Refresh
    # ========================================================================

    def _mark_analysis_up_to_date(self):
        """Clear stale-analysis flag after a successful run."""
        was_stale = self._analysis_requires_refresh
        self._analysis_requires_refresh = False
        if was_stale:
            self.analysis_refresh_cleared.emit()

    def _clear_analysis_refresh_state(self):
        """Reset stale-analysis tracking when results are cleared."""
        was_stale = self._analysis_requires_refresh
        self._analysis_requires_refresh = False
        if was_stale:
            self.analysis_refresh_cleared.emit()

    # ========================================================================
    # Private Helpers - Worker Lifecycle
    # ========================================================================

    def _disconnect_and_cancel_active_worker(self) -> None:
        """Cancel and signal-disconnect any in-flight worker.

        Mirrors :meth:`Snapshots5HzBandViewModel._disconnect_and_cancel_active_worker`.
        Critical for correctness: without disconnecting the carrier's signals
        from this VM's slots, a late ``finished`` (cancellation sometimes
        loses the race with the last service call) could write stale results
        on top of a new patient or run. Disconnect by ``(signal, slot)`` pair
        so we don't touch other connections that share the same carrier.
        """
        if self._active_worker is None:
            return

        # Request cooperative cancellation. The worker polls ``_is_cancelled``
        # at each phase boundary; depending on timing the worker may still
        # emit ``cancelled``, ``finished``, or ``error`` — disconnection
        # ensures none of those reach our slots.
        self._active_worker.cancel()

        for sig, slot in self._worker_signal_connections:
            try:
                sig.disconnect(slot)
            except (RuntimeError, TypeError):
                # Already disconnected or carrier C++ object gone — both safe.
                pass
        self._worker_signal_connections.clear()
        self._active_worker = None

    def _connect_worker_signals(self, worker: SnapshotsPsdWorker) -> None:
        """Connect a fresh worker's signals to this VM's slots.

        Uses :data:`Qt.QueuedConnection` explicitly so worker-thread emissions
        are queued onto the GUI thread's event loop. Auto-detected connection
        would do the same here, but explicit removes ambiguity.
        """
        sig = worker.signals
        pairs: List[Tuple[Signal, object]] = [
            (sig.progress, self._on_worker_progress),
            (sig.partial_psd, self._on_worker_partial_psd),
            (sig.partial_band, self._on_worker_partial_band),
            (sig.finished, self._on_worker_finished),
            (sig.error, self._on_worker_error),
            (sig.cancelled, self._on_worker_cancelled),
        ]
        for s, slot in pairs:
            s.connect(slot, Qt.QueuedConnection)
            self._worker_signal_connections.append((s, slot))

    # ========================================================================
    # Private Slots - Worker Signal Handlers
    # ========================================================================

    def _on_worker_progress(self, done: int, total: int, label: str) -> None:
        """Bridge worker ``(done, total, label)`` to VM ``(percent, label)``."""
        percent = int(round(100.0 * done / total)) if total else 0
        percent = max(0, min(100, percent))
        self.progress_updated.emit(percent, label)

    def _on_worker_partial_psd(self, hemisphere: str, curves: object) -> None:
        """Store per-hemisphere PSD curves silently. The public
        ``psd_curves_ready`` signal fires once after both hemispheres land
        in :meth:`_on_worker_finished`, so the View renders a complete
        bilateral plot rather than a half-populated one."""
        if hemisphere == "LEFT":
            self._psd_curves_left = curves  # type: ignore[assignment]
        elif hemisphere == "RIGHT":
            self._psd_curves_right = curves  # type: ignore[assignment]

    def _on_worker_partial_band(self, hemisphere: str, bands: object) -> None:
        """Store per-hemisphere band statistics silently (same rationale as
        :meth:`_on_worker_partial_psd`)."""
        if hemisphere == "LEFT":
            self._band_results_left = bands  # type: ignore[assignment]
        elif hemisphere == "RIGHT":
            self._band_results_right = bands  # type: ignore[assignment]

    def _on_worker_finished(self, payload: object) -> None:
        """Compose the final results, emit payload-ready signals in the
        deterministic order ``psd_curves_ready`` → ``band_statistics_ready``
        → ``progress_updated(100, …)`` → ``analysis_complete``, then clear
        worker tracking. Mirrors
        :meth:`Snapshots5HzBandViewModel._on_worker_finished`."""
        # Update combined ``_psd_curves`` for backward compatibility with
        # the old hemisphere-mode API (LEFT/RIGHT/BOTH).
        if self._hemisphere == "BOTH":
            self._psd_curves = {
                'left': self._psd_curves_left,
                'right': self._psd_curves_right,
            }
        elif self._hemisphere == "LEFT":
            self._psd_curves = self._psd_curves_left
        else:
            self._psd_curves = self._psd_curves_right

        self._band_results = {
            **self._band_results_left,
            **self._band_results_right,
        }
        self._cache_band_statistics_rows()

        self._active_worker = None
        self._worker_signal_connections.clear()

        self.psd_curves_ready.emit()
        self.band_statistics_ready.emit()
        self._mark_analysis_up_to_date()

        significant_bands = [
            band for band, result in self._band_results.items()
            if result.is_significant
        ]
        if significant_bands:
            logger.info(f"Significant bands after FDR: {significant_bands}")
        else:
            logger.info("No significant differences found after FDR correction")

        self.analysis_complete.emit()

    def _on_worker_error(self, msg: str) -> None:
        """Forward worker errors to ``error_occurred`` and clear worker
        state. Does NOT emit ``analysis_complete`` (mirrors Snapshots 5 Hz Band)."""
        logger.error(f"Snapshots PSD worker reported error: {msg}")
        self._active_worker = None
        self._worker_signal_connections.clear()
        # ``error_occurred`` triggers the View's QMessageBox; the View also
        # hides the popup in its error slot. No progress emission needed.
        self.error_occurred.emit(msg)

    def _on_worker_cancelled(self) -> None:
        """Acknowledge user-driven cancellation. Logs at INFO; does NOT emit
        ``error_occurred`` or ``analysis_complete`` (the run was not an error
        and exports should not be enabled). The View hides the popup in its
        cancel slot, so no progress emission is needed here."""
        logger.info("Snapshots PSD worker cancellation acknowledged")
        self._active_worker = None
        self._worker_signal_connections.clear()
