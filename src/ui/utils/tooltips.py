"""Tooltip text helpers."""

import html


def wrap_tooltip(text: str) -> str:
    """Return ``text`` as rich text so Qt word-wraps the tooltip when it is shown.

    Qt wraps a plain-text tooltip only once it is wider than the screen (a
    975-px single line was measured on a 1093-px screen). Rich text wraps using
    the current tooltip font, so the width follows the interface size. Don't add
    a QSS ``max-width`` instead: it clips plain-text tooltips.
    """
    return "<p>" + html.escape(text).replace("\n", "<br>") + "</p>"
