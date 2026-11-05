"""
Equal columns that reflow in whole steps as their container narrows.

:class:`EqualColumnsLayout` lays its items out in a grid of equal cells. The
column count is the largest of a few allowed counts — (4, 2, 1) for the data
page's statistics cards, (2, 1) for its metadata — whose columns are at least
as wide as the widest item's minimum. The count therefore follows the items'
own fonts and content rather than a window breakpoint, and an orphan row such
as 3 + 1 never appears. Every cell has the column width and the height of the
tallest item at that width.

The layout has height-for-width, so its parent learns the reflowed height in
the same layout pass. Its minimum size is optimistic, like a word-wrapped
``QLabel``'s: the widest item minimum by one row; ``heightForWidth()`` gives the
true height at a width. A pessimistic (one-column) minimum would make a
resizable scroll area keep the content at that height (plan §7, trap 9).
"""

import math
from typing import List, Optional, Sequence, Tuple

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtWidgets import QLayout, QLayoutItem, QWidget


class EqualColumnsLayout(QLayout):
    """Items in equal cells, in as many columns as fit (see the module docstring).

    ``column_counts`` are the allowed column counts; ``horizontal_spacing`` is
    the gap between columns and ``vertical_spacing`` the gap between rows.
    """

    def __init__(self, parent: Optional[QWidget] = None, *,
                 column_counts: Sequence[int] = (4, 2, 1),
                 horizontal_spacing: int = 0, vertical_spacing: int = 0) -> None:
        super().__init__(parent)
        self._column_counts = tuple(sorted(column_counts, reverse=True))
        self._horizontal_spacing = horizontal_spacing
        self._vertical_spacing = vertical_spacing
        self._items: List[QLayoutItem] = []
        self._height_for_width: Optional[Tuple[int, int]] = None  # (width, height)
        self.setContentsMargins(0, 0, 0, 0)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def columns_for_width(self, width: int) -> int:
        """How many columns ``width`` px (inside the margins) holds: the largest
        allowed count whose columns are at least the widest item minimum."""
        widest = max((item.minimumSize().width() for item in self._visible_items()), default=0)
        for count in self._column_counts:
            if count * widest + (count - 1) * self._horizontal_spacing <= width:
                return count
        return self._column_counts[-1]

    # ------------------------------------------------------------------
    # QLayout
    # ------------------------------------------------------------------

    def addItem(self, item: QLayoutItem) -> None:
        self._items.append(item)
        self.invalidate()

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> Optional[QLayoutItem]:
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int) -> Optional[QLayoutItem]:
        if not 0 <= index < len(self._items):
            return None
        item = self._items.pop(index)
        self.invalidate()
        return item

    def expandingDirections(self) -> Qt.Orientation:
        return Qt.Orientation.Horizontal

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        if self._height_for_width is None or self._height_for_width[0] != width:
            self._height_for_width = (width, self._arrange(QRect(0, 0, width, 0), apply=False))
        return self._height_for_width[1]

    def minimumSize(self) -> QSize:
        """Optimistic: the widest item minimum by one row (see the module docstring)."""
        size = QSize(0, 0)
        for item in self._visible_items():
            size = size.expandedTo(item.minimumSize())
        return size + self._margin_size()

    def sizeHint(self) -> QSize:
        """Every item side by side at its preferred width (the largest allowed count)."""
        count = self._column_counts[0]
        widest = max((item.sizeHint().width() for item in self._visible_items()), default=0)
        width = (count * widest + (count - 1) * self._horizontal_spacing
                 + self._margin_size().width())
        return QSize(width, self.heightForWidth(width))

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._arrange(rect, apply=True)

    def invalidate(self) -> None:
        self._height_for_width = None
        super().invalidate()

    # ------------------------------------------------------------------
    # Arranging
    # ------------------------------------------------------------------

    def _visible_items(self) -> List[QLayoutItem]:
        return [item for item in self._items if not item.isEmpty()]

    def _margin_size(self) -> QSize:
        margins = self.contentsMargins()
        return QSize(margins.left() + margins.right(), margins.top() + margins.bottom())

    def _columns(self, x: int, width: int) -> List[Tuple[int, int]]:
        """(x, width) of each column across ``width`` px, equal to within 1 px."""
        count = self.columns_for_width(width)
        pitch = (width + self._horizontal_spacing) / count
        edges = [x + round(i * pitch) for i in range(count + 1)]
        return [(edges[i], edges[i + 1] - edges[i] - self._horizontal_spacing)
                for i in range(count)]

    @staticmethod
    def _item_height(item: QLayoutItem, width: int) -> int:
        """The item's preferred height at ``width``, never below its minimum."""
        height = (item.heightForWidth(width) if item.hasHeightForWidth()
                  else item.sizeHint().height())
        return max(height, item.minimumSize().height())

    def _arrange(self, rect: QRect, apply: bool) -> int:
        """Lay the items out in ``rect`` (when ``apply``); the height they need."""
        items = self._visible_items()
        inner = rect.marginsRemoved(self.contentsMargins())
        if not items:
            return self._margin_size().height()
        columns = self._columns(inner.x(), inner.width())
        narrowest = min(width for _, width in columns)
        row_height = max(self._item_height(item, narrowest) for item in items)
        if apply:
            for index, item in enumerate(items):
                row, column = divmod(index, len(columns))
                x, width = columns[column]
                top = inner.y() + row * (row_height + self._vertical_spacing)
                item.setGeometry(QRect(x, top, width, row_height))
        rows = math.ceil(len(items) / len(columns))
        return (rows * row_height + (rows - 1) * self._vertical_spacing
                + self._margin_size().height())
