"""
Biomarker models for craving prediction.

Provides two biomarker types:
1. CompositeBiomarker: Full 15-feature weighted formula (research/future)
2. PerceptBiomarker: Single-band threshold for Percept device (practical/now)

Author: iEEG BrainSense Development Team
"""

from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional
import numpy as np


@dataclass(frozen=True)
class CompositeBiomarker:
    """
    Full composite biomarker with 15-feature weighted formula.

    Demonstrates craving's distributed neural signature using all
    extracted features. Provides weighted coefficients that can be
    used for probability estimation:

        Score = w1*Delta_L + w2*Theta_L + ... + intercept
        P(craving) = sigmoid(Score)

    Attributes
    ----------
    feature_weights : Dict[str, float]
        Feature name -> coefficient weight mapping
    intercept : float
        Model intercept (bias term)
    feature_importances : Dict[str, float]
        Feature name -> importance score (absolute weight or RF importance)
    ranked_features : List[Tuple[str, float]]
        Features sorted by importance (descending)
    classifier_type : str
        Type of classifier used (logistic_regression, linear_svm, random_forest)
    """

    feature_weights: Dict[str, float]
    intercept: float
    feature_importances: Dict[str, float]
    ranked_features: List[Tuple[str, float]]
    classifier_type: str

    @property
    def top_feature(self) -> Tuple[str, float]:
        """Get the most important feature and its importance."""
        return self.ranked_features[0] if self.ranked_features else ("", 0.0)

    @property
    def formula_string(self) -> str:
        """
        Generate human-readable formula string.

        Returns
        -------
        str
            Formula like: Score = 0.42*Beta_Left - 0.28*Alpha_Right + ...
        """
        terms = []
        for feature, importance in self.ranked_features[:5]:  # Top 5 for readability
            weight = self.feature_weights.get(feature, 0.0)
            sign = "+" if weight >= 0 else "-"
            terms.append(f"{sign} {abs(weight):.3f}*{feature}")

        formula = "Score = " + " ".join(terms)
        if self.intercept != 0:
            sign = "+" if self.intercept >= 0 else "-"
            formula += f" {sign} {abs(self.intercept):.3f}"

        return formula

    def predict_score(self, features: Dict[str, float]) -> float:
        """
        Calculate raw biomarker score for given features.

        Parameters
        ----------
        features : Dict[str, float]
            Feature name -> value mapping

        Returns
        -------
        float
            Raw score (higher = more likely craving)
        """
        score = self.intercept
        for feature_name, weight in self.feature_weights.items():
            if feature_name in features:
                score += weight * features[feature_name]
        return score

    def predict_probability(self, features: Dict[str, float]) -> float:
        """
        Calculate probability of craving state.

        Parameters
        ----------
        features : Dict[str, float]
            Feature name -> value mapping

        Returns
        -------
        float
            Probability of craving (0 to 1)
        """
        score = self.predict_score(features)
        return 1 / (1 + np.exp(-score))


@dataclass(frozen=True)
class PerceptBiomarker:
    """
    Single-band biomarker for Percept device deployment.

    Extracts the top-performing single frequency band that can be
    monitored using the Percept device's limited streaming capabilities.

    Attributes
    ----------
    band_name : str
        Frequency band name (Delta, Theta, Alpha, Beta, Gamma)
    hemisphere : str
        Hemisphere to monitor (Left, Right, or Bilateral)
    importance : float
        Importance score of this band
    weight : float
        Coefficient weight (positive = higher power predicts craving)
    threshold : float
        Recommended power threshold (log-transformed μV²)
    threshold_probability : float
        Probability of craving at threshold (typically 0.5 or 0.7)
    direction : str
        Threshold direction: "above" or "below" predicts craving
    sensitivity : float
        Estimated sensitivity at threshold (if available)
    specificity : float
        Estimated specificity at threshold (if available)
    """

    band_name: str
    hemisphere: str
    importance: float
    weight: float
    threshold: float
    threshold_probability: float = 0.5
    direction: str = "above"
    sensitivity: Optional[float] = None
    specificity: Optional[float] = None

    @property
    def clinical_recommendation(self) -> str:
        """
        Generate clinical recommendation string.

        Returns
        -------
        str
            Recommendation like: "Monitor Beta band, Left hemisphere"
        """
        return f"Monitor {self.band_name} band, {self.hemisphere} hemisphere"

    @property
    def threshold_description(self) -> str:
        """
        Generate threshold description string.

        Returns
        -------
        str
            Description like: "Threshold: 2.3 μV² (P(craving) > 0.7)"
        """
        return (
            f"Threshold: {np.exp(self.threshold):.2f} μV² "
            f"(P(craving) > {self.threshold_probability:.1f})"
        )

    @property
    def full_recommendation(self) -> str:
        """
        Generate full clinical recommendation.

        Returns
        -------
        str
            Full recommendation with threshold and metrics
        """
        lines = [
            self.clinical_recommendation,
            self.threshold_description,
        ]
        if self.sensitivity is not None and self.specificity is not None:
            lines.append(
                f"Sensitivity: {self.sensitivity:.1%}, "
                f"Specificity: {self.specificity:.1%}"
            )
        return "\n".join(lines)


@dataclass
class BiomarkerPair:
    """
    Container for both composite and Percept biomarkers.

    Groups the dual biomarker delivery for a patient model.

    Attributes
    ----------
    composite : CompositeBiomarker
        Full 15-feature research biomarker
    percept : PerceptBiomarker
        Single-band clinical biomarker
    patient_id : str
        Patient identifier
    classifier_type : str
        Classifier that generated these biomarkers
    """

    composite: CompositeBiomarker
    percept: PerceptBiomarker
    patient_id: str
    classifier_type: str
