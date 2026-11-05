"""
Domain models for Timeline + Snapshots analysis.

This module provides immutable domain models for event-triggered LFP analysis:

Raw Data Models:
    - TimelineRecording: Single 10-minute power measurement
    - SnapshotEvent: Patient-triggered behavioral event

Synchronized Models:
    - TimelineWindow: ±120 minute window of Timeline data
    - SynchronizedEvent: Snapshot paired with Timeline window

Dataset Containers:
    - TimelineDataset: Collection of Timeline recordings
    - SnapshotDataset: Collection of Snapshot events
    - SynchronizedDataset: Collection of synchronized events

Statistical Result Models:
    - TimepointResult: Statistics for single time point
    - PeakInfo: Peak significance information
    - EventComparisonResult: Complete comparison results
"""

from .models import (
    # Raw data models
    TimelineRecording,
    SnapshotEvent,

    # Synchronized models
    TimelineWindow,
    SynchronizedEvent,

    # Dataset containers
    TimelineDataset,
    SnapshotDataset,
    SynchronizedDataset,

    # Statistical result models
    TimepointResult,
    PeakInfo,
    EventComparisonResult,
)

__all__ = [
    # Raw data models
    'TimelineRecording',
    'SnapshotEvent',

    # Synchronized models
    'TimelineWindow',
    'SynchronizedEvent',

    # Dataset containers
    'TimelineDataset',
    'SnapshotDataset',
    'SynchronizedDataset',

    # Statistical result models
    'TimepointResult',
    'PeakInfo',
    'EventComparisonResult',
]
