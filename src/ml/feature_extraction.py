"""
Feature extraction from Snapshot PSD data for ML classification.

Extracts 15 features per event:
- 5 band powers (Left): Delta, Theta, Alpha, Beta, Gamma (log-transformed)
- 5 band powers (Right): Delta, Theta, Alpha, Beta, Gamma (log-transformed)
- 5 asymmetry ratios: (Left - Right) / (Left + Right) per band

Author: iEEG BrainSense Development Team
"""

import logging
from typing import List, Tuple, Optional, Dict
from dataclasses import dataclass
import numpy as np
from scipy import integrate

from src.domain.psd_models import (
    SnapshotPsdDataset,
    SnapshotPsdEvent,
    FrequencyBandDefinitions,
    FrequencyBand,
)
from src.ml.models.dataset import MLDataset


logger = logging.getLogger(__name__)


# Canonical frequency bands for ML features
ML_FEATURE_BANDS = ("Delta", "Theta", "Alpha", "Beta", "Gamma_low")

# Event type mappings for binary classification
# Uses substring matching to handle combined types like "Neutral/Happy", "Anxious/Sad"
CRAVING_KEYWORDS = ["Craving", "Drinking"]
NON_CRAVING_KEYWORDS = ["Happy", "Neutral"]  # Clean comparison: craving vs neutral/happy baseline


@dataclass
class BandPowerFeatures:
    """
    Extracted band powers for a single event.

    Attributes
    ----------
    left_powers : Dict[str, float]
        Band name -> log power for left hemisphere
    right_powers : Dict[str, float]
        Band name -> log power for right hemisphere
    asymmetries : Dict[str, float]
        Band name -> asymmetry ratio
    has_valid_data : bool
        Whether extraction succeeded for both hemispheres
    """

    left_powers: Dict[str, float]
    right_powers: Dict[str, float]
    asymmetries: Dict[str, float]
    has_valid_data: bool


