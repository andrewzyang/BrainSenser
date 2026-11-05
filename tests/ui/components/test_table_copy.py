"""
Tests for ``src.ui.components.table_copy``: Copy Table's TSV, selection and row
copies, Cmd/Ctrl+C on a read-only table, and the Copy · Copy Row · Copy Table
context menu.
"""

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QAction, QContextMenuEvent, QGuiApplication, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QMainWindow, QTableWidget, QTableWidgetItem,
    QTableWidgetSelectionRange,
)

from src.ui.components.table_copy import (
    TableCopyActions, cell_text, rows_tsv, selected_rows, selection_tsv, table_tsv,
)

SENTINEL = "clipboard before the copy"


def _make_table(qtbot, rows=3, columns=4) -> QTableWidget:
    table = QTableWidget(rows, columns)
    table.setHorizontalHeaderLabels([f"H{c}" for c in range(columns)])
    for row in range(rows):
        for column in range(columns):
            table.setItem(row, column, QTableWidgetItem(f"r{row}c{column}"))
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    qtbot.addWidget(table)
    return table


def _select(table: QTableWidget, top: int, left: int, bottom: int, right: int) -> None:
    table.setRangeSelected(QTableWidgetSelectionRange(top, left, bottom, right), True)


def _press_copy(qtbot, table: QTableWidget) -> None:
    """Send the platform's Copy key (Cmd+C on macOS, Ctrl+C elsewhere)."""
    combo = QKeySequence(QKeySequence.StandardKey.Copy)[0]
    qtbot.keyClick(table, combo.key(), combo.keyboardModifiers())


@pytest.fixture
def clipboard(qapp):
    board = QGuiApplication.clipboard()
    board.setText(SENTINEL)
    return board


class TestTsv:
    def test_table_tsv_is_header_then_rows(self, qtbot):
        table = _make_table(qtbot, rows=2, columns=3)
        assert table_tsv(table) == "H0\tH1\tH2\nr0c0\tr0c1\tr0c2\nr1c0\tr1c1\tr1c2"

    def test_missing_items_and_header_items_copy_as_empty(self, qtbot):
        table = _make_table(qtbot, rows=2, columns=3)
        table.takeItem(1, 1)
        table.takeHorizontalHeaderItem(2)
        assert cell_text(table, 1, 1) == ""
        assert table_tsv(table) == "H0\tH1\t\nr0c0\tr0c1\tr0c2\nr1c0\t\tr1c2"

    def test_table_without_rows_is_the_header_line(self, qtbot):
        table = _make_table(qtbot, rows=0, columns=2)
        assert table_tsv(table) == "H0\tH1"

    def test_rows_tsv_matches_copy_table_lines(self, qtbot):
        table = _make_table(qtbot)
        lines = table_tsv(table).split("\n")
        assert rows_tsv(table, [0, 2]) == "\n".join([lines[1], lines[3]])

    def test_selection_is_the_matching_block_of_copy_table(self, qtbot):
        table = _make_table(qtbot, rows=4, columns=5)
        _select(table, 1, 1, 2, 3)
        lines = table_tsv(table).split("\n")[1:]
        block = "\n".join("\t".join(line.split("\t")[1:4]) for line in lines[1:3])
        assert selection_tsv(table) == block

    def test_disjoint_selection_keeps_its_shape(self, qtbot):
        table = _make_table(qtbot)
        _select(table, 0, 0, 0, 0)
        _select(table, 2, 3, 2, 3)
        assert selection_tsv(table) == "r0c0\t\n\tr2c3"
        assert selected_rows(table) == [0, 2]

    def test_selecting_a_span_copies_it_like_copy_table(self, qtbot):
        table = _make_table(qtbot, rows=2, columns=4)
        for column in (2, 3):
            table.takeItem(1, column)
        table.item(1, 1).setText("insufficient: fewer than 5 events in Group 2")
        table.setSpan(1, 1, 1, 3)
        table.show()
        qtbot.mouseClick(table.viewport(), Qt.MouseButton.LeftButton,
                         pos=table.visualItemRect(table.item(1, 1)).center())
        copy_table_line = table_tsv(table).split("\n")[2]
        assert selection_tsv(table) == "\t".join(copy_table_line.split("\t")[1:])


