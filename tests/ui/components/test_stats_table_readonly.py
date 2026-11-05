"""
Statistics tables are read-only and copy with Copy Table's strings (plan M0.6, D7).

Runs on a real MainWindow filled with the deterministic synthetic results of
``tests/ui/_synthetic.py`` — never patient data. On every analysis page: no
key, click, double-click or F2 changes a cell; Cmd/Ctrl+C on a range copies the
matching block of the page's Copy Table text; Copy Row copies its lines; the
context menu offers Copy · Copy Row · Copy Table, and its Copy Table does what
the top-bar button does.
"""

import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QPoint, QSettings, Qt
from PySide6.QtGui import QContextMenuEvent, QGuiApplication, QKeySequence
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QLineEdit, QMessageBox, QTableWidget,
    QTableWidgetSelectionRange,
)

from src.ui.components.table_copy import table_tsv
from tests.ui._synthetic import populate_main_window, settle

PAGES = ["snapshots_canonical_bands", "snapshots_5hz_band",
         "timeline_lfp_threshold", "timeline_peri_event"]
SENTINEL = "clipboard before the copy"


@pytest.fixture(scope="module")
def window(qapp, tmp_path_factory):
    """One populated MainWindow for the module (building it takes ~3 s)."""
    import main
    import src.domain.effect_size_preference as effect_size_preference
    from src.ui.app_bootstrap import build_presentation

    # Module fixtures are set up before the per-test isolation in
    # tests/conftest.py, so keep the preference store off the real plist here.
    ini_path = tmp_path_factory.mktemp("qsettings") / "iEEG-App.ini"
    with pytest.MonkeyPatch.context() as patcher:
        patcher.setattr(effect_size_preference, "QSettings",
                        lambda *_args, **_kwargs: QSettings(str(ini_path), QSettings.Format.IniFormat))
        effect_size_preference.EffectSizePreference.reset_singleton()
        win = main.MainWindow(container=build_presentation().container)
        win.resize(1280, 769)
        win.show()
        populate_main_window(win, Path(os.environ["BRAINSENSER_DATA_DIR"]))
        yield win
        win.close()
        win.deleteLater()
        qapp.processEvents()
    effect_size_preference.EffectSizePreference.reset_singleton()


@pytest.fixture(params=PAGES)
def page(request, window, monkeypatch):
    """The analysis page under test, shown."""
    window.main_layout.switch_page(request.param)
    view = window.main_layout.get_page(request.param)
    # The Snapshots pages gate Copy Table on their ViewModel's results; the
    # synthetic tables are filled through the panel, so report results present.
    viewmodel = getattr(view, "viewmodel", None)
    if viewmodel is not None:
        monkeypatch.setattr(viewmodel, "has_analysis_results", lambda: True)
    settle(window, 50)
    return view


@pytest.fixture
def dialogs(monkeypatch):
    """Stand-ins for the views' static QMessageBox calls (no modal dialogs)."""
    mocks = {"information": MagicMock(), "warning": MagicMock()}
    for name, mock in mocks.items():
        monkeypatch.setattr(QMessageBox, name, mock)
    return mocks


@pytest.fixture
def clipboard(qapp):
    board = QGuiApplication.clipboard()
    board.setText(SENTINEL)
    return board


def _top_bar_copy_table(window, view, clipboard) -> str:
    """What the top-bar Copy Table button puts on the clipboard for ``view``."""
    view.export_state_changed.emit(True)
    assert window.top_bar.copy_table_button.isEnabled()
    clipboard.setText(SENTINEL)
    window.top_bar.copy_table_button.click()
    text = clipboard.text()
    assert text != SENTINEL
    return text


def _press_copy(table: QTableWidget) -> None:
    """The platform's Copy key: Cmd+C on macOS, Ctrl+C elsewhere."""
    table.setFocus()
    combo = QKeySequence(QKeySequence.StandardKey.Copy)[0]
    QTest.keyClick(table, combo.key(), combo.keyboardModifiers())


