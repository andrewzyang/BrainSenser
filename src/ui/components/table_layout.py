"""
Responsive column and row sizing for item tables.

:class:`FitColumnsController` replaces ``ResizeToContents``/``Stretch`` header
modes with one rule: columns are as wide as their content, the table fills its
viewport when that fits, and it scrolls horizontally inside itself when it
doesn't. It only sizes sections — it never sets a minimum size or a
``sizeAdjustPolicy`` on the table, so a table can't push up the minimum size
of the page it sits on.
"""

import math
from dataclasses import dataclass
from typing import Dict, List, Mapping, Optional, Sequence

from PySide6.QtCore import QEvent, QObject, QRect, QSize, Qt, QTimer
from PySide6.QtGui import QFontInfo
from PySide6.QtWidgets import (
    QAbstractItemView, QHeaderView, QStyle, QStyleOptionViewItem, QTableView,
)


@dataclass(frozen=True)
class Elastic:
    """An elastic column: it takes spare width and gives it back first.

    ``min_em`` is the narrowest it gets when the table doesn't fit, in em of
    the table's own font, so the floor follows the table's type role and the
    interface size. ``weight`` is its share, among the elastic columns, of the
    spare width and of the width given back.
    """

    min_em: float
    weight: float = 1.0


def _split(total: int, weights: Sequence[float]) -> List[int]:
    """``total`` px split by ``weights`` into integers that sum to ``total``."""
    weight_sum = sum(weights)
    parts: List[int] = []
    done, running = 0, 0.0
    for weight in weights:
        running += weight
        upto = round(total * running / weight_sum)
        parts.append(upto - done)
        done = upto
    return parts


def fit_widths(natural: Sequence[int], available: int, *,
               floors: Mapping[int, int], weights: Mapping[int, float]) -> List[int]:
    """Column widths for a viewport ``available`` px wide.

    ``natural`` are the content widths; ``floors`` and ``weights`` are keyed by
    the elastic columns. When the content fits, the spare width goes to the
    elastic columns by weight — or, with none, to every column in proportion to
    its natural width — so the widths sum to exactly ``available``. When it
    doesn't, the elastic columns give width back by weight down to their floors,
    every other column keeps its natural width, and the table scrolls.
    """
    widths = list(natural)
    spare = available - sum(widths)
    if spare >= 0:
        if weights:
            columns = sorted(weights)
            shares = [weights[c] for c in columns]
        else:
            columns, shares = range(len(widths)), list(natural)
        if sum(shares) > 0:
            for column, extra in zip(columns, _split(spare, shares)):
                widths[column] += extra
        return widths

    deficit = -spare
    active = [c for c in sorted(weights) if weights[c] > 0 and widths[c] > floors[c]]
    while deficit > 0 and active:
        for column, cut in zip(active, _split(deficit, [weights[c] for c in active])):
            cut = min(cut, widths[column] - floors[column])
            widths[column] -= cut
            deficit -= cut
        active = [c for c in active if widths[c] > floors[c]]
    return widths


