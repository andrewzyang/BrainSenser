"""
ML Dataset model for feature matrices and labels.

Author: iEEG BrainSense Development Team
"""

from dataclasses import dataclass
from typing import List, Optional
import numpy as np


@dataclass(frozen=True)
class MLDataset:
    """
    Feature matrix with labels for ML classification.

    Contains extracted features from Snapshot PSD data ready for
    classifier training. Features are 15-dimensional:
    - 5 band powers (Left): Delta, Theta, Alpha, Beta, Gamma
    - 5 band powers (Right): Delta, Theta, Alpha, Beta, Gamma
    - 5 asymmetry ratios: (Left - Right) / (Left + Right) per band

    All band powers are log-transformed for normalization.

    Attributes
    ----------
    X : np.ndarray
        Feature matrix of shape (n_samples, n_features)
    y : np.ndarray
        Binary labels (1 = craving, 0 = non-craving)
    feature_names : List[str]
        Names for each feature column
    patient_id : str
        Patient identifier
    event_timestamps : Optional[List]
        Timestamps of each sample (for tracking)
    """

    X: np.ndarray
    y: np.ndarray
    feature_names: List[str]
    patient_id: str
    event_timestamps: Optional[List] = None

    @property
    def n_samples(self) -> int:
        """Number of samples in the dataset."""
        return self.X.shape[0]

    @property
    def n_features(self) -> int:
        """Number of features per sample."""
        return self.X.shape[1]

    @property
    def n_craving(self) -> int:
        """Number of craving samples (y=1)."""
        return int(np.sum(self.y == 1))

    @property
    def n_non_craving(self) -> int:
        """Number of non-craving samples (y=0)."""
        return int(np.sum(self.y == 0))

    @property
    def class_balance(self) -> float:
        """Ratio of craving to non-craving samples."""
        if self.n_non_craving == 0:
            return float("inf")
        return self.n_craving / self.n_non_craving

    @property
    def is_valid_for_training(self) -> bool:
        """
        Check if dataset has sufficient samples for training.

        Requires at least 3 samples per class for stratified k-fold CV.
        """
        return self.n_craving >= 3 and self.n_non_craving >= 3

    def get_feature_index(self, feature_name: str) -> int:
        """Get column index for a feature by name."""
        try:
            return self.feature_names.index(feature_name)
        except ValueError:
            raise KeyError(f"Feature '{feature_name}' not found in dataset")

    def __repr__(self) -> str:
        return (
            f"MLDataset(patient={self.patient_id}, "
            f"samples={self.n_samples}, features={self.n_features}, "
            f"craving={self.n_craving}, non_craving={self.n_non_craving})"
        )
