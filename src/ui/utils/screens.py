"""The screen a widget or window is on, looked up so PySide cannot delete it.

``QWidget.screen()`` and ``QWindow.screen()`` hand Python the application's
QScreen as a child of the caller's wrapper (Shiboken's return-value heuristic),
and the one wrapper per screen moves to each later caller. When the cycle
collector frees a caller while nothing else references that wrapper, it can
clear the wrapper first: Shiboken then gives Python ownership of the QScreen and
deletes it while QGuiApplication still lists it, and the next window shown or
hidden reads freed memory (a segfault). Two windows in turn are enough, e.g. a
test's window whose ``deleteLater()`` never ran, then the next test's.

:func:`screen_of` makes the same call and keeps the wrapper referenced here, so
the collector never finds it unreachable. Code in ``src/`` and ``main.py`` looks
screens up only through it (``tests/architecture/test_screen_lookups.py``).
"""

from typing import Optional, Union

import shiboken6
from PySide6.QtGui import QScreen, QWindow
from PySide6.QtWidgets import QWidget

# The valid screen wrappers screen_of() has returned. One per screen while it
# stays valid; Shiboken invalidates it when a window it was fetched from is
# deleted, and the next lookup hands out (and keeps) a new one.
_held: list[QScreen] = []


def screen_of(target: Union[QWidget, QWindow]) -> Optional[QScreen]:
    """``target.screen()``: the screen the widget or window is on, as Qt reports it."""
    screen = target.screen()
    _held[:] = [held for held in _held if shiboken6.isValid(held)]
    if screen is not None and not any(held is screen for held in _held):
        _held.append(screen)
    return screen
