"""
TopBar - Top horizontal bar with patient dropdown and action buttons.

Provides:
- Patient search/selection dropdown (left side)
- Action buttons: Create Patient, Upload, Delete Patient (right side)

When the bar is too narrow for every label, it compacts button by button (plan
M3.8): the patient combo first shrinks to its minimum (its layout does that),
then Create Patient and Upload lose their labels one at a time; Copy Table and
Save Plot lose theirs together. Delete Patient… never does (D14): it moves into
a "⋯" menu last. Each button keeps a tooltip and an accessible name.

Professional medical software design - no emojis, clean interface.

Author: iEEG BrainSense Development Team
Last Updated: 2025-10-01
"""

from typing import List
from PySide6.QtWidgets import (QWidget, QHBoxLayout, QSpacerItem, QSizePolicy, QPushButton,
                               QComboBox, QMenu)
from PySide6.QtCore import Qt, Signal, QEvent, QSize

from src.core.models import Patient
from src.ui.icons import Icons
from src.ui.policy.tokens import Dim
from src.ui.shell.focus_ring import keep_focus_ring
from src.ui.theme import Theme
from src.ui.asset_paths import qss_url
from src.ui.utils.tooltips import wrap_tooltip

# The patient combo is never narrower than this many characters (SH-09).
_PATIENT_MIN_CHARS = 14

# Compaction steps, tried in order until the shown buttons fit: the buttons
# shown without their labels, and whether Delete Patient… is in the "⋯" menu.
_STEPS = (
    (frozenset(), False),
    (frozenset({"create", "copy", "save"}), False),
    (frozenset({"create", "upload", "copy", "save"}), False),
    (frozenset({"create", "upload", "copy", "save"}), True),
)

# While the bar is resized, a step with more labels than the current one comes
# back only with this much room to spare, so the buttons don't flap at an edge.
_EXPAND_MARGIN = 16


