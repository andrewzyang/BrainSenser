"""
Domain models for Snapshot PSD analysis.

These models extend the base snapshot models to include power spectral density
data for frequency-domain analysis of patient-triggered events.

Author: iEEG BrainSense Development Team
Last Updated: 2025-10-16
"""
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Tuple
from datetime import datetime
import numpy as np

from src.core.services.bootstrap_statistics import BootstrapStatistics


# ============================================================================
# PART 1: PSD DATA MODELS
# ============================================================================

@dataclass(frozen=True)
class SnapshotPsdEvent:
    """
    Patient-triggered event with full PSD data.

    Extends the basic SnapshotEvent to include frequency and power arrays
    from the BrainSense snapshots (30s, 250 Hz bilateral spectra).

    Attributes
    ----------
    timestamp : datetime
        When the patient triggered this snapshot
    event_name : str
        Type of event (e.g., "Craving", "Happy", "Neutral")
    patient_event_id : Optional[str]
        Unique identifier from patient database
    frequency_axis : np.ndarray
        Frequency bins (0.98 Hz resolution, 0.98–96.04 Hz centers)
    psd_left : Optional[np.ndarray]
        Power spectral density for left hemisphere (μV²/Hz)
    psd_right : Optional[np.ndarray]
        Power spectral density for right hemisphere (μV²/Hz)
    artifact_mask_left : Optional[np.ndarray]
        Boolean mask for censored bins in left hemisphere
    artifact_mask_right : Optional[np.ndarray]
        Boolean mask for censored bins in right hemisphere
    therapy_amplitude_left : Optional[float]
        Stimulation amplitude for left hemisphere at snapshot time
    therapy_amplitude_right : Optional[float]
        Stimulation amplitude for right hemisphere at snapshot time
    therapy_frequency : Optional[float]
        Stimulation frequency at snapshot time
    hemisphere : str
        Which hemisphere(s) recorded ("LEFT", "RIGHT", "BOTH")
    """
    timestamp: datetime
    event_name: str
    patient_event_id: Optional[str]
    frequency_axis: np.ndarray
    psd_left: Optional[np.ndarray]
    psd_right: Optional[np.ndarray]
    artifact_mask_left: Optional[np.ndarray]
    artifact_mask_right: Optional[np.ndarray]
    therapy_amplitude_left: Optional[float] = None
    therapy_amplitude_right: Optional[float] = None
    therapy_frequency: Optional[float] = None
    hemisphere: str = "BOTH"

    @property
    def has_left_data(self) -> bool:
        """Check if left hemisphere data is available."""
        return self.psd_left is not None and len(self.psd_left) > 0

    @property
    def has_right_data(self) -> bool:
        """Check if right hemisphere data is available."""
        return self.psd_right is not None and len(self.psd_right) > 0

    @property
    def has_stimulation_info(self) -> bool:
        """Check if stimulation parameters are available."""
        return any([
            self.therapy_amplitude_left is not None,
            self.therapy_amplitude_right is not None,
            self.therapy_frequency is not None
        ])

    def get_psd_for_hemisphere(self, hemisphere: str) -> Optional[np.ndarray]:
        """Get PSD array for specified hemisphere."""
        if hemisphere.upper() == "LEFT":
            return self.psd_left
        elif hemisphere.upper() == "RIGHT":
            return self.psd_right
        return None

    def get_artifact_mask_for_hemisphere(self, hemisphere: str) -> Optional[np.ndarray]:
        """Get artifact mask for specified hemisphere."""
        if hemisphere.upper() == "LEFT":
            return self.artifact_mask_left
        elif hemisphere.upper() == "RIGHT":
            return self.artifact_mask_right
        return None


# ============================================================================
# PART 2: PSD DATASETS
# ============================================================================

