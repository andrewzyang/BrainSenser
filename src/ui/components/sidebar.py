"""
Sidebar - Navigation sidebar component.

Two modes (``set_mode``), chosen by ShellViewModel from the window's width
class, the View ▸ Sidebar preference and the footer toggle (plan M3.6, D4):

- "labels": the labelled sidebar, 200 px wide: Data Management, then the
  Snapshots and Timeline pages under their read-only group headers;
- "icons": a 64-px icon rail. Data Management navigates at once; Snapshots and
  Timeline open a flyout of their pages on click, under the group's name and
  with a check mark on the current page. The logo is not a link there: at the
  top of an icon column it would read as "Home".

One exclusive QActionGroup, a checkable action per page with Ctrl/Cmd+1…5,
drives the labelled buttons, the rail and the Go menu, so they always agree on
the current page. The navigation scrolls when the window is too short for it.
Modes change without animation (every frame would re-lay out the pages). The
buttons take focus from Tab, never from a click, and show a focus ring only
after keyboard navigation (keep_focus_ring). The footer holds the mode toggle
(a session override, ``toggle_requested``) and the interface-size "Aa" button,
whose action and menu come from ShellActions.

The sidebar holds no ViewModel; MainWindow wires it.

Author: iEEG BrainSense Development Team
"""

from PySide6.QtWidgets import (QBoxLayout, QFrame, QLabel, QMenu, QPushButton, QHBoxLayout,
                               QScrollArea, QSizePolicy, QToolButton, QVBoxLayout, QWidget)
from PySide6.QtCore import Qt, Signal, QPoint, QSize, QUrl
from PySide6.QtGui import QAction, QActionGroup, QDesktopServices, QIcon, QKeySequence, QPixmap
from pathlib import Path

from src.ui.policy.layout import SidebarMode
from src.ui.policy.tokens import TYPE_PX, Dim, IconSize, Radius, Space, TypeRole
from src.ui.shell.focus_ring import keep_focus_ring
from src.ui.theme import Theme
from src.ui.icons import Icons

LAB_URL = "https://research.sunnybrook.ca/research/centres/harquail-centre-for-neuromodulation/"

# The navigation in sidebar order (Ctrl/Cmd+1…5 follow it): a page, or a group
# of pages under a read-only header — a flyout on the rail.
NAVIGATION = (
    ("data_management", "Data Management", Icons.database, ()),
    ("snapshots", "Snapshots", Icons.camera, (
        ("snapshots_canonical_bands", "Canonical Bands"),
        ("snapshots_5hz_band", "5 Hz Band"),
    )),
    ("timeline", "Timeline", Icons.clock, (
        ("timeline_peri_event", "Peri-Event"),
        ("timeline_lfp_threshold", "LFP Threshold"),
    )),
)

# Rail and footer icons in slate 500 (4.8:1 on the light sidebar, ux:S6); the
# current page's rail icon white on the active fill.
ICON_COLOR = Theme.TEXT_SECONDARY
ICON_COLOR_ACTIVE = Theme.SIDEBAR_FG

# The keyboard focus ring is a border, so every focusable box reserves it.
FOCUS_RING = 2