class TopBar(QWidget):
    """
    Top bar component with patient dropdown and action buttons.

    Layout:
    [Patient Dropdown]                    [Create] [Upload] [Delete Patient]
    LEFT SIDE                             RIGHT SIDE

    Signals:
        patient_selected: Emitted when user selects a patient (emits patient_id)
        create_patient_clicked: Emitted when Create Patient button clicked
        upload_clicked: Emitted when Upload button clicked (file or directory)
        delete_patient_clicked: Emitted when Delete Patient button clicked
    """

    # Signals
    patient_selected = Signal(str)      # patient_id
    create_patient_clicked = Signal()
    upload_clicked = Signal()
    delete_patient_clicked = Signal()
    save_plot_clicked = Signal()        # Timeline page save plot
    copy_table_clicked = Signal()       # Timeline page copy table

    def __init__(self):
        super().__init__()
        self._patients: List[Patient] = []
        self._crud_visible = True       # Create / Upload / Delete Patient… (the data page)
        self._export_visible = False    # Copy Table / Save Plot (the analysis pages)
        self._step = 0                  # index into _STEPS
        self._widths = {}               # (button name, labelled) -> width; see _button_width
        self._setup_ui()
        self._apply_styles()

    def _setup_ui(self):
        """Setup the top bar UI."""
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 24, 0)
        layout.setSpacing(12)
        self.setLayout(layout)

        # LEFT: Patient dropdown. It grows with the longest name up to the cap;
        # a longer name shows its start, and the tooltip shows it whole.
        self.patient_dropdown = QComboBox()
        self.patient_dropdown.setPlaceholderText("Select Patient...")
        self.patient_dropdown.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.patient_dropdown.setMinimumContentsLength(_PATIENT_MIN_CHARS)
        self.patient_dropdown.setMaximumWidth(Dim.PATIENT_COMBO_MAX_W)
        self.patient_dropdown.setEditable(True)  # Enable search
        self.patient_dropdown.lineEdit().setPlaceholderText("Select patient...")
        self.patient_dropdown.currentIndexChanged.connect(self._on_patient_selected)

        # Style the dropdown
        self.patient_dropdown.setStyleSheet(f"""
            QComboBox {{
                background-color: #ffffff;
                border: 1px solid {Theme.BORDER};
                border-radius: 6px;
                padding: 8px 12px;
                color: {Theme.TEXT_PRIMARY};
                font-size: 14px;
            }}
            QComboBox:hover {{
                border-color: #2A2A2A;
            }}
            QComboBox::drop-down {{
                border: none;
                width: 20px;
            }}
            QComboBox::down-arrow {{
                image: {qss_url("icons", "chevron_down.svg")};
                width: 12px;
                height: 8px;
            }}
        """)

        layout.addWidget(self.patient_dropdown)

        # Spacer to push buttons to the right
        layout.addSpacerItem(QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum))

        # RIGHT: Action buttons (with icons matching reference design)
        # Greyscale palette aligned with manuscript figures:
        #   Create Patient:    #8A8A8A (chance-line grey)
        #   Upload:            #555555 (cluster-bar grey, primary action)
        #   Delete Patient:    #2A2A2A (manuscript dark)
        # The transparent border is the room of the keyboard focus ring
        # (keep_focus_ring), within today's box.
        grey_button_qss = """
            QPushButton {{ background-color: {bg}; color: #ffffff;
                           border: 2px solid transparent; padding: 3px 18px; }}
            QPushButton[iconOnly="true"] {{ padding: 3px 8px; }}
            QPushButton:hover {{ background-color: {hover}; }}
            QPushButton:pressed {{ background-color: {pressed}; }}
            QPushButton[focusRing="true"] {{ border-color: #ffffff; }}
            QPushButton:disabled {{ background-color: #cbd5e1; color: #ffffff; }}
        """

        # Create Patient button
        self.create_button = QPushButton()
        self.create_button.setIcon(Icons.user_plus(color="#ffffff"))
        self.create_button.setIconSize(QSize(16, 16))  # h-4 w-4
        self.create_button.setText("Create Patient")
        self.create_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.create_button.setStyleSheet(grey_button_qss.format(
            bg="#8A8A8A", hover="#757575", pressed="#616161"
        ))
        self.create_button.clicked.connect(self.create_patient_clicked.emit)
        layout.addWidget(self.create_button)

        # Upload button (single JSON file or a whole directory)
        self.upload_button = QPushButton()
        self.upload_button.setIcon(Icons.upload(color="#ffffff"))
        self.upload_button.setIconSize(QSize(16, 16))  # h-4 w-4
        self.upload_button.setText("Upload")
        self.upload_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.upload_button.setStyleSheet(grey_button_qss.format(
            bg="#555555", hover="#454545", pressed="#363636"
        ))
        self.upload_button.clicked.connect(self.upload_clicked.emit)
        layout.addWidget(self.upload_button)

        # Delete Patient button. It removes the whole patient, not the upload
        # selected in the table below, so it always says so (never icon-only,
        # D14); user-minus pairs it with Create Patient's user-plus.
        self.delete_button = QPushButton()
        self.delete_button.setIcon(Icons.user_minus(color="#ffffff"))
        self.delete_button.setIconSize(QSize(16, 16))  # h-4 w-4
        self.delete_button.setText("Delete Patient…")
        self.delete_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.delete_button.setStyleSheet(grey_button_qss.format(
            bg="#2A2A2A", hover="#1A1A1A", pressed="#000000"
        ))
        self.delete_button.clicked.connect(self.delete_patient_clicked.emit)
        layout.addWidget(self.delete_button)

        # Timeline page buttons (initially hidden, shown only on Timeline page)
        # Copy Table button
        self.copy_table_button = QPushButton()
        self.copy_table_button.setIcon(Icons.copy(color="#ffffff"))
        self.copy_table_button.setIconSize(QSize(16, 16))
        self.copy_table_button.setText("Copy Table")
        self.copy_table_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.copy_table_button.setStyleSheet(grey_button_qss.format(
            bg="#8A8A8A", hover="#757575", pressed="#616161"
        ))
        self.copy_table_button.clicked.connect(self.copy_table_clicked.emit)
        self.copy_table_button.setVisible(False)  # Hidden by default
        layout.addWidget(self.copy_table_button)

        # Save Plot button
        self.save_plot_button = QPushButton()
        self.save_plot_button.setIcon(Icons.save(color="#ffffff"))
        self.save_plot_button.setIconSize(QSize(16, 16))
        self.save_plot_button.setText("Save Plot")
        self.save_plot_button.setToolTip(wrap_tooltip(
            "Save Plot… — exports the manuscript-format figure (side by side, fixed size); "
            "the on-screen layout may differ."
        ))
        self.save_plot_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.save_plot_button.setStyleSheet(grey_button_qss.format(
            bg="#555555", hover="#454545", pressed="#363636"
        ))
        self.save_plot_button.clicked.connect(self.save_plot_clicked.emit)
        self.save_plot_button.setVisible(False)  # Hidden by default
        layout.addWidget(self.save_plot_button)

        # "⋯" holds Delete Patient… when the bar is too narrow for its label; it
        # takes Delete Patient…'s place in the row.
        self.overflow_button = QPushButton()
        self.overflow_button.setIcon(Icons.more(color="#ffffff"))
        self.overflow_button.setIconSize(QSize(16, 16))
        self.overflow_button.setProperty("iconOnly", True)
        self.overflow_button.setToolTip("More")
        self.overflow_button.setAccessibleName("More")
        self.overflow_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.overflow_button.setStyleSheet(grey_button_qss.format(
            bg="#2A2A2A", hover="#1A1A1A", pressed="#000000"
        ))
        self._overflow_menu = QMenu(self.overflow_button)
        self._delete_action = self._overflow_menu.addAction(Icons.user_minus(), "Delete Patient…")
        self._delete_action.triggered.connect(self.delete_patient_clicked)
        self.overflow_button.clicked.connect(self._open_overflow_menu)
        self.overflow_button.setVisible(False)
        layout.insertWidget(layout.indexOf(self.delete_button) + 1, self.overflow_button)

        # Upload and Delete Patient… are disabled until a patient is selected
        self._set_patient_actions_enabled(False)

        # The buttons that compact: (button, label, tooltip when labelled, when icon-only)
        self._compactable = {
            "create": (self.create_button, "Create Patient", "", "Create Patient"),
            "upload": (self.upload_button, "Upload", "", "Upload"),
            "copy": (self.copy_table_button, "Copy Table", "", "Copy statistics table"),
            "save": (self.save_plot_button, "Save Plot", self.save_plot_button.toolTip(),
                     self.save_plot_button.toolTip()),
        }
        for button, label, _tooltip, _compact_tooltip in self._compactable.values():
            button.setAccessibleName(label)
        # Focus from Tab only, never from a click; the ring only after keyboard navigation
        focusable = (*(entry[0] for entry in self._compactable.values()),
                     self.delete_button, self.overflow_button)
        for button in focusable:
            button.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        keep_focus_ring(self, focusable)

        # Measures the buttons with and without their labels (_button_width),
        # styled as they are; hidden, it is in no layout.
        self._probe = QPushButton(self)
        self._probe.setIconSize(QSize(16, 16))
        self._probe.setStyleSheet(grey_button_qss.format(
            bg="#8A8A8A", hover="#757575", pressed="#616161"
        ))
        self._probe.setVisible(False)

    def _on_patient_selected(self, index: int):
        """
        Handle patient dropdown selection.

        Args:
            index: Selected index in dropdown
        """
        self._sync_name_display()
        if index < 0:
            # No selection or cleared
            self._set_patient_actions_enabled(False)
            return

        # Get patient_id from dropdown data
        patient_id = self.patient_dropdown.itemData(index)
        if patient_id:
            # Enable action buttons
            self._set_patient_actions_enabled(True)

            # Emit signal
            self.patient_selected.emit(patient_id)

    def update_patient_list(self, patients: List[Patient]):
        """
        Update the patient dropdown with new patient list.

        Args:
            patients: List of Patient objects
        """
        self._patients = patients

        # Block signals while updating
        self.patient_dropdown.blockSignals(True)

        # Clear current items
        self.patient_dropdown.clear()

        # Show the human-facing name only — the patient_id is an internal key,
        # kept as item data for selection. This avoids redundant labels like
        # "test2 (TEST2)" when the id is just an uppercased form of the name.
        # Falls back to the id if a record somehow has no name.
        for patient in patients:
            display_text = patient.patient_name or patient.patient_id
            self.patient_dropdown.addItem(display_text, patient.patient_id)

        # Restore signals
        self.patient_dropdown.blockSignals(False)

        # Reset to no selection
        self.patient_dropdown.setCurrentIndex(-1)
        # An empty list leaves the index at -1, so the slot above didn't run.
        self._sync_name_display()

    def set_selected_patient(self, patient_id: str):
        """
        Reflect the given patient as selected in the dropdown.

        Used when selection is driven programmatically (e.g. the AppViewModel
        auto-selects a patient right after creation). Signals are blocked during
        the index change so this does NOT re-emit ``patient_selected`` and bounce
        back into the ViewModel — which would redundantly reload every page. The
        action buttons are enabled here directly, since the blocked
        ``currentIndexChanged`` would otherwise skip ``_on_patient_selected``.

        Args:
            patient_id: Patient identifier to select. Unknown ids are a no-op.
        """
        # Find index of patient_id
        for i in range(self.patient_dropdown.count()):
            if self.patient_dropdown.itemData(i) == patient_id:
                self.patient_dropdown.blockSignals(True)
                self.patient_dropdown.setCurrentIndex(i)
                self.patient_dropdown.blockSignals(False)
                self._sync_name_display()
                # update_patient_list() reset the index to -1 (disabling these);
                # a programmatic selection must re-enable them itself.
                self._set_patient_actions_enabled(True)
                return

    def clear_selection(self):
        """Clear the patient dropdown selection."""
        self.patient_dropdown.setCurrentIndex(-1)
        self._set_patient_actions_enabled(False)

    def _set_patient_actions_enabled(self, enabled: bool):
        """Upload and Delete Patient… (the button and its "⋯" entry) act on the
        selected patient."""
        self.upload_button.setEnabled(enabled)
        self.delete_button.setEnabled(enabled)
        self.overflow_button.setEnabled(enabled)
        self._delete_action.setEnabled(enabled)

    def _sync_name_display(self):
        """Put the full name in the tooltip and show the name from its start.

        Setting the text leaves the cursor at its end, so a name longer than
        the field would show only its end (SH-09).
        """
        name = self.patient_dropdown.currentText()
        self.patient_dropdown.setToolTip(wrap_tooltip(name) if name else "")
        self.patient_dropdown.lineEdit().setCursorPosition(0)

    def set_buttons_visible(self, visible: bool):
        """
        Show or hide action buttons.

        Args:
            visible: True to show buttons, False to hide
        """
        self._crud_visible = visible
        self.create_button.setVisible(visible)
        self.upload_button.setVisible(visible)
        self._refit()

    def set_timeline_buttons_visible(self, visible: bool):
        """
        Show or hide Timeline page specific buttons.

        Args:
            visible: True to show buttons, False to hide
        """
        self._export_visible = visible
        self.copy_table_button.setVisible(visible)
        self.save_plot_button.setVisible(visible)
        self._refit()

    def set_timeline_buttons_enabled(self, enabled: bool):
        """
        Enable or disable Timeline page buttons.

        Args:
            enabled: True to enable, False to disable
        """
        self.copy_table_button.setEnabled(enabled)
        self.save_plot_button.setEnabled(enabled)

    def _open_overflow_menu(self):
        """Open the "⋯" menu below its button."""
        self._overflow_menu.popup(
            self.overflow_button.mapToGlobal(self.overflow_button.rect().bottomLeft()))

    # ------------------------------------------------------------------ compaction

    def minimumSizeHint(self) -> QSize:
        """As narrow as the shown buttons get at the last step: the bar compacts
        itself to whatever width its layout gives it (_fit)."""
        return QSize(self._required_width(_STEPS[-1]), super().minimumSizeHint().height())

    def showEvent(self, event):
        super().showEvent(event)
        self._fit(sticky=False)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit(sticky=True)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in (QEvent.Type.StyleChange, QEvent.Type.FontChange):
            self._widths.clear()
            self._refit()

    def _refit(self):
        """The shown buttons or their sizes changed: fit them afresh."""
        self.updateGeometry()  # the minimum follows the shown buttons
        self._fit(sticky=False)

    def _fit(self, *, sticky: bool):
        """
        Show the first step whose buttons fit the bar.

        Args:
            sticky: The bar is being resized: a step with more labels than the
                current one needs _EXPAND_MARGIN px to spare.
        """
        if not self.isVisible():
            return  # sized for real once shown
        fitting = len(_STEPS) - 1
        for index, step in enumerate(_STEPS):
            margin = _EXPAND_MARGIN if sticky and index < self._step else 0
            if self._required_width(step) + margin <= self.width():
                fitting = index
                break
        self._show_step(fitting)

    def _show_step(self, index: int):
        """Show ``_STEPS[index]``: who keeps a label, and Delete Patient… or "⋯"."""
        icon_only, delete_in_menu = _STEPS[index]
        for name, (button, label, tooltip, compact_tooltip) in self._compactable.items():
            labelled = name not in icon_only
            if button.text() == (label if labelled else ""):
                continue
            button.setText(label if labelled else "")
            button.setToolTip(tooltip if labelled else compact_tooltip)
            button.setProperty("iconOnly", not labelled)
            button.style().unpolish(button)
            button.style().polish(button)
        self.delete_button.setVisible(self._crud_visible and not delete_in_menu)
        self.overflow_button.setVisible(self._crud_visible and delete_in_menu)
        self._step = index

    def _required_width(self, step) -> int:
        """The width the shown buttons need at ``step``, the combo at its minimum."""
        icon_only, delete_in_menu = step
        widths = [self.patient_dropdown.minimumSizeHint().width()]
        names = (["create", "upload"] if self._crud_visible else []) + (
            ["copy", "save"] if self._export_visible else [])
        widths += [self._button_width(name, name not in icon_only) for name in names]
        if self._crud_visible:
            delete = self.overflow_button if delete_in_menu else self.delete_button
            widths.append(delete.sizeHint().width())
        layout = self.layout()
        margins = layout.contentsMargins()
        return (sum(widths) + layout.spacing() * (len(widths) - 1)
                + margins.left() + margins.right())

    def _button_width(self, name: str, labelled: bool) -> int:
        """A compactable button's width with or without its label, measured on
        the hidden probe so the button itself never changes to find out."""
        key = (name, labelled)
        if key not in self._widths:
            button, label = self._compactable[name][:2]
            probe = self._probe
            probe.setIcon(button.icon())
            probe.setText(label if labelled else "")
            probe.setProperty("iconOnly", not labelled)
            probe.style().unpolish(probe)
            probe.style().polish(probe)
            self._widths[key] = probe.sizeHint().width()
        return self._widths[key]

    def _apply_styles(self):
        """Apply styling to top bar container."""
        self.setStyleSheet(f"""
            TopBar {{
                background-color: #ffffff !important;
                min-height: {Dim.TOPBAR_H}px;
                max-height: {Dim.TOPBAR_H}px;
            }}
        """)
        # Force white background on the widget itself
        self.setAutoFillBackground(True)
        from PySide6.QtGui import QPalette, QColor
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor("#ffffff"))
        self.setPalette(palette)
