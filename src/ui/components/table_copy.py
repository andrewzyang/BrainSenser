"""
Tab-separated copies of a table, cell for cell as Copy Table writes them.

Copy Table, Cmd/Ctrl+C on a selection and the context menu's Copy Row all read
a cell through :func:`cell_text`, so a copied block is always the matching
block of Copy Table's output. Only item and header-item text is read — never
widths, fonts or elision — so a copy never depends on the window or the
display scale.
"""

from typing import Iterable, List

from PySide6.QtCore import QEvent, QObject, QPoint, Qt
from PySide6.QtGui import QAction, QGuiApplication, QKeySequence
from PySide6.QtWidgets import QMenu, QTableWidget


def cell_text(table: QTableWidget, row: int, column: int) -> str:
    """The text Copy Table writes for one cell ("" when it has no item)."""
    item = table.item(row, column)
    return item.text() if item else ""


def _row_line(table: QTableWidget, row: int) -> str:
    return "\t".join(cell_text(table, row, column) for column in range(table.columnCount()))


def table_tsv(table: QTableWidget) -> str:
    """Copy Table's text: the header line, then one line per row."""
    headers = []
    for column in range(table.columnCount()):
        item = table.horizontalHeaderItem(column)
        headers.append(item.text() if item else "")
    lines = ["\t".join(headers)]
    lines.extend(_row_line(table, row) for row in range(table.rowCount()))
    return "\n".join(lines)


def rows_tsv(table: QTableWidget, rows: Iterable[int]) -> str:
    """Copy Table's lines for ``rows``, full width."""
    return "\n".join(_row_line(table, row) for row in rows)


def selection_tsv(table: QTableWidget) -> str:
    """The selected cells as one block.

    The block has every row and every column that holds a selected cell, in
    table order; an unselected cell inside it is left empty, so a disjoint
    selection keeps its shape. Selecting a span selects every cell it covers,
    so a copied span matches Copy Table too.
    """
    selected = {(index.row(), index.column())
                for index in table.selectionModel().selectedIndexes()}
    rows = sorted({row for row, _ in selected})
    columns = sorted({column for _, column in selected})
    return "\n".join(
        "\t".join(cell_text(table, row, column) if (row, column) in selected else ""
                  for column in columns)
        for row in rows
    )


def selected_rows(table: QTableWidget) -> List[int]:
    """Rows holding at least one selected cell, in table order."""
    return sorted({index.row() for index in table.selectionModel().selectedIndexes()})


class TableCopyActions(QObject):
    """Copying for a read-only table.

    Cmd/Ctrl+C copies the selected block (Qt's own handler copies only the
    current cell). The context menu offers Copy · Copy Row · Copy Table. Copy
    Table only triggers :attr:`copy_table_action`; the owner connects it to the
    page's Copy Table, so the menu and the top-bar button behave identically.
    """

    def __init__(self, table: QTableWidget) -> None:
        super().__init__(table)
        self._table = table

        self.copy_action = QAction("Copy", self)
        self.copy_action.triggered.connect(self.copy_selection)
        self.copy_row_action = QAction("Copy Row", self)
        self.copy_row_action.triggered.connect(self.copy_rows)
        self.copy_table_action = QAction("Copy Table", self)

        self.menu = QMenu(table)
        self.menu.addActions([self.copy_action, self.copy_row_action, self.copy_table_action])
        table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        table.customContextMenuRequested.connect(self._show_menu)
        table.installEventFilter(self)

    def copy_selection(self) -> None:
        """Copy the selected block; without a selection the clipboard is left alone."""
        if self._table.selectionModel().hasSelection():
            QGuiApplication.clipboard().setText(selection_tsv(self._table))

    def copy_rows(self) -> None:
        """Copy every row holding a selected cell, full width."""
        rows = selected_rows(self._table)
        if rows:
            QGuiApplication.clipboard().setText(rows_tsv(self._table, rows))

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if (event.type() in (QEvent.Type.ShortcutOverride, QEvent.Type.KeyPress)
                and event.matches(QKeySequence.StandardKey.Copy)):
            # Accepting the override keeps a window-level Copy shortcut from
            # taking the key while the table has focus; the press then copies.
            event.accept()
            if event.type() == QEvent.Type.KeyPress:
                self.copy_selection()
            return True
        return super().eventFilter(watched, event)

    def _show_menu(self, pos: QPoint) -> None:
        has_selection = self._table.selectionModel().hasSelection()
        self.copy_action.setEnabled(has_selection)
        self.copy_row_action.setEnabled(has_selection)
        self.copy_table_action.setEnabled(self._table.rowCount() > 0)
        # Item views report the request position in viewport coordinates.
        self.menu.popup(self._table.viewport().mapToGlobal(pos))
