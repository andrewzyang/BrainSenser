"""
DataManagementPage - Data Management page content.

This page displays patient data overview and statistics.
It does NOT contain the top bar or patient dropdown - those are in the
app-level layout (MainLayout with TopBar).

This page responds to AppViewModel patient selection signals.

Author: iEEG BrainSense Development Team
Last Updated: 2025-10-01
"""

from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QStackedLayout, QSpacerItem, QSizePolicy, QMessageBox
)
from PySide6.QtCore import Qt, QSize

from src.ui.viewmodels import DataManagementViewModel
from src.ui.components import EmptyStateWidget
from src.ui.components.dialog_fit import show_message
from src.ui.policy.layout import Density, HeightClass
from src.ui.policy.tokens import Dim, Space
from .components import PatientOverviewWidget

# The page's margins by density: regular is today's; with the overview's own
# margins, compact leaves 16 px at the sides and the bottom and 12 at the top.
_PAGE_MARGIN = {HeightClass.REGULAR: Space.X8, HeightClass.COMPACT: Space.X2}


class _CurrentPageLayout(QStackedLayout):
    """A stacked layout sized by its current page alone.

    QStackedLayout reports the largest minimum and height-for-width of all its
    pages, hidden ones included, so the hidden patient overview would make the
    empty state's page tall enough to scroll.
    """

    def _current(self):
        return self.itemAt(self.currentIndex())

    def sizeHint(self) -> QSize:
        item = self._current()
        return item.sizeHint() if item is not None else QSize(0, 0)

    def minimumSize(self) -> QSize:
        item = self._current()
        return item.minimumSize() if item is not None else QSize(0, 0)

    def hasHeightForWidth(self) -> bool:
        item = self._current()
        return item is not None and item.hasHeightForWidth()

    def heightForWidth(self, width: int) -> int:
        item = self._current()
        return item.heightForWidth(width) if item is not None else -1


