"""
Domain models for Timeline + Snapshots event-triggered analysis.

These immutable models represent:
1. Raw data containers (Timeline recordings, Snapshot events)
2. Synchronized events (Timeline windows aligned to Snapshots)
3. Statistical analysis results (comparison between event types)
"""
from dataclasses import dataclass
from typing import List, Optional, Dict
from datetime import datetime
import numpy as np


# ============================================================================
# PART 1: RAW DATA MODELS
# ============================================================================

@dataclass(frozen=True)
class TimelineRecording:
    """
    Single 10-minute LFP measurement from Timeline data.

    Represents one chunk of bilateral LFP amplitude recorded by the Percept device.
    Timeline recordings are sampled every 10 minutes and contain raw microvolt readings
    for a specific frequency band.

    Attributes
    ----------
    timestamp : datetime
        When this recording was captured
    time_relative : float
        Time in minutes relative to a snapshot event (set during synchronization)
    power_left : float
        LFP amplitude in microvolts (uV) for the left hemisphere
    power_right : float
        LFP amplitude in microvolts (uV) for the right hemisphere
    frequency_band : str
        Frequency band (e.g., "Beta", "Gamma")
    coverage : float
        Proportion of valid data in this chunk (0.0 to 1.0)
    has_overvoltage : bool
        Whether this chunk had overvoltage events
    """
    timestamp: datetime
    time_relative: float
    power_left: float
    power_right: float
    frequency_band: str
    coverage: float = 1.0
    has_overvoltage: bool = False


@dataclass(frozen=True)
class SnapshotEvent:
    """
    Patient-triggered behavioral event marker.

    Represents a single snapshot where the patient logged an affective state
    (Craving, Happy, Anxious, etc.) via the Medtronic mobile interface.

    Attributes
    ----------
    timestamp : datetime
        When the patient triggered this snapshot
    event_name : str
        Type of event (e.g., "Craving", "Happy", "Neutral")
    patient_event_id : Optional[str]
        Unique identifier from patient database
    frequency_band : str
        Frequency band associated with this event
    """
    timestamp: datetime
    event_name: str
    patient_event_id: Optional[str]
    frequency_band: str


# ============================================================================
# PART 2: SYNCHRONIZED DATA MODELS
# ============================================================================

@dataclass(frozen=True)
class TimelineWindow:
    """
    ±120 minute window of Timeline recordings around a Snapshot event.

    Contains 25 consecutive 10-minute chunks (12 baseline + event-centered + 12 response)
    extracted from Timeline data to match a specific snapshot.

    Attributes
    ----------
    recordings : List[TimelineRecording]
        25 timeline recordings centered on event (may be fewer if data missing)
    coverage : float
        Overall coverage for this window (proportion of valid data)
    n_deficient_chunks : int
        Number of chunks with <50% coverage
    is_valid : bool
        Whether this window passes quality thresholds
    """
    recordings: List[TimelineRecording]
    coverage: float
    n_deficient_chunks: int
    is_valid: bool

    @property
    def time_axis(self) -> np.ndarray:
        """Get array of time points (minutes relative to event)."""
        return np.array([rec.time_relative for rec in self.recordings])

    @property
    def power_left(self) -> np.ndarray:
        """Get left hemisphere LFP amplitude array."""
        return np.array([rec.power_left for rec in self.recordings])

    @property
    def power_right(self) -> np.ndarray:
        """Get right hemisphere LFP amplitude array."""
        return np.array([rec.power_right for rec in self.recordings])


@dataclass(frozen=True)
class SynchronizedEvent:
    """
    A Snapshot event paired with its Timeline window.

    Combines a patient-triggered snapshot with the ±120 minute Timeline window
    of bilateral power recordings around that event.

    Attributes
    ----------
    snapshot : SnapshotEvent
        The patient-triggered event
    timeline_window : TimelineWindow
        The ±120 minute window of Timeline data
    """
    snapshot: SnapshotEvent
    timeline_window: TimelineWindow

    @property
    def event_name(self) -> str:
        """Get the event type name."""
        return self.snapshot.event_name

    @property
    def timestamp(self) -> datetime:
        """Get the event timestamp."""
        return self.snapshot.timestamp

    @property
    def is_valid(self) -> bool:
        """Check if this synchronized event is valid for analysis."""
        return self.timeline_window.is_valid


