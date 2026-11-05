"""The keyboard focus ring of the shell's buttons, shown only after keyboard navigation (ux:S10).

A watched button has the ``focusRing`` property while it holds focus that Tab,
Backtab or a shortcut gave it; its stylesheet draws the ring for that property.
Qt marks such focus on the window (``WA_KeyboardFocusChange``) and clears the
mark on a mouse press, so focus that lands on a button otherwise — the window
being activated, the focused button disabled — shows no ring. (QSS ``:focus``
can't tell these apart.)
"""

from typing import Iterable

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QWidget


class _FocusRing(QObject):
    """Event filter keeping the watched widgets' ``focusRing`` property."""

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.FocusIn:
            _show(watched, watched.window().testAttribute(
                Qt.WidgetAttribute.WA_KeyboardFocusChange))
        elif event.type() == QEvent.Type.FocusOut:
            _show(watched, False)
        return False


def keep_focus_ring(owner: QObject, widgets: Iterable[QWidget]) -> None:
    """Show ``widgets``' focus ring (``focusRing``) only for keyboard-given focus;
    the filter lives as long as ``owner``."""
    ring = _FocusRing(owner)
    for widget in widgets:
        widget.installEventFilter(ring)


def _show(widget: QWidget, ring: bool) -> None:
    if bool(widget.property("focusRing")) == ring:
        return
    widget.setProperty("focusRing", ring)
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()
