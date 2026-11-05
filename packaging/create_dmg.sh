#!/bin/bash
#
# BrainSenser DMG Creator
#
# This script creates a professional .dmg installer for the BrainSenser macOS application.
# It uses dmgbuild to package the .app bundle.
#
# Usage:
#   ./create_dmg.sh [version]
#
# Arguments:
#   version  - Optional version number (e.g., 1.0.0). If not provided, uses VERSION from brainsenser.spec
#
# Requirements:
#   - dmgbuild: pip install dmgbuild
#

set -e  # Exit on error

# ==============================================================================
# Configuration
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
APP_NAME="BrainSenser"
DIST_DIR="$PROJECT_ROOT/dist"
APP_BUNDLE="$DIST_DIR/${APP_NAME}.app"
SETTINGS_FILE="$SCRIPT_DIR/dmg_settings.py"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# ==============================================================================
# Helper Functions
# ==============================================================================

print_step() {
    echo -e "${BLUE}==>${NC} $1"
}

print_success() {
    echo -e "${GREEN}✓${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

print_error() {
    echo -e "${RED}✗${NC} $1"
}

check_command() {
    if command -v "$1" &> /dev/null; then
        return 0
    else
        return 1
    fi
}

# ==============================================================================
# Version Detection
# ==============================================================================

get_version_from_main() {
    # The bundle's version (the spec's VERSION, which also goes into Info.plist),
    # so the dmg's name always matches the app inside it.
    local version=$(grep -E "^VERSION = '[0-9.]+'" "$SCRIPT_DIR/brainsenser.spec" | sed -E "s/^VERSION = '([0-9.]+)'.*/\1/")
    if [ -z "$version" ]; then
        print_error "No VERSION found in packaging/brainsenser.spec" >&2
        exit 1
    fi
    echo "$version"
}

# ==============================================================================
# Main Script
# ==============================================================================

main() {
    print_step "BrainSenser DMG Builder"
    echo

    # Get version number
    if [ -n "$1" ]; then
        VERSION="$1"
        print_step "Using provided version: $VERSION"
    else
        VERSION=$(get_version_from_main)
        print_step "Auto-detected version: $VERSION"
    fi

    DMG_NAME="${APP_NAME}-${VERSION}.dmg"
    DMG_PATH="$DIST_DIR/$DMG_NAME"

    # Check if .app bundle exists
    print_step "Checking for .app bundle..."
    if [ ! -d "$APP_BUNDLE" ]; then
        print_error ".app bundle not found at: $APP_BUNDLE"
        echo
        echo "Please build the .app bundle first using PyInstaller:"
        echo "  pyinstaller BrainSenser.spec"
        exit 1
    fi
    print_success "Found .app bundle: $APP_BUNDLE"

    # Check if dist directory exists
    if [ ! -d "$DIST_DIR" ]; then
        print_step "Creating dist directory..."
        mkdir -p "$DIST_DIR"
    fi

    # Remove existing DMG if it exists
    if [ -f "$DMG_PATH" ]; then
        print_step "Removing existing DMG..."
        rm -f "$DMG_PATH"
    fi

    # Export APP_PATH and settings dir for dmg_settings.py
    export APP_PATH="$APP_BUNDLE"
    export DMG_SETTINGS_DIR="$SCRIPT_DIR"

    # dmgbuild only: dmg_settings.py is what puts LICENSE.txt and
    # THIRD_PARTY_NOTICES.txt next to the app. (The old create-dmg fallback
    # skipped them, and passing it the .app packed the bundle's insides.)
    if check_command dmgbuild; then
        print_step "Using dmgbuild to create DMG..."
        print_step "Output: $DMG_PATH"
        echo

        dmgbuild \
            -s "$SETTINGS_FILE" \
            -D app="$APP_BUNDLE" \
            "BrainSenser Installer" \
            "$DMG_PATH"

        if [ $? -eq 0 ]; then
            print_success "DMG created successfully using dmgbuild!"
        else
            print_error "dmgbuild failed!"
            exit 1
        fi

    else
        print_error "dmgbuild not found!"
        echo
        echo "Install it with: pip install dmgbuild"
        exit 1
    fi

    # Show DMG info
    echo
    print_step "DMG Information:"
    echo "  Name: $DMG_NAME"
    echo "  Path: $DMG_PATH"
    if [ -f "$DMG_PATH" ]; then
        SIZE=$(du -h "$DMG_PATH" | cut -f1)
        echo "  Size: $SIZE"
    fi

    echo
    print_success "Build complete!"
    echo
    echo "Next steps:"
    echo "  1. Test the DMG by mounting it: open $DMG_PATH"
    echo "  2. Drag the app to Applications and verify it launches"
    echo "  3. Run the checks in packaging/REEXPORT.md before sharing it"
}

# Run main function
main "$@"
