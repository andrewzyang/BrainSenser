"""
The Data page widgets set no font size of their own (plan §4.1, trap 3): the
app stylesheet owns every size. Without it, their text follows the application
font, so removing or changing ``* { font-size }`` can never revive the old
9–24 pt widget sizes. (Rendered sizes under the stylesheet: the scale-1 golden
and ``test_data_management_page_layout.TestFonts``.)
"""

import pytest
from PySide6.QtGui import QFont, QFontInfo
from PySide6.QtWidgets import QApplication, QLabel

from src.ui.components.badge import Badge
from src.ui.components.empty_state import EmptyStateWidget
from src.ui.views.data_management.components.patient_metadata_panel import PatientMetadataPanel
from src.ui.views.data_management.components.statistics_card import StatisticsCard

APP_FONT_PX = 21  # unlike any size the widgets ever set themselves

WIDGETS = {
    "statistics card": lambda: StatisticsCard(title="Snapshots"),
    "metadata panel": PatientMetadataPanel,
    "empty state": EmptyStateWidget,
    "badge": lambda: Badge("Snapshots"),
}


@pytest.mark.parametrize("make", WIDGETS.values(), ids=WIDGETS.keys())
def test_text_follows_the_application_font(qtbot, make):
    app = QApplication.instance()
    font = QFont(app.font())
    font.setPixelSize(APP_FONT_PX)
    app.setFont(font)  # the UI conftest restores the application font
    widget = make()
    qtbot.addWidget(widget)
    labels = [widget] * isinstance(widget, QLabel) + widget.findChildren(QLabel)
    texts = [label for label in labels if label.text()]
    assert texts
    assert {label.text(): QFontInfo(label.font()).pixelSize() for label in texts} == {
        label.text(): APP_FONT_PX for label in texts}
