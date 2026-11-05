"""
UI layer for the iEEG BrainSense Analysis App.

Provides:
- Shadcn-inspired design system (theme, components)
- Application-level components (Sidebar, TopBar)
- ViewModels for MVVM architecture
- View layouts and pages

Usage:
    from src.ui import Theme, Button, Input, Card
    from src.ui.components import Sidebar, TopBar
    from src.ui.viewmodels import AppViewModel
"""

from .theme import Theme, Colors

__all__ = [
    'Theme',
    'Colors',
]
