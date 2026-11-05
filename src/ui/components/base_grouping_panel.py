"""
Base Grouping Panel Component

Abstract base class for grouping panels that enable event-based group comparisons
with statistical test configuration. Follows MVVM architecture principles.
"""

from typing import Dict, List, Optional
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QGridLayout, QGroupBox, QListWidget,
    QListWidgetItem, QPushButton, QLabel, QTableWidget, QComboBox, QLineEdit,
    QAbstractItemView, QSpacerItem, QSizePolicy, QStyle,
    QStyledItemDelegate, QStyleOptionViewItem
)
from PySide6.QtCore import QCoreApplication, QEvent, QObject, QSize, Signal, Qt
from PySide6.QtGui import QWheelEvent

from src.ui.policy.layout import Arrangement, Density, HeightClass
from src.ui.policy.tokens import DENSITY_SPECS, Dim, Space
from src.ui.theme import Theme
from src.ui.components.effect_size_selector import EffectSizeSelector
from src.ui.components.selector_combo_style import ElidingComboBox, apply_selector_combo_style
from src.ui.components.table_copy import TableCopyActions
from src.ui.components.table_layout import FitColumnsController
from src.ui.utils.tooltips import wrap_tooltip


# --------------------------------------------------------------------------
# Shared perm/boot selector configuration (single source of truth)
# --------------------------------------------------------------------------
# Every analysis page that offers a permutation/bootstrap selector pair
# (Snapshots 5 Hz Band, Timeline LFP Threshold, Timeline Peri-Event) draws its
# dropdown options and labels from these constants so the menus can never drift
# apart. The canonical menus are the UNION of what the pages historically
# offered, so unifying them removes no capability and keeps every page's
# manuscript-locked DEFAULT selection a valid member.
#
# These are presentation config (which values the user MAY pick), kept in the
# View layer alongside the panels that render them. They are intentionally
# distinct from the per-page statistical DEFAULT selection (which value is
# chosen out of the box) — those stay with each panel and are NOT defined here,
# so changing the menu never changes what reproduces the published analysis.
#
# Convention enforced across all three pages:
#   * the Bootstrap (CI) row sits ABOVE the Permutations (p) row;
#   * labels read exactly "Bootstrap (CI):" and "Permutations (p):" — "(CI)"
#     drives the bootstrap confidence intervals, "(p)" the permutation p-value.
PERMUTATION_VALUES = (200, 1_000, 5_000, 10_000)
BOOTSTRAP_VALUES = (500, 1_000, 2_000, 5_000, 10_000)

# Comma-grouped display labels matching the canonical values (e.g. 10_000 ->
# "10,000"). String-combo pages feed these straight into ``addItems``; the
# data-combo page (5 Hz Band) pairs each label with its int via
# ``addItem(text, value)`` so ``currentData()`` reads back a real int.
PERMUTATION_OPTION_LABELS = tuple(f"{v:,}" for v in PERMUTATION_VALUES)
BOOTSTRAP_OPTION_LABELS = tuple(f"{v:,}" for v in BOOTSTRAP_VALUES)

BOOTSTRAP_LABEL = "Bootstrap (CI):"
PERMUTATION_LABEL = "Permutations (p):"

# Event Types : Active Groups : Statistical Controls : Statistics Table. In the
# ROW arrangement the four sections share the panel width by these stretches,
# and the three setup sections stop at their caps (reached on panels wider than
# ~1245 px), so a wide panel gives its extra width to the table.
_SECTION_STRETCH = (2, 2, 3, 7)
_SETUP_SECTION_MAX_W = (Dim.EVENT_TYPES_MAX_W, Dim.GROUPS_MAX_W, Dim.CONTROLS_MAX_W)
_UNCAPPED = 16777215  # QWIDGETSIZE_MAX

# STACKED: the setup row and the table share the panel's height 2:3, and the
# table never shows fewer rows than this.
_STACKED_ROW_STRETCH = (2, 3)
_STACKED_TABLE_ROWS = 4

# The controls style.qss sizes by the panel's "density" property (~28 px compact).
_DENSITY_STYLED = (QPushButton, QComboBox, QLineEdit)

# Side padding of the statistics-table header sections; a near fit uses the tight one.
_SECTION_PAD_X = Space.X1
_SECTION_PAD_X_TIGHT = Space.HALF