@dataclass(frozen=True)
class SnapshotPsdDataset:
    """
    Collection of Snapshot PSD events for a patient.

    Provides methods for grouping, filtering, and extracting PSD matrices
    for statistical analysis.

    Attributes
    ----------
    patient_id : str
        Patient identifier
    events : List[SnapshotPsdEvent]
        All PSD events for this patient
    frequency_axis : np.ndarray
        Common frequency axis for all events
    bootstrap_service : BootstrapStatistics
        Service for calculating bootstrap confidence intervals (injected dependency)
    """
    patient_id: str
    events: List[SnapshotPsdEvent]
    frequency_axis: np.ndarray
    bootstrap_service: BootstrapStatistics = field(default_factory=BootstrapStatistics)

    def get_event_types(self) -> List[str]:
        """Get list of unique event types."""
        return list(set(event.event_name for event in self.events))

    def get_event_counts(self) -> Dict[str, int]:
        """Get count of events per type."""
        counts: Dict[str, int] = {}
        for event in self.events:
            counts[event.event_name] = counts.get(event.event_name, 0) + 1
        return counts

    def filter_by_event_type(self, event_type: str) -> List[SnapshotPsdEvent]:
        """Get all events of a specific type."""
        return [event for event in self.events if event.event_name == event_type]

    def filter_by_event_group(self, event_group: List[str]) -> List[SnapshotPsdEvent]:
        """Get all events matching any type in the group."""
        return [event for event in self.events if event.event_name in event_group]

    def filter_by_stimulation_state(self, require_matching: bool = True) -> List[SnapshotPsdEvent]:
        """Filter events based on stimulation state consistency."""
        if not require_matching:
            return self.events

        # Find reference stimulation state from first event with info
        ref_state = None
        for event in self.events:
            if event.has_stimulation_info:
                ref_state = (
                    event.therapy_amplitude_left,
                    event.therapy_amplitude_right,
                    event.therapy_frequency
                )
                break

        if ref_state is None:
            # No stimulation info available, return all
            return self.events

        # Filter for matching stimulation states
        filtered = []
        for event in self.events:
            if event.has_stimulation_info:
                state = (
                    event.therapy_amplitude_left,
                    event.therapy_amplitude_right,
                    event.therapy_frequency
                )
                if state == ref_state:
                    filtered.append(event)
            else:
                # Include events without stimulation info
                filtered.append(event)

        return filtered

    def get_psd_matrix(
        self,
        event_group: List[str],
        hemisphere: str,
        apply_artifact_mask: bool = True
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Get PSD matrix for a group of events.

        Parameters
        ----------
        event_group : List[str]
            Event types to include (e.g., ["Craving", "Drinking"])
        hemisphere : str
            Hemisphere to extract ("LEFT" or "RIGHT")
        apply_artifact_mask : bool
            Whether to apply artifact censoring (NaN for bad bins)

        Returns
        -------
        psd_matrix : np.ndarray
            Matrix of shape (n_events, n_frequencies) with raw PSD values (µV²/Hz)
        valid_mask : np.ndarray
            Boolean matrix indicating valid (non-NaN) values
        """
        events = self.filter_by_event_group(event_group)

        if not events:
            return np.array([]), np.array([])

        n_events = len(events)
        n_freqs = len(self.frequency_axis)
        psd_matrix = np.full((n_events, n_freqs), np.nan)

        for i, event in enumerate(events):
            psd = event.get_psd_for_hemisphere(hemisphere)
            if psd is not None and len(psd) == n_freqs:
                psd_matrix[i, :] = psd

                if apply_artifact_mask:
                    mask = event.get_artifact_mask_for_hemisphere(hemisphere)
                    if mask is not None:
                        # Apply mask (censored bins become NaN)
                        psd_matrix[i, mask] = np.nan

        # Create valid mask
        valid_mask = ~np.isnan(psd_matrix)

        return psd_matrix, valid_mask

    def get_group_median_psd(
        self,
        event_group: List[str],
        hemisphere: str,
        confidence_level: float = 0.95
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray, int]:
        """
        Get median PSD curve with bootstrap confidence intervals for an event group.

        Parameters
        ----------
        event_group : List[str]
            Event types to include
        hemisphere : str
            Hemisphere to analyze
        confidence_level : float
            Confidence level for bootstrap CIs (default 0.95 for 95% CI)

        Returns
        -------
        median_psd : np.ndarray
            Median PSD across events at each frequency (raw power in µV²/Hz)
        ci_lower : np.ndarray
            Lower bound of bootstrap confidence interval at each frequency
        ci_upper : np.ndarray
            Upper bound of bootstrap confidence interval at each frequency
        n_events : int
            Number of events contributing

        Notes
        -----
        Uses bootstrap percentile method for confidence intervals, which is
        appropriate for medians and does not assume normality of the data.
        This is consistent with using Mann-Whitney U test for group comparisons.
        """
        psd_matrix, valid_mask = self.get_psd_matrix(
            event_group, hemisphere
        )

        if psd_matrix.size == 0:
            return np.array([]), np.array([]), np.array([]), 0

        # Use bootstrap service to calculate median with CIs
        median_psd, ci_lower, ci_upper = self.bootstrap_service.calculate_median_ci_matrix(
            psd_matrix, confidence_level
        )

        n_events = psd_matrix.shape[0]

        return median_psd, ci_lower, ci_upper, n_events


# ============================================================================
# PART 3: FREQUENCY BAND DEFINITIONS
# ============================================================================

@dataclass(frozen=True)
class FrequencyBand:
    """
    Definition of a frequency band for analysis.

    Attributes
    ----------
    name : str
        Band name (e.g., "Beta", "Gamma_low")
    min_freq : float
        Lower frequency bound (Hz)
    max_freq : float
        Upper frequency bound (Hz)
    center_freqs : List[float]
        Percept-specific bin centers within this band
    """
    name: str
    min_freq: float
    max_freq: float
    center_freqs: List[float]

    @property
    def bandwidth(self) -> float:
        """Get band width in Hz."""
        return self.max_freq - self.min_freq

    def contains_frequency(self, freq: float) -> bool:
        """Check if frequency falls within band."""
        return self.min_freq <= freq <= self.max_freq

    def get_bin_indices(self, frequency_axis: np.ndarray, tolerance: float = 1e-3) -> np.ndarray:
        """
        Get indices of frequency bins within this band.

        Parameters
        ----------
        frequency_axis : np.ndarray
            Full frequency axis
        tolerance : float
            Tolerance for frequency matching

        Returns
        -------
        np.ndarray
            Boolean mask of bins within band
        """
        # Use range-based approach: include all frequencies within band limits
        # This is more flexible than looking for exact center frequencies
        mask = (frequency_axis >= self.min_freq) & (frequency_axis <= self.max_freq)
        return mask


class FrequencyBandDefinitions:
    """
    Standard frequency band definitions for Percept device.

    Based on 0.98 Hz resolution bins from 0.98 to 96.04 Hz.
    """

    @staticmethod
    def get_percept_bands() -> Dict[str, FrequencyBand]:
        """Get all standard Percept frequency bands."""
        return {
            "Timeline": FrequencyBand(
                name="Timeline",
                min_freq=5.31,
                max_freq=10.31,
                center_freqs=[5.88, 6.86, 7.84, 8.82, 9.80]
            ),
            "Delta": FrequencyBand(
                name="Delta",
                min_freq=1.0,
                max_freq=4.0,
                center_freqs=[1.96, 2.94, 3.92]
            ),
            "Theta": FrequencyBand(
                name="Theta",
                min_freq=4.0,
                max_freq=8.0,
                center_freqs=[4.90, 5.88, 6.86, 7.84]
            ),
            "Alpha": FrequencyBand(
                name="Alpha",
                min_freq=8.0,
                max_freq=13.0,
                center_freqs=[8.82, 9.80, 10.78, 11.76, 12.74]
            ),
            "Beta": FrequencyBand(
                name="Beta",
                min_freq=13.0,
                max_freq=30.0,
                center_freqs=[13.72, 14.70, 15.68, 16.66, 17.64, 18.62, 19.60,
                            20.58, 21.56, 22.54, 23.52, 24.50, 25.48, 26.46,
                            27.44, 28.42, 29.40]
            ),
            "Gamma_low": FrequencyBand(
                name="Gamma_low",
                min_freq=30.0,
                max_freq=40.0,
                center_freqs=[30.38, 31.36, 32.34, 33.32, 34.30, 35.28, 36.26,
                            37.24, 38.22, 39.20]
            ),
            "Gamma_high": FrequencyBand(
                name="Gamma_high",
                min_freq=50.0,
                max_freq=96.68,
                center_freqs=[50.96, 51.94, 52.92, 53.90, 54.88, 55.86, 56.84,
                            57.82, 58.80, 59.78, 60.76, 61.74, 62.72, 63.70,
                            64.68, 65.66, 66.64, 67.62, 68.60, 69.58, 70.56,
                            71.54, 72.52, 73.50, 74.48, 75.46, 76.44, 77.42,
                            78.40, 79.38, 80.36, 81.34, 82.32, 83.30, 84.28,
                            85.26, 86.24, 87.22, 88.20, 89.18, 90.16, 91.14,
                            92.12, 93.10, 94.08, 95.06, 96.04]
            )
        }

    @staticmethod
    def get_band(name: str) -> Optional[FrequencyBand]:
        """Get a specific frequency band by name."""
        bands = FrequencyBandDefinitions.get_percept_bands()
        return bands.get(name)