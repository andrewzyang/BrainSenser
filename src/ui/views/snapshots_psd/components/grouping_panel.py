"""
Grouping Panel Component for Snapshots PSD Analysis

This panel enables flexible event grouping and statistical test configuration,
matching the Timeline + Snapshots page's UX pattern.
"""

from typing import List, Optional
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QLineEdit,
    QTableWidgetItem
)
from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QColor

from src.ui.components.base_grouping_panel import BaseGroupingPanel
from src.ui.theme import Theme


def _centred_item(text: str) -> QTableWidgetItem:
    """A centred cell, like every column of the other statistics tables."""
    item = QTableWidgetItem(text)
    item.setTextAlignment(Qt.AlignCenter)
    return item


class SnapshotsGroupingPanel(BaseGroupingPanel):
    """
    Grouping panel for Snapshots PSD analysis.
    Adds an optional timeline-style frequency band center input for custom windowing.
    """

    # Signals
    comparison_requested = Signal(list, list, str, str, object)  # group1, group2, test, correction, timeline_center

    def __init__(self):
        self.timeline_band_input: Optional[QLineEdit] = None
        self._timeline_layout: Optional[QHBoxLayout] = None
        self._timeline_label: Optional[QLabel] = None
        self._timeline_suffix_label: Optional[QLabel] = None
        self._timeline_input_default_style = ""
        self._timeline_input_error_style = ""
        super().__init__()

    def _create_custom_control_widget(self) -> Optional[QWidget]:
        """Create the optional timeline band frequency input control."""
        # Container widget for the timeline band control
        container = QWidget()
        timeline_layout = QHBoxLayout(container)
        timeline_layout.setContentsMargins(0, 0, 0, 0)
        timeline_layout.setSpacing(8)

        timeline_label = QLabel("Timeline?")
        timeline_label.setStyleSheet("font-weight: bold; background-color: transparent; font-size: 11px;")
        timeline_layout.addWidget(timeline_label)

        self._timeline_input_default_style = """
            QLineEdit {
                border: 1px solid #cbd5e1;
                border-radius: 4px;
                padding: 4px;
                font-size: 10px;
            }
            QLineEdit:focus {
                border: 1px solid #3353a5;
            }
        """
        self._timeline_input_error_style = """
            QLineEdit {
                border: 1px solid #ef4444;
                border-radius: 4px;
                padding: 4px;
                font-size: 10px;
            }
            QLineEdit:focus {
                border: 1px solid #ef4444;
            }
        """

        timeline_input = QLineEdit()
        timeline_input.setPlaceholderText("N/A")
        timeline_input.setFixedWidth(40)
        timeline_input.setStyleSheet(self._timeline_input_default_style)
        timeline_layout.addWidget(timeline_input)

        timeline_suffix = QLabel("±2.5 Hz")
        timeline_suffix.setStyleSheet("color: #64748b; background-color: transparent; font-size: 10px;")
        timeline_layout.addWidget(timeline_suffix)

        timeline_layout.addStretch()

        # Store references
        self._timeline_layout = timeline_layout
        self._timeline_label = timeline_label
        self.timeline_band_input = timeline_input
        self._timeline_suffix_label = timeline_suffix

        return container

    def _get_stats_table_headers(self) -> List[str]:
        """Return column headers for snapshots PSD analysis."""
        return [
            "Band", "Freq Range", "G1 Median", "G2 Median",
            "Median Δ 95% CI", "p-value", "p-corrected",
            "Effect Size", "Effect Size 95% CI"
        ]

    def _emit_comparison_signal(self, group1: List[str], group2: List[str],
                                 test_method: str, correction: str):
        """Emit the comparison signal for snapshots PSD analysis."""
        timeline_center = self.get_timeline_band_center()

        if self.timeline_band_input:
            # Provide simple visual feedback for invalid input
            invalid_text = self.timeline_band_input.text().strip()
            if (
                timeline_center is None
                and invalid_text
                and invalid_text.upper() != "N/A"
            ):
                self.timeline_band_input.setStyleSheet(self._timeline_input_error_style)
            else:
                # Reset to default styling when valid / cleared
                self.timeline_band_input.setStyleSheet(self._timeline_input_default_style)

        self.comparison_requested.emit(group1, group2, test_method, correction, timeline_center)

    def update_statistics_table(self, results_data: List[dict]):
        """
        Update the statistics table with band comparison results.

        Parameters
        ----------
        results_data : List[dict]
            List of result dictionaries with keys:
            - band_label: str
            - freq_range: str
            - group1_median_text: str
            - group2_median_text: str
            - central_tendency_ci_text: str
            - p_value_text: str
            - p_value_highlight: bool
            - q_value_text: str
            - q_value_highlight: bool
            - effect_size_value_text: str
            - effect_size_ci_text: str
        """
        self.stats_table.setRowCount(len(results_data))

        for row, data in enumerate(results_data):
            # Band name
            self.stats_table.setItem(row, 0, _centred_item(data['band_label']))
            # Frequency range
            self.stats_table.setItem(row, 1, _centred_item(data['freq_range']))
            # Group 1 median
            self.stats_table.setItem(row, 2, _centred_item(data['group1_median_text']))
            # Group 2 median
            self.stats_table.setItem(row, 3, _centred_item(data['group2_median_text']))
            # Median difference CI
            self.stats_table.setItem(row, 4, _centred_item(data['central_tendency_ci_text']))
            # p-value
            p_item = _centred_item(data['p_value_text'])
            if data.get('p_value_highlight'):
                p_item.setBackground(QColor(Theme.TABLE_HIGHLIGHT_BG))
            self.stats_table.setItem(row, 5, p_item)
            # p-corrected
            p_corr_item = _centred_item(data['q_value_text'])
            if data.get('q_value_highlight'):
                p_corr_item.setBackground(QColor(Theme.TABLE_HIGHLIGHT_BG))
            self.stats_table.setItem(row, 6, p_corr_item)
            # Effect size
            self.stats_table.setItem(row, 7, _centred_item(data['effect_size_value_text']))
            # Effect size 95% CI
            self.stats_table.setItem(row, 8, _centred_item(data['effect_size_ci_text']))

    # Public API methods specific to snapshots panel

    def get_timeline_band_center(self) -> Optional[float]:
        """
        Get the user-specified center frequency for the optional 5 Hz band.

        Returns
        -------
        Optional[float]
            Center frequency in Hz, or None if disabled/invalid
        """
        if not self.timeline_band_input:
            return None

        text = self.timeline_band_input.text().strip()
        if not text or text.upper() == "N/A":
            return None

        try:
            value = float(text)
        except ValueError:
            return None

        if value <= 0:
            return None

        return value

    def set_timeline_band_center(self, value: Optional[float]):
        """
        Set the timeline band center input.

        Parameters
        ----------
        value : Optional[float]
            Frequency in Hz, or None to clear / show N/A
        """
        if not self.timeline_band_input:
            return

        if value is None:
            self.timeline_band_input.setText("")
        else:
            self.timeline_band_input.setText(f"{value:.2f}")

        if self.timeline_band_input:
            self.timeline_band_input.setStyleSheet(self._timeline_input_default_style)

    def get_selected_hemisphere(self) -> str:
        """Get the currently selected hemisphere - always returns BOTH"""
        return "BOTH"

    def set_effect_size_header(self, display_name: str):
        """
        Update the effect size column headers based on the selected metric.

        Parameters
        ----------
        display_name : str
            Human-readable name of the effect size (e.g., "Cohen's d")
        """
        value_header = display_name or "Effect Size"
        value_item = self.stats_table.horizontalHeaderItem(7)
        if value_item:
            value_item.setText(value_header)

        ci_header = self.stats_table.horizontalHeaderItem(8)
        if ci_header:
            ci_header.setText(f"{value_header} 95% CI")

    def set_central_tendency_header(self, header_text: str):
        """Update the central tendency CI column header."""
        central_header = header_text or "Median Δ 95% CI"
        header_item = self.stats_table.horizontalHeaderItem(4)
        if header_item:
            header_item.setText(central_header)
