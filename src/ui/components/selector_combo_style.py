"""Single source of truth for the statistical-selector dropdown look + sizing.

The grouping-panel controls column exposes several ``QComboBox`` selectors —
Test, Correction, and Effect Size. They must look identical: a flat white box
with a 1 px border, rounded corners, and a shared chevron. Historically each
combo was styled at its own call site, so they drifted apart — Effect Size
rendered as a bordered box while Test and Correction were borderless. Defining
the stylesheet once here, and applying it through :func:`apply_selector_combo_style`,
is what keeps them in lock-step.

:class:`ElidingComboBox` is the selector for the width-constrained controls
column. A plain ``QComboBox`` reports a minimum width wide enough to show its
longest item verbatim (e.g. the full "FDR (Benjamini-Hochberg)"), which makes
the whole controls column refuse to shrink past that width. Because the
bottom-strip sections share width by stretch factors *above* their minimums,
that oversized minimum is what made the canonical-bands table narrower than the
other pages at smaller window sizes. An eliding combo can be squeezed instead:
it ends its text with "…" and shows the full text as its tooltip, so the
2:2:3:7 section ratio holds on every page.

This is pure View-layer presentation config — no Model/ViewModel involvement.
"""

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QFontMetricsF, QPalette
from PySide6.QtWidgets import QComboBox, QStyle, QStyleOptionComboBox, QStylePainter

from src.ui.asset_paths import qss_url
from src.ui.theme import Theme

# Matches the look established by the Effect-Size dropdown. Keep this as the only
# definition; all three selectors reference it.
SELECTOR_COMBO_QSS = f"""
    QComboBox {{
        background-color: #ffffff;
        border: 1px solid {Theme.BORDER};
        border-radius: 4px;
        padding: 4px 8px;
        font-size: 11px;
        color: {Theme.TEXT_PRIMARY};
    }}
    QComboBox:hover {{
        border-color: {Theme.PRIMARY};
    }}
    QComboBox:disabled {{
        background-color: #f1f5f9;
        color: #94a3b8;
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
    QComboBox QAbstractItemView {{
        background-color: #ffffff;
        border: 1px solid {Theme.BORDER};
        selection-background-color: #e0e7ff;
        selection-color: {Theme.TEXT_PRIMARY};
        padding: 4px;
    }}
"""

# Minimum visible characters when an eliding combo is squeezed. The load-bearing
# quantity is the *resulting* minimum width (~108 px at this font plus the 20 px
# drop-down), which is comfortably below each page's controls-column share so the
# combo never dictates that column's width; 6 is simply the character count that
# yields it. minimumContentsLength governs only the minimum — the Expanding size
# policy plus layout stretch still let the combo grow to fill the available space.
_SHRINK_MIN_CHARS = 6


def apply_selector_combo_style(combo: QComboBox) -> None:
    """Give ``combo`` the shared selector look."""
    combo.setStyleSheet(SELECTOR_COMBO_QSS)


class ElidingComboBox(QComboBox):
    """A selector combo that may be narrower than its longest item.

    Its minimum width comes from a few characters instead of the longest item;
    when squeezed it ends its current text with "…" (Qt's own combo cuts the
    text off at the arrow) and shows the full text as its tooltip, which it
    clears again once the text fits.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.setMinimumContentsLength(_SHRINK_MIN_CHARS)
        self.currentTextChanged.connect(self._update_tooltip)

    def paintEvent(self, event) -> None:
        # QComboBox.paintEvent with the label text elided to the edit field.
        painter = QStylePainter(self)
        painter.setPen(self.palette().color(QPalette.ColorRole.Text))
        option = QStyleOptionComboBox()
        self.initStyleOption(option)
        painter.drawComplexControl(QStyle.ComplexControl.CC_ComboBox, option)
        if self.currentIndex() < 0 and self.placeholderText():
            option.palette.setBrush(QPalette.ColorRole.ButtonText, option.palette.placeholderText())
            option.currentText = self.placeholderText()
        option.currentText = self._shown_text(option.currentText)
        painter.drawControl(QStyle.ControlElement.CE_ComboBoxLabel, option)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_tooltip()

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange):
            self._update_tooltip()

    def _shown_text(self, text: str) -> str:
        """``text`` as it fits the edit field, where the selector sheet draws it.

        Up to a pixel of overflow is the last glyph's side bearing, so such a
        text still shows in full instead of losing a character to "…".
        """
        option = QStyleOptionComboBox()
        self.initStyleOption(option)
        width = self.style().subControlRect(QStyle.ComplexControl.CC_ComboBox, option,
                                            QStyle.SubControl.SC_ComboBoxEditField, self).width()
        if QFontMetricsF(self.font()).horizontalAdvance(text) <= width + 1:
            return text
        return self.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, width)

    def _update_tooltip(self) -> None:
        text = self.currentText()
        self.setToolTip(text if self._shown_text(text) != text else "")