class TestKeyboardCopy:
    def test_copy_key_copies_the_selection_not_the_current_cell(self, qtbot, clipboard):
        table = _make_table(qtbot)
        TableCopyActions(table)
        table.setCurrentCell(2, 3)
        table.clearSelection()
        _select(table, 0, 0, 1, 1)
        _press_copy(qtbot, table)
        assert clipboard.text() == "r0c0\tr0c1\nr1c0\tr1c1"

    def test_copy_key_without_selection_leaves_the_clipboard(self, qtbot, clipboard):
        table = _make_table(qtbot)
        TableCopyActions(table)
        table.setCurrentCell(1, 1)
        table.clearSelection()
        _press_copy(qtbot, table)
        assert clipboard.text() == SENTINEL

    def test_selected_empty_cell_copies_empty_text(self, qtbot, clipboard):
        table = _make_table(qtbot)
        TableCopyActions(table)
        table.takeItem(0, 0)
        _select(table, 0, 0, 0, 0)
        _press_copy(qtbot, table)
        assert clipboard.text() == ""

    def test_other_keys_reach_the_table(self, qtbot):
        table = _make_table(qtbot)
        TableCopyActions(table)
        combo = QKeySequence(QKeySequence.StandardKey.SelectAll)[0]
        qtbot.keyClick(table, combo.key(), combo.keyboardModifiers())
        selected = table.selectionModel().selectedIndexes()
        assert len(selected) == table.rowCount() * table.columnCount()

    def test_table_copy_wins_over_a_window_copy_shortcut(self, qtbot, clipboard):
        window = QMainWindow()
        table = _make_table(qtbot)
        window.setCentralWidget(table)
        TableCopyActions(table)
        window_copies = []
        window_copy = QAction("Copy", window)
        window_copy.setShortcut(QKeySequence(QKeySequence.StandardKey.Copy))
        window_copy.triggered.connect(lambda: window_copies.append(True))
        window.addAction(window_copy)
        qtbot.addWidget(window)
        window.show()
        window.activateWindow()
        qtbot.waitUntil(lambda: QApplication.activeWindow() is window)
        table.setFocus()
        _select(table, 1, 0, 1, 3)
        _press_copy(qtbot, table)
        assert window_copies == []
        assert clipboard.text() == "r1c0\tr1c1\tr1c2\tr1c3"


def open_context_menu(qtbot, table: QTableWidget, copy: TableCopyActions) -> None:
    """Right-click the table's viewport the way the platform does and wait for the menu."""
    table.show()
    pos = QPoint(5, 5)
    QApplication.sendEvent(table.viewport(), QContextMenuEvent(
        QContextMenuEvent.Reason.Mouse, pos, table.viewport().mapToGlobal(pos)))
    qtbot.waitUntil(copy.menu.isVisible)


class TestContextMenu:
    def test_menu_offers_copy_copy_row_copy_table(self, qtbot):
        table = _make_table(qtbot)
        copy = TableCopyActions(table)
        _select(table, 0, 0, 0, 0)
        open_context_menu(qtbot, table, copy)
        assert [action.text() for action in copy.menu.actions()] == ["Copy", "Copy Row", "Copy Table"]
        assert all(action.isEnabled() for action in copy.menu.actions())
        copy.menu.hide()

    def test_copy_entries_disabled_without_selection(self, qtbot):
        table = _make_table(qtbot)
        copy = TableCopyActions(table)
        table.clearSelection()
        open_context_menu(qtbot, table, copy)
        assert not copy.copy_action.isEnabled()
        assert not copy.copy_row_action.isEnabled()
        assert copy.copy_table_action.isEnabled()
        copy.menu.hide()

    def test_copy_table_disabled_on_an_empty_table(self, qtbot):
        table = _make_table(qtbot, rows=0)
        copy = TableCopyActions(table)
        open_context_menu(qtbot, table, copy)
        assert not copy.copy_table_action.isEnabled()
        copy.menu.hide()

    def test_copy_row_copies_full_rows_of_the_selection(self, qtbot, clipboard):
        table = _make_table(qtbot)
        copy = TableCopyActions(table)
        _select(table, 0, 2, 0, 2)
        _select(table, 2, 1, 2, 1)
        copy.copy_row_action.trigger()
        assert clipboard.text() == rows_tsv(table, [0, 2])

    def test_copy_entry_copies_the_selection(self, qtbot, clipboard):
        table = _make_table(qtbot)
        copy = TableCopyActions(table)
        _select(table, 1, 1, 2, 2)
        copy.copy_action.trigger()
        assert clipboard.text() == "r1c1\tr1c2\nr2c1\tr2c2"

    def test_copy_table_entry_only_triggers_its_action(self, qtbot, clipboard):
        table = _make_table(qtbot)
        copy = TableCopyActions(table)
        requests = []
        copy.copy_table_action.triggered.connect(lambda: requests.append(True))
        copy.copy_table_action.trigger()
        assert requests == [True]
        assert clipboard.text() == SENTINEL
