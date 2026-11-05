"""
GreyscaleProxyStyle - app-wide greyscale severity icons for standard dialogs.

QSS can theme dialog *buttons* and backgrounds, but it cannot recolour the
coloured standard icons Qt paints in QMessageBox (the red "critical" octagon,
the blue "information" disc, the amber "warning" triangle). This QProxyStyle
overrides ``standardIcon()`` for the four ``SP_MessageBox*`` pixmaps so every
message box in the app shows a greyscale glyph from the manuscript palette -
with no changes to the ~37 QMessageBox call sites.

Install once at startup, right after the QApplication is created:

    from src.ui.greyscale_proxy_style import install_greyscale_dialog_icons
    install_greyscale_dialog_icons(app)

Author: iEEG BrainSense Development Team
Last Updated: 2026-06-03
"""

import qtawesome as qta
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QProxyStyle, QStyle

from src.ui.theme import Theme


# Standard-pixmap name -> (Font Awesome glyph, greyscale colour). Message-box
# severity icons: error/warning use the darkest tier, info/question a mid grey
# (a subtle severity cue while staying fully greyscale). File-dialog toolbar
# chrome (the green "up" arrow, yellow "new folder") uses mid grey too. The
# folder/drive icons in the file listing are content and are intentionally left
# untouched. Resolved via getattr so a name missing on some Qt build is skipped
# rather than raising.
_ICON_SPEC_NAMES = {
    "SP_MessageBoxCritical": ("fa5s.times-circle", Theme.NEUTRAL_DARK),
    "SP_MessageBoxWarning": ("fa5s.exclamation-triangle", Theme.NEUTRAL_DARK),
    "SP_MessageBoxInformation": ("fa5s.info-circle", Theme.NEUTRAL_MID),
    "SP_MessageBoxQuestion": ("fa5s.question-circle", Theme.NEUTRAL_MID),
    "SP_FileDialogToParent": ("fa5s.arrow-up", Theme.NEUTRAL_MID),
    "SP_FileDialogNewFolder": ("fa5s.folder-plus", Theme.NEUTRAL_MID),
}


def _resolve_icon_specs() -> dict:
    """Map available QStyle.StandardPixmap members to their greyscale specs."""
    specs = {}
    for name, spec in _ICON_SPEC_NAMES.items():
        standard_pixmap = getattr(QStyle.StandardPixmap, name, None)
        if standard_pixmap is not None:
            specs[standard_pixmap] = spec
    return specs


class GreyscaleProxyStyle(QProxyStyle):
    """
    Proxy style that swaps the coloured standard dialog icons for greyscale ones.

    Wraps the application's default style and only intercepts the message-box
    severity icons and the file-dialog toolbar chrome; everything else is
    delegated unchanged to the base style, so native widget rendering is
    preserved.
    """

    _ICON_SPECS = _resolve_icon_specs()

    def __init__(self):
        super().__init__()  # no base -> wraps the default application style
        self._icon_cache: dict = {}

    def standardIcon(self, standard_icon, option=None, widget=None) -> QIcon:  # noqa: N802 - Qt override
        spec = self._ICON_SPECS.get(standard_icon)
        if spec is not None:
            if standard_icon not in self._icon_cache:
                glyph, color = spec
                self._icon_cache[standard_icon] = qta.icon(glyph, color=color)
            return self._icon_cache[standard_icon]
        return super().standardIcon(standard_icon, option, widget)


def install_greyscale_dialog_icons(app: QApplication) -> None:
    """Wrap the application's style so dialog severity icons render in greyscale."""
    app.setStyle(GreyscaleProxyStyle())