# ============================================================================
# PART 3: DATASET CONTAINERS
# ============================================================================

@dataclass(frozen=True)
class TimelineDataset:
    """
    Collection of Timeline recordings for a patient.

    Attributes
    ----------
    patient_id : str
        Patient identifier
    recordings : List[TimelineRecording]
        All timeline recordings for this patient
    frequency_band : str
        Frequency band filter applied
    """
    patient_id: str
    recordings: List[TimelineRecording]
    frequency_band: str


@dataclass(frozen=True)
class SnapshotDataset:
    """
    Collection of Snapshot events for a patient.

    Attributes
    ----------
    patient_id : str
        Patient identifier
    events : List[SnapshotEvent]
        All snapshot events for this patient
    frequency_band : str
        Frequency band filter applied
    """
    patient_id: str
    events: List[SnapshotEvent]
    frequency_band: str

    def get_event_types(self) -> List[str]:
        """Get list of unique event types."""
        return list(set(event.event_name for event in self.events))

    def get_event_counts(self) -> Dict[str, int]:
        """Get count of events per type."""
        counts: Dict[str, int] = {}
        for event in self.events:
            counts[event.event_name] = counts.get(event.event_name, 0) + 1
        return counts


@dataclass(frozen=True)
class SynchronizedDataset:
    """
    Collection of synchronized events for a patient.

    Contains all valid snapshot events paired with their Timeline windows.

    Attributes
    ----------
    patient_id : str
        Patient identifier
    events : List[SynchronizedEvent]
        All synchronized events (only valid ones included)
    frequency_band : str
        Frequency band used
    """
    patient_id: str
    events: List[SynchronizedEvent]
    frequency_band: str

    def get_event_types(self) -> List[str]:
        """Get list of unique event types."""
        return list(set(event.event_name for event in self.events))

    def get_event_counts(self) -> Dict[str, int]:
        """Get count of events per type."""
        counts: Dict[str, int] = {}
        for event in self.events:
            counts[event.event_name] = counts.get(event.event_name, 0) + 1
        return counts

    def filter_by_event_type(self, event_type: str) -> List[SynchronizedEvent]:
        """Get all events of a specific type."""
        return [event for event in self.events if event.event_name == event_type]

    def get_power_matrix(
        self,
        event_type: str,
        hemisphere: str,
        window_minutes: int = 60,
        bin_size_minutes: int = 10
    ) -> np.ndarray:
        """
        Get power matrix for a specific event type and hemisphere, binned to fixed time points.

        Parameters
        ----------
        event_type : str
            Event type to extract (e.g., "Craving")
        hemisphere : str
            Hemisphere to extract ("Left" or "Right")
        window_minutes : int
            Size of the symmetric time window (default ±60 minutes)
        bin_size_minutes : int
            Width of each time bin in minutes (default 10 minutes)

        Returns
        -------
        np.ndarray
            Matrix of shape (n_events, n_bins) with binned power values
        """
        if window_minutes <= 0:
            raise ValueError("window_minutes must be positive")
        if bin_size_minutes <= 0:
            raise ValueError("bin_size_minutes must be positive")
        if window_minutes % bin_size_minutes != 0:
            raise ValueError(
                f"window_minutes ({window_minutes}) must be a multiple of bin_size_minutes ({bin_size_minutes})"
            )

        events = self.filter_by_event_type(event_type)

        if not events:
            return np.array([])

        # Create fixed time bins centred every bin_size_minutes from -window to +window
        bin_centers = np.arange(-window_minutes, window_minutes + bin_size_minutes, bin_size_minutes, dtype=float)
        n_bins = len(bin_centers)
        half_bin = bin_size_minutes / 2.0
        inner_edges = (bin_centers[:-1] + bin_centers[1:]) / 2.0 if n_bins > 1 else np.array([])
        bin_edges = np.concatenate((
            np.array([bin_centers[0] - half_bin]),
            inner_edges,
            np.array([bin_centers[-1] + half_bin])
        ))

        # Bin each event's power data
        binned_arrays = []
        for event in events:
            time_axis = event.timeline_window.time_axis
            if hemisphere.lower() == "left":
                power = event.timeline_window.power_left
            else:
                power = event.timeline_window.power_right

            # Bin the data using histogram weighted by power values
            binned_power = np.zeros(n_bins)
            counts = np.zeros(n_bins)

            # Assign each recording to the appropriate bin
            for t, p in zip(time_axis, power):
                if -window_minutes <= t <= window_minutes:  # Only include data within target range
                    bin_idx = np.digitize(t, bin_edges, right=False) - 1
                    if 0 <= bin_idx < n_bins:
                        binned_power[bin_idx] += p
                        counts[bin_idx] += 1

            # Average the power in each bin (avoid division by zero)
            with np.errstate(divide='ignore', invalid='ignore'):
                binned_power = np.where(counts > 0, binned_power / counts, np.nan)

            # Interpolate NaN values if needed
            if np.any(np.isnan(binned_power)):
                # Find non-NaN indices
                valid_idx = ~np.isnan(binned_power)
                if np.any(valid_idx):
                    # Interpolate NaN values
                    from scipy import interpolate
                    f = interpolate.interp1d(
                        bin_centers[valid_idx],
                        binned_power[valid_idx],
                        kind='linear',
                        bounds_error=False,
                        fill_value='extrapolate'
                    )
                    binned_power = f(bin_centers)

            binned_arrays.append(binned_power)

        return np.array(binned_arrays)