def _block(copy_table_text: str, rows, columns) -> str:
    """The cells (``rows`` × ``columns``) of Copy Table's text, as TSV."""
    lines = copy_table_text.split("\n")[1:]
    return "\n".join("\t".join(lines[row].split("\t")[column] for column in columns)
                     for row in rows)


def test_stats_tables_have_no_edit_triggers(page):
    table = page.grouping_panel.stats_table
    assert table.editTriggers() == QAbstractItemView.EditTrigger.NoEditTriggers


def test_keys_clicks_double_clicks_and_f2_never_change_a_cell(page):
    table = page.grouping_panel.stats_table
    before = table_tsv(table)
    last_row, last_column = table.rowCount() - 1, table.columnCount() - 1
    for row, column in ((0, 0), (last_row // 2, last_column // 2), (last_row, last_column)):
        index = table.model().index(row, column)
        table.scrollTo(index)
        center = table.visualRect(index).center()
        QTest.mouseClick(table.viewport(), Qt.MouseButton.LeftButton, pos=center)
        QTest.mouseClick(table.viewport(), Qt.MouseButton.LeftButton, pos=center)
        QTest.mouseDClick(table.viewport(), Qt.MouseButton.LeftButton, pos=center)
        table.setCurrentIndex(index)
        for key in (Qt.Key.Key_F2, Qt.Key.Key_Return, Qt.Key.Key_Enter,
                    Qt.Key.Key_Backspace, Qt.Key.Key_Delete, Qt.Key.Key_Space):
            QTest.keyClick(table, key)
        QTest.keyClicks(table, "9x")
        assert table.state() != QAbstractItemView.State.EditingState
    assert table.findChildren(QLineEdit) == []
    assert table_tsv(table) == before


def test_copy_key_copies_the_matching_block_of_copy_table(window, page, dialogs, clipboard):
    table = page.grouping_panel.stats_table
    copy_table_text = _top_bar_copy_table(window, page, clipboard)
    dialogs["information"].reset_mock()
    rows = range(min(2, table.rowCount()))
    columns = range(1, min(4, table.columnCount()))

    table.clearSelection()
    table.setRangeSelected(QTableWidgetSelectionRange(rows[0], columns[0], rows[-1], columns[-1]), True)
    clipboard.setText(SENTINEL)
    _press_copy(table)
    assert clipboard.text() == _block(copy_table_text, rows, columns)

    table.selectAll()
    _press_copy(table)
    assert clipboard.text() == copy_table_text.split("\n", 1)[1]
    dialogs["information"].assert_not_called()


def test_copy_row_copies_its_copy_table_line(window, page, dialogs, clipboard):
    table = page.grouping_panel.stats_table
    lines = _top_bar_copy_table(window, page, clipboard).split("\n")
    last_row = table.rowCount() - 1
    table.clearSelection()
    table.setCurrentCell(last_row, 0)
    page.grouping_panel.stats_table_copy.copy_row_action.trigger()
    assert clipboard.text() == lines[1 + last_row]


def test_context_menu_offers_copy_copy_row_copy_table(page):
    table = page.grouping_panel.stats_table
    copy = page.grouping_panel.stats_table_copy
    table.setCurrentCell(0, 0)
    pos = QPoint(5, 5)
    QApplication.sendEvent(table.viewport(), QContextMenuEvent(
        QContextMenuEvent.Reason.Mouse, pos, table.viewport().mapToGlobal(pos)))
    assert copy.menu.isVisible()
    assert [action.text() for action in copy.menu.actions()] == ["Copy", "Copy Row", "Copy Table"]
    assert all(action.isEnabled() for action in copy.menu.actions())
    copy.menu.hide()


def test_context_menu_copy_table_is_the_top_bar_copy_table(window, page, dialogs, clipboard):
    top_bar_text = _top_bar_copy_table(window, page, clipboard)
    dialogs["information"].reset_mock()
    clipboard.setText(SENTINEL)
    page.grouping_panel.stats_table_copy.copy_table_action.trigger()
    assert clipboard.text() == top_bar_text
    dialogs["information"].assert_called_once()
