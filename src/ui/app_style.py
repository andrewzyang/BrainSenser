"""Global application stylesheet: the one place that reads and applies ``style.qss``.

Shared by ``main()`` (via :mod:`src.ui.app_bootstrap`) and the UI test harness,
so tests measure the app with exactly the stylesheet it ships with.
"""

import logging
from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import QApplication

from src.ui.asset_paths import qss_url

logger = logging.getLogger(__name__)

STYLESHEET_PATH = Path(__file__).parent / "style.qss"

# Placeholder in style.qss for the combo-box chevron; QSS url() needs a real
# absolute file path (no data: URIs), which differs between checkout and bundle.
_CHEVRON_PLACEHOLDER = "__CHEVRON_URL__"


def load_app_stylesheet(path: Path = STYLESHEET_PATH) -> str:
    """Return the global stylesheet with its asset placeholders resolved."""
    with open(path, "r", encoding="utf-8") as f:
        return f.read().replace(_CHEVRON_PLACEHOLDER, qss_url("icons", "chevron_down.svg"))


def apply_app_stylesheet(app: QApplication, path: Path = STYLESHEET_PATH) -> Optional[str]:
    """Load the global stylesheet and apply it to ``app``.

    Returns the applied stylesheet, or ``None`` (logged) when the file is missing.
    """
    try:
        qss = load_app_stylesheet(path)
    except FileNotFoundError:
        logger.warning(f"Stylesheet not found: {path}")
        return None
    app.setStyleSheet(qss)
    logger.info(f"Loaded stylesheet: {path}")
    return qss
