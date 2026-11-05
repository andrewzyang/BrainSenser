"""
DMG Build Settings for BrainSenser macOS Application

This configuration file is used by dmgbuild to create a professional
.dmg installer for the BrainSenser application.

Usage:
    dmgbuild -s dmg_settings.py "BrainSenser" BrainSenser.dmg
"""

import os
from pathlib import Path

# dmgbuild loads this file via exec() WITHOUT defining __file__, so derive the
# settings directory from an env var (exported by create_dmg.sh); fall back to cwd.
_SETTINGS_DIR = Path(os.environ.get("DMG_SETTINGS_DIR", os.getcwd()))

# ==============================================================================
# Application Settings
# ==============================================================================

# Name of the application (without .app extension)
application_name = "BrainSenser"

# Path to the .app bundle (relative to packaging directory)
# This will be set dynamically by create_dmg.sh
app_path = os.environ.get('APP_PATH', '../dist/BrainSenser.app')

# ==============================================================================
# DMG Volume Settings
# ==============================================================================

# Volume name (shown in Finder when mounted)
volume_name = "BrainSenser Installer"

# DMG format: UDZO (compressed), UDBZ (bzip2), ULFO (lzfse)
format = "UDBZ"

# File size (None = automatic)
size = None

# ==============================================================================
# DMG Window Appearance
# ==============================================================================

# Window position and size when opened
# Format: (x, y, width, height)
window_rect = ((100, 100), (640, 580))

# Icon size in the DMG window (pixels)
icon_size = 128

# Text size for icon labels
text_size = 12

# Icon positions: {filename: (x, y)}
# Positions are in pixels from top-left of window
icon_locations = {
    f'{application_name}.app': (160, 240),
    'Applications': (480, 240),
    'HOW_TO_OPEN.txt': (160, 440),
    'LICENSE.txt': (320, 440),
    'THIRD_PARTY_NOTICES.txt': (480, 440)
}

# ==============================================================================
# Background Image
# ==============================================================================

# Background image for the DMG window
# Set to None if no background image is available
# When ready, place image at: packaging/assets/dmg_background.png
background_image_path = _SETTINGS_DIR / "assets" / "dmg_background.png"

if background_image_path.exists():
    background = str(background_image_path)
else:
    # Fallback: use a solid color background
    background = None

# ==============================================================================
# Files to Include
# ==============================================================================

# Files to copy into the DMG: the .app bundle, the first-launch instructions
# (the app is unsigned), and the license and third-party notices at the top
# level, where the LGPL's "prominent notice" gets seen. They are copied as .txt
# so they open on double-click; a missing file fails the build.
_PROJECT_ROOT = _SETTINGS_DIR.parent
files = [
    app_path,
    (str(_PROJECT_ROOT / 'HOW_TO_OPEN.txt'), 'HOW_TO_OPEN.txt'),
    (str(_PROJECT_ROOT / 'LICENSE'), 'LICENSE.txt'),
    (str(_PROJECT_ROOT / 'THIRD_PARTY_NOTICES.txt'), 'THIRD_PARTY_NOTICES.txt'),
]

# Create symbolic link to /Applications for easy installation
symlinks = {
    'Applications': '/Applications'
}

# ==============================================================================
# Volume Icon
# ==============================================================================

# Icon for the DMG volume itself (.icns file)
# When ready, place icon at: packaging/assets/volume_icon.icns
volume_icon_path = _SETTINGS_DIR / "assets" / "volume_icon.icns"

if volume_icon_path.exists():
    badge_icon = str(volume_icon_path)
else:
    badge_icon = None

# ==============================================================================
# License Agreement (Optional)
# ==============================================================================

# License file to display during installation
# Uncomment and set path when ready
# license = {
#     'default-language': 'en_US',
#     'licenses': {
#         'en_US': str(Path(__file__).parent / 'LICENSE.txt')
#     }
# }

# ==============================================================================
# Code Signing (Optional - for future use)
# ==============================================================================

# Sign the DMG with a Developer ID
# Requires valid Apple Developer certificate
# sign = {
#     'signing-identity': 'Developer ID Application: Your Name (TEAM_ID)',
#     'timestamp': True
# }

# ==============================================================================
# Advanced Settings
# ==============================================================================

# Show/hide icon preview column in Finder
icon_view_settings = {
    'iconSize': icon_size,
    'textSize': text_size,
    'arrangeBy': 'none',
    'showIconPreview': False,
    'showItemInfo': False,
    'labelOnBottom': True,
    'viewOptionsVersion': 1
}

# Grid spacing
grid_offset = (0, 0)
grid_spacing = 100

# Scroll position
scroll_position = (0, 0)

# Finder view (icons, list, columns, flow)
default_view = 'icon-view'

# Show toolbar
show_toolbar = False

# Show tab view
show_tab_view = False

# Show path bar
show_path_bar = False

# Show sidebar
show_sidebar = False

# Show status bar
show_status_bar = False

# Sidebar width
sidebar_width = 180
