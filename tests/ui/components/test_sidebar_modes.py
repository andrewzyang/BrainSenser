"""Sidebar modes: the labelled sidebar and the icon rail (plan M3.6, D4; ux:S6).

One exclusive action group drives the labelled buttons, the rail flyouts, the Go
menu and Ctrl/Cmd+1…5; the rail's flyouts open on click with the group's name
and a check on the current page; the rail's tooltips list the shortcuts and the
labelled entries have none; the logo is a link
only beside the title; the navigation scrolls when the window is short; the
header lines up with the top bar; a focus ring shows only after keyboard focus;
the footer's toggle asks for the other mode and its "Aa" button shows the
interface-size action. The sidebar holds no ViewModel. Measured under the app
stylesheet.
"""

import ast
from collections import Counter
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QAction, QColor, QDesktopServices, QKeySequence
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QMenu, QPushButton, QScrollArea,
                               QToolButton, QVBoxLayout, QWidget)

from src.ui.app_style import apply_app_stylesheet
from src.ui.components import sidebar as sidebar_module
from src.ui.components.sidebar import Sidebar
from src.ui.components.top_bar import TopBar
from src.ui.policy.tokens import Dim
from src.ui.theme import Theme

PAGES = ("data_management", "snapshots_canonical_bands", "snapshots_5hz_band",
         "timeline_peri_event", "timeline_lfp_threshold")


@pytest.fixture
def host(qtbot, qapp):
    """A shown window holding a sidebar, under the app stylesheet."""
    apply_app_stylesheet(qapp)  # the UI conftest restores the session's sheet
    window = QWidget()
    layout = QHBoxLayout(window)
    layout.setContentsMargins(0, 0, 0, 0)
    window.sidebar = Sidebar()
    layout.addWidget(window.sidebar)
    layout.addStretch()
    qtbot.addWidget(window)
    window.resize(800, 769)
    window.show()
    qtbot.waitExposed(window)
    return window


@pytest.fixture
def sidebar(host):
    return host.sidebar


def _rail_item(sidebar, name: str) -> QToolButton:
    return next(b for b in sidebar.findChildren(QToolButton, "rail_item") if b.accessibleName() == name)


def _icon_color(icon) -> str:
    """The most common opaque colour of a 16-px rendering of ``icon``."""
    image = icon.pixmap(16, 16).toImage()
    colors = Counter(image.pixelColor(x, y).name() for x in range(image.width())
                     for y in range(image.height()) if image.pixelColor(x, y).alpha() == 255)
    return colors.most_common(1)[0][0]


def _native(text: str) -> str:
    return QKeySequence(text).toString(QKeySequence.SequenceFormat.NativeText)


# --------------------------------------------------------------------- modes

def test_starts_labelled_200_px_wide(sidebar):
    assert sidebar.mode == "labels"
    assert sidebar.width() == Dim.SIDEBAR_W
    assert all(button.isVisible() for button in sidebar.nav_items.values())
    assert not any(b.isVisible() for b in sidebar.findChildren(QToolButton, "rail_item"))


def test_icons_mode_is_a_64_px_rail_without_labels(sidebar, qtbot):
    sidebar.set_mode("icons")
    qtbot.waitUntil(lambda: sidebar.width() == Dim.SIDEBAR_RAIL_W)
    assert sidebar.mode == "icons"
    assert not any(button.isVisible() for button in sidebar.nav_items.values())
    rail = sidebar.findChildren(QToolButton, "rail_item")
    assert [b.accessibleName() for b in rail] == ["Data Management", "Snapshots", "Timeline"]
    assert all(b.isVisible() and b.text() == "" for b in rail)
    assert not sidebar.findChild(QWidget, "app_title").isVisible()


def test_set_mode_is_idempotent_and_reversible(sidebar, qtbot):
    sidebar.set_mode("labels")
    assert sidebar.width() == Dim.SIDEBAR_W
    sidebar.set_mode("icons")
    sidebar.set_mode("icons")
    sidebar.set_mode("labels")
    qtbot.waitUntil(lambda: sidebar.width() == Dim.SIDEBAR_W)
    assert all(button.isVisible() for button in sidebar.nav_items.values())
    assert sidebar.findChild(QWidget, "app_title").isVisible()


def test_unknown_mode_is_rejected(sidebar):
    with pytest.raises(ValueError):
        sidebar.set_mode("expanded")


