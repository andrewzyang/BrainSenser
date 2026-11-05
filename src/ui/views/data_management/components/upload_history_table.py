"""
UploadHistoryTable widget for displaying file upload history.

Displays upload history with sortable columns for date, filename, size, and type badges.
Matches reference React design with badges.

Author: iEEG BrainSense Development Team
Last Updated: 2025-10-02
"""

from typing import List, Optional
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QTableWidget, QTableWidgetItem,
    QAbstractItemView, QHBoxLayout, QApplication, QMenu, QSizePolicy
)
from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QFont, QColor, QAction

from src.core.models import UploadedFile
from src.ui.components.badge import Badge
from src.ui.components.table_layout import Elastic, FitColumnsController
from src.ui.policy.tokens import TYPE_PX, Space, TypeRole
from src.ui.theme import Theme

# The table is never shorter than its header plus this many rows.
_MIN_VISIBLE_ROWS = 3
# The "no uploads" message row is this many data rows tall.
_EMPTY_ROW_HEIGHT_IN_ROWS = 2.5


class _SizeItem(QTableWidgetItem):
    """A Size cell that sorts by its size in MB (UserRole) rather than its text."""

    def __lt__(self, other: QTableWidgetItem) -> bool:
        return self.data(Qt.ItemDataRole.UserRole) < other.data(Qt.ItemDataRole.UserRole)


