"""Child-process side of the plot tests (run through ``AppProcess``).

A child can take fonts out of matplotlib's font list before any plot module
resolves its family (:func:`drop_fonts`), which is how a machine without
Helvetica Neue — Windows, Linux — is simulated on macOS.
"""

import logging
import time
import warnings
from pathlib import Path

from tests.ui.plots import _states

# Where the font tests render: a regular and a compact canvas.
FONT_TEST_SIZES = ((1048, 466), (600, 220))


class _Records(logging.Handler):
    def __init__(self):
        super().__init__(logging.WARNING)
        self.messages = []

    def emit(self, record):
        self.messages.append(record.getMessage())


def drop_fonts(families) -> None:
    """Remove ``families`` from matplotlib's font list (this process only)."""
    from matplotlib import font_manager

    font_manager.fontManager.ttflist = [font for font in font_manager.fontManager.ttflist
                                        if font.name not in families]


def settle(widget, timeout_s: float = 30.0) -> None:
    """Process events until the widget shows its final frame."""
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    deadline = time.monotonic() + timeout_s
    app.processEvents()
    while not widget.is_layout_settled():
        if time.monotonic() > deadline:
            raise TimeoutError(f"{type(widget).__name__} did not settle")
        app.processEvents()
        time.sleep(0.002)


def render_without_fonts(payload) -> dict:
    """Show and export every plot without ``payload["drop"]``'s fonts; report
    the family the plots resolved and every warning matplotlib raised."""
    drop_fonts(payload["drop"])
    out_dir = Path(payload["out_dir"])
    out_dir.mkdir()
    records = _Records()
    logging.getLogger("matplotlib").addHandler(records)
    exports = 0
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        from src.ui.widgets.plot_fonts import plot_font_family

        for kind in _states.KINDS:
            for state in ("result", "mixed"):
                widget = _states.make(kind)
                _states.show(kind, widget, state, event_types=5)
                widget.setMinimumHeight(0)
                widget.show()
                for size in FONT_TEST_SIZES:
                    widget.resize(*size)
                    settle(widget)
                for fmt in ("png", "pdf", "svg"):
                    widget.render_export(str(out_dir / f"{kind}_{state}.{fmt}"), 100)
                    exports += 1
                widget.close()
    return {"family": plot_font_family(), "exports": exports,
            "warnings": records.messages + [str(warning.message) for warning in caught]}
