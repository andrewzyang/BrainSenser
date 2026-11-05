"""
Utilities for routing toolbar export enablement between multiple pages.
"""

from __future__ import annotations

from typing import Callable, Dict, Optional


class ToolbarExportStateRouter:
    """
    Track per-page export enablement and apply it to the toolbar.

    The router keeps a simple mapping of page identifiers to their export-ready
    state. When the active page changes, the stored state for that page is
    reapplied to the toolbar. Updates from inactive pages are remembered but do
    not immediately toggle the toolbar.
    """

    def __init__(self, apply_enabled: Callable[[bool], None]) -> None:
        self._apply_enabled = apply_enabled
        self._states: Dict[str, bool] = {}
        self._current_page: Optional[str] = None

    def update_page_state(self, page: str, enabled: bool) -> None:
        """Record the export state for a page and apply it if the page is active."""
        self._states[page] = enabled
        if page == self._current_page:
            self._apply_enabled(enabled)

    def on_page_changed(self, page: str) -> None:
        """
        Apply the stored state for the newly active page.

        Unknown pages default to `False` so the toolbar stays disabled unless a
        page explicitly marks itself export-ready.
        """
        self._current_page = page
        self._apply_enabled(self._states.get(page, False))