# ============================================================================
# PART 4: STATISTICAL RESULT MODELS
# ============================================================================

from enum import Enum


class EffectSizeType(Enum):
    """
    Available effect size metrics for statistical comparisons.

    Each metric is appropriate for different types of statistical tests
    and data distributions. Supports pairwise (2-group) comparisons.
    """
    COHENS_D = "cohens_d"
    RANK_BISERIAL = "rank_biserial"
    ROSENTHAL_R = "rosenthal_r"


@dataclass(frozen=True)
class EffectSizeResult:
    """
    Container for effect size calculation with confidence interval.

    Attributes
    ----------
    effect_size_type : EffectSizeType
        Type of effect size metric used
    value : float
        Calculated effect size value
    ci_lower : float
        Lower bound of 95% confidence interval
    ci_upper : float
        Upper bound of 95% confidence interval
    interpretation : str
        Qualitative interpretation: "small", "medium", "large", or "unreliable"

    Examples
    --------
    >>> result = EffectSizeResult(
    ...     effect_size_type=EffectSizeType.COHENS_D,
    ...     value=0.65,
    ...     ci_lower=0.35,
    ...     ci_upper=0.95,
    ...     interpretation="medium"
    ... )
    >>> print(result.display_name)
    Cohen's d
    """
    effect_size_type: EffectSizeType
    value: float
    ci_lower: float
    ci_upper: float
    interpretation: str

    @property
    def display_name(self) -> str:
        """Human-readable name for display in tables and plots."""
        names = {
            EffectSizeType.COHENS_D: "Cohen's d",
            EffectSizeType.RANK_BISERIAL: "Rank-biserial r",
            EffectSizeType.ROSENTHAL_R: "Rosenthal's r"
        }
        return names[self.effect_size_type]

    @property
    def is_reliable(self) -> bool:
        """Check if effect size is reliable (not flagged as unreliable)."""
        return self.interpretation != "unreliable"


