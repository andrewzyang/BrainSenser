"""TopBar compaction (plan M3.8; ux:U6, D14).

Too narrow for every label, the bar compacts button by button: the combo shrinks
to its minimum, then Create Patient and then Upload go icon-only; Delete
Patient… keeps its label and, last, moves into the "⋯" menu. Copy Table and Save
Plot go icon-only together. Labels come back only with 16 px to spare while the
bar is resized; a page switch fits afresh. Icon-only buttons keep a tooltip and
an accessible name; nothing is ever clipped. The buttons take focus from Tab
only and ring only then. Measured under the app stylesheet,
in a host widget (a top-level window couldn't shrink below its layout).
"""

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

from src.ui.app_style import apply_app_stylesheet
from src.ui.components.top_bar import _EXPAND_MARGIN, _STEPS, TopBar


@pytest.fixture
def host(qtbot, qapp):
    apply_app_stylesheet(qapp)  # the UI conftest restores the session's sheet
    window = QWidget()
    layout = QVBoxLayout(window)
    layout.setContentsMargins(0, 0, 0, 0)
    window.bar = TopBar()
    layout.addWidget(window.bar)
    layout.addStretch()
    qtbot.addWidget(window)
    window.resize(1080, 200)
    window.show()
    qtbot.waitExposed(window)
    return window


@pytest.fixture
def bar(host):
    return host.bar


def _resize(host, qtbot, width: int) -> None:
    """Resize, then lay out what the bar's new step changed."""
    host.resize(width, 200)
    qtbot.waitUntil(lambda: host.bar.width() == max(width, host.bar.minimumSizeHint().width()))
    QCoreApplication.sendPostedEvents(None, QEvent.Type.LayoutRequest)


def _shown(bar) -> dict:
    """Visible action buttons: name -> text ("" when icon-only)."""
    buttons = {"create": bar.create_button, "upload": bar.upload_button,
               "delete": bar.delete_button, "more": bar.overflow_button,
               "copy": bar.copy_table_button, "save": bar.save_plot_button}
    return {name: b.text() for name, b in buttons.items() if b.isVisible()}


def _required(bar) -> list:
    return [bar._required_width(step) for step in _STEPS]


def test_all_labels_when_wide(bar):
    assert _shown(bar) == {"create": "Create Patient", "upload": "Upload",
                           "delete": "Delete Patient…"}


def test_buttons_compact_one_by_one_and_delete_keeps_its_label(host, bar, qtbot):
    full, create_icon, upload_icon, overflow = _required(bar)
    assert full > create_icon > upload_icon > overflow

    _resize(host, qtbot, full)
    assert _shown(bar)["create"] == "Create Patient"
    _resize(host, qtbot, full - 1)
    assert _shown(bar) == {"create": "", "upload": "Upload", "delete": "Delete Patient…"}
    _resize(host, qtbot, create_icon - 1)
    assert _shown(bar) == {"create": "", "upload": "", "delete": "Delete Patient…"}
    _resize(host, qtbot, upload_icon - 1)
    assert _shown(bar) == {"create": "", "upload": "", "more": ""}
    assert bar.delete_button.text() == "Delete Patient…"  # never icon-only


def test_labels_return_only_with_16_px_to_spare(host, bar, qtbot):
    full, create_icon = _required(bar)[:2]
    _resize(host, qtbot, create_icon - 1)
    _resize(host, qtbot, create_icon + _EXPAND_MARGIN - 1)
    assert _shown(bar)["upload"] == ""
    _resize(host, qtbot, create_icon + _EXPAND_MARGIN)
    assert _shown(bar)["upload"] == "Upload"
    _resize(host, qtbot, full + _EXPAND_MARGIN - 1)
    assert _shown(bar)["create"] == ""
    _resize(host, qtbot, full + _EXPAND_MARGIN)
    assert _shown(bar)["create"] == "Create Patient"


def test_copy_and_save_compact_together(host, bar, qtbot):
    bar.set_buttons_visible(False)
    bar.set_timeline_buttons_visible(True)
    labelled, icons = _required(bar)[:2]
    assert _required(bar)[1:] == [icons] * 3  # one step for both
    _resize(host, qtbot, labelled)
    assert _shown(bar) == {"copy": "Copy Table", "save": "Save Plot"}
    _resize(host, qtbot, labelled - 1)
    assert _shown(bar) == {"copy": "", "save": ""}