class SnapshotPsdFeatureExtractor:
    """
    Extract ML features from Snapshot PSD data.

    Converts raw 98-bin bilateral PSD spectra into 15 ML-ready features:
    - Band powers are integrated using trapezoidal rule
    - Powers are log-transformed for normalization
    - Asymmetry ratios quantify hemispheric differences

    Parameters
    ----------
    bands : Optional[Tuple[str, ...]]
        Frequency bands to use (default: Delta, Theta, Alpha, Beta, Gamma_low)
    craving_keywords : Optional[List[str]]
        Keywords to match for craving label (y=1). Matches if any keyword
        is contained in event name (e.g., "Craving" matches "Craving/Drinking")
    non_craving_keywords : Optional[List[str]]
        Keywords to match for non-craving label (y=0)
    min_valid_fraction : float
        Minimum fraction of valid bins required per band (default: 0.5)

    Example
    -------
    >>> from src.ml.feature_extraction import SnapshotPsdFeatureExtractor
    >>> from src.infrastructure.psd_data_loader import load_snapshot_psd_dataset
    >>>
    >>> extractor = SnapshotPsdFeatureExtractor()
    >>> psd_dataset = load_snapshot_psd_dataset("PT2", records)
    >>> ml_dataset = extractor.extract(psd_dataset)
    >>> print(ml_dataset)
    MLDataset(patient=PT2, samples=107, features=15, craving=45, non_craving=62)
    """

    def __init__(
        self,
        bands: Optional[Tuple[str, ...]] = None,
        craving_keywords: Optional[List[str]] = None,
        non_craving_keywords: Optional[List[str]] = None,
        min_valid_fraction: float = 0.5,
    ):
        self.band_names = bands or ML_FEATURE_BANDS
        self.craving_keywords = craving_keywords or CRAVING_KEYWORDS
        self.non_craving_keywords = non_craving_keywords or NON_CRAVING_KEYWORDS

        self.min_valid_fraction = min_valid_fraction

        # Load frequency band definitions
        all_bands = FrequencyBandDefinitions.get_percept_bands()
        self.bands: Dict[str, FrequencyBand] = {
            name: all_bands[name]
            for name in self.band_names
            if name in all_bands
        }

        if not self.bands:
            raise ValueError(f"No valid bands found from {self.band_names}")

        # Build feature names
        self.feature_names = self._build_feature_names()

        logger.info(
            f"SnapshotPsdFeatureExtractor initialized with {len(self.bands)} bands, "
            f"{len(self.feature_names)} features"
        )

    def _build_feature_names(self) -> List[str]:
        """
        Build ordered list of feature names.

        Returns
        -------
        List[str]
            Feature names in order: Left powers, Right powers
        """
        names = []

        # Left hemisphere band powers
        for band_name in self.band_names:
            if band_name in self.bands:
                display_name = band_name.replace("_low", "").replace("_high", "")
                names.append(f"{display_name}_Left")

        # Right hemisphere band powers
        for band_name in self.band_names:
            if band_name in self.bands:
                display_name = band_name.replace("_low", "").replace("_high", "")
                names.append(f"{display_name}_Right")

        return names

    def extract(self, dataset: SnapshotPsdDataset) -> MLDataset:
        """
        Extract ML features from a Snapshot PSD dataset.

        Parameters
        ----------
        dataset : SnapshotPsdDataset
            Raw PSD dataset for a patient

        Returns
        -------
        MLDataset
            Feature matrix with labels ready for classification

        Raises
        ------
        ValueError
            If dataset contains no valid events for either class
        """
        features_list = []
        labels_list = []
        timestamps_list = []

        for event in dataset.events:
            # Determine label
            label = self._get_event_label(event.event_name)
            if label is None:
                # Skip events not in either group
                continue

            # Extract features
            band_features = self._extract_event_features(event, dataset.frequency_axis)
            if not band_features.has_valid_data:
                logger.debug(
                    f"Skipping event {event.event_name} at {event.timestamp}: "
                    "insufficient valid data"
                )
                continue

            # Build feature vector in consistent order
            feature_vector = self._build_feature_vector(band_features)
            features_list.append(feature_vector)
            labels_list.append(label)
            timestamps_list.append(event.timestamp)

        if not features_list:
            raise ValueError(
                f"No valid events extracted from dataset for patient {dataset.patient_id}"
            )

        X = np.array(features_list)
        y = np.array(labels_list)

        n_craving = int(np.sum(y == 1))
        n_non_craving = int(np.sum(y == 0))

        logger.info(
            f"Extracted {X.shape[0]} events ({n_craving} craving, {n_non_craving} non-craving) "
            f"with {X.shape[1]} features for patient {dataset.patient_id}"
        )

        return MLDataset(
            X=X,
            y=y,
            feature_names=self.feature_names,
            patient_id=dataset.patient_id,
            event_timestamps=timestamps_list,
        )

    def _get_event_label(self, event_name: str) -> Optional[int]:
        """
        Get binary label for an event type using keyword matching.

        Handles combined event types like "Neutral/Happy" or "Anxious/Sad"
        by checking if any keyword is contained in the event name.

        Parameters
        ----------
        event_name : str
            Event type name

        Returns
        -------
        Optional[int]
            1 for craving, 0 for non-craving, None if not in either group
        """
        # Check for craving keywords first (takes priority)
        for keyword in self.craving_keywords:
            if keyword in event_name:
                return 1

        # Check for non-craving keywords
        for keyword in self.non_craving_keywords:
            if keyword in event_name:
                return 0

        return None

    def _extract_event_features(
        self,
        event: SnapshotPsdEvent,
        frequency_axis: np.ndarray,
    ) -> BandPowerFeatures:
        """
        Extract band power features from a single event.

        Parameters
        ----------
        event : SnapshotPsdEvent
            Single PSD event
        frequency_axis : np.ndarray
            Frequency axis for the dataset

        Returns
        -------
        BandPowerFeatures
            Extracted features for this event
        """
        left_powers: Dict[str, float] = {}
        right_powers: Dict[str, float] = {}
        asymmetries: Dict[str, float] = {}
        has_valid_data = True

        # Use event's own frequency axis if available
        freq_axis = event.frequency_axis if event.frequency_axis is not None else frequency_axis

        for band_name, band_def in self.bands.items():
            # Extract left hemisphere power
            left_power = self._integrate_band_power(
                freq_axis,
                event.psd_left,
                event.artifact_mask_left,
                band_def,
            )

            # Extract right hemisphere power
            right_power = self._integrate_band_power(
                freq_axis,
                event.psd_right,
                event.artifact_mask_right,
                band_def,
            )

            # Check validity
            if left_power is None or right_power is None:
                has_valid_data = False
                # Use NaN as placeholder
                left_powers[band_name] = np.nan
                right_powers[band_name] = np.nan
                asymmetries[band_name] = np.nan
                continue

            # Log-transform powers
            left_log = np.log(left_power + 1e-10)  # Add small epsilon to avoid log(0)
            right_log = np.log(right_power + 1e-10)

            left_powers[band_name] = left_log
            right_powers[band_name] = right_log

            # Compute asymmetry ratio
            # (Left - Right) / (Left + Right) in linear space for interpretability
            total_power = left_power + right_power
            if total_power > 0:
                asymmetry = (left_power - right_power) / total_power
            else:
                asymmetry = 0.0

            asymmetries[band_name] = asymmetry

        return BandPowerFeatures(
            left_powers=left_powers,
            right_powers=right_powers,
            asymmetries=asymmetries,
            has_valid_data=has_valid_data,
        )

    def _integrate_band_power(
        self,
        frequency_axis: np.ndarray,
        psd: Optional[np.ndarray],
        artifact_mask: Optional[np.ndarray],
        band: FrequencyBand,
    ) -> Optional[float]:
        """
        Integrate power within a frequency band.

        Uses trapezoidal integration over valid bins, handling NaN values
        from artifact censoring.

        Parameters
        ----------
        frequency_axis : np.ndarray
            Frequency axis
        psd : Optional[np.ndarray]
            Power spectral density array
        artifact_mask : Optional[np.ndarray]
            Boolean mask where True indicates artifact (censored)
        band : FrequencyBand
            Band definition to integrate

        Returns
        -------
        Optional[float]
            Integrated band power in μV², or None if insufficient data
        """
        if psd is None or len(psd) == 0:
            return None

        # Get bin indices for this band
        bin_mask = band.get_bin_indices(frequency_axis)
        if not np.any(bin_mask):
            return None

        # Extract band data
        band_freqs = frequency_axis[bin_mask]
        band_psd = psd[bin_mask].copy()

        # Apply artifact mask if available
        if artifact_mask is not None and len(artifact_mask) == len(psd):
            band_artifacts = artifact_mask[bin_mask]
            band_psd[band_artifacts] = np.nan

        # Check valid fraction
        valid_mask = ~np.isnan(band_psd)
        valid_fraction = np.sum(valid_mask) / len(band_psd)

        if valid_fraction < self.min_valid_fraction:
            return None

        # Need at least 2 points for integration
        if np.sum(valid_mask) < 2:
            return None

        # Integrate using trapezoidal rule over valid points
        valid_freqs = band_freqs[valid_mask]
        valid_psd = band_psd[valid_mask]

        return integrate.trapezoid(valid_psd, valid_freqs)

    def _build_feature_vector(self, band_features: BandPowerFeatures) -> np.ndarray:
        """
        Build ordered feature vector from band features.

        Parameters
        ----------
        band_features : BandPowerFeatures
            Extracted band features

        Returns
        -------
        np.ndarray
            Feature vector in consistent order
        """
        features = []

        # Left hemisphere powers
        for band_name in self.band_names:
            if band_name in self.bands:
                features.append(band_features.left_powers.get(band_name, np.nan))

        # Right hemisphere powers
        for band_name in self.band_names:
            if band_name in self.bands:
                features.append(band_features.right_powers.get(band_name, np.nan))

        return np.array(features)

    def get_feature_names(self) -> List[str]:
        """Get list of feature names in order."""
        return self.feature_names.copy()

    def get_band_for_feature(self, feature_name: str) -> Tuple[str, str]:
        """
        Parse feature name into band and hemisphere/type.

        Parameters
        ----------
        feature_name : str
            Feature name like "Beta_Left" or "Theta_Asym"

        Returns
        -------
        Tuple[str, str]
            (band_name, hemisphere_or_type) like ("Beta", "Left")
        """
        parts = feature_name.rsplit("_", 1)
        if len(parts) == 2:
            return parts[0], parts[1]
        return feature_name, ""
