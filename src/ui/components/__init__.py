"""
UI Components - App-level reusable components.

Components:
    - Sidebar: Navigation sidebar with menu items
    - TopBar: Top bar with patient dropdown and action buttons
    - Badge: Badge component for labels and tags
    - BaseGroupingPanel: Abstract base class for grouping panels
    - EmptyStateWidget: Shared no-patient-selected placeholder
    - MlProgressDialog: Shared modal progress popup for ML pages
    - FileOrDirectoryDialog: Open dialog accepting a single file OR a directory
    - RestartBanner: Interface-size notice under the top bar (restart, D2 suggestion)
"""

from .sidebar import Sidebar
from .top_bar import TopBar
from .badge import Badge
from .base_grouping_panel import BaseGroupingPanel
from .empty_state import EmptyStateWidget
from .ml_progress_dialog import MlProgressDialog
from .file_or_directory_dialog import FileOrDirectoryDialog
from .restart_banner import RestartBanner

__all__ = [
    'Sidebar',
    'TopBar',
    'Badge',
    'BaseGroupingPanel',
    'EmptyStateWidget',
    'MlProgressDialog',
    'FileOrDirectoryDialog',
    'RestartBanner',
]