@dataclass(frozen=True)
class TimepointResult:
    """
    Statistical results for a single time point.

    Represents the comparison between two event groups at one specific
    time point relative to the event onset.

    Attributes
    ----------
    time_point : float
        Time in minutes relative to event onset (e.g., -120, -110, ..., 0, ..., +120)
    group1_mean : float
        Mean LFP amplitude (uV) for group 1 at this time point
    group1_std : float
        Standard deviation for group 1
    group2_mean : float
        Mean LFP amplitude (uV) for group 2 at this time point
    group2_std : float
        Standard deviation for group 2
    p_value : float
        Raw p-value from Mann-Whitney U test
    p_value_corrected : float
        FDR-corrected p-value (Benjamini-Hochberg)
    test_statistic : float
        Test statistic (U-statistic for Mann-Whitney U test)
    effect_size : float
        Effect size value (DEPRECATED: use effect_size_result instead)
    ci_lower : float
        Lower bound of 95% CI for effect size (DEPRECATED: use effect_size_result instead)
    ci_upper : float
        Upper bound of 95% CI for effect size (DEPRECATED: use effect_size_result instead)
    is_significant : bool
        Whether this time point is statistically significant after FDR correction
    effect_size_result : Optional[EffectSizeResult]
        Complete effect size result with type, value, CI, and interpretation
    central_tendency_label : str
        Label describing the central tendency metric (e.g., "Mean" or "Median")
    central_tendency_difference : float
        Difference in central tendency between the two groups (group1 - group2)
    central_tendency_ci_lower : float
        Lower bound of 95% CI for the central tendency difference
    central_tendency_ci_upper : float
        Upper bound of 95% CI for the central tendency difference
    """
    time_point: float
    group1_mean: float
    group1_std: float
    group2_mean: float
    group2_std: float
    p_value: float
    p_value_corrected: float
    test_statistic: float
    effect_size: float
    ci_lower: float = 0.0
    ci_upper: float = 0.0
    is_significant: bool = False
    effect_size_result: Optional[EffectSizeResult] = None
    central_tendency_label: str = "Mean"
    central_tendency_difference: float = 0.0
    central_tendency_ci_lower: float = 0.0
    central_tendency_ci_upper: float = 0.0


@dataclass(frozen=True)
class PeakInfo:
    """
    Information about the peak (most significant) time point.

    Attributes
    ----------
    peak_time : float
        Time point with minimum p-value
    peak_p_value : float
        FDR-corrected p-value at peak
    peak_effect_size : float
        Effect size value at peak (DEPRECATED: use peak_effect_size_result instead)
    is_significant : bool
        Whether peak passes FDR threshold
    peak_effect_size_result : Optional[EffectSizeResult]
        Complete effect size result at peak
    """
    peak_time: float
    peak_p_value: float
    peak_effect_size: float
    is_significant: bool
    peak_effect_size_result: Optional[EffectSizeResult] = None


@dataclass(frozen=True)
class EventComparisonResult:
    """
    Complete statistical comparison between two event types.

    Contains timepoint-by-timepoint results for one hemisphere, comparing
    LFP power trajectories around different behavioral events.

    Attributes
    ----------
    group1_name : str
        Name of first event type (e.g., "Craving")
    group2_name : str
        Name of second event type (e.g., "Happy")
    hemisphere : str
        Hemisphere analyzed ("Left" or "Right")
    frequency_band : str
        Frequency band analyzed (e.g., "Beta")
    time_axis : np.ndarray
        Array of time points in minutes (e.g., [-120, -110, ..., 0, ..., +120])
    timepoint_results : List[TimepointResult]
        Statistical results for each time point
    peak_info : Optional[PeakInfo]
        Information about the most significant time point
    n_events_group1 : int
        Number of events in group 1
    n_events_group2 : int
        Number of events in group 2
    alpha : float
        Significance threshold used (default 0.05)
    """
    group1_name: str
    group2_name: str
    hemisphere: str
    frequency_band: str
    time_axis: np.ndarray
    timepoint_results: List[TimepointResult]
    peak_info: Optional[PeakInfo]
    n_events_group1: int
    n_events_group2: int
    alpha: float = 0.05

    def get_significant_timepoints(self) -> List[TimepointResult]:
        """
        Get all time points that are statistically significant.

        Returns
        -------
        List[TimepointResult]
            Significant time points, sorted by p-value (most significant first)
        """
        significant = [tp for tp in self.timepoint_results if tp.is_significant]
        return sorted(significant, key=lambda tp: tp.p_value_corrected)

    def get_timepoint_at(self, time: float) -> Optional[TimepointResult]:
        """
        Get result for a specific time point.

        Parameters
        ----------
        time : float
            Time in minutes relative to event

        Returns
        -------
        Optional[TimepointResult]
            Result at that time point, or None if not found
        """
        for tp in self.timepoint_results:
            if abs(tp.time_point - time) < 0.1:  # Tolerance for floating point
                return tp
        return None

    @property
    def has_significant_differences(self) -> bool:
        """Check if any time points are significant."""
        return any(tp.is_significant for tp in self.timepoint_results)

    @property
    def n_significant_timepoints(self) -> int:
        """Count of significant time points."""
        return sum(1 for tp in self.timepoint_results if tp.is_significant)
