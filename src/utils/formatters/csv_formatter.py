"""
CSV formatter for snapshot timeline data.

Provides CSV output format suitable for spreadsheet analysis and data export.
"""

import csv
from io import StringIO
from typing import List

from src.core.models.snapshot_timeline import PatientTimeline


class CsvFormatter:
    """
    Format patient timeline data as CSV.

    Outputs a flat CSV structure with one row per snapshot event,
    including patient information, day grouping, and event metadata.

    CSV Columns:
        - patient_id: Patient identifier
        - date: Calendar date (YYYY-MM-DD)
        - day_of_year: Day number (1-366)
        - time: Time of day (HH:MM:SS)
        - event_name: Event classification
        - event_type: Event trigger type
        - hemisphere: Brain hemisphere
        - patient_triggered: Boolean (1=patient, 0=system)
        - source_file: Original data file

    Example:
        >>> formatter = CsvFormatter()
        >>> csv_output = formatter.format([timeline1, timeline2])
        >>> print(csv_output)
        patient_id,date,day_of_year,time,event_name,event_type,hemisphere,patient_triggered,source_file
        PATIENT001,2025-01-15,15,08:30:45,Craving,PatientTriggered,LEFT,1,session_001.json
    """

    HEADERS = [
        'patient_id',
        'date',
        'day_of_year',
        'time',
        'event_name',
        'event_type',
        'hemisphere',
        'patient_triggered',
        'source_file'
    ]

    def format(self, timelines: List[PatientTimeline]) -> str:
        """
        Format patient timelines as CSV.

        Args:
            timelines: List of patient timelines to format

        Returns:
            str: CSV-formatted string with headers

        Example:
            >>> timelines = service.get_all_timelines()
            >>> csv_data = formatter.format(timelines)
            >>> with open('output.csv', 'w') as f:
            ...     f.write(csv_data)
        """
        output = StringIO()
        writer = csv.DictWriter(output, fieldnames=self.HEADERS)

        # Write header
        writer.writeheader()

        # Write data rows
        for timeline in timelines:
            for day in timeline.days:
                for event in day.events:
                    writer.writerow({
                        'patient_id': timeline.patient_id,
                        'date': day.date.isoformat(),
                        'day_of_year': day.day_of_year,
                        'time': event.time_of_day.isoformat(),
                        'event_name': event.event_name or '',
                        'event_type': event.event_type or '',
                        'hemisphere': event.hemisphere or '',
                        'patient_triggered': 1 if event.patient_triggered else 0,
                        'source_file': event.source_file
                    })

        return output.getvalue()

    def format_to_file(self, timelines: List[PatientTimeline], file_path: str) -> None:
        """
        Format and write timelines directly to file.

        Args:
            timelines: List of patient timelines to format
            file_path: Path to output CSV file

        Example:
            >>> formatter.format_to_file(timelines, 'snapshots.csv')
        """
        csv_data = self.format(timelines)
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(csv_data)