class DataManagementPage(QWidget):
    """
    Data Management page content widget.

    Shows:
    - Empty state when no patient selected
    - Patient overview with statistics when patient selected

    The page responds to signals from DataManagementViewModel,
    which in turn listens to AppViewModel for patient selection.
    Its gutters follow the window's density (apply_density).

    Example:
        >>> page = DataManagementPage(data_management_viewmodel)
        >>> # Patient selection happens via AppViewModel -> DataManagementViewModel
        >>> # This page just displays the content
    """

    def __init__(self, viewmodel: DataManagementViewModel, parent=None):
        """
        Initialize DataManagementPage.

        Args:
            viewmodel: DataManagementViewModel instance
            parent: Parent widget (optional)
        """
        super().__init__(parent)
        self._viewmodel = viewmodel
        self.viewmodel = viewmodel  # Backward-compatible attribute for tests/tools

        # Track signal connections for cleanup
        self._signal_connections = []

        self._setup_ui()
        self._connect_signals()

    def _setup_ui(self):
        """Setup the UI layout and widgets."""
        # Main layout: the content column fills the page up to
        # Dim.CONTENT_MAX_W and is centred on wider pages, where the two
        # spacers share the width beyond it
        layout = QHBoxLayout(self)
        margin = _PAGE_MARGIN[HeightClass.REGULAR]
        layout.setContentsMargins(margin, margin, margin, margin)
        layout.setSpacing(0)

        # Content area: one page at a time, sized by the page it shows
        self.content_stack = QWidget()
        self.content_stack.setMaximumWidth(Dim.CONTENT_MAX_W)
        self.content_stack.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._pages = _CurrentPageLayout(self.content_stack)

        # Empty state (index 0)
        self.empty_state = EmptyStateWidget()
        self._pages.addWidget(self.empty_state)

        # Patient overview (index 1)
        self.patient_overview = PatientOverviewWidget()
        self._pages.addWidget(self.patient_overview)

        # Start with empty state
        self._pages.setCurrentIndex(0)

        # Preferred spacers take width only once the expanding column is capped
        layout.addSpacerItem(QSpacerItem(0, 0, QSizePolicy.Policy.Preferred))
        layout.addWidget(self.content_stack)
        layout.addSpacerItem(QSpacerItem(0, 0, QSizePolicy.Policy.Preferred))

        # Set background
        self.setStyleSheet("""
            DataManagementPage {
                background-color: #ffffff;
            }
        """)

    def _connect_signals(self):
        """
        Connect ViewModel signals to UI slots with proper cleanup tracking.

        Uses Qt.UniqueConnection to prevent duplicate connections and tracks
        all connections for proper cleanup in closeEvent.
        """
        # Define all signal-slot pairs
        connections = [
            (self._viewmodel.patient_selected, self._on_patient_selected),
            (self._viewmodel.patient_cleared, self._on_patient_cleared),
            (self._viewmodel.metadata_updated, self._on_metadata_updated),
            (self._viewmodel.statistics_updated, self._on_statistics_updated),
            (self._viewmodel.upload_history_updated, self._on_upload_history_updated),
            (self._viewmodel.error_occurred, self._on_error),
            (self._viewmodel.success_message, self._on_success),
        ]

        # Connect with UniqueConnection flag and track for cleanup
        for signal, slot in connections:
            signal.connect(slot, Qt.UniqueConnection)
            self._signal_connections.append((signal, slot))

    def apply_density(self, density: Density) -> None:
        """
        Adapt the page's gutters to the window's density (DensityAware).

        Args:
            density: The window's density, pushed by the ResponsiveContext
        """
        margin = _PAGE_MARGIN[density.height]
        self.layout().setContentsMargins(margin, margin, margin, margin)
        self.patient_overview.apply_density(density)

    # ========================================================================
    # Signal Handlers - ViewModel
    # ========================================================================

    def _on_patient_selected(self, patient):
        """
        Handle patient selected signal.

        Args:
            patient: Patient object
        """
        # Switch to overview
        self._pages.setCurrentIndex(1)

    def _on_patient_cleared(self):
        """Handle patient selection cleared."""
        # Clear patient overview
        self.patient_overview.clear()

        # Switch to empty state
        self._pages.setCurrentIndex(0)

    def _on_metadata_updated(self, metadata: dict):
        """
        Handle metadata updated signal.

        Args:
            metadata: Patient metadata dictionary
        """
        self.patient_overview.update_metadata(metadata)

    def _on_statistics_updated(self, statistics):
        """
        Handle statistics updated signal.

        Args:
            statistics: PatientStatistics object
        """
        self.patient_overview.update_statistics(statistics)

    def _on_upload_history_updated(self, uploads):
        """
        Handle upload history updated signal.

        Args:
            uploads: List[UploadedFile]
        """
        self.patient_overview.update_upload_history(uploads)

    def _on_error(self, error_message: str):
        """
        Handle error signal.

        Args:
            error_message: Error message to display
        """
        show_message(self, QMessageBox.Icon.Critical, "Error", error_message)

    def _on_success(self, success_message: str):
        """
        Handle success signal.

        Args:
            success_message: Success message to display
        """
        show_message(self, QMessageBox.Icon.Information, "Success", success_message)

    # ========================================================================
    # Lifecycle Methods
    # ========================================================================

    def closeEvent(self, event):
        """
        Override closeEvent to clean up signal connections.

        This prevents memory leaks by ensuring signal connections are properly
        disconnected when the widget is destroyed. Without this cleanup, the
        ViewModel and View maintain references to each other, preventing
        garbage collection.

        Args:
            event (QCloseEvent): The close event
        """
        self._disconnect_signals()
        QWidget.closeEvent(self, event)

    def _disconnect_signals(self):
        """
        Disconnect all ViewModel signals.

        This is called during widget cleanup to prevent memory leaks.
        Uses try/except to handle signals that may already be disconnected
        or objects that may have been destroyed.
        """
        for signal, slot in self._signal_connections:
            try:
                signal.disconnect(slot)
            except (RuntimeError, TypeError):
                # Signal might already be disconnected or object deleted
                # This is expected in some shutdown scenarios
                pass

        # Clear the connections list
        self._signal_connections.clear()