def _stats_table_qss(tight: bool) -> str:
    """The statistics table's sheet; ``tight`` narrows the header sections' side padding.

    Greyscale + minimal, driven by the Theme.TABLE_* tokens (single source of
    truth). This stylesheet REPLACES the global QSS for this widget, so it
    restates the alternating-row / selection rules rather than relying on the
    app-wide block. No gridlines, no per-cell borders — structure comes from the
    header underline and alternating row shades only. The header widget gets the
    sections' font size too: Qt measures sections with the header's own font
    (else the app's 15 px), so a 10-px header was laid out for 15-px text.
    """
    pad_x = _SECTION_PAD_X_TIGHT if tight else _SECTION_PAD_X
    return f"""
        QTableWidget {{
            border: none;
            background-color: {Theme.TABLE_ROW_EVEN};
            gridline-color: {Theme.TABLE_GRIDLINE};
            selection-background-color: {Theme.TABLE_SELECTION_BG};
            selection-color: {Theme.TABLE_SELECTION_FG};
            font-size: 10px;
        }}
        QTableWidget::item {{
            padding: {Space.HALF}px;
        }}
        QTableWidget::item:alternate {{
            background-color: {Theme.TABLE_ROW_ODD};
        }}
        QHeaderView {{
            font-size: 10px;
        }}
        QHeaderView::section {{
            background-color: {Theme.TABLE_HEADER_BG};
            color: {Theme.TABLE_HEADER_FG};
            padding: {_SECTION_PAD_X}px {pad_x}px;
            border: none;
            border-bottom: 1px solid {Theme.TABLE_BORDER};
            font-weight: bold;
            font-size: 10px;
        }}
    """


class _StatsTableColumns(FitColumnsController):
    """Fit-or-scroll columns that take the tight header padding for a near fit.

    When the columns are at most Dim.TABLE_NEAR_FIT px wider than the viewport,
    the header sections' side padding drops from 4 to 2 px: those few pixels
    then never cost a horizontal scrollbar, while a table that scrolls anyway
    keeps the roomier padding. The header is what makes these columns wide, so
    only its padding changes.
    """

    def __init__(self, table: QTableWidget) -> None:
        super().__init__(table)
        self._stats_table = table
        self._tight = False

    def refit(self) -> None:
        self._settle_padding()
        super().refit()

    def _settle_padding(self) -> None:
        natural = self.natural_widths()
        if self._tight:
            # The widths with the regular padding: a header section grows by the
            # padding difference on both sides; the cells don't change.
            header = self._stats_table.horizontalHeader()
            grow = 2 * (_SECTION_PAD_X - _SECTION_PAD_X_TIGHT)
            natural = [max(width, header.sectionSizeHint(column) + grow)
                       for column, width in enumerate(natural)]
        overflow = sum(natural) - self._stats_table.viewport().width()
        tight = 0 < overflow <= Dim.TABLE_NEAR_FIT
        if tight != self._tight:
            self._tight = tight
            # The style change makes the controller measure again before it fits.
            self._stats_table.setStyleSheet(_stats_table_qss(tight))


class _ShiftWheelScrollsSideways(QObject):
    """Shift+wheel over a table scrolls it sideways when it doesn't fit its viewport.

    Qt sends a vertical wheel to the vertical scrollbar whatever the modifiers.
    macOS turns Shift+wheel into a sideways wheel itself, but Windows and Linux
    don't, so there the thin horizontal bar was the only way to the columns on
    the right.
    """

    def __init__(self, table: QTableWidget) -> None:
        super().__init__(table)
        self._bar = table.horizontalScrollBar()
        table.viewport().installEventFilter(self)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if (event.type() == QEvent.Type.Wheel
                and event.modifiers() & Qt.KeyboardModifier.ShiftModifier
                and abs(event.angleDelta().y()) > abs(event.angleDelta().x())
                and self._bar.maximum() > 0):
            # A horizontal bar scrolls sideways on a vertical wheel; Shift would
            # make it page, so the forwarded wheel goes without it.
            QCoreApplication.sendEvent(self._bar, QWheelEvent(
                event.position(), event.globalPosition(), event.pixelDelta(),
                event.angleDelta(), event.buttons(),
                event.modifiers() & ~Qt.KeyboardModifier.ShiftModifier,
                event.phase(), event.inverted()))
            return True
        return super().eventFilter(watched, event)


class _ElidingItemDelegate(QStyledItemDelegate):
    """Fits list items to the list's width: one line each, long ones elided,
    never scrolled to.

    QListView makes an item as wide as its viewport, or wider when the item's
    size hint is; a wide hint widens the list's contents and scrolls it
    sideways. A zero hint width keeps every item exactly as wide as the
    viewport, so the view elides its text (``textElideMode``) as it paints it.
    """

    def sizeHint(self, option: QStyleOptionViewItem, index) -> QSize:
        return QSize(0, super().sizeHint(option, index).height())


