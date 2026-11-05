"""
ML domain models for craving classification.

Contains dataclasses for:
- MLDataset: Feature matrix with labels
- CompositeBiomarker: Full 15-feature weighted formula
- PerceptBiomarker: Single-band threshold for Percept device
"""

from src.ml.models.dataset import MLDataset
from src.ml.models.biomarker import CompositeBiomarker, PerceptBiomarker

__all__ = [
    "MLDataset",
    "CompositeBiomarker",
    "PerceptBiomarker",
]
