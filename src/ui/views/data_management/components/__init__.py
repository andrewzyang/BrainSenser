"""
Components for Data Management page.

Reusable UI components used in the Data Management page.

Components:
    - StatisticsCard: Reusable card for displaying statistics
    - PatientOverviewWidget: Overview widget with statistics cards
    - PatientMetadataPanel: Panel for displaying patient and device metadata
    - UploadHistoryTable: Table widget for displaying upload history
"""

from .statistics_card import StatisticsCard
from .patient_overview import PatientOverviewWidget
from .patient_metadata_panel import PatientMetadataPanel
from .upload_history_table import UploadHistoryTable

__all__ = [
    'StatisticsCard',
    'PatientOverviewWidget',
    'PatientMetadataPanel',
    'UploadHistoryTable',
]