class _ElidedList(QListWidget):
    """A one-column list that elides long items in the middle — keeping their
    "(n=…)" — instead of scrolling sideways. Every item added with
    :meth:`add_named` has its full text as its tooltip, so hovering an elided
    name reveals it.

    With ``full_rows``, the list's minimum height is exactly that many whole
    rows of its font and item style, so at its minimum it never shows a row cut
    in half.
    """

    def __init__(self, full_rows: int = 0) -> None:
        super().__init__()
        self._full_rows = full_rows
        self.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setItemDelegate(_ElidingItemDelegate(self))

    def minimumSizeHint(self) -> QSize:
        hint = super().minimumSizeHint()
        if self._full_rows:
            option = QStyleOptionViewItem()
            option.initFrom(self)
            option.font = self.font()
            option.text = "0"
            option.features = QStyleOptionViewItem.ViewItemFeature.HasDisplay
            row = self.style().sizeFromContents(
                QStyle.ContentsType.CT_ItemViewItem, option, QSize(), self).height()
            frame, margins = self.contentsMargins(), self.viewportMargins()
            hint.setHeight(self._full_rows * row + frame.top() + frame.bottom()
                           + margins.top() + margins.bottom())
        return hint

    def add_named(self, text: str, value=None) -> None:
        """Add an item that shows ``text`` on one line and in full on hover;
        ``value`` goes in its UserRole."""
        item = QListWidgetItem(text)
        item.setToolTip(text)
        if value is not None:
            item.setData(Qt.ItemDataRole.UserRole, value)
        self.addItem(item)