class Sidebar(QWidget):
    """
    Navigation sidebar component.

    Provides app-level navigation with visual feedback for the active page, as
    labelled buttons or as an icon rail.

    Signals:
        navigation_changed: Emitted when the user picks a page (button, rail
                          flyout, Go menu or Ctrl/Cmd+1…5). Emits the page
                          name: "data_management", "snapshots_canonical_bands", etc.
        toggle_requested: Emitted when the user clicks the footer toggle.
    """

    # Signals
    navigation_changed = Signal(str)  # page_name
    toggle_requested = Signal()

    def __init__(self):
        super().__init__()
        self._active_page = "data_management"
        self._mode = SidebarMode.LABELS

        self._setup_ui()
        self._apply_styles()

    def _setup_ui(self):
        """Setup the sidebar UI."""
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.setLayout(layout)

        layout.addWidget(self._create_header())

        # One checkable action per page; buttons, rail flyouts and the Go menu
        # trigger these. Added to the sidebar, their shortcuts work anywhere
        # in its window.
        self._page_actions = {}
        self._action_group = QActionGroup(self)
        self._action_group.triggered.connect(self._on_action_triggered)
        for number, (page_name, text) in enumerate(_pages(), start=1):
            action = QAction(text, self)
            action.setData(page_name)
            action.setCheckable(True)
            action.setShortcut(QKeySequence(f"Ctrl+{number}"))
            self._action_group.addAction(action)
            self._page_actions[page_name] = action
        self.addActions(list(self._page_actions.values()))

        # Navigation items: the labelled ones or the rail, above a spacer that
        # pushes them to the top
        nav = QWidget()
        nav_layout = QVBoxLayout(nav)
        nav_layout.setContentsMargins(0, 0, 0, 0)
        nav_layout.setSpacing(0)
        self._labelled_nav = self._create_labelled_nav()
        nav_layout.addWidget(self._labelled_nav)
        self._rail = self._create_rail()
        self._rail.setVisible(False)
        nav_layout.addWidget(self._rail)
        nav_layout.addStretch()
        layout.addWidget(self._create_scroll_area(nav), 1)

        layout.addWidget(self._create_footer())

        keep_focus_ring(self, [*self.nav_items.values(), *self._rail_items.values(),
                               self._toggle_button, self._interface_button])
        self.setFixedWidth(Dim.SIDEBAR_W)

        # Set initial active state
        self.set_active_page("data_management")

    def _create_header(self) -> QWidget:
        """App branding: the lab's logo and the app title."""
        header = QWidget()
        header.setObjectName("sidebar_header")
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(16, 9, 16, 9)
        header_layout.setSpacing(8)
        header.setLayout(header_layout)

        # Logo image - high resolution for sharp rendering (a link to the lab's
        # site beside the title; on the rail a plain image)
        self._logo = QPushButton()
        self._logo.setCursor(Qt.CursorShape.PointingHandCursor)
        self._logo.clicked.connect(self._open_lab_site)

        # sidebar.py is in src/ui/components/, so need 4 parents to get to project root
        logo_path = Path(__file__).parent.parent.parent.parent / "assets" / "davidson_lab_logo.png"
        if logo_path.exists():
            logo_pixmap = QPixmap(str(logo_path))
            target_size = IconSize.LG
            scaled_logo = logo_pixmap.scaled(
                target_size * 4,
                target_size * 4,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            scaled_logo.setDevicePixelRatio(4.0)
            # The same image when the button is disabled (on the rail), not a greyed one
            logo_icon = QIcon(scaled_logo)
            logo_icon.addPixmap(scaled_logo, QIcon.Mode.Disabled)
            self._logo.setIcon(logo_icon)
            icon_size = scaled_logo.size() / 4.0
            self._logo.setIconSize(icon_size)
            self._logo.setFixedSize(icon_size.width(), icon_size.height())
        else:
            self._logo.setIcon(Icons.database(Theme.TEXT_ON_DARK))
            self._logo.setIconSize(Icons.database(Theme.TEXT_ON_DARK).pixmap(16, 16).size())
            self._logo.setFixedSize(IconSize.LG, IconSize.LG)

        self._logo.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                border: none;
                padding: 0;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 0.1);
                border-radius: 6px;
            }
        """)
        header_layout.addWidget(self._logo)

        # App title (size and weight: #app_title in _apply_styles)
        self._app_title = QLabel("BrainSenser")
        self._app_title.setObjectName("app_title")
        header_layout.addWidget(self._app_title)
        header_layout.addStretch()

        return header

    def _create_labelled_nav(self) -> QWidget:
        """The labelled navigation: each entry below the same large visual gap."""
        nav = QWidget()
        nav.setObjectName("labelled_nav")
        layout = QVBoxLayout(nav)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.nav_items = {}
        for name, text, icon, pages in NAVIGATION:
            layout.addSpacing(Dim.NAV_GROUP_GAP)
            if pages:
                layout.addWidget(self._create_nav_group(text, icon(), pages))
            else:
                self.nav_items[name] = self._create_nav_item(text, name, icon())
                layout.addWidget(self.nav_items[name])
        return nav

    def _create_nav_item(self, text: str, page_name: str, icon=None) -> QPushButton:
        """
        Create a navigation item button with icon.

        Args:
            text: Display text
            page_name: Internal page identifier
            icon: QtAwesome icon (optional)

        Returns:
            QPushButton configured as navigation item
        """
        button = QPushButton()
        button.setObjectName("nav_item")
        button.setProperty("page_name", page_name)
        button.setCursor(Qt.CursorShape.PointingHandCursor)

        if icon:
            button.setIcon(icon)
            button.setIconSize(QSize(IconSize.SM, IconSize.SM))

        button.setText(text)
        self._bind_to_page(button, page_name)

        return button

    def _create_nav_group(self, text: str, icon, children) -> QWidget:
        """
        Create a navigation group with a static header and always-visible children.

        Args:
            text: Display text for the parent header
            icon: QtAwesome icon for the parent header
            children: (page_name, display_text) pairs

        Returns:
            QWidget containing the header and child items
        """
        container = QWidget()
        container.setObjectName("nav_group_container")
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)

        # Read-only section header — no click handler, no hover, no pointer cursor.
        header = QPushButton()
        header.setObjectName("nav_group_header")
        header.setIcon(icon)
        header.setIconSize(QSize(IconSize.SM, IconSize.SM))
        header.setText(text)
        header.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        container_layout.addWidget(header)

        # Children always visible
        children_widget = QWidget()
        children_widget.setObjectName("nav_group_children")
        children_layout = QVBoxLayout(children_widget)
        children_layout.setContentsMargins(0, 0, 0, 0)
        children_layout.setSpacing(0)

        for child_page_name, child_text in children:
            child_button = self._create_nav_child_item(child_text, child_page_name)
            children_layout.addWidget(child_button)
            self.nav_items[child_page_name] = child_button

        container_layout.addWidget(children_widget)

        return container

    def _create_nav_child_item(self, text: str, page_name: str) -> QPushButton:
        """
        Create an indented child navigation item.

        Args:
            text: Display text
            page_name: Internal page identifier

        Returns:
            QPushButton configured as child navigation item
        """
        button = QPushButton()
        button.setObjectName("nav_child_item")
        button.setProperty("page_name", page_name)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setText(text)
        self._bind_to_page(button, page_name)

        return button

    def _bind_to_page(self, button: QPushButton, page_name: str) -> None:
        """Let ``button`` trigger the page's action; focus from Tab only. No
        tooltip: the button shows the page's name (the Go menu lists the
        shortcuts); only the rail's icon-only buttons have one."""
        action = self._page_actions[page_name]
        button.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        button.clicked.connect(action.trigger)

    def _create_rail(self) -> QWidget:
        """The icon rail: an icon per entry; a group's icon opens its flyout."""
        rail = QWidget()
        rail.setObjectName("rail")
        layout = QVBoxLayout(rail)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._rail_items = {}    # entry name -> button
        self._rail_icons = {}    # entry name -> (idle icon, active icon)
        self._rail_pages = {}    # entry name -> the pages it stands for
        self._flyouts = {}       # group button -> its flyout
        for name, text, icon, pages in NAVIGATION:
            layout.addSpacing(Dim.NAV_GROUP_GAP)
            button = QToolButton()
            button.setObjectName("rail_item")
            button.setAccessibleName(text)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFocusPolicy(Qt.FocusPolicy.TabFocus)
            button.setIconSize(QSize(IconSize.SM, IconSize.SM))
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            button.setFixedHeight(Dim.NAV_ITEM_H)
            if pages:
                flyout = QMenu(button)
                self._add_group(flyout, text, pages)
                self._flyouts[button] = flyout
                shortcuts = " · ".join(self._with_shortcut(self._page_actions[page])
                                       for page, _text in pages)
                button.setToolTip(f"{text} — {shortcuts}")
                button.clicked.connect(self._open_flyout)
            else:
                button.setToolTip(self._with_shortcut(self._page_actions[name]))
                button.clicked.connect(self._page_actions[name].trigger)
            self._rail_items[name] = button
            self._rail_icons[name] = (icon(ICON_COLOR), icon(ICON_COLOR_ACTIVE))
            self._rail_pages[name] = [page for page, _text in pages] or [name]
            layout.addWidget(button)
        return rail

    def _create_scroll_area(self, nav: QWidget) -> QScrollArea:
        """``nav`` in a frameless, transparent scroll area: it scrolls when the
        window is too short for it, never sideways."""
        scroll = QScrollArea()
        scroll.setObjectName("sidebar_nav")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        scroll.viewport().setAutoFillBackground(False)
        # Ignored horizontally: the navigation is exactly as wide as the sidebar.
        nav.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        scroll.setWidget(nav)
        nav.setAutoFillBackground(False)  # setWidget() turned it on
        return scroll

    def _create_footer(self) -> QWidget:
        """The mode toggle and the interface-size "Aa" button: side by side under
        the labels, one above the other on the rail."""
        footer = QWidget()
        footer.setObjectName("sidebar_footer")
        self._footer_layout = QBoxLayout(QBoxLayout.Direction.LeftToRight, footer)
        self._footer_layout.setContentsMargins(Space.X2, Space.X2, Space.X2, Space.X2)
        self._footer_layout.setSpacing(Space.X2)

        self._toggle_button = QToolButton()
        self._toggle_button.setObjectName("sidebar_footer_button")
        self._toggle_button.setFixedSize(Dim.SIDEBAR_FOOTER_BUTTON, Dim.SIDEBAR_FOOTER_BUTTON)
        self._toggle_button.setIconSize(QSize(IconSize.SM, IconSize.SM))
        self._toggle_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._toggle_button.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self._toggle_button.clicked.connect(self.toggle_requested)
        self._footer_layout.addWidget(self._toggle_button, 0, Qt.AlignmentFlag.AlignCenter)
        self._footer_layout.addStretch()

        # Shows ShellActions' interface-size action ("Aa", plus the size when
        # it isn't the default) and opens its menu on click. At least as tall
        # as the toggle; on the rail the size goes under "Aa".
        self._interface_action = None
        self._interface_button = QToolButton()
        self._interface_button.setObjectName("sidebar_footer_button")
        self._interface_button.setMinimumSize(Dim.SIDEBAR_FOOTER_BUTTON, Dim.SIDEBAR_FOOTER_BUTTON)
        self._interface_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._interface_button.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self._interface_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._interface_button.setAccessibleName("Interface Size")
        self._interface_button.setVisible(False)  # until set_interface_action()
        self._footer_layout.addWidget(self._interface_button, 0, Qt.AlignmentFlag.AlignCenter)

        self._show_toggle()
        return footer

    def _add_group(self, menu: QMenu, title: str, pages) -> None:
        """Add a group's header (greyed, not a command) and its pages to ``menu``."""
        menu.addAction(title).setEnabled(False)
        for page_name, _text in pages:
            menu.addAction(self._page_actions[page_name])

    @staticmethod
    def _with_shortcut(action: QAction) -> str:
        """``action``'s text and shortcut as the platform writes it, e.g. "Peri-Event ⌘4"."""
        return f"{action.text()} {action.shortcut().toString(QKeySequence.SequenceFormat.NativeText)}"

    def _open_lab_site(self):
        """Open the lab's website (the logo beside the title)."""
        QDesktopServices.openUrl(QUrl(LAB_URL))

    def _open_flyout(self):
        """Open the clicked rail group's flyout beside the rail."""
        button = self.sender()
        self._flyouts[button].popup(button.mapToGlobal(QPoint(button.width(), 0)))

    def _on_action_triggered(self, action: QAction):
        """A page's action was triggered (button, rail, flyout, Go menu or shortcut)."""
        self._on_nav_clicked(action.data())

    def _on_nav_clicked(self, page_name: str):
        """
        Handle navigation item click.

        Args:
            page_name: Page identifier
        """
        self.set_active_page(page_name)
        self.navigation_changed.emit(page_name)

    def set_active_page(self, page_name: str):
        """
        Set the active page (updates visual state).

        Args:
            page_name: Page identifier ("data_management", "snapshots_canonical_bands", etc.)
        """
        self._active_page = page_name

        # Check the page's action; the group unchecks the others (nothing is triggered)
        action = self._page_actions.get(page_name)
        if action is not None:
            action.setChecked(True)
        elif self._action_group.checkedAction() is not None:
            self._action_group.checkedAction().setChecked(False)

        # Update all navigable items (flat + child buttons)
        for name, button in self.nav_items.items():
            self._show_active(button, name == page_name)

        # A rail icon is active when it stands for the page (Data Management) or its group does
        for name, button in self._rail_items.items():
            active = page_name in self._rail_pages[name]
            self._show_active(button, active)
            button.setIcon(self._rail_icons[name][active])

    @staticmethod
    def _show_active(button, active: bool):
        button.setProperty("active", active)
        button.style().unpolish(button)
        button.style().polish(button)
        button.update()

    @property
    def mode(self) -> str:
        """What the sidebar shows: "labels" | "icons"."""
        return self._mode.value

    def set_mode(self, mode: str):
        """
        Show the labelled sidebar or the icon rail; the same mode again changes nothing.

        Args:
            mode: "labels" | "icons" (ShellViewModel.sidebar_mode)
        """
        new_mode = SidebarMode(mode)
        if new_mode is self._mode:
            return
        self._mode = new_mode
        icons = new_mode is SidebarMode.ICONS

        self.setFixedWidth(Dim.SIDEBAR_RAIL_W if icons else Dim.SIDEBAR_W)
        self._labelled_nav.setVisible(not icons)
        self._rail.setVisible(icons)
        self._app_title.setVisible(not icons)
        # On the rail the logo is a plain image, centred by the header's margins
        self._logo.setEnabled(not icons)
        self._logo.setCursor(Qt.CursorShape.ArrowCursor if icons
                             else Qt.CursorShape.PointingHandCursor)
        # The footer's buttons stack on the rail and use its whole width
        self._footer_layout.setDirection(QBoxLayout.Direction.TopToBottom if icons
                                         else QBoxLayout.Direction.LeftToRight)
        side = 0 if icons else Space.X2
        self._footer_layout.setContentsMargins(side, Space.X2, side, Space.X2)
        self._show_toggle()
        if self._interface_action is not None:
            self._show_interface_action()

    def _show_toggle(self):
        """The footer toggle offers the other mode."""
        if self._mode is SidebarMode.LABELS:
            icon, text = Icons.collapse(ICON_COLOR), "Collapse Sidebar"
        else:
            icon, text = Icons.expand(ICON_COLOR), "Expand Sidebar"
        self._toggle_button.setIcon(icon)
        self._toggle_button.setToolTip(text)
        self._toggle_button.setAccessibleName(text)

    def set_interface_action(self, action: QAction):
        """
        Show the interface-size action in the footer; a click opens its menu.

        Args:
            action: ShellActions.interface_action: its text is "Aa", or "Aa"
                and the size when it isn't the default ("Aa 125 %")
        """
        self._interface_action = action
        self._interface_button.setMenu(action.menu())
        action.changed.connect(self._show_interface_action)
        self._show_interface_action()
        self._interface_button.setVisible(True)

    def _show_interface_action(self):
        """The action's text, tooltip and state on the "Aa" button; on the
        64-px rail the size goes on a second line, under "Aa"."""
        action = self._interface_action
        text = action.text()
        if self._mode is SidebarMode.ICONS:
            text = text.replace(" ", "\n", 1)
        self._interface_button.setText(text)
        self._interface_button.setToolTip(action.toolTip())
        self._interface_button.setEnabled(action.isEnabled())

    def go_menu(self, parent: QWidget) -> QMenu:
        """A "Go" menu of every page (the Data Management page, then each group
        under its greyed header), on the same actions as the sidebar."""
        menu = QMenu("Go", parent)
        for name, text, _icon, pages in NAVIGATION:
            if pages:
                menu.addSeparator()
                self._add_group(menu, text, pages)
            else:
                menu.addAction(self._page_actions[name])
        return menu

    def page_title(self, page_name: str) -> str:
        """
        The page's name as the window title shows it.

        Args:
            page_name: Page identifier

        Returns:
            e.g. "Data Management" or "Timeline: Peri-Event"; "" for an unknown page
        """
        for name, text, _icon, pages in NAVIGATION:
            if name == page_name:
                return text
            for page, page_text in pages:
                if page == page_name:
                    return f"{text}: {page_text}"
        return ""

    def _apply_styles(self):
        """Apply styling using Theme constants."""
        self.setStyleSheet(f"""
            /* Sidebar container (its width: set_mode) */
            Sidebar {{
                background-color: {Theme.SIDEBAR_BG};
            }}

            /* Header */
            #sidebar_header {{
                background-color: #eeeeee;
                min-height: {Dim.SIDEBAR_HEADER_H}px;
                max-height: {Dim.SIDEBAR_HEADER_H}px;
            }}

            /* px, not pt: 18pt is 24 px on Windows/Linux; regular weight (D8) */
            #app_title {{
                color: #000000;
                font-size: {TYPE_PX[TypeRole.TITLE]}px;
                font-weight: {Theme.FONT_WEIGHT_NORMAL};
            }}

            /* Navigation items. The transparent border is the focus ring's room,
               so the text stays 20 px in and the item 50 px tall. */
            QPushButton#nav_item {{
                background-color: transparent;
                color: {Theme.TEXT_MUTED};
                border: {FOCUS_RING}px solid transparent;
                border-radius: 0px;
                text-align: left;
                padding: 0px {20 - FOCUS_RING}px;
                font-size: {Theme.FONT_SIZE_MD};
                font-weight: {Theme.FONT_WEIGHT_MEDIUM};
                min-height: {Dim.NAV_ITEM_H - 2 * FOCUS_RING}px;
                max-height: {Dim.NAV_ITEM_H - 2 * FOCUS_RING}px;
            }}

            QPushButton#nav_item:hover {{
                background-color: {Theme.SIDEBAR_HOVER};
                color: {Theme.SIDEBAR_FG};
                border-radius: 0px;
            }}

            QPushButton#nav_item[active="true"] {{
                background-color: {Theme.SIDEBAR_ACTIVE};
                color: {Theme.SIDEBAR_FG};
                border-radius: 0px;
            }}

            QPushButton#nav_item:pressed {{
                background-color: {Theme.SIDEBAR_ACTIVE};
                border-radius: 0px;
            }}

            /* Group section header (read-only — no hover, no pressed, no active state) */
            QPushButton#nav_group_header {{
                background-color: transparent;
                color: {Theme.TEXT_MUTED};
                border: none;
                border-radius: 0px;
                text-align: left;
                padding: 0px 20px;
                font-size: {Theme.FONT_SIZE_MD};
                font-weight: {Theme.FONT_WEIGHT_MEDIUM};
                min-height: 40px;
                max-height: 40px;
            }}

            /* Group children container */
            #nav_group_container, #nav_group_children {{
                background-color: transparent;
                border: none;
            }}

            /* Child navigation items (indented, smaller) */
            QPushButton#nav_child_item {{
                background-color: transparent;
                color: {Theme.TEXT_MUTED};
                border: {FOCUS_RING}px solid transparent;
                border-radius: 0px;
                text-align: left;
                padding: 0px {20 - FOCUS_RING}px 0px {44 - FOCUS_RING}px;
                font-size: {Theme.FONT_SIZE_SM};
                font-weight: {Theme.FONT_WEIGHT_MEDIUM};
                min-height: {Dim.NAV_CHILD_H - 2 * FOCUS_RING}px;
                max-height: {Dim.NAV_CHILD_H - 2 * FOCUS_RING}px;
            }}

            QPushButton#nav_child_item:hover {{
                background-color: {Theme.SIDEBAR_HOVER};
                color: {Theme.SIDEBAR_FG};
                border-radius: 0px;
            }}

            QPushButton#nav_child_item[active="true"] {{
                background-color: {Theme.SIDEBAR_ACTIVE};
                color: {Theme.SIDEBAR_FG};
                border-radius: 0px;
            }}

            QPushButton#nav_child_item:pressed {{
                background-color: {Theme.SIDEBAR_ACTIVE};
                border-radius: 0px;
            }}

            /* Rail items: the icon alone, in the labelled items' active fill */
            QToolButton#rail_item {{
                background-color: transparent;
                border: {FOCUS_RING}px solid transparent;
                border-radius: 0px;
            }}

            QToolButton#rail_item:hover {{
                background-color: {Theme.BORDER};
            }}

            QToolButton#rail_item[active="true"] {{
                background-color: {Theme.SIDEBAR_ACTIVE};
            }}

            /* Footer: the mode toggle and "Aa" */
            QToolButton#sidebar_footer_button {{
                background-color: transparent;
                color: {Theme.TEXT_SECONDARY};
                border: {FOCUS_RING}px solid transparent;
                border-radius: {Radius.SM}px;
                padding: 0px {Space.X1}px;
                font-size: {TYPE_PX[TypeRole.SECONDARY]}px;
                font-weight: {Theme.FONT_WEIGHT_MEDIUM};
            }}

            QToolButton#sidebar_footer_button:hover {{
                background-color: {Theme.BORDER};
            }}

            QToolButton#sidebar_footer_button::menu-indicator {{
                image: none;
                width: 0px;
            }}

            /* Keyboard focus ring (keep_focus_ring), white on the active fill */
            QPushButton#nav_item[focusRing="true"], QPushButton#nav_child_item[focusRing="true"],
            QToolButton#rail_item[focusRing="true"],
            QToolButton#sidebar_footer_button[focusRing="true"] {{
                border-color: {Theme.SIDEBAR_ACTIVE};
            }}

            QPushButton#nav_item[active="true"][focusRing="true"],
            QPushButton#nav_child_item[active="true"][focusRing="true"],
            QToolButton#rail_item[active="true"][focusRing="true"] {{
                border-color: {Theme.SIDEBAR_FG};
            }}
        """)


def _pages():
    """(page_name, text) of every page, in sidebar order."""
    for name, text, _icon, pages in NAVIGATION:
        yield from pages or ((name, text),)
