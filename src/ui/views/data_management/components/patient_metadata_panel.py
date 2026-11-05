"""
PatientMetadataPanel for displaying patient and device metadata.

Professional medical software design component that displays:
- Patient information (name, DOB, gender, diagnosis)
- Device information (model, serial, implant date, battery)

Uses shadcn design system for consistent styling.

Author: iEEG BrainSense Development Team
Last Updated: 2025-10-09
"""

from typing import Dict, Any, Optional
from datetime import datetime
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QFrame, QSizePolicy, QSpacerItem
)
from PySide6.QtCore import Qt

from src.ui.policy.tokens import Space
from src.ui.theme import Theme
from src.ui.widgets.equal_columns_layout import EqualColumnsLayout


class PatientMetadataPanel(QWidget):
    """
    Patient metadata display panel.

    Displays patient and device metadata in a professional card layout
    with two columns, Patient Info and Device Info, stacked when the panel
    is too narrow for both.

    Example:
        >>> panel = PatientMetadataPanel()
        >>> panel.set_metadata(patient.metadata)
    """

    def __init__(self, parent=None):
        """
        Initialize PatientMetadataPanel.

        Args:
            parent: Parent widget (optional)
        """
        super().__init__(parent)
        self._metadata: Dict[str, Any] = {}
        self._setup_ui()

    def _setup_ui(self):
        """Setup the UI layout and widgets."""
        # Main layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Card container (with border and shadow)
        self.card = QFrame()
        self.card.setObjectName("metadata_card")
        card_layout = QHBoxLayout(self.card)
        card_layout.setContentsMargins(0, Space.X3, 0, Space.X3)
        card_layout.setSpacing(0)

        # Two equal columns, or one above the other when the panel is narrower
        # than both columns' minimum widths
        columns_layout = EqualColumnsLayout(
            column_counts=(2, 1),
            horizontal_spacing=Space.X16, vertical_spacing=Space.X3,
        )

        # Left (or upper) column: Patient Information
        patient_column = self._create_patient_info_column()
        columns_layout.addWidget(patient_column)

        # Right (or lower) column: Device Information
        device_column = self._create_device_info_column()
        columns_layout.addWidget(device_column)

        # 48-px side margins that give way only once the columns are at their
        # minimum width: with a stretch factor the columns count as
        # minimum-sized, so the Maximum-policy spacers shrink first
        card_layout.addSpacerItem(QSpacerItem(Space.X12, 0, QSizePolicy.Policy.Maximum))
        card_layout.addLayout(columns_layout, stretch=1)
        card_layout.addSpacerItem(QSpacerItem(Space.X12, 0, QSizePolicy.Policy.Maximum))

        # Apply card styling - transparent background, no border
        self.card.setStyleSheet("""
            QFrame#metadata_card {
                background-color: transparent;
                border: none;
            }
        """)

        layout.addWidget(self.card)

    def _create_patient_info_column(self) -> QWidget:
        """Create the patient information column."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)  # Reduced from 16 to 12

        # Info grid
        self.patient_grid = QGridLayout()
        self.patient_grid.setSpacing(6)  # Reduced from 8 to 6
        self.patient_grid.setColumnStretch(0, 0)  # Label column (fixed width)
        self.patient_grid.setColumnStretch(1, 1)  # Value column (expand)

        # Create labels (will be populated in set_metadata)
        self.name_label = self._create_info_row("Name:", "—", 0)
        self.dob_label = self._create_info_row("Date of Birth:", "—", 1)
        self.gender_label = self._create_info_row("Gender:", "—", 2)
        self.device_id_label = self._create_info_row("Device ID:", "—", 3)
        self.diagnosis_label = self._create_info_row("Diagnosis:", "—", 4)

        layout.addLayout(self.patient_grid)
        layout.addStretch()

        return widget

    def _create_device_info_column(self) -> QWidget:
        """Create the device information column."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)  # Reduced from 16 to 12

        # Info grid
        self.device_grid = QGridLayout()
        self.device_grid.setSpacing(6)  # Reduced from 8 to 6
        self.device_grid.setColumnStretch(0, 0)  # Label column (fixed width)
        self.device_grid.setColumnStretch(1, 1)  # Value column (expand)

        # Create labels (will be populated in set_metadata)
        self.neurostimulator_label = self._create_info_row("Model:", "—", 0, grid=self.device_grid)
        self.serial_label = self._create_info_row("Serial Number:", "—", 1, grid=self.device_grid)
        self.implant_date_label = self._create_info_row("Implant Date:", "—", 2, grid=self.device_grid)
        self.location_label = self._create_info_row("Location:", "—", 3, grid=self.device_grid)
        self.battery_label = self._create_info_row("Battery:", "—", 4, grid=self.device_grid)

        layout.addLayout(self.device_grid)
        layout.addStretch()

        return widget

    def _create_info_row(
        self,
        label_text: str,
        value_text: str,
        row: int,
        grid: Optional[QGridLayout] = None
    ) -> QLabel:
        """
        Create an info row with label and value.

        Args:
            label_text: Label text (e.g., "Name:")
            value_text: Initial value text
            row: Grid row number
            grid: Optional grid layout (defaults to patient_grid)

        Returns:
            QLabel: The value label (for later updates)
        """
        if grid is None:
            grid = self.patient_grid

        # Label
        label = QLabel(label_text)
        label.setStyleSheet(f"""
            QLabel {{
                color: {Theme.TEXT_MUTED};
                border: none;
                background: transparent;
            }}
        """)
        label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        label.setMinimumWidth(120)

        # Value
        value = QLabel(value_text)
        value.setStyleSheet(f"""
            QLabel {{
                color: {Theme.TEXT_PRIMARY};
                border: none;
                background: transparent;
            }}
        """)
        value.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        value.setWordWrap(True)

        grid.addWidget(label, row, 0)
        grid.addWidget(value, row, 1)

        return value

    def set_metadata(self, metadata: Optional[Dict[str, Any]]):
        """
        Update the panel with patient metadata.

        Args:
            metadata: Patient metadata dictionary (from Patient.metadata)

        Example:
            >>> metadata = {
            ...     'first_name': 'Jane',
            ...     'last_name': 'Doe',
            ...     'date_of_birth': '1960-01-01T04:00:00Z',
            ...     'gender': 'Male',
            ...     'diagnosis': 'Parkinson\'s Disease',
            ...     'neurostimulator': 'Percept PC',
            ...     'serial_number': 'SN0000000',
            ...     'implant_date': '2020-01-15T10:55:51Z',
            ...     'battery_percentage': 97,
            ...     'battery_life_months': 96,
            ...     'last_session_date': '2020-06-01T20:27:29Z'
            ... }
            >>> panel.set_metadata(metadata)
        """
        if not metadata:
            self.clear()
            return

        self._metadata = metadata

        # Update patient info
        first_name = metadata.get('first_name', '')
        last_name = metadata.get('last_name', '')
        full_name = f"{first_name} {last_name}".strip() or "—"
        self.name_label.setText(full_name)

        dob = self._format_date(metadata.get('date_of_birth'))
        self.dob_label.setText(dob)

        gender = metadata.get('gender', '—')
        self.gender_label.setText(gender)

        device_id = metadata.get('device_patient_id', '—')
        self.device_id_label.setText(str(device_id))

        diagnosis = metadata.get('diagnosis', '—')
        self.diagnosis_label.setText(diagnosis)

        # Update device info
        neurostimulator = metadata.get('neurostimulator', '')
        model = metadata.get('neurostimulator_model', '')
        full_model = f"{neurostimulator} {model}".strip() or "—"
        self.neurostimulator_label.setText(full_model)

        serial = metadata.get('serial_number', '—')
        self.serial_label.setText(serial)

        implant_date = self._format_date(metadata.get('implant_date'))
        self.implant_date_label.setText(implant_date)

        location = metadata.get('device_location', '—')
        self.location_label.setText(location)

        # Battery info (percentage + estimated life + date)
        battery_pct = metadata.get('battery_percentage')
        battery_life = metadata.get('battery_life_months')
        last_session_date = metadata.get('last_session_date')

        if battery_pct is not None:
            battery_text = f"{battery_pct}%"
            if battery_life is not None:
                battery_text += f" (~{battery_life} months)"
            # Add date if available
            if last_session_date:
                date_str = self._format_date(last_session_date)
                if date_str != "—":
                    battery_text += f"\n{date_str}"
            self.battery_label.setText(battery_text)
        else:
            self.battery_label.setText("—")

    def clear(self):
        """Clear all metadata and reset to empty state."""
        self._metadata = {}
        self.name_label.setText("—")
        self.dob_label.setText("—")
        self.gender_label.setText("—")
        self.device_id_label.setText("—")
        self.diagnosis_label.setText("—")
        self.neurostimulator_label.setText("—")
        self.serial_label.setText("—")
        self.implant_date_label.setText("—")
        self.location_label.setText("—")
        self.battery_label.setText("—")

    @staticmethod
    def _format_date(date_str: Optional[str]) -> str:
        """
        Format ISO date string to readable format.

        Args:
            date_str: ISO format date string (e.g., "2020-01-15T10:55:51Z")

        Returns:
            str: Formatted date (e.g., "2020-01-15") or "—" if invalid
        """
        if not date_str:
            return "—"

        try:
            # Parse ISO format
            if date_str.endswith('Z'):
                date_str = date_str[:-1] + '+00:00'

            dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
            return dt.strftime("%b %d, %Y")
        except (ValueError, AttributeError):
            # If parsing fails, try to extract just the date part
            try:
                date_part = date_str.split('T')[0]  # Get "2020-01-15"
                dt = datetime.strptime(date_part, "%Y-%m-%d")
                return dt.strftime("%b %d, %Y")
            except (ValueError, AttributeError, IndexError):
                return date_str  # Return as-is if all parsing fails