class UploadHistoryTable(QWidget):
    """
    Table widget displaying file upload history for a patient.

    Matches reference React design with:
    - 4 columns: Upload Date, File Name, Size, Type
    - Badges for data types in Type column
    - Columns as wide as their content; File Name takes the spare width and,
      when the table is too narrow, gives width back first (eliding in the
      middle, full name in its tooltip) before the table scrolls sideways
      inside itself

    Columns:
    - Upload Date (sortable)
    - File Name (sortable)
    - Size (sortable, MB)
    - Type (badges: Snapshots, Timeline, etc.)

    Features:
    - Sortable columns
    - Formatted dates (YYYY-MM-DD HH:MM)
    - File sizes in MB
    - Multiple badges per row for different data types
    - At least the header and three rows tall; fills the height it is given

    Example:
        >>> table = UploadHistoryTable()
        >>> table.populate_uploads(uploads)
    """

    # Signal emitted when a row is selected
    upload_selected = Signal(object)  # Emits UploadedFile

    # Column indices
    COL_DATE = 0
    COL_FILENAME = 1
    COL_SIZE = 2
    COL_TYPE = 3

    def __init__(self, parent=None):
        """
        Initialize UploadHistoryTable.

        Args:
            parent: Parent widget (optional)
        """
        super().__init__(parent)
        self._uploads: List[UploadedFile] = []
        self._setup_ui()

    def _setup_ui(self):
        """Setup table structure."""
        # Main layout
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Create table widget
        self.table = QTableWidget()

        # Set column count and headers
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels([
            "Upload Date",
            "File Name",
            "Size",
            "Type"
        ])

        # Column widths come from the FitColumnsController set up below
        self.table.horizontalHeader().setSortIndicatorShown(True)

        # Hide row numbers (vertical header)
        self.table.verticalHeader().setVisible(False)

        # Enable sorting
        self.table.setSortingEnabled(True)

        # Configure selection behavior - allow cell selection for copying
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)

        # Disable editing
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)

        # Enable alternating row colors
        self.table.setAlternatingRowColors(True)

        # Set cursor to pointer for better UX
        self.table.viewport().setCursor(Qt.CursorShape.PointingHandCursor)

        # Style table with improved visual hierarchy
        self.table.setStyleSheet(f"""
            QTableWidget {{
                background-color: {Theme.TABLE_ROW_EVEN};
                border: none;
                gridline-color: {Theme.TABLE_GRIDLINE};
                selection-background-color: {Theme.TABLE_SELECTION_BG};
            }}
            QTableWidget::item {{
                padding: 10px 12px;
                color: {Theme.NEUTRAL_DARK};
                border-bottom: 1px solid transparent;
            }}
            QTableWidget::item:hover {{
                background-color: {Theme.TABLE_ROW_EVEN};
            }}
            QTableWidget::item:selected {{
                background-color: {Theme.TABLE_SELECTION_BG};
                color: {Theme.TABLE_SELECTION_FG};
            }}
            QTableWidget::item:alternate {{
                background-color: {Theme.TABLE_ROW_ODD};
            }}
            QHeaderView::section {{
                background-color: {Theme.TABLE_HEADER_BG};
                padding: 12px 12px;
                border: none;
                border-bottom: 2px solid transparent;
                font-weight: 600;
                font-size: 14px;
                color: {Theme.TABLE_HEADER_FG};
                text-align: left;
            }}
            QHeaderView::section:horizontal {{
                border-right: 1px solid transparent;
            }}
            QHeaderView::section:horizontal:last {{
                border-right: none;
            }}
        """)

        # Install event filter for keyboard shortcuts
        self.table.installEventFilter(self)

        # Enable custom context menu for right-click copy
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_context_menu)

        # Connect selection signal
        self.table.itemSelectionChanged.connect(self._on_selection_changed)

        # Columns sized to their content (Type to its badges); File Name takes
        # the spare width and, when the table is too narrow, shrinks to 12 em
        # (room for a name's start and its timestamp around the "…") before
        # the table scrolls sideways inside itself. Rows are one line tall.
        self._fit = FitColumnsController(
            self.table, elastic={self.COL_FILENAME: Elastic(min_em=12)}
        )

        main_layout.addWidget(self.table)

        # Expand to fill the vertical space the parent gives it: the data page
        # gives this table stretch so it grows on tall windows instead of
        # leaving dead space below; rows scroll inside the table.
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)

    def minimumSizeHint(self) -> QSize:
        """As narrow as the table allows (wider content scrolls inside it),
        and tall enough for the header and three rows."""
        rows_height = (self.table.horizontalHeader().sizeHint().height()
                       + _MIN_VISIBLE_ROWS * self._fit.row_height()
                       + 2 * self.table.frameWidth())
        return QSize(self.table.minimumSizeHint().width(), rows_height)

    def sizeHint(self) -> QSize:
        """The minimum height: the page hands the table its spare height, and a
        taller hint would make the data page (laid out height-for-width in its
        page host) scroll before it has to."""
        return QSize(self.table.sizeHint().width(), self.minimumSizeHint().height())

    def populate_uploads(self, uploads: List[UploadedFile]) -> None:
        """
        Populate table with upload history.

        Args:
            uploads: List of UploadedFile objects

        Example:
            >>> table.populate_uploads(uploads)
        """
        # Store uploads
        self._uploads = uploads

        # Disable sorting temporarily for performance
        self.table.setSortingEnabled(False)

        # Clear existing rows
        self.table.setRowCount(0)

        # Handle empty state
        if len(uploads) == 0:
            self._add_empty_state_row()
        else:
            # Add rows
            for upload in uploads:
                self._add_upload_row(upload)

        # Re-enable sorting and sort by date descending (most recent first)
        self.table.setSortingEnabled(True)
        if len(uploads) > 0:
            self.table.sortItems(self.COL_DATE, Qt.SortOrder.DescendingOrder)

        # Badge rows and the message row differ in height: re-query the minimum
        self.updateGeometry()

    def _add_upload_row(self, upload: UploadedFile) -> None:
        """
        Add a single upload row to the table.

        Args:
            upload: UploadedFile object
        """
        row = self.table.rowCount()
        self.table.insertRow(row)

        # Upload Date (sortable by timestamp)
        date_item = QTableWidgetItem(upload.processed_at.strftime("%Y-%m-%d %H:%M"))
        date_item.setData(Qt.ItemDataRole.UserRole, upload.processed_at.timestamp())
        self.table.setItem(row, self.COL_DATE, date_item)

        # File Name (with tooltip for long names)
        filename_item = QTableWidgetItem(upload.file_name)
        filename_item.setToolTip(upload.file_name)  # Show full name on hover
        self.table.setItem(row, self.COL_FILENAME, filename_item)

        # Size (MB) - right-aligned, sorted by numeric value
        size_item = _SizeItem(f"{upload.file_size_mb:.2f} MB")
        size_item.setData(Qt.ItemDataRole.UserRole, upload.file_size_mb)
        size_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.table.setItem(row, self.COL_SIZE, size_item)

        # Type column - Create widget with badges
        type_widget = self._create_type_badges_widget(upload)
        self.table.setCellWidget(row, self.COL_TYPE, type_widget)

        # Store upload reference in the row
        date_item.setData(Qt.ItemDataRole.UserRole + 1, upload)

    def _create_type_badges_widget(self, upload: UploadedFile) -> QWidget:
        """
        Create a widget containing badges for data types.

        Uses UploadedFile.data_type_tags property which includes all four BrainSense types:
        - Snapshots (BrainSense Events/PatientEvents)
        - Timeline (BrainSenseLfp chronic power tracking)
        - Indefinite Streaming (IndefiniteStreaming high-res waveforms)
        - Definite Streaming (BrainSenseTimeDomain high-res waveforms)

        Args:
            upload: UploadedFile object

        Returns:
            QWidget with horizontal layout containing badges
        """
        widget = QWidget()
        layout = QHBoxLayout(widget)
        # Thin vertical margins: the view already insets a cell widget by the
        # item padding, and these keep badge rows at their former 48-px height
        layout.setContentsMargins(Space.X2, Space.HALF, Space.X2, Space.HALF)
        layout.setSpacing(Space.X1_5)
        layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        # Get data type tags from UploadedFile model (includes all 4 BrainSense types)
        types = upload.data_type_tags

        # Map of badge labels (all grayscale secondary variant)
        badge_labels = {
            "Snapshots": "Snapshots",
            "Timeline": "Timeline",
            "Indefinite Streaming": "Stream (I)",
            "Definite Streaming": "Stream (D)",
        }

        # Create badges for each type with grayscale styling
        for type_name in types:
            label = badge_labels.get(type_name, type_name)
            badge = Badge(label, variant="secondary")
            layout.addWidget(badge)

        layout.addStretch()
        return widget

    def _add_empty_state_row(self) -> None:
        """
        Add empty state row when no uploads exist.

        Matches reference design: centered message spanning all columns.
        """
        self.table.insertRow(0)

        # Create centered message spanning all columns
        empty_item = QTableWidgetItem("No upload history available for this patient")
        empty_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_item.setForeground(QColor(Theme.NEUTRAL_LIGHT))

        # Set font (item fonts bypass the stylesheet, so in px, never pt)
        empty_font = QFont()
        empty_font.setPixelSize(TYPE_PX[TypeRole.CAPTION])
        empty_item.setFont(empty_font)

        # Set in first column
        self.table.setItem(0, 0, empty_item)

        # Span all 4 columns
        self.table.setSpan(0, 0, 1, 4)

        # Taller than a data row for visibility. Size the rows first: a later
        # change of the default row height would reset this one.
        self._fit.refit()
        self.table.setRowHeight(0, round(_EMPTY_ROW_HEIGHT_IN_ROWS * self._fit.row_height()))

    def clear_table(self) -> None:
        """
        Clear all rows from the table.

        Example:
            >>> table.clear_table()
        """
        self._uploads = []
        self.table.setRowCount(0)
        self.updateGeometry()

    def get_selected_upload(self) -> Optional[UploadedFile]:
        """
        Get the currently selected upload.

        Returns:
            UploadedFile if row selected, None otherwise

        Example:
            >>> upload = table.get_selected_upload()
            >>> if upload:
            ...     print(upload.file_name)
        """
        selected_rows = self.table.selectedIndexes()
        if not selected_rows:
            return None

        row = selected_rows[0].row()
        date_item = self.table.item(row, self.COL_DATE)
        if date_item:
            return date_item.data(Qt.ItemDataRole.UserRole + 1)
        return None

    def _on_selection_changed(self) -> None:
        """Handle row selection change."""
        selected = self.get_selected_upload()
        if selected:
            self.upload_selected.emit(selected)

    def get_upload_count(self) -> int:
        """
        Get the number of uploads in the table.

        Returns:
            Number of rows

        Example:
            >>> count = table.get_upload_count()
        """
        return len(self._uploads)

    def get_all_uploads(self) -> List[UploadedFile]:
        """
        Get all uploads in the table.

        Returns:
            List of UploadedFile objects

        Example:
            >>> uploads = table.get_all_uploads()
        """
        return self._uploads.copy()

    def eventFilter(self, source, event):
        """
        Event filter to handle keyboard shortcuts for copying table data.

        Handles:
        - Cmd+C (Mac) / Ctrl+C (Windows/Linux) to copy selected cells
        - Cmd+A (Mac) / Ctrl+A (Windows/Linux) to select all cells
        """
        if source == self.table and event.type() == event.Type.KeyPress:
            if event.modifiers() & Qt.ControlModifier:
                if event.key() == Qt.Key_C:
                    self.copy_selection_to_clipboard()
                    return True
                elif event.key() == Qt.Key_A:
                    self.table.selectAll()
                    return True
        return super().eventFilter(source, event)

    def show_context_menu(self, position):
        """Show context menu on right-click."""
        menu = QMenu(self.table)

        # Copy action
        copy_action = QAction("Copy", self.table)
        copy_action.setShortcut("Ctrl+C")
        copy_action.triggered.connect(self.copy_selection_to_clipboard)
        menu.addAction(copy_action)

        # Select All action
        select_all_action = QAction("Select All", self.table)
        select_all_action.setShortcut("Ctrl+A")
        select_all_action.triggered.connect(self.table.selectAll)
        menu.addAction(select_all_action)

        # Show the menu at the cursor: a scroll area reports the position in
        # its viewport's coordinates (below the header)
        menu.exec(self.table.viewport().mapToGlobal(position))

    def copy_selection_to_clipboard(self):
        """
        Copy selected cells to clipboard in tab-separated format.
        If no cells are selected, copies the entire table.
        Handles the Type column with badges specially.
        """
        selected = self.table.selectedRanges()

        if not selected:
            # If nothing selected, select all and copy
            self.table.selectAll()
            selected = self.table.selectedRanges()

        if selected:
            # Get the bounding rectangle of all selected ranges
            min_row = min(r.topRow() for r in selected)
            max_row = max(r.bottomRow() for r in selected)
            min_col = min(r.leftColumn() for r in selected)
            max_col = max(r.rightColumn() for r in selected)

            # Build the text to copy
            copied_text = []

            # Add headers if copying from first row or full table
            if min_row == 0 or len(selected) == 1 and selected[0].rowCount() == self.table.rowCount():
                headers = []
                for col in range(min_col, max_col + 1):
                    headers.append(self.table.horizontalHeaderItem(col).text())
                copied_text.append('\t'.join(headers))

            # Add data rows
            for row in range(min_row, max_row + 1):
                row_data = []
                for col in range(min_col, max_col + 1):
                    if col == self.COL_TYPE:
                        # Special handling for Type column - extract badge text
                        widget = self.table.cellWidget(row, col)
                        if widget:
                            # Extract badge labels from the widget
                            badge_texts = []
                            layout = widget.layout()
                            for i in range(layout.count()):
                                item = layout.itemAt(i)
                                if item and item.widget():
                                    badge = item.widget()
                                    if hasattr(badge, 'text'):
                                        badge_texts.append(badge.text())
                            row_data.append(', '.join(badge_texts))
                        else:
                            row_data.append('')
                    else:
                        # Regular cell
                        item = self.table.item(row, col)
                        if item:
                            row_data.append(item.text())
                        else:
                            row_data.append('')
                copied_text.append('\t'.join(row_data))

            # Copy to clipboard
            clipboard = QApplication.clipboard()
            clipboard.setText('\n'.join(copied_text))
