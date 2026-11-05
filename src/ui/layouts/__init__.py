"""
UI Layouts - Layout coordinators for app structure.

Layouts:
    - MainLayout: Main app layout (Sidebar + TopBar + Content)
    - PageHost: Vertical scroll fallback around each page
    - ResponsiveContext: The window's layout classes, pushed to the pages
"""

from .main_layout import MainLayout
from .page_host import PageHost
from .responsive_context import ResponsiveContext

__all__ = [
    'MainLayout',
    'PageHost',
    'ResponsiveContext',
]
