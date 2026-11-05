"""
Preprocessing modules for BrainSense data.

This package contains preprocessing modules that clean and correct
BrainSense data during the upload workflow.

Modules:
    - OvervoltagePreprocessor: Corrects overvoltage events in timeline data
    - CardiacArtifactRemoval: Removes ECG/QRS artifacts from streaming data
    - SignalIntegrityCleaner: Repairs NaNs/frozen segments in streaming data
    - cardiac_qc: Quality control and validation functions for cardiac removal
"""

from .overvoltage_preprocessor import OvervoltagePreprocessor
from .cardiac_artifact_removal import CardiacArtifactRemoval, validate_cardiac_removal
from .cardiac_qc import (
    compute_qc_metrics,
    generate_qc_report,
    bootstrap_validation,
    assess_signal_integrity
)
from .signal_integrity_cleaner import SignalIntegrityCleaner, SignalIntegrityConfig

__all__ = [
    'OvervoltagePreprocessor',
    'CardiacArtifactRemoval',
    'validate_cardiac_removal',
    'SignalIntegrityCleaner',
    'SignalIntegrityConfig',
    'compute_qc_metrics',
    'generate_qc_report',
    'bootstrap_validation',
    'assess_signal_integrity'
]
