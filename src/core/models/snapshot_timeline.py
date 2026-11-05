"""
Domain models for snapshot timeline analysis.

These immutable models represent the temporal organization of patient snapshots,
grouped by day with preserved timing and metadata.
"""

from dataclasses import dataclass
from datetime import date, time, datetime
from typing import Optional
from enum import Enum


class Hemisphere(str, Enum):
    """Brain hemisphere identifier."""
    LEFT = "LEFT"
    RIGHT = "RIGHT"
    BOTH = "BOTH"


@dataclass(frozen=True)
class SnapshotEvent:
    """
    Single snapshot event with metadata.

    Represents one frequency-domain snapshot capture with timing,
    event classification, and hemisphere information.
    """
    timestamp: datetime
    time_of_day: time
    event_name: Optional[str]
    event_type: Optional[str]
    hemisphere: Optional[str]
    patient_triggered: bool
    source_file: str

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            'timestamp': self.timestamp.isoformat(),
            'time_of_day': self.time_of_day.isoformat(),
            'event_name': self.event_name or '',
            'event_type': self.event_type or '',
            'hemisphere': self.hemisphere or '',
            'patient_triggered': self.patient_triggered,
            'source_file': self.source_file
        }


@dataclass(frozen=True)
class DaySnapshots:
    """
    All snapshots for a specific day.

    Groups snapshot events by calendar day with day-of-year calculation
    and basic statistics.
    """
    date: date
    day_of_year: int
    events: tuple  # tuple[SnapshotEvent, ...] - immutable

    @property
    def count(self) -> int:
        """Total number of snapshots for this day."""
        return len(self.events)

    @property
    def patient_triggered_count(self) -> int:
        """Number of patient-triggered snapshots."""
        return sum(1 for e in self.events if e.patient_triggered)

    @property
    def system_triggered_count(self) -> int:
        """Number of system-triggered snapshots."""
        return sum(1 for e in self.events if not e.patient_triggered)

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            'date': self.date.isoformat(),
            'day_of_year': self.day_of_year,
            'count': self.count,
            'patient_triggered_count': self.patient_triggered_count,
            'system_triggered_count': self.system_triggered_count,
            'events': [e.to_dict() for e in self.events]
        }


@dataclass(frozen=True)
class PatientTimeline:
    """
    Complete timeline for a patient.

    Aggregates all snapshot data organized by day with summary statistics
    and date range information.
    """
    patient_id: str
    days: tuple  # tuple[DaySnapshots, ...] - immutable, sorted by date
    total_snapshots: int
    date_range: Optional[tuple]  # tuple[date, date] - (first, last)

    @property
    def total_days(self) -> int:
        """Number of days with recorded snapshots."""
        return len(self.days)

    @property
    def average_snapshots_per_day(self) -> float:
        """Average number of snapshots per day."""
        if self.total_days == 0:
            return 0.0
        return self.total_snapshots / self.total_days

    @property
    def total_patient_triggered(self) -> int:
        """Total number of patient-triggered snapshots."""
        return sum(day.patient_triggered_count for day in self.days)

    @property
    def total_system_triggered(self) -> int:
        """Total number of system-triggered snapshots."""
        return sum(day.system_triggered_count for day in self.days)

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            'patient_id': self.patient_id,
            'total_snapshots': self.total_snapshots,
            'total_days': self.total_days,
            'average_snapshots_per_day': self.average_snapshots_per_day,
            'total_patient_triggered': self.total_patient_triggered,
            'total_system_triggered': self.total_system_triggered,
            'date_range': {
                'start': self.date_range[0].isoformat() if self.date_range else None,
                'end': self.date_range[1].isoformat() if self.date_range else None
            } if self.date_range else None,
            'days': [day.to_dict() for day in self.days]
        }
