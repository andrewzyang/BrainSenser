"""
Shadcn-inspired Design System for iEEG BrainSense.

Based on shadcn/ui zinc theme, adapted for light mode with dark sidebar.
This theme provides centralized design tokens for colors, spacing, typography,
shadows, and other visual properties.

Usage:
    from src.ui.theme import Theme

    # Use in code
    button.setStyleSheet(f"background-color: {Theme.PRIMARY};")

    # Or use in QSS templates
    background-color: {Theme.PRIMARY};

Author: iEEG BrainSense Development Team
Last Updated: 2025-10-01
"""


class Theme:
    """
    Design tokens for the iEEG BrainSense application.

    Follows shadcn/ui zinc theme principles with a hybrid light/dark approach:
    - Dark sidebar for navigation
    - Light main content area
    - Consistent color palette
    - Accessible contrast ratios
    """

    # ========================================================================
    # Sidebar Colors (Dark Theme)
    # ========================================================================

    SIDEBAR_BG = "#1e293b"              # Dark slate background
    SIDEBAR_FG = "#ffffff"              # White text
    SIDEBAR_ACTIVE = "#2A2A2A"          # Active item background (manuscript dark)
    SIDEBAR_HOVER = "#555555"           # Hover state (manuscript cluster-bar grey)
    SIDEBAR_ACCENT = "#2A2A2A"          # Accent color (left border)
    SIDEBAR_BORDER = "#334155"          # Border between sections

    # ========================================================================
    # Neutral Greyscale Palette (manuscript-aligned)
    # Three filled tiers + hover/pressed variants. Use for buttons that should
    # match the paper-figure / slide aesthetic (no chromatic semantic colors).
    # ========================================================================

    NEUTRAL_LIGHT = "#8A8A8A"           # Manuscript chance-line grey
    NEUTRAL_LIGHT_HOVER = "#757575"
    NEUTRAL_LIGHT_PRESSED = "#616161"

    NEUTRAL_MID = "#555555"             # Manuscript cluster-bar grey (primary tier)
    NEUTRAL_MID_HOVER = "#454545"
    NEUTRAL_MID_PRESSED = "#363636"

    NEUTRAL_DARK = "#2A2A2A"            # Manuscript text dark (destructive tier)
    NEUTRAL_DARK_HOVER = "#1A1A1A"
    NEUTRAL_DARK_PRESSED = "#000000"

    # ========================================================================
    # Group Colors (manuscript palette — Jade / Rose)
    # Group 1 (non-craving / neutral): Jade family
    # Group 2 (craving): Rose family
    # ========================================================================

    JADE = "#2BA495"                    # Group 1 primary
    JADE_DARK = "#218377"               # Group 1 hover (derived)
    JADE_LIGHT = "#8DD4CA"              # Group 1 list bg / violin fill

    ROSE = "#D97F86"                    # Group 2 primary
    ROSE_DARK = "#AC4E8D"               # Group 2 label / hover / violin edge
    ROSE_LIGHT = "#F4D7D9"              # Group 2 list bg (derived pastel)

    # Neutral grey used to highlight rows in stats tables (e.g., the modal
    # band row of the Snapshots 5 Hz Band table or significant p-value rows in
    # PSD tables). Greyscale to match the manuscript aesthetic — soft enough to
    # keep black text readable, dark enough to read as "marked" against both the
    # white and #F4F4F4 alternating rows. Replace ad-hoc ``Qt.yellow`` references
    # with this token (or the TABLE_HIGHLIGHT_BG alias) so the whole app re-tunes
    # in one place.
    HIGHLIGHT_MODAL = "#D0D0D0"         # Neutral grey (was Material yellow-200)

    # ========================================================================
    # Main Content Colors (Light Theme)
    # ========================================================================

    MAIN_BG = "#f8fafc"                 # Very light gray background
    CARD_BG = "#ffffff"                 # White card background
    CARD_BORDER = "#e2e8f0"             # Light border

    # Semantic alias for muted backgrounds (maps to GRAY_100)
    # Use this for icon containers, disabled states, etc.
    MUTED = "#f1f5f9"                   # Muted background (slate-100)

    # ========================================================================
    # Interactive Colors (Buttons, Links, etc.)
    # ========================================================================

    # Primary (Blue)
    PRIMARY = "#3353a5"                 # Blue 500
    PRIMARY_HOVER = "#2b468c"           # Blue 600
    PRIMARY_ACTIVE = "#243b75"          # Blue 700
    PRIMARY_FG = "#ffffff"              # Text on primary

    # Secondary (Gray)
    SECONDARY = "#e2e8f0"               # Slate 200
    SECONDARY_HOVER = "#cbd5e1"         # Slate 300
    SECONDARY_ACTIVE = "#94a3b8"        # Slate 400
    SECONDARY_FG = "#1e293b"            # Text on secondary

    # Success (Green)
    SUCCESS = "#7cb842"                 # Emerald 500
    SUCCESS_HOVER = "#6a9f38"           # Emerald 600
    SUCCESS_ACTIVE = "#588530"          # Emerald 700
    SUCCESS_FG = "#ffffff"              # Text on success

    # Destructive (Red)
    DESTRUCTIVE = "#ef4444"             # Red 500
    DESTRUCTIVE_HOVER = "#dc2626"       # Red 600
    DESTRUCTIVE_ACTIVE = "#b91c1c"      # Red 700
    DESTRUCTIVE_FG = "#ffffff"          # Text on destructive

    # Warning (Amber)
    WARNING = "#f59e0b"                 # Amber 500
    WARNING_HOVER = "#d97706"           # Amber 600
    WARNING_ACTIVE = "#b45309"          # Amber 700
    WARNING_FG = "#ffffff"              # Text on warning

    # Ghost/Outline (Transparent)
    GHOST_HOVER = "#f1f5f9"             # Slate 100
    OUTLINE_BORDER = "#cbd5e1"          # Slate 300

    # ========================================================================
    # Text Colors
    # ========================================================================

    TEXT_PRIMARY = "#1e293b"            # Dark slate (main text)
    TEXT_SECONDARY = "#64748b"          # Slate 500 (secondary text)
    TEXT_MUTED = "#94a3b8"              # Slate 400 (muted text)
    TEXT_DISABLED = "#cbd5e1"           # Slate 300 (disabled text)
    TEXT_ON_DARK = "#ffffff"            # White text on dark backgrounds

    # ========================================================================
    # Border Colors
    # ========================================================================

    BORDER = "#e2e8f0"                  # Default border (slate 200)
    BORDER_MUTED = "#f1f5f9"            # Muted border (slate 100)
    BORDER_STRONG = "#cbd5e1"           # Strong border (slate 300)
    BORDER_FOCUS = "#3353a5"            # Focus ring (primary)

    # ========================================================================
    # Input Colors
    # ========================================================================

    INPUT_BG = "#ffffff"                # White background
    INPUT_BORDER = "#cbd5e1"            # Slate 300
    INPUT_BORDER_HOVER = "#94a3b8"      # Slate 400
    INPUT_BORDER_FOCUS = "#3353a5"      # Primary blue
    INPUT_PLACEHOLDER = "#94a3b8"       # Slate 400
    INPUT_DISABLED_BG = "#f1f5f9"       # Slate 100
    INPUT_DISABLED_FG = "#cbd5e1"       # Slate 300

    # ========================================================================
    # Table Colors (greyscale, manuscript-aligned — flat & minimal)
    # Single source of truth for every on-screen table. Kept in sync with the
    # global QSS QTableWidget block in ``src/ui/style.qss``; widgets that set
    # their own stylesheet read these tokens directly. No chromatic accents:
    # selection and significance highlights are neutral greys, gridlines are
    # suppressed, and the only border is a thin header underline.
    # ========================================================================

    TABLE_HEADER_BG = "#ffffff"         # Flat white header (no slate fill)
    TABLE_HEADER_FG = "#000000"         # Black header text
    TABLE_ROW_EVEN = "#ffffff"          # White rows
    TABLE_ROW_ODD = "#f4f4f4"           # Alternating light grey (manuscript band bg)
    TABLE_ROW_HOVER = "#ececec"         # Hover state (subtle grey)
    TABLE_BORDER = "#e0e0e0"            # Header underline / minimal border (manuscript sig grey)
    TABLE_GRIDLINE = "transparent"      # No cell gridlines (minimal)
    TABLE_SELECTION_BG = "#e0e0e0"      # Selected row/cell (grey, not blue)
    TABLE_SELECTION_FG = "#000000"      # Text on selection
    TABLE_HIGHLIGHT_BG = "#d0d0d0"      # Significant / modal-row highlight (grey, not yellow)

    # ========================================================================
    # Spacing (using 4px base unit)
    # ========================================================================

    SPACE_XS = "4px"                    # 1 unit
    SPACE_SM = "8px"                    # 2 units
    SPACE_MD = "16px"                   # 4 units
    SPACE_LG = "24px"                   # 6 units
    SPACE_XL = "32px"                   # 8 units
    SPACE_2XL = "48px"                  # 12 units

    # ========================================================================
    # Border Radius
    # ========================================================================

    RADIUS_SM = "6px"                   # Small (buttons, inputs)
    RADIUS_MD = "8px"                   # Medium (cards)
    RADIUS_LG = "12px"                  # Large (modals)
    RADIUS_FULL = "9999px"              # Full (pills, avatars)

    # ========================================================================
    # Shadows
    # ========================================================================

    SHADOW_SM = "0 1px 2px 0 rgba(0, 0, 0, 0.05)"
    SHADOW_MD = "0 1px 3px 0 rgba(0, 0, 0, 0.1), 0 1px 2px -1px rgba(0, 0, 0, 0.1)"
    SHADOW_LG = "0 10px 15px -3px rgba(0, 0, 0, 0.1), 0 4px 6px -4px rgba(0, 0, 0, 0.1)"
    SHADOW_XL = "0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 8px 10px -6px rgba(0, 0, 0, 0.1)"

    # ========================================================================
    # Typography
    # ========================================================================

    # Font Sizes
    FONT_SIZE_XS = "12px"
    FONT_SIZE_SM = "13px"
    FONT_SIZE_MD = "15px"
    FONT_SIZE_LG = "18px"
    FONT_SIZE_XL = "24px"
    FONT_SIZE_2XL = "28px"

    # Font Weights
    FONT_WEIGHT_NORMAL = "400"
    FONT_WEIGHT_MEDIUM = "500"
    FONT_WEIGHT_SEMIBOLD = "600"
    FONT_WEIGHT_BOLD = "700"

    # Line Heights
    LINE_HEIGHT_TIGHT = "1.25"
    LINE_HEIGHT_NORMAL = "1.5"
    LINE_HEIGHT_RELAXED = "1.75"

    # ========================================================================
    # Z-Index Layers
    # ========================================================================

    Z_INDEX_BASE = 0
    Z_INDEX_DROPDOWN = 1000
    Z_INDEX_MODAL = 2000
    Z_INDEX_TOOLTIP = 3000
    Z_INDEX_OVERLAY = 4000

    # ========================================================================
    # Transitions
    # ========================================================================

    TRANSITION_FAST = "150ms"
    TRANSITION_NORMAL = "200ms"
    TRANSITION_SLOW = "300ms"

    # ========================================================================
    # Component-Specific Heights
    # ========================================================================

    BUTTON_HEIGHT = "20px"
    BUTTON_HEIGHT_SM = "16px"
    BUTTON_HEIGHT_LG = "24px"

    INPUT_HEIGHT = "40px"
    INPUT_HEIGHT_SM = "32px"
    INPUT_HEIGHT_LG = "48px"

    TOPBAR_HEIGHT = "50px"
    SIDEBAR_WIDTH = "200px"


# Convenience aliases for common use cases
class Colors:
    """Convenience class for accessing colors without Theme prefix."""

    # Semantic colors
    PRIMARY = Theme.PRIMARY
    SUCCESS = Theme.SUCCESS
    DANGER = Theme.DESTRUCTIVE
    WARNING = Theme.WARNING

    # Grayscale
    BLACK = "#000000"
    WHITE = "#ffffff"
    GRAY_50 = "#f8fafc"
    GRAY_100 = "#f1f5f9"
    GRAY_200 = "#e2e8f0"
    GRAY_300 = "#cbd5e1"
    GRAY_400 = "#94a3b8"
    GRAY_500 = "#64748b"
    GRAY_600 = "#475569"
    GRAY_700 = "#334155"
    GRAY_800 = "#1e293b"
    GRAY_900 = "#0f172a"