def test_mode_change_keeps_the_current_page(sidebar):
    sidebar.set_active_page("timeline_lfp_threshold")
    sidebar.set_mode("icons")
    assert _rail_item(sidebar, "Timeline").property("active") is True
    sidebar.set_mode("labels")
    assert sidebar.nav_items["timeline_lfp_threshold"].property("active") is True


# ---------------------------------------------------------------------- rail

def test_rail_data_management_navigates_at_once(sidebar, qtbot):
    sidebar.set_active_page("timeline_peri_event")
    sidebar.set_mode("icons")
    with qtbot.waitSignal(sidebar.navigation_changed, timeout=1000) as blocker:
        _rail_item(sidebar, "Data Management").click()
    assert blocker.args == ["data_management"]


def test_rail_group_opens_its_flyout_on_click(sidebar, qtbot):
    sidebar.set_active_page("snapshots_5hz_band")
    sidebar.set_mode("icons")
    button = _rail_item(sidebar, "Snapshots")
    flyout = button.findChild(QMenu)
    received = []
    sidebar.navigation_changed.connect(received.append)

    button.click()
    qtbot.waitUntil(flyout.isVisible)

    header, *pages = flyout.actions()
    assert (header.text(), header.isEnabled()) == ("Snapshots", False)
    assert [(a.text(), a.isChecked()) for a in pages] == [("Canonical Bands", False),
                                                          ("5 Hz Band", True)]
    assert flyout.geometry().left() >= button.mapToGlobal(QPoint(button.width(), 0)).x() - 1
    assert received == []  # opening the flyout navigates nowhere
    flyout.close()


def test_flyout_entry_navigates(sidebar, qtbot):
    sidebar.set_mode("icons")
    flyout = _rail_item(sidebar, "Timeline").findChild(QMenu)
    entry = next(a for a in flyout.actions() if a.text() == "LFP Threshold")
    with qtbot.waitSignal(sidebar.navigation_changed, timeout=1000) as blocker:
        entry.trigger()
    assert blocker.args == ["timeline_lfp_threshold"]
    assert _rail_item(sidebar, "Timeline").property("active") is True
    assert sidebar.nav_items["timeline_lfp_threshold"].property("active") is True


