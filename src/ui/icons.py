"""
Icon helper module using QtAwesome.

Provides consistent icon styling and easy access to commonly used icons.
Maps lucide-react icons from reference design to FontAwesome equivalents.

Author: iEEG BrainSense Development Team
Last Updated: 2025-10-02
"""

import qtawesome as qta
from PySide6.QtGui import QIcon
from src.ui.theme import Theme


class Icons:
    """
    Icon provider using QtAwesome (FontAwesome).

    Maps lucide-react icons to FontAwesome equivalents.
    All icons use consistent theming.
    """

    # Color scheme
    PRIMARY = Theme.TEXT_PRIMARY
    SECONDARY = Theme.TEXT_SECONDARY
    MUTED = Theme.TEXT_MUTED

    @staticmethod
    def camera(color: str = None) -> QIcon:
        """Camera icon (Snapshots)."""
        return qta.icon('fa5s.camera', color=color or Icons.MUTED)

    @staticmethod
    def clock(color: str = None) -> QIcon:
        """Clock icon (Timeline)."""
        return qta.icon('fa5s.clock', color=color or Icons.MUTED)

    @staticmethod
    def radio(color: str = None) -> QIcon:
        """Radio/Broadcast icon (Indefinite Streaming)."""
        return qta.icon('fa5s.broadcast-tower', color=color or Icons.MUTED)

    @staticmethod
    def zap(color: str = None) -> QIcon:
        """Bolt/Zap icon (Definite Streaming)."""
        return qta.icon('fa5s.bolt', color=color or Icons.MUTED)

    @staticmethod
    def database(color: str = None) -> QIcon:
        """Database icon (Data Management)."""
        return qta.icon('fa5s.database', color=color or Icons.MUTED)

    @staticmethod
    def user_x(color: str = None) -> QIcon:
        """User-slash icon (No patient selected)."""
        return qta.icon('fa5s.user-slash', color=color or Icons.MUTED)

    @staticmethod
    def search(color: str = None) -> QIcon:
        """Search icon."""
        return qta.icon('fa5s.search', color=color or Icons.MUTED)

    @staticmethod
    def chevron_down(color: str = None) -> QIcon:
        """Chevron down icon."""
        return qta.icon('fa5s.chevron-down', color=color or Icons.MUTED)

    @staticmethod
    def upload(color: str = None) -> QIcon:
        """Upload icon."""
        return qta.icon('fa5s.upload', color=color or Icons.MUTED)

    @staticmethod
    def edit(color: str = None) -> QIcon:
        """Edit icon."""
        return qta.icon('fa5s.edit', color=color or Icons.MUTED)

    @staticmethod
    def user_plus(color: str = None) -> QIcon:
        """User plus icon (Create patient)."""
        return qta.icon('fa5s.user-plus', color=color or Icons.MUTED)

    @staticmethod
    def user_minus(color: str = None) -> QIcon:
        """User minus icon (Delete patient)."""
        return qta.icon('fa5s.user-minus', color=color or Icons.MUTED)

    @staticmethod
    def trash(color: str = None) -> QIcon:
        """Trash icon (Delete)."""
        return qta.icon('fa5s.trash', color=color or Icons.MUTED)

    @staticmethod
    def folder(color: str = None) -> QIcon:
        """Folder icon (Directory upload)."""
        return qta.icon('fa5s.folder-open', color=color or Icons.MUTED)

    @staticmethod
    def copy(color: str = None) -> QIcon:
        """Copy icon."""
        return qta.icon('fa5s.copy', color=color or Icons.MUTED)

    @staticmethod
    def save(color: str = None) -> QIcon:
        """Save icon."""
        return qta.icon('fa5s.save', color=color or Icons.MUTED)

    @staticmethod
    def refresh(color: str = None) -> QIcon:
        """Refresh icon (Reset view)."""
        return qta.icon('fa5s.sync', color=color or Icons.MUTED)

    @staticmethod
    def chart_line(color: str = None) -> QIcon:
        """Chart-line icon (Analysis/Visualization)."""
        return qta.icon('fa5s.chart-line', color=color or Icons.MUTED)

    @staticmethod
    def chevron_right(color: str = None) -> QIcon:
        """Chevron right icon."""
        return qta.icon('fa5s.chevron-right', color=color or Icons.MUTED)

    @staticmethod
    def robot(color: str = None) -> QIcon:
        """Robot icon (Machine Learning)."""
        return qta.icon('fa5s.robot', color=color or Icons.MUTED)

    @staticmethod
    def collapse(color: str = None) -> QIcon:
        """Double chevron left (collapse the sidebar to its icon rail)."""
        return qta.icon('fa5s.angle-double-left', color=color or Icons.MUTED)

    @staticmethod
    def expand(color: str = None) -> QIcon:
        """Double chevron right (expand the sidebar to its labels)."""
        return qta.icon('fa5s.angle-double-right', color=color or Icons.MUTED)

    @staticmethod
    def more(color: str = None) -> QIcon:
        """Horizontal ellipsis (overflow menu)."""
        return qta.icon('fa5s.ellipsis-h', color=color or Icons.MUTED)


# Convenience function for getting icon with custom options
def get_icon(name: str, color: str = None, size: int = None) -> QIcon:
    """
    Get an icon by name with optional color and size.

    Args:
        name: Icon name (e.g., 'camera', 'clock', 'database')
        color: Icon color (defaults to Theme.TEXT_MUTED)
        size: Icon size in pixels (optional)

    Returns:
        QIcon object

    Example:
        >>> icon = get_icon('camera', Theme.TEXT_PRIMARY)
        >>> icon = get_icon('database', '#1e293b', 32)
    """
    icon_map = {
        'camera': Icons.camera,
        'clock': Icons.clock,
        'radio': Icons.radio,
        'zap': Icons.zap,
        'bolt': Icons.zap,  # Alias
        'database': Icons.database,
        'user-x': Icons.user_x,
        'user-slash': Icons.user_x,  # Alias
        'search': Icons.search,
        'chevron-down': Icons.chevron_down,
        'upload': Icons.upload,
        'edit': Icons.edit,
        'user-plus': Icons.user_plus,
        'user-minus': Icons.user_minus,
        'trash': Icons.trash,
        'folder': Icons.folder,
        'copy': Icons.copy,
        'save': Icons.save,
        'refresh': Icons.refresh,
        'chart-line': Icons.chart_line,
        'chevron-right': Icons.chevron_right,
        'robot': Icons.robot,
    }

    if name not in icon_map:
        raise ValueError(f"Unknown icon: {name}")

    return icon_map[name](color)
