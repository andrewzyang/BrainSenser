"""
ViewModels for UI layer.

ViewModels implement the MVVM pattern, coordinating between UI widgets
and the service layer. They manage UI state and emit signals for updates.

ViewModels:
    - AppViewModel: Application-level state (patient selection)
    - DataManagementViewModel: Coordinates Data Management page
    - SplashViewModel: Drives the startup splash screen lifecycle
    - ShellViewModel: Sidebar mode and window placement
    - UiScaleViewModel: Interface size per display
"""

from .app_viewmodel import AppViewModel
from .data_management_viewmodel import DataManagementViewModel
from .splash_viewmodel import SplashViewModel
from .shell_viewmodel import ShellViewModel
from .ui_scale_viewmodel import UiScaleViewModel

__all__ = [
    'AppViewModel',
    'DataManagementViewModel',
    'SplashViewModel',
    'ShellViewModel',
    'UiScaleViewModel',
]
