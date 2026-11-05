"""
MainLayout - Main application layout coordinator.

Combines:
- Sidebar (left, fixed width)
- TopBar + Content (right, fills space)
  - TopBar (top, fixed height)
  - Banners (full width, optional; add_banner)
  - Content area (QStackedWidget for multiple pages, each in a PageHost)

Layout structure:
┌────────────┬─────────────────────────┐
│            │    TopBar               │
│            ├─────────────────────────┤
│  Sidebar   │    (banners)            │
│            ├─────────────────────────┤
│            │    Page Content         │
│            │    (QStackedWidget)     │
└────────────┴─────────────────────────┘

A QStackedWidget's minimum is the largest of all its pages' minimums, shown or
not; wrapping each page in a PageHost keeps one page's minimum from becoming
every page's, and the window's.

The layout owns the window's ResponsiveContext: it classifies this widget's
width (the window's client width) and the content stack's size, and commands
every DensityAware page added here with the resulting Density.

Author: iEEG BrainSense Development Team
Last Updated: 2025-10-01
"""

from typing import Optional

from PySide6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QStackedWidget
from PySide6.QtCore import Signal

from src.ui.components import Sidebar, TopBar
from src.ui.layouts.page_host import PageHost
from src.ui.layouts.responsive_context import ResponsiveContext


class MainLayout(QWidget):
    """
    Main application layout coordinator.

    Manages the overall app structure with sidebar navigation and
    page switching via QStackedWidget.

    Signals:
        page_changed: Emitted when user navigates to different page

    Attributes:
        responsive_context: The window's layout classes (ResponsiveContext)

    Example:
        >>> layout = MainLayout()
        >>> layout.add_page("data_management", data_mgmt_page)
        >>> layout.add_page("snapshots", snapshots_page)
        >>> layout.switch_page("data_management")
    """

    # Signals
    page_changed = Signal(str)  # page_name

    def __init__(self, sidebar: Sidebar, top_bar: TopBar):
        """
        Initialize MainLayout.

        Args:
            sidebar: Sidebar navigation component
            top_bar: TopBar component with patient dropdown and actions
        """
        super().__init__()
        self.sidebar = sidebar
        self.top_bar = top_bar
        self._pages = {}  # page_name -> (widget, index)
        self._current_page: Optional[str] = None
        self._setup_ui()
        self._connect_signals()

    def _setup_ui(self):
        """Setup the main layout structure."""
        # Root layout: Horizontal (Sidebar | Right Content)
        root_layout = QHBoxLayout()
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        self.setLayout(root_layout)

        # Left: Sidebar
        root_layout.addWidget(self.sidebar)

        # Right: Vertical (TopBar / Content)
        right_container = QWidget()
        right_layout = QVBoxLayout()
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)
        right_container.setLayout(right_layout)

        # Top bar
        right_layout.addWidget(self.top_bar)

        # Content area (QStackedWidget for multiple pages)
        self.content_stack = QStackedWidget()
        self.content_stack.setObjectName("content_stack")
        right_layout.addWidget(self.content_stack)
        self._right_layout = right_layout

        root_layout.addWidget(right_container)

        # Window and content classes, pushed to the pages as a Density
        self.responsive_context = ResponsiveContext(self, self.content_stack)

        # Apply styling
        self._apply_styles()

    def _connect_signals(self):
        """Connect internal signals."""
        # Sidebar navigation -> switch page
        self.sidebar.navigation_changed.connect(self.switch_page)

    def add_page(self, page_name: str, widget: QWidget, *, scroll_fallback: bool = True,
                 height_for_width: bool = False):
        """
        Add a page to the content stack.

        Args:
            page_name: Page identifier (e.g., "data_management")
            widget: QWidget to display for this page
            scroll_fallback: Wrap the page in a PageHost, so it scrolls vertically
                when the window is shorter than the page's minimum. False puts the
                page in the stack directly.
            height_for_width: Let the page's height follow its width inside the
                PageHost; only for pages that reflow by width (see PageHost).

        A DensityAware page gets the current Density at once, and every new one.

        Example:
            >>> layout.add_page("data_management", DataManagementPage())
        """
        host = PageHost(widget, height_for_width=height_for_width) if scroll_fallback else widget
        index = self.content_stack.addWidget(host)
        self._pages[page_name] = (widget, index)
        self.responsive_context.register(widget)

    def add_banner(self, widget: QWidget):
        """
        Show a full-width widget between the top bar and the pages.

        Banners stack in the order they are added. A shown banner takes its
        height from the content stack, which the pages' density follows.

        Args:
            widget: The banner (e.g. the interface-size restart banner)
        """
        self._right_layout.insertWidget(self._right_layout.indexOf(self.content_stack), widget)

    def switch_page(self, page_name: str):
        """
        Switch to a different page.

        Args:
            page_name: Page identifier

        Emits:
            page_changed: With page_name
        """
        if page_name not in self._pages:
            return

        widget, index = self._pages[page_name]
        self.content_stack.setCurrentIndex(index)

        # Update sidebar active state
        self.sidebar.set_active_page(page_name)
        self._current_page = page_name

        # Show Copy/Save buttons on analysis pages, CRUD buttons on others
        if page_name in ('timeline_lfp_threshold', 'timeline_peri_event', 'snapshots_canonical_bands', 'snapshots_5hz_band'):
            self.top_bar.set_buttons_visible(False)  # Hide CRUD buttons
            self.top_bar.set_timeline_buttons_visible(True)  # Show Copy/Save buttons
        else:
            self.top_bar.set_buttons_visible(True)  # Show CRUD buttons
            self.top_bar.set_timeline_buttons_visible(False)  # Hide Copy/Save buttons

        # Emit signal
        self.page_changed.emit(page_name)

    def get_page(self, page_name: str) -> QWidget:
        """
        Get page widget by name.

        Args:
            page_name: Page identifier

        Returns:
            QWidget or None if not found
        """
        if page_name in self._pages:
            return self._pages[page_name][0]
        return None

    @property
    def current_page(self) -> Optional[str]:
        """Return the identifier of the currently active page."""
        return self._current_page

    def _apply_styles(self):
        """Apply styling to content area."""
        self.content_stack.setStyleSheet("""
            QStackedWidget#content_stack {
                background-color: #ffffff;
            }
        """)
