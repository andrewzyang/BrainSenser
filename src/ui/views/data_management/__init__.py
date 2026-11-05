"""
Data Management page and components.

Main page for patient and data management.

Modules:
    - data_management_page: Main page widget
    - components: Reusable UI components
"""

from .data_management_page import DataManagementPage
from .components import (
    StatisticsCard,
    PatientOverviewWidget
)

__all__ = [
    'DataManagementPage',
    'StatisticsCard',
    'PatientOverviewWidget',
]
