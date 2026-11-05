"""Filesystem paths to bundled, read-only UI assets (icons, logos).

Resolved for both development (running from the repo) and a frozen PyInstaller
build. ``PathResolver`` deliberately owns only the *writable* ``.brainsense_data``
tree; this module owns the *read-only* assets that ship inside the bundle, so the
two concerns stay separate.

Pure ``pathlib`` — no Qt, no qtawesome, no project imports — so it is safe to
import from any view module and from ``main`` while the global stylesheet is
being loaded.
"""

from __future__ import annotations

import sys
from pathlib import Path


def _base_dir() -> Path:
    """Directory that contains the bundled ``assets/`` tree.

    PyInstaller extracts data files (including ``assets/``, added by the
    packaging spec) under ``sys._MEIPASS``. In a normal checkout the assets sit
    at the repo root, two parents above this file (``src/ui/asset_paths.py``).
    """
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parents[2]


_ASSETS_DIR = _base_dir() / "assets"


def asset_path(*parts: str) -> Path:
    """Absolute path to a bundled asset, e.g. ``asset_path("icons", "x.svg")``."""
    return _ASSETS_DIR.joinpath(*parts)


def qss_url(*parts: str) -> str:
    """Return a Qt-stylesheet-ready ``url("…")`` for a bundled asset.

    The path is absolute and forward-slashed (Qt accepts ``/`` on every
    platform) and wrapped in double quotes so paths containing spaces — e.g. an
    installed ``/Applications/BrainSenser.app`` under a user folder with a space
    — still parse. Qt's QSS ``url()`` does **not** accept ``data:`` URIs, which
    is why a real file path is required rather than an inline SVG.
    """
    return f'url("{asset_path(*parts).as_posix()}")'
