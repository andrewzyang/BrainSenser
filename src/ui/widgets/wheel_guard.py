"""Wheel guard: a wheel over an unfocused combo or spinbox scrolls the page instead.

Qt hands a wheel event to the widget under the pointer. Every QAbstractSpinBox,
and a QComboBox outside the macOS style, steps its value on it even without focus
and takes focus from it (``Qt.WheelFocus``). Inside a scrolling page that would
silently change a correction method, a permutation count or a time window while
the user scrolls past (plan §4.5, review 12 U3).

:class:`WheelGuard` turns ``Qt.WheelFocus`` into ``Qt.StrongFocus`` (a click or
Tab focuses the control, the wheel does not; Qt's macOS combos already have
``Qt.TabFocus``) and ignores the wheel until the control has focus. Qt passes an
ignored wheel event on to the parent, so the page scrolls.
"""

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QAbstractSpinBox, QComboBox, QWidget

_GUARDED_TYPES = (QComboBox, QAbstractSpinBox)


class WheelGuard(QObject):
    """Guards the combos and spinboxes below ``root``, including ones added later:
    ``root`` is re-scanned whenever it is shown or laid out again."""

    def __init__(self, root: QWidget):
        super().__init__(root)
        self._root = root
        root.installEventFilter(self)
        self._guard_controls()

    def _guard_controls(self) -> None:
        window = self._root.window()
        for control_type in _GUARDED_TYPES:
            for control in self._root.findChildren(control_type):
                if control.window() is not window:
                    continue  # a dialog parented inside the page is not part of it
                if control.focusPolicy() == Qt.FocusPolicy.WheelFocus:
                    control.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
                control.installEventFilter(self)  # installing twice keeps one filter

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        # Check the event type first: this filter sees every event of every
        # guarded control, and touches nothing else for the ones it ignores.
        kind = event.type()
        if kind == QEvent.Type.Wheel:
            if watched is not self._root and not watched.hasFocus():
                event.ignore()  # not delivered to the control; Qt hands it to the parent
                return True
        elif kind in (QEvent.Type.Show, QEvent.Type.LayoutRequest) and watched is self._root:
            self._guard_controls()
        return False
