"""Message dialogs that fit the screen they open on.

``QMessageBox`` sizes itself to its whole text each time it is shown and never
limits its height: a 40-line message gave a 1549-px box on a 576-px screen,
with OK off-screen (``tables:D1``). :func:`message_box` keeps the box's own
text to what fits and moves the rest into the scrollable, fixed-height
"Show Details…" area; :func:`clamp_to_screen` caps other dialogs at 90 % of
their screen.
"""

import math
import traceback
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QSize, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QFontMetrics, QScreen
from PySide6.QtWidgets import QLabel, QMessageBox, QWidget

from src.ui.utils.screens import screen_of

# A dialog never takes more than this share of its screen's available size.
SCREEN_SHARE = 0.9

# The message text may fill half the screen's height; the icon, the buttons and
# the expanded details area fit in the other half.
_TEXT_SHARE = 0.5
_MIN_LINES = 6

# QMessageBox wraps its text at min(half the screen, 420 px on macOS, 500 px
# elsewhere) minus the icon column and margins (under 120 px). Counting wrapped
# lines at the narrowest of these widths can only over-count them.
_WRAP_LIMIT_PX = 420
_ICON_COLUMN_PX = 120

ELLIPSIS = "…"


def _dialog_screen(widget: QWidget) -> QScreen:
    """The screen ``widget`` is on; a dialog not shown yet opens on its parent window's."""
    window = widget.window()
    parent = window.parentWidget()
    if parent is not None and not window.isVisible():
        window = parent.window()
    return screen_of(window)


def screen_limit(widget: QWidget) -> QSize:
    """90 % of the available size of the screen ``widget`` is on (a dialog: its parent's)."""
    return _dialog_screen(widget).availableGeometry().size() * SCREEN_SHARE


def clamp_to_screen(dialog: QWidget) -> None:
    """Resize ``dialog`` to its size hint, but no larger than :func:`screen_limit`."""
    dialog.resize(dialog.sizeHint().boundedTo(screen_limit(dialog)))


def fit_message_text(text: str, box: QMessageBox) -> tuple[str, Optional[str]]:
    """Split ``text`` into what ``box`` shows and what goes under "Show Details…".

    Returns ``(text, None)`` when the text, wrapped as the box wraps it and in
    its label's font, takes at most half the height of the box's screen.
    Otherwise returns the leading lines that fit, ending in "…", and the whole
    text for the details area.
    """
    label = box.findChild(QLabel, "qt_msgbox_label") or box  # the box's text label
    metrics = QFontMetrics(label.font())
    available = _dialog_screen(box).availableGeometry()
    wrap = min(available.width() // 2, _WRAP_LIMIT_PX) - _ICON_COLUMN_PX
    budget = max(_MIN_LINES, int(_TEXT_SHARE * available.height() / metrics.lineSpacing()))

    lines = text.split("\n")
    rows = [max(1, math.ceil(metrics.horizontalAdvance(line) / wrap)) for line in lines]
    if sum(rows) <= budget:
        return text, None
    kept, used = 0, 0
    while used + rows[kept] <= budget - 1:  # the last row is for the ellipsis
        used += rows[kept]
        kept += 1
    if kept:
        return "\n".join(lines[:kept]) + "\n" + ELLIPSIS, text
    # The first paragraph alone is too long; word wrap may need one row more.
    return metrics.elidedText(lines[0], Qt.TextElideMode.ElideRight, (budget - 2) * wrap), text


def message_box(parent: Optional[QWidget], icon: QMessageBox.Icon, title: str, text: str,
                details: Optional[str] = None) -> QMessageBox:
    """An OK box showing ``text`` (plain text) that fits its screen.

    What does not fit, then ``details``, go under "Show Details…".
    """
    box = QMessageBox(icon, title, "", QMessageBox.StandardButton.Ok, parent)
    box.setTextFormat(Qt.TextFormat.PlainText)
    box.ensurePolished()  # measure in the stylesheet's font
    summary, overflow = fit_message_text(text, box)
    box.setText(summary)
    detailed = "\n\n".join(part for part in (overflow, details) if part)
    if detailed:
        box.setDetailedText(detailed)
    return box


def show_message(parent: Optional[QWidget], icon: QMessageBox.Icon, title: str, text: str,
                 details: Optional[str] = None) -> int:
    """Show :func:`message_box` modally; returns what ``exec()`` returns."""
    box = message_box(parent, icon, title, text, details)
    result = box.exec()
    box.deleteLater()  # a parented box would otherwise live as long as its parent
    return result


def show_unexpected_error(parent: Optional[QWidget], exc_info, log_file: Optional[Path]) -> None:
    """Report an uncaught exception, given as ``(type, value, traceback)``, over ``parent``.

    The traceback goes under "Show Details…"; with a ``log_file``, "Open Log
    Folder" shows it in the file manager. If the fitted box cannot be built, the
    plain static box still tells the user what happened.
    """
    exc_type, exc_value, _ = exc_info
    paragraphs = [f"An unexpected error occurred ({exc_type.__name__}).", str(exc_value),
                  "The app may be unstable. Export anything you need, then restart."]
    if log_file is not None:
        paragraphs.append("The error was written to the log.")
    text = "\n\n".join(paragraph for paragraph in paragraphs if paragraph)
    try:
        box = message_box(parent, QMessageBox.Icon.Critical, "Unexpected Error", text,
                          details="".join(traceback.format_exception(*exc_info)))
        open_folder = (box.addButton("Open Log Folder", QMessageBox.ButtonRole.ActionRole)
                       if log_file is not None else None)
    except Exception:
        QMessageBox.critical(None, "Unexpected Error", text)
        return
    box.exec()
    if open_folder is not None and box.clickedButton() is open_folder:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(log_file.parent)))
    box.deleteLater()
