"""PageHost: the one scroll fallback every page sits in (plan §4.5).

A page gets the viewport's width and at least the viewport's height. When the
window is shorter than the page's honest minimum, the page scrolls vertically.
It never scrolls sideways: pages reflow to the width they get (tables scroll
inside themselves), and one that cannot is squeezed, which the responsive sweep
reports (I1).

The page sits in a holder whose layout reports no height-for-width unless the
page opts in, so the page is sized to max(viewport, its minimumSizeHint). One
word-wrapped label would otherwise switch the scroll area to height-for-width,
where the page's minimum height becomes the sum of its children's size hints and
a plot can no longer shrink below its last height (+615 px of scroll measured,
review 11 B1). A page that opts in (the Data page reflows its cards by width)
must keep every other child's ``sizeHint().height()`` at about its minimum.

Combos and spinboxes in the page get the wheel guard, so a wheel that scrolls
the page never changes a value on the way.
"""

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QScrollArea, QSizePolicy, QVBoxLayout, QWidget

from src.ui.widgets.wheel_guard import WheelGuard


class _HolderLayout(QVBoxLayout):
    """The holder's layout: height-for-width only if the page opted in and has it."""

    def __init__(self, height_for_width: bool, parent: QWidget):
        super().__init__(parent)
        self._height_for_width = height_for_width

    def hasHeightForWidth(self) -> bool:
        return self._height_for_width and super().hasHeightForWidth()


class PageHost(QScrollArea):
    """Vertical scroll fallback around one page (``MainLayout.add_page``)."""

    def __init__(self, page: QWidget, *, height_for_width: bool = False,
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("page_host")
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # Not a Tab stop itself: the page keeps its own focus order, and Tab to a
        # control below the fold still scrolls it into view.
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        # Transparent viewport and holder: the stack behind them paints the background.
        self.viewport().setAutoFillBackground(False)

        holder = QWidget()
        # Ignored horizontally: the holder is exactly as wide as the viewport.
        holder.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        layout = _HolderLayout(height_for_width, holder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(page)
        self.setWidget(holder)
        holder.setAutoFillBackground(False)  # setWidget() turned it on
        WheelGuard(holder)