class BaseGroupingPanel(QWidget):
    """
    Abstract base panel with 4 sections for event grouping and analysis:
    - Event Types (left): Multi-select list of available event types
    - Active Groups (middle-left): Shows Group 1 and Group 2 contents
    - Statistical Controls (middle-right): Test method and correction selection
    - Statistics Table (right): Comprehensive results display

    The sections sit side by side (ROW) or, on narrow and tall pages, the three
    setup sections sit above a full-width table (STACKED); the page commands
    the arrangement and the density with :meth:`apply_density`.

    Subclasses must implement abstract methods for customization points.
    """

    # Signals
    group_cleared = Signal()
    # The table's context-menu "Copy Table"; the page connects it to its own
    # copy_table_to_clipboard so the menu matches the top-bar button.
    copy_table_requested = Signal()

    def __init__(self):
        super().__init__()
        self._available_event_types: Dict[str, int] = {}  # {event_type: count}
        self._active_groups: Dict[int, List[str]] = {1: [], 2: []}
        self._current_group_target = 1  # Which group to add to next
        self.effect_size_selector: Optional[EffectSizeSelector] = None
        self._event_types_group: Optional[QGroupBox] = None
        self._active_groups_group: Optional[QGroupBox] = None
        self._test_controls_group: Optional[QGroupBox] = None
        self._test_method_layout: Optional[QHBoxLayout] = None
        self._test_label: Optional[QLabel] = None
        self._correction_layout: Optional[QHBoxLayout] = None
        self._correction_label: Optional[QLabel] = None
        self._stats_group: Optional[QGroupBox] = None
        self._height = HeightClass.REGULAR
        self._arrangement = Arrangement.ROW
        self._setup_ui()

    def _setup_ui(self):
        """Create the 4 sections and arrange them in one row"""
        grid = QGridLayout(self)
        grid.setContentsMargins(Space.X1, Space.X1, Space.X1, Space.X1)
        grid.setSpacing(Space.X2)
        # Created once; an arrangement only places them in the grid.
        self._sections = (
            self._create_event_types_section(),
            self._create_active_groups_section(),
            self._create_test_controls_section(),
            self._create_statistics_section(),
        )
        self._arrange_in_row()

    def _arrange_in_row(self) -> None:
        """ROW: Event Types | Active Groups | Controls | Statistics Table.

        The 2:2:3:7 section ratio (total 14) is expressed purely through column
        stretch factors — Qt's layout engine distributes width and reflows on
        resize. The table's 7 equals Event-Types + Active-Groups + Controls
        (2+2+3), so the Statistics Table gets half the strip until the setup
        sections reach their caps on a wide panel; the table takes the rest.
        Versus the previous 1:1:2:3, Event Types and Active Groups keep their
        14.3% each (1/7 == 2/14); only the Controls box narrows (28.6% ->
        21.4%) to donate the table's extra width.
        """
        grid = self.layout()
        for row in range(grid.rowCount()):
            grid.setRowStretch(row, 0)
        for column, (section, stretch) in enumerate(zip(self._sections, _SECTION_STRETCH)):
            grid.addWidget(section, 0, column)
            grid.setColumnStretch(column, stretch)
        for section, max_width in zip(self._sections, _SETUP_SECTION_MAX_W):
            section.setMaximumWidth(max_width)
        self.stats_table.setMinimumHeight(0)

    def _arrange_stacked(self) -> None:
        """STACKED: Event Types | Active Groups | Controls above the Statistics
        Table, which spans their width.

        The setup sections keep their 2:2:3 share of the width, without caps;
        the table shows its header and at least _STACKED_TABLE_ROWS rows.
        """
        grid = self.layout()
        *setup, table = self._sections
        for column, (section, stretch) in enumerate(zip(setup, _SECTION_STRETCH)):
            grid.addWidget(section, 0, column)
            grid.setColumnStretch(column, stretch)
            section.setMaximumWidth(_UNCAPPED)
        grid.setColumnStretch(len(setup), 0)
        grid.addWidget(table, 1, 0, 1, len(setup))
        for row, stretch in enumerate(_STACKED_ROW_STRETCH):
            grid.setRowStretch(row, stretch)
        header = self.stats_table.horizontalHeader().sizeHint().height()
        rows = _STACKED_TABLE_ROWS * self._stats_columns.row_height()
        self.stats_table.setMinimumHeight(header + rows + 2 * self.stats_table.frameWidth())

    def apply_density(self, density: Density) -> None:
        """Adapt to the page's density: compact controls and group spacing, and
        the ROW or STACKED arrangement. Idempotent; sections are re-placed,
        never re-created.

        Compact controls are ~28 px tall: the "density" property selects the
        [density="compact"] rules of style.qss, which only take effect once the
        controls are re-polished.
        """
        if density.height is not self._height:
            self._height = density.height
            self._active_groups_group.layout().setSpacing(
                DENSITY_SPECS[density.height.value].group_spacing)
            self.setProperty("density", density.height.value)
            for widget in self.findChildren(QWidget):
                if isinstance(widget, _DENSITY_STYLED):
                    widget.style().unpolish(widget)
                    widget.style().polish(widget)
        if density.arrangement is not self._arrangement:
            self._arrangement = density.arrangement
            for section in self._sections:
                self.layout().removeWidget(section)
            if density.arrangement is Arrangement.STACKED:
                self._arrange_stacked()
            else:
                self._arrange_in_row()

    def row_minimum_width(self) -> int:
        """The narrowest the panel gets with its four sections side by side."""
        grid = self.layout()
        margins = grid.contentsMargins()
        sections = sum(grid.itemAt(grid.indexOf(section)).minimumSize().width()
                       for section in self._sections)
        return (sections + (len(self._sections) - 1) * grid.horizontalSpacing()
                + margins.left() + margins.right())

    def section_stretches(self) -> List[int]:
        """Each section's width stretch, in order: Event Types, Active Groups,
        Controls, Statistics Table."""
        grid = self.layout()
        return [grid.columnStretch(grid.getItemPosition(grid.indexOf(section))[1])
                for section in self._sections]

    @staticmethod
    def _strip_groupbox_frame(group: QGroupBox) -> None:
        """Render a section container flat — no default QGroupBox frame — so its
        controls sit directly on the page background for a minimal aesthetic.

        With the app-wide stylesheet active and no ``QGroupBox`` rule in it, an
        unstyled group box paints Qt's default rounded frame (the "white box"
        behind each section). Suppressing it in one place keeps all four
        sections frameless and uniform.
        """
        group.setFlat(True)
        group.setStyleSheet(
            "QGroupBox { border: none; background: transparent; margin: 0; padding: 0; }"
        )

    def _create_event_types_section(self) -> QGroupBox:
        """Create the Event Types list section"""
        group = QGroupBox("")
        self._strip_groupbox_frame(group)
        self._event_types_group = group
        layout = QVBoxLayout(group)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(1)

        # Event types list (multi-select; greyscale selection)
        self.event_types_list = _ElidedList()
        self.event_types_list.setSelectionMode(QAbstractItemView.MultiSelection)
        self.event_types_list.setStyleSheet(f"""
            QListWidget {{
                border: none;
                border-radius: 4px;
                padding: 4px;
            }}
            QListWidget::item {{
                padding: 4px;
                border-radius: 2px;
            }}
            QListWidget::item:selected {{
                background-color: {Theme.NEUTRAL_MID};
                color: white;
            }}
        """)
        layout.addWidget(self.event_types_list)

        # Buttons
        btn_layout = QHBoxLayout()

        self.add_to_group1_btn = QPushButton("→ Group 1")
        self.add_to_group1_btn.clicked.connect(lambda: self._add_to_group(1))
        self.add_to_group1_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {Theme.JADE};
                color: white;
                border: none;
                padding: 4px 8px;
                border-radius: 4px;
                font-weight: bold;
                font-size: 10px;
            }}
            QPushButton:hover {{
                background-color: {Theme.JADE_DARK};
            }}
            QPushButton:disabled {{
                background-color: #cbd5e1;
                color: #64748b;
            }}
        """)
        btn_layout.addWidget(self.add_to_group1_btn)

        self.add_to_group2_btn = QPushButton("→ Group 2")
        self.add_to_group2_btn.clicked.connect(lambda: self._add_to_group(2))
        self.add_to_group2_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {Theme.ROSE};
                color: white;
                border: none;
                padding: 4px 8px;
                border-radius: 4px;
                font-weight: bold;
                font-size: 10px;
            }}
            QPushButton:hover {{
                background-color: {Theme.ROSE_DARK};
            }}
            QPushButton:disabled {{
                background-color: #cbd5e1;
                color: #64748b;
            }}
        """)
        btn_layout.addWidget(self.add_to_group2_btn)

        layout.addLayout(btn_layout)

        return group

    def _create_active_groups_section(self) -> QGroupBox:
        """Create the Active Groups display section"""
        group = QGroupBox("")
        self._strip_groupbox_frame(group)
        self._active_groups_group = group
        layout = QVBoxLayout(group)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(DENSITY_SPECS["regular"].group_spacing)

        # Group 1 label and list (Jade — manuscript non-craving). Each list shows
        # at least DENSITY_SPECS' list_rows whole rows, and its label's tooltip
        # names every member, so membership can be checked before Compare (D11).
        member_rows = DENSITY_SPECS["regular"].list_rows
        self.group1_label = QLabel("Group 1 (n=0)")
        self.group1_label.setStyleSheet(f"font-weight: bold; color: {Theme.JADE}; background-color: transparent; font-size: 11px;")
        layout.addWidget(self.group1_label)

        self.group1_list = _ElidedList(full_rows=member_rows)
        self.group1_list.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        self.group1_list.setStyleSheet(f"""
            QListWidget {{
                border: none;
                border-radius: 4px;
                padding: 2px;
                background-color: {Theme.JADE_LIGHT};
            }}
        """)
        layout.addWidget(self.group1_list)

        # Group 2 label and list (Rose — manuscript craving)
        self.group2_label = QLabel("Group 2 (n=0)")
        self.group2_label.setStyleSheet(f"font-weight: bold; color: {Theme.ROSE_DARK}; background-color: transparent; font-size: 11px;")
        layout.addWidget(self.group2_label)

        self.group2_list = _ElidedList(full_rows=member_rows)
        self.group2_list.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        self.group2_list.setStyleSheet(f"""
            QListWidget {{
                border: none;
                border-radius: 4px;
                padding: 2px;
                background-color: {Theme.ROSE_LIGHT};
            }}
        """)
        layout.addWidget(self.group2_list)

        # Clear groups button (greyscale, manuscript dark — clearing action)
        self.clear_groups_btn = QPushButton("Reset")
        self.clear_groups_btn.clicked.connect(self._clear_groups)
        self.clear_groups_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {Theme.NEUTRAL_DARK};
                color: white;
                border: none;
                padding: 6px 12px;
                border-radius: 4px;
            }}
            QPushButton:hover {{
                background-color: {Theme.NEUTRAL_DARK_HOVER};
            }}
            QPushButton:pressed {{
                background-color: {Theme.NEUTRAL_DARK_PRESSED};
            }}
        """)
        reset_row = QHBoxLayout()
        self._add_capped(reset_row, self.clear_groups_btn, Dim.BUTTON_MAX_W)
        layout.addLayout(reset_row)

        return group

    def _create_test_controls_section(self) -> QGroupBox:
        """Create the Statistical Test Controls section"""
        group = QGroupBox("")
        self._strip_groupbox_frame(group)
        self._test_controls_group = group
        layout = QVBoxLayout(group)
        layout.setSpacing(1)
        layout.setContentsMargins(0, 0, 0, 0)

        # Custom control widget (e.g., time window spinbox or frequency band input)
        custom_control = self._create_custom_control_widget()
        if custom_control:
            layout.addWidget(custom_control)
            self._add_expanding_gap(layout)

        # Test method row — wrapped in a QWidget so subclasses that need to
        # hide the entire row (ML page) can ``setVisible(False)`` on the
        # wrapper and have its layout slot fully reclaimed. Hiding the
        # individual widgets only collapses their internal HBox without
        # freeing the QVBoxLayout slot, leaving a residual gap.
        self._test_row_widget = QWidget()
        test_method_layout = QHBoxLayout(self._test_row_widget)
        test_method_layout.setContentsMargins(0, 0, 0, 0)
        test_method_layout.setSpacing(8)

        test_label = QLabel("Test:")
        test_label.setStyleSheet("font-weight: bold; background-color: transparent; font-size: 11px;")
        test_label.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)
        test_method_layout.addWidget(test_label)
        self._test_method_layout = test_method_layout
        self._test_label = test_label

        # Elide-instead-of-dictate-width (see selector_combo_style): keeps this
        # combo from forcing the controls column wider than its stretch share,
        # which is what skewed the canonical-bands table width relative to the
        # other pages.
        self.test_method_combo = ElidingComboBox()
        self.test_method_combo.addItems([
            "Mann-Whitney U",
            "Independent t-test",
            "Welch's t-test",
            "Wilcoxon Rank-Sum"
        ])
        self.test_method_combo.setCurrentText("Mann-Whitney U")
        apply_selector_combo_style(self.test_method_combo)
        self.test_method_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._add_capped(test_method_layout, self.test_method_combo)

        layout.addWidget(self._test_row_widget)
        self._add_expanding_gap(layout)

        # Correction method row — wrapped in a QWidget for the same reason
        # as the test row above (ML subclass hides this whole wrapper).
        self._correction_row_widget = QWidget()
        correction_method_layout = QHBoxLayout(self._correction_row_widget)
        correction_method_layout.setContentsMargins(0, 0, 0, 0)
        correction_method_layout.setSpacing(8)

        correction_label = QLabel("Correction:")
        correction_label.setStyleSheet("font-weight: bold; background-color: transparent; font-size: 11px;")
        correction_label.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)
        correction_method_layout.addWidget(correction_label)
        self._correction_layout = correction_method_layout
        self._correction_label = correction_label

        # Eliding like the Test combo. The long "FDR (Benjamini-Hochberg)" item
        # is precisely what set the canonical-bands controls column's 243 px
        # floor; eliding removes it.
        self.correction_method_combo = ElidingComboBox()
        self.correction_method_combo.addItems([
            "FDR (Benjamini-Hochberg)",
            "FDR (Benjamini-Yekutieli)",
            "Bonferroni",
            "Holm",
            "Holm-Sidak",
            "None"
        ])
        self.correction_method_combo.setCurrentText("FDR (Benjamini-Hochberg)")
        apply_selector_combo_style(self.correction_method_combo)
        self.correction_method_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._add_capped(correction_method_layout, self.correction_method_combo)

        layout.addWidget(self._correction_row_widget)
        self._add_expanding_gap(layout)

        # Effect size selector
        self.effect_size_selector = EffectSizeSelector()
        layout.addWidget(self.effect_size_selector)
        self._add_expanding_gap(layout, stretch=2)

        # Compare button (greyscale, manuscript mid — primary action)
        self.compare_btn = QPushButton("Compare Groups")
        self.compare_btn.clicked.connect(self._request_comparison)
        self.compare_btn.setEnabled(False)
        self.compare_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {Theme.NEUTRAL_MID};
                color: white;
                border: none;
                padding: 6px 10px;
                border-radius: 4px;
                font-weight: bold;
                font-size: 11px;
            }}
            QPushButton:hover {{
                background-color: {Theme.NEUTRAL_MID_HOVER};
            }}
            QPushButton:pressed {{
                background-color: {Theme.NEUTRAL_MID_PRESSED};
            }}
            QPushButton:disabled {{
                background-color: #cbd5e1;
                color: #64748b;
            }}
        """)
        compare_row = QHBoxLayout()
        self._add_capped(compare_row, self.compare_btn, Dim.BUTTON_MAX_W)
        layout.addLayout(compare_row)

        return group

    def _create_statistics_section(self) -> QGroupBox:
        """Create the Statistics Table section"""
        group = QGroupBox("")
        self._strip_groupbox_frame(group)
        layout = QVBoxLayout(group)
        layout.setContentsMargins(0, 0, 0, 0)

        # Statistics table
        headers = self._get_stats_table_headers()
        self.stats_table = QTableWidget()
        self.stats_table.setColumnCount(len(headers))
        self.stats_table.setHorizontalHeaderLabels(headers)

        # Read-only: a stray keypress or double-click must never overwrite a
        # statistic that Copy Table then exports. Copying goes through Cmd/Ctrl+C
        # on a selection and the Copy · Copy Row · Copy Table context menu,
        # which use Copy Table's cell strings.
        self.stats_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.stats_table_copy = TableCopyActions(self.stats_table)
        self.stats_table_copy.copy_table_action.triggered.connect(self.copy_table_requested)

        # Style the table. Row numbers carry no information (Copy Table never
        # copied them) and cost 22–31 px of width.
        self.stats_table.setAlternatingRowColors(True)
        self.stats_table.verticalHeader().hide()
        self.stats_table.setStyleSheet(_stats_table_qss(tight=False))
        # Columns as wide as their content: they fill the table when they fit
        # and scroll inside it when they don't; rows are one line of its font.
        self._stats_columns = _StatsTableColumns(self.stats_table)
        _ShiftWheelScrollsSideways(self.stats_table)

        layout.addWidget(self.stats_table)

        self._stats_group = group
        return group

    @staticmethod
    def _add_capped(row: QHBoxLayout, widget: QWidget, max_width: int = Dim.FIELD_MAX_W) -> None:
        """Add ``widget`` as the last item of ``row``: it fills the row up to
        ``max_width``, and a wider row leaves the rest empty on the right rather
        than spreading the row's widgets apart. Fields take the default cap."""
        widget.setMaximumWidth(max_width)
        row.addWidget(widget, 1)
        row.addStretch()

    def _add_expanding_gap(self, layout: QVBoxLayout, stretch: int = 1):
        """Insert a gap that expands to soak up vertical slack."""
        spacer = QSpacerItem(0, 1, QSizePolicy.Minimum, QSizePolicy.Expanding)
        layout.addItem(spacer)
        layout.setStretch(layout.count() - 1, stretch)

    # Public API methods

    def set_available_event_types(self, event_types: Dict[str, int]):
        """
        Set the available event types with their counts.

        Parameters
        ----------
        event_types : Dict[str, int]
            Dictionary of {event_type: count}
        """
        self._available_event_types = event_types
        self.event_types_list.clear()

        for event_type, count in sorted(event_types.items()):
            # The actual event type rides in UserRole.
            self.event_types_list.add_named(f"{event_type} (n={count})", event_type)

    def get_group_events(self, group_id: int) -> List[str]:
        """Get the event types in a specific group"""
        return self._active_groups.get(group_id, [])

    def get_selected_test_method(self) -> str:
        """Get the currently selected test method"""
        return self.test_method_combo.currentText()

    def get_selected_correction_method(self) -> str:
        """Get the currently selected correction method"""
        return self.correction_method_combo.currentText()

    def clear_statistics_table(self):
        """Clear all statistics results"""
        self.stats_table.setRowCount(0)

    # Private helper methods

    def _add_to_group(self, group_id: int):
        """Assign the currently-selected event types to ``group_id``.

        Accumulate-and-move semantics: each selected type is appended to the
        target group (deduplicated, insertion order preserved) and removed from
        the *other* group, so a given type belongs to exactly one group at a
        time. The list selection is then cleared so the next pick starts from a
        clean slate — this is the frictionless behaviour: you can build a group
        up across several picks without re-selecting prior choices, and
        re-selecting an already-grouped type and sending it to the other group
        relocates (moves) it rather than duplicating it.

        A move can mutate the other group too, so both group displays are
        refreshed (the previous implementation replaced the target group's
        contents wholesale and refreshed only that one).
        """
        selected_items = self.event_types_list.selectedItems()
        if not selected_items:
            return

        other_group_id = 2 if group_id == 1 else 1

        for item in selected_items:
            event_type = item.data(Qt.UserRole)
            # Move: drop the type from the other group if it lived there.
            if event_type in self._active_groups[other_group_id]:
                self._active_groups[other_group_id].remove(event_type)
            # Accumulate + dedup: append to the target group if not already in.
            if event_type not in self._active_groups[group_id]:
                self._active_groups[group_id].append(event_type)

        # Auto-deselect so the next batch is a clean pick (the friction fix).
        self.event_types_list.clearSelection()

        # Refresh both groups — a move above may have changed the other one.
        self._update_group_display(group_id)
        self._update_group_display(other_group_id)
        self._update_compare_button_state()

    def _update_group_display(self, group_id: int):
        """Update the display for a specific group: its list, its label and the
        label's tooltip, which names every member without hovering the list."""
        event_types = self._active_groups[group_id]
        if group_id == 1:
            members, label = self.group1_list, self.group1_label
        else:
            members, label = self.group2_list, self.group2_label

        rows = []
        total_count = 0
        for et in event_types:
            count = self._available_event_types.get(et, 0)
            total_count += count
            rows.append(f"{et} (n={count})")
        members.clear()
        for row in rows:
            members.add_named(row)
        label.setText(f"Group {group_id} (n={total_count})")
        label.setToolTip(wrap_tooltip("\n".join(rows)) if rows else "")

    def clear_active_groups(self):
        """Reset both active groups, the displayed lists, the labels, and the
        Compare button state. **Does not** emit :attr:`group_cleared` — use
        this when the *system* (e.g. a patient switch) needs to drop stale
        selections without triggering Reset-button-style side effects in
        listening views (which typically also wipe ViewModel state)."""
        self._active_groups = {1: [], 2: []}
        self._update_group_display(1)
        self._update_group_display(2)
        self._update_compare_button_state()

    def _clear_groups(self):
        """Reset-button handler: clear visual state and emit ``group_cleared``
        so views/ViewModels can wipe the rest of their analysis state in
        response to an explicit user reset."""
        self.clear_active_groups()
        self.group_cleared.emit()

    def _update_compare_button_state(self):
        """Enable/disable compare button based on group contents"""
        has_both_groups = (
            len(self._active_groups[1]) > 0 and
            len(self._active_groups[2]) > 0
        )
        self.compare_btn.setEnabled(has_both_groups)

    def _request_comparison(self):
        """Emit signal to request comparison analysis - delegates to subclass"""
        group1 = self._active_groups[1]
        group2 = self._active_groups[2]
        test_method = self.get_selected_test_method()
        correction = self.get_selected_correction_method()

        self._emit_comparison_signal(group1, group2, test_method, correction)

    # Abstract methods for subclass customization (must be implemented by subclasses)

    def _create_custom_control_widget(self) -> Optional[QWidget]:
        """
        Create the custom control widget (e.g., time window spinbox, frequency band input).

        Returns
        -------
        Optional[QWidget]
            The custom control widget, or None if not needed

        Raises
        ------
        NotImplementedError
            Must be implemented by subclass
        """
        raise NotImplementedError("Subclass must implement _create_custom_control_widget")

    def _get_stats_table_headers(self) -> List[str]:
        """
        Return the column headers for the statistics table.

        Returns
        -------
        List[str]
            List of column header labels

        Raises
        ------
        NotImplementedError
            Must be implemented by subclass
        """
        raise NotImplementedError("Subclass must implement _get_stats_table_headers")

    def _emit_comparison_signal(self, group1: List[str], group2: List[str],
                                 test_method: str, correction: str):
        """
        Emit the comparison signal with appropriate parameters for this panel type.

        Panel convention: Group 1 (Jade box) carries the manuscript
        non-craving class (label 0); Group 2 (Rose box) carries craving
        (label 1). Subclasses must preserve this ordering when forwarding
        ``group1`` / ``group2`` to their downstream ViewModel — the analysis
        service relies on it.

        Parameters
        ----------
        group1 : List[str]
            Event types in Group 1 (Jade — non-craving).
        group2 : List[str]
            Event types in Group 2 (Rose — craving).
        test_method : str
            Selected statistical test method
        correction : str
            Selected multiple comparison correction method

        Raises
        ------
        NotImplementedError
            Must be implemented by subclass
        """
        raise NotImplementedError("Subclass must implement _emit_comparison_signal")

    def update_statistics_table(self, results_data: List[dict]):
        """
        Update the statistics table with results (format varies by panel type).

        Default implementation is a no-op. Subclasses whose result schema
        matches the dict-of-rows contract may override; subclasses with a
        different schema (e.g. the Snapshots 5 Hz Band panel) should ignore this
        method and surface results through their own population API
        (``populate_ml_table`` etc.). Previously this method raised
        ``NotImplementedError`` which forced every subclass to ship a
        thrower of its own.

        Parameters
        ----------
        results_data : List[dict]
            List of result dictionaries (structure varies by subclass)
        """
        del results_data  # default: do nothing
