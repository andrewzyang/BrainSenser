# DMG Assets

This directory contains visual assets for the BrainSenser DMG installer.

## Required Files

### 1. dmg_background.png
- **Purpose:** Background image for the DMG window
- **Size:** 1280x800 pixels (2x resolution for Retina displays)
- **Format:** PNG with transparency support
- **Design:** Should show installation instructions (drag app to Applications)

### 2. volume_icon.icns
- **Purpose:** Icon displayed for the mounted DMG volume
- **Format:** Apple .icns format (contains multiple sizes)
- **Sizes Required:**
  - 16x16, 32x32, 64x64, 128x128, 256x256, 512x512, 1024x1024 pixels
- **Creation:** Use `iconutil` to convert from iconset (`iconutil -c icns <name>.iconset`)

## Current Status

Currently, these assets are **not included** in the repository. The DMG build script will work without them but will use fallback styling:
- No background image (solid color instead)
- Default macOS volume icon

## Creating Assets

The app icon itself is made by `packaging/make_app_icon.py`; the full build
procedure is in `packaging/REEXPORT.md`.

## Adding Assets to This Directory

Once created, place the files here:
```
packaging/assets/
├── dmg_background.png
├── volume_icon.icns
└── README.md (this file)
```

The build script will automatically detect and use them.