def test_active_rail_icon_is_white_on_the_active_fill(sidebar):
    sidebar.set_mode("icons")
    sidebar.set_active_page("snapshots_canonical_bands")
    snapshots, data = _rail_item(sidebar, "Snapshots"), _rail_item(sidebar, "Data Management")
    assert (snapshots.property("active"), data.property("active")) == (True, False)
    assert _icon_color(snapshots.icon()) == QColor(Theme.SIDEBAR_FG).name()
    assert _icon_color(data.icon()) == QColor(Theme.TEXT_SECONDARY).name()  # #64748b
    image = snapshots.grab().toImage()
    assert image.pixelColor(snapshots.width() // 2, 6) == QColor(Theme.SIDEBAR_ACTIVE)


def test_only_the_rails_icons_have_tooltips(sidebar):
    """The rail's icon-only buttons name their pages and shortcuts on hover; the
    labelled entries show their names, so hovering them pops nothing up."""
    assert _rail_item(sidebar, "Data Management").toolTip() == f"Data Management {_native('Ctrl+1')}"
    assert _rail_item(sidebar, "Timeline").toolTip() == (
        f"Timeline — Peri-Event {_native('Ctrl+4')} · LFP Threshold {_native('Ctrl+5')}")
    assert {name: item.toolTip() for name, item in sidebar.nav_items.items()} == {
        name: "" for name in sidebar.nav_items}


def test_logo_is_a_link_only_beside_the_title(sidebar, monkeypatch):
    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl", staticmethod(opened.append))
    logo = sidebar.findChild(QWidget, "sidebar_header").findChild(QPushButton)

    assert logo.isEnabled() and logo.cursor().shape() == Qt.CursorShape.PointingHandCursor
    logo.click()
    assert [url.toString() for url in opened] == [sidebar_module.LAB_URL]

    sidebar.set_mode("icons")
    assert not logo.isEnabled() and logo.cursor().shape() == Qt.CursorShape.ArrowCursor
    logo.click()
    assert len(opened) == 1
    assert not logo.icon().pixmap(32, 32, logo.icon().Mode.Disabled).isNull()


# --------------------------------------------------------------- navigation

def test_one_action_per_page_with_ctrl_1_to_5(sidebar):
    actions = sidebar.actions()
    assert [a.data() for a in actions] == list(PAGES)
    assert [a.shortcut() for a in actions] == [QKeySequence(f"Ctrl+{n}") for n in range(1, 6)]
    assert all(a.isCheckable() for a in actions)
    assert [a.data() for a in actions if a.isChecked()] == ["data_management"]


def test_shortcut_navigates_from_anywhere_in_the_window(host, sidebar, qtbot):
    host.activateWindow()
    qtbot.waitActive(host)
    with qtbot.waitSignal(sidebar.navigation_changed, timeout=1000) as blocker:
        QTest.keyClick(host, Qt.Key.Key_3, Qt.KeyboardModifier.ControlModifier)
    assert blocker.args == ["snapshots_5hz_band"]
    assert sidebar.nav_items["snapshots_5hz_band"].property("active") is True


def test_go_menu_lists_every_page_on_the_same_actions(sidebar, qtbot):
    menu = sidebar.go_menu(sidebar)
    entries = [(a.text(), a.isSeparator(), a.isEnabled()) for a in menu.actions()]
    assert entries == [
        ("Data Management", False, True),
        ("", True, True), ("Snapshots", False, False),
        ("Canonical Bands", False, True), ("5 Hz Band", False, True),
        ("", True, True), ("Timeline", False, False),
        ("Peri-Event", False, True), ("LFP Threshold", False, True),
    ]
    assert set(menu.actions()) >= set(sidebar.actions())
    assert menu.title() == "Go"


def test_page_title(sidebar):
    assert sidebar.page_title("data_management") == "Data Management"
    assert sidebar.page_title("snapshots_5hz_band") == "Snapshots: 5 Hz Band"
    assert sidebar.page_title("timeline_peri_event") == "Timeline: Peri-Event"
    assert sidebar.page_title("nowhere") == ""


def test_navigation_scrolls_when_the_window_is_short(host, sidebar, qtbot):
    host.resize(800, 300)
    scroll = sidebar.findChild(QScrollArea, "sidebar_nav")
    qtbot.waitUntil(lambda: scroll.verticalScrollBar().maximum() > 0)
    assert scroll.horizontalScrollBar().maximum() == 0
    assert sidebar.minimumSizeHint().height() < 300


# ---------------------------------------------------------- header, focus

def test_header_lines_up_with_the_top_bar(qtbot, qapp):
    apply_app_stylesheet(qapp)
    window = QWidget()
    row = QHBoxLayout(window)
    row.setContentsMargins(0, 0, 0, 0)
    sidebar = Sidebar()
    row.addWidget(sidebar)
    column = QVBoxLayout()
    top_bar = TopBar()
    column.addWidget(top_bar)
    column.addStretch()
    row.addLayout(column)
    qtbot.addWidget(window)
    window.resize(1280, 769)
    window.show()
    qtbot.waitExposed(window)
    header = sidebar.findChild(QWidget, "sidebar_header")
    assert header.height() == top_bar.height() == Dim.TOPBAR_H


def test_labelled_items_keep_their_size_with_the_focus_ring(sidebar):
    assert sidebar.nav_items["data_management"].height() == Dim.NAV_ITEM_H
    assert sidebar.nav_items["snapshots_canonical_bands"].height() == Dim.NAV_CHILD_H
    assert all(b.width() == Dim.SIDEBAR_W for b in sidebar.nav_items.values())


def test_focus_ring_only_after_keyboard_navigation(host, sidebar, qtbot):
    host.activateWindow()
    qtbot.waitActive(host)
    button = sidebar.nav_items["timeline_peri_event"]
    edge = QPoint(0, button.height() // 2)
    assert button.focusPolicy() == Qt.FocusPolicy.TabFocus

    QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    assert not button.hasFocus()  # a click never focuses it

    button.setFocus(Qt.FocusReason.OtherFocusReason)  # focus not from the keyboard
    assert button.hasFocus() and not button.property("focusRing")
    unringed = button.grab().toImage().pixelColor(edge)

    sidebar.nav_items["snapshots_5hz_band"].setFocus()
    QTest.keyClick(QApplication.focusWidget(), Qt.Key.Key_Tab)  # Tab onto it
    assert button.hasFocus() and button.property("focusRing")
    # The current page's ring is white on its dark fill
    assert unringed != button.grab().toImage().pixelColor(edge) == QColor(Theme.SIDEBAR_FG)

    QTest.keyClick(button, Qt.Key.Key_Tab)  # and on to the next
    assert not button.property("focusRing")
    following = sidebar.nav_items["timeline_lfp_threshold"]
    assert following.hasFocus() and following.property("focusRing")
    assert following.grab().toImage().pixelColor(edge) == QColor(Theme.SIDEBAR_ACTIVE)


def test_no_focus_ring_where_focus_lands_by_itself(qtbot, qapp):
    """On the rail the logo can't take focus, so activating the window focuses
    the first rail item — without a ring."""
    apply_app_stylesheet(qapp)
    window = QWidget()
    QHBoxLayout(window).addWidget(sidebar := Sidebar())
    sidebar.set_mode("icons")
    qtbot.addWidget(window)
    window.show()
    window.activateWindow()
    qtbot.waitUntil(lambda: QApplication.focusWidget() is not None)
    focused = QApplication.focusWidget()
    assert focused.objectName() == "rail_item"
    assert not focused.property("focusRing")
    edge = focused.grab().toImage().pixelColor(0, focused.height() // 2)
    assert edge != QColor(Theme.SIDEBAR_FG)  # the active item's ring colour


def test_every_sidebar_button_is_a_tab_stop_or_read_only(sidebar):
    sidebar.set_interface_action(QAction("Aa"))
    for button in sidebar.findChildren(QPushButton) + sidebar.findChildren(QToolButton):
        if button.objectName() == "nav_group_header":
            assert button.focusPolicy() == Qt.FocusPolicy.NoFocus
        elif button.objectName():
            assert button.focusPolicy() == Qt.FocusPolicy.TabFocus, button.objectName()


# ------------------------------------------------------------------- footer

def test_footer_toggle_asks_for_the_other_mode(sidebar, qtbot):
    toggle = next(b for b in sidebar.findChildren(QToolButton, "sidebar_footer_button")
                  if b.toolTip().endswith("Sidebar"))
    assert toggle.toolTip() == "Collapse Sidebar"
    with qtbot.waitSignal(sidebar.toggle_requested, timeout=1000):
        toggle.click()
    assert sidebar.mode == "labels"  # the sidebar asks; ShellViewModel decides
    sidebar.set_mode("icons")
    assert (toggle.toolTip(), toggle.accessibleName()) == ("Expand Sidebar", "Expand Sidebar")


def test_interface_button_shows_the_action_and_opens_its_menu(sidebar, qtbot):
    buttons = sidebar.findChildren(QToolButton, "sidebar_footer_button")
    interface = next(b for b in buttons if not b.toolTip().endswith("Sidebar"))
    assert not interface.isVisible()  # until there is an action to show

    menu = QMenu(sidebar)
    action = QAction("Aa", sidebar)
    action.setMenu(menu)
    action.setToolTip("Interface Size: 100 %")
    sidebar.set_interface_action(action)
    assert interface.isVisible() and interface.text() == "Aa"
    assert (interface.menu(), interface.toolTip()) == (menu, "Interface Size: 100 %")
    assert interface.popupMode() == QToolButton.ToolButtonPopupMode.InstantPopup
    assert interface.accessibleName() == "Interface Size"
    action.setText("Aa 125 %")
    assert interface.text() == "Aa 125 %"
    action.setEnabled(False)
    assert not interface.isEnabled()
    action.setEnabled(True)

    # On the rail the size goes under "Aa", so the button fits the 64 px
    sidebar.set_mode("icons")
    assert interface.text() == "Aa\n125 %"
    qtbot.waitUntil(lambda: sidebar.width() == Dim.SIDEBAR_RAIL_W)
    toggle = next(b for b in buttons if b is not interface)
    qtbot.waitUntil(lambda: interface.y() > toggle.y())  # stacked under the toggle
    assert 0 <= interface.x() and interface.geometry().right() < sidebar.width()
    assert interface.sizeHint().width() <= interface.width()
    sidebar.set_mode("labels")
    assert interface.text() == "Aa 125 %"


def test_sidebar_holds_no_viewmodel():
    tree = ast.parse(Path(sidebar_module.__file__).read_text(encoding="utf-8"))
    imported = [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import)
                for alias in node.names]
    imported += [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert not [m for m in imported if m.startswith(("src.ui.viewmodels", "src.infrastructure"))]