def test_page_switch_fits_afresh(host, bar, qtbot):
    """A width inside the hysteresis band keeps icons while resizing, but a
    page switch (a discrete event) shows every label that fits."""
    full = _required(bar)[0]
    _resize(host, qtbot, full - 1)
    _resize(host, qtbot, full + _EXPAND_MARGIN // 2)
    assert _shown(bar)["create"] == ""
    bar.set_buttons_visible(False)
    bar.set_timeline_buttons_visible(True)
    bar.set_timeline_buttons_visible(False)
    bar.set_buttons_visible(True)
    assert _shown(bar)["create"] == "Create Patient"


def test_icon_only_buttons_keep_tooltips_and_accessible_names(host, bar, qtbot):
    _resize(host, qtbot, _required(bar)[3])
    assert (bar.create_button.toolTip(), bar.create_button.accessibleName()) == (
        "Create Patient", "Create Patient")
    assert (bar.upload_button.toolTip(), bar.upload_button.accessibleName()) == (
        "Upload", "Upload")
    assert (bar.overflow_button.toolTip(), bar.overflow_button.accessibleName()) == (
        "More", "More")
    bar.set_buttons_visible(False)
    bar.set_timeline_buttons_visible(True)
    _resize(host, qtbot, _required(bar)[3])
    assert bar.copy_table_button.toolTip() == "Copy statistics table"
    assert "manuscript-format figure" in bar.save_plot_button.toolTip()
    assert bar.copy_table_button.accessibleName() == "Copy Table"


def test_labelled_buttons_have_no_new_tooltips(bar):
    assert (bar.create_button.toolTip(), bar.upload_button.toolTip(),
            bar.copy_table_button.toolTip()) == ("", "", "")


def test_icon_only_buttons_are_square(host, bar, qtbot):
    _resize(host, qtbot, _required(bar)[3])
    for button in (bar.create_button, bar.upload_button, bar.overflow_button):
        assert button.width() == button.height()


def test_overflow_menu_deletes_the_patient(host, bar, qtbot):
    _resize(host, qtbot, _required(bar)[3])
    (delete,) = bar._overflow_menu.actions()
    assert delete.text() == "Delete Patient…"
    assert not delete.isEnabled() and not bar.overflow_button.isEnabled()  # no patient yet

    bar._set_patient_actions_enabled(True)
    with qtbot.waitSignal(bar.delete_patient_clicked, timeout=1000):
        delete.trigger()

    bar.overflow_button.click()
    qtbot.waitUntil(bar._overflow_menu.isVisible)
    bar._overflow_menu.close()


def test_minimum_is_the_most_compact_step(host, bar, qtbot):
    assert bar.minimumSizeHint().width() == _required(bar)[-1]
    _resize(host, qtbot, 200)
    assert bar.width() == _required(bar)[-1]


@pytest.mark.parametrize("crud", [True, False])
def test_nothing_clipped_at_any_width(host, bar, qtbot, crud):
    bar.set_buttons_visible(crud)
    bar.set_timeline_buttons_visible(not crud)
    for width in range(bar.minimumSizeHint().width(), 1100, 23):
        _resize(host, qtbot, width)
        assert bar.layout().totalMinimumSize().width() <= bar.width()
        for button in (bar.create_button, bar.upload_button, bar.delete_button,
                       bar.overflow_button, bar.copy_table_button, bar.save_plot_button):
            if button.isVisible():
                assert button.sizeHint().width() <= button.width() + 1, (width, button.text())


def test_buttons_ring_only_after_keyboard_focus(host, bar, qtbot):
    host.activateWindow()
    qtbot.waitActive(host)
    button = bar.create_button
    assert all(b.focusPolicy() == Qt.FocusPolicy.TabFocus
               for b in (bar.create_button, bar.upload_button, bar.delete_button,
                         bar.overflow_button, bar.copy_table_button, bar.save_plot_button))

    QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    assert not button.hasFocus()  # a click never focuses it

    bar.patient_dropdown.setFocus()
    QTest.keyClick(QApplication.focusWidget(), Qt.Key.Key_Tab)  # Tab onto Create Patient
    assert button.hasFocus() and button.property("focusRing")
    assert button.grab().toImage().pixelColor(0, button.height() // 2) == QColor("#ffffff")
    assert button.size() == button.sizeHint()  # the ring is drawn within the box