class FitColumnsController(QObject):
    """Content-sized columns that fill the viewport when they fit, else scroll.

    * A column's natural width is the widest of its header section and its
      cells (the first ``resizeContentsPrecision()`` rows, cell widgets
      included with the item padding the view keeps around them). Span cells
      are skipped, so a spanned message never widens the column it starts in.
    * A content column is never narrower than its natural width, so its text
      is never elided. Columns named in ``elastic`` shrink toward their floor
      when the table doesn't fit; the view then elides in the middle, keeping
      both ends of e.g. a timestamped file name.
    * Rows are single-line and fixed at the tallest of one line of the table
      font (with the stylesheet's item padding) and the sampled cells.

    Measuring is redone only when content, header text, font or style change; a
    resize only redistributes the measured widths. Every trigger goes through
    one 0-ms timer and sections are written only when they differ, so the
    scrollbars toggling after a refit settle instead of feeding back.
    """

    def __init__(self, table: QTableView, *,
                 elastic: Optional[Mapping[int, Elastic]] = None) -> None:
        super().__init__(table)
        self._table = table
        self._viewport = table.viewport()
        self._elastic: Dict[int, Elastic] = dict(elastic or {})
        self._weights = {column: e.weight for column, e in self._elastic.items()}
        self._natural: List[int] = []
        self._floors: Dict[int, int] = {}
        self._row_height = 0
        self._stale = True

        header = table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        header.setStretchLastSection(False)
        table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        table.setWordWrap(False)
        if self._elastic:
            table.setTextElideMode(Qt.TextElideMode.ElideMiddle)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(0)
        self._timer.timeout.connect(self.refit)

        model = table.model()
        for signal in (model.modelReset, model.layoutChanged, model.dataChanged,
                       model.headerDataChanged, model.rowsInserted, model.rowsRemoved,
                       model.columnsInserted, model.columnsRemoved):
            signal.connect(self._remeasure)
        table.installEventFilter(self)
        header.installEventFilter(self)
        self._viewport.installEventFilter(self)
        # Qt destroys the controller with its table, and the table's teardown
        # still sends it events and model signals. When Python frees the table,
        # it releases the controller's Python side first, so those would fail;
        # a callable held by this connection keeps it alive until Qt drops the
        # connection, at destruction.
        self.destroyed.connect(lambda: self)
        self._timer.start()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def natural_widths(self) -> List[int]:
        """Each column's content width in px (header, cells and grid line)."""
        self._ensure_measured()
        return list(self._natural)

    def natural_width(self) -> int:
        """Width the columns need side by side without eliding anything."""
        return sum(self.natural_widths())

    def row_height(self) -> int:
        """The fixed row height in px, grid line included."""
        self._ensure_measured()
        return self._row_height

    def refit(self) -> None:
        """Size the rows and columns now (normally run by the coalescing timer)."""
        self._timer.stop()
        self._ensure_measured()
        vertical = self._table.verticalHeader()
        if vertical.defaultSectionSize() != self._row_height:
            vertical.setMinimumSectionSize(self._row_height)
            vertical.setDefaultSectionSize(self._row_height)
        header = self._table.horizontalHeader()
        widths = fit_widths(self._natural, self._viewport.width(),
                            floors=self._floors, weights=self._weights)
        for column, width in enumerate(widths):
            if header.sectionSize(column) != width:
                header.resizeSection(column, width)

    # ------------------------------------------------------------------
    # Triggers
    # ------------------------------------------------------------------

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self._viewport:
            if event.type() == QEvent.Type.Resize:
                self._timer.start()
        elif event.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange):
            self._remeasure()
        return False

    def _remeasure(self) -> None:
        self._stale = True
        self._timer.start()

    # ------------------------------------------------------------------
    # Measuring
    # ------------------------------------------------------------------

    def _ensure_measured(self) -> None:
        if self._stale:
            self._measure()

    def _measure(self) -> None:
        table = self._table
        table.ensurePolished()
        model = table.model()
        header = table.horizontalHeader()
        grid = 1 if table.showGrid() else 0
        # Sample like ResizeToContents does: resizeContentsPrecision() rows.
        rows = model.rowCount()
        precision = table.verticalHeader().resizeContentsPrecision()
        if precision > 0:
            rows = min(rows, precision)

        natural = [header.sectionSizeHint(column) for column in range(model.columnCount())]
        tallest = self._line_height()
        widget_insets = self._cell_widget_insets()
        for row in range(rows):
            for column in range(len(natural)):
                if table.rowSpan(row, column) > 1 or table.columnSpan(row, column) > 1:
                    continue
                index = model.index(row, column)
                hint = table.sizeHintForIndex(index)
                widget = table.indexWidget(index)
                if widget is not None:
                    hint = hint.expandedTo(widget.sizeHint() + widget_insets)
                natural[column] = max(natural[column], hint.width() + grid)
                tallest = max(tallest, hint.height())

        em = QFontInfo(table.font()).pixelSize()
        self._natural = natural
        self._floors = {column: min(natural[column], math.ceil(e.min_em * em))
                        for column, e in self._elastic.items()}
        self._row_height = tallest + grid
        self._stale = False

    def _line_height(self) -> int:
        """Height of a one-line text cell in the table's font and item style."""
        option = QStyleOptionViewItem()
        option.initFrom(self._table)
        option.font = self._table.font()
        option.text = "0"
        option.features = QStyleOptionViewItem.ViewItemFeature.HasDisplay
        return self._table.style().sizeFromContents(
            QStyle.ContentsType.CT_ItemViewItem, option, QSize(), self._table,
        ).height()

    def _cell_widget_insets(self) -> QSize:
        """How much smaller than its cell a cell widget is. The view places it in
        the item's text rect, inside the stylesheet's item padding and border."""
        option = QStyleOptionViewItem()
        option.initFrom(self._table)
        option.rect = QRect(0, 0, 1000, 1000)  # any cell: only the difference counts
        text = self._table.style().subElementRect(
            QStyle.SubElement.SE_ItemViewItemText, option, self._table,
        )
        return option.rect.size() - text.size()
