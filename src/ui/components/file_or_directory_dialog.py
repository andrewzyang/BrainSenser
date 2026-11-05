"""
FileOrDirectoryDialog - Open dialog that accepts a single file OR a directory.

Qt's native open panels are either file-only (``getOpenFileName``) or
folder-only (``getExistingDirectory``); there is no native "file or directory"
mode. This component uses Qt's own (non-native) ``QFileDialog`` configured so a
single picker can return either one JSON file or one directory in one step, with
no intermediate "are you picking a file or a folder?" prompt.

Usage (View layer only - returns a Path, makes no upload decisions):
    path = FileOrDirectoryDialog.get_file_or_directory(
        parent, "Select a JSON file or a directory of JSON files"
    )
    if path is not None:
        viewmodel.upload_path(path)

Author: iEEG BrainSense Development Team
Last Updated: 2026-06-03
"""

from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import (
    QFileDialog,
    QWidget,
    QListView,
    QTreeView,
    QAbstractItemView,
)

from src.ui.components.dialog_fit import clamp_to_screen


class FileOrDirectoryDialog(QFileDialog):
    """
    Non-native open dialog that lets the user choose one file or one directory.

    Interaction:
    - Single-click a file or a folder to highlight it, then click Open (or press
      Enter) to *choose* it.
    - Double-click a folder still navigates into it (normal browsing).

    The directory-vs-file decision is left to the caller (the ViewModel); this
    dialog only returns the selected ``Path``.
    """

    # Directories are shown regardless of the name filter; the filter only
    # constrains which files are selectable.
    JSON_FILTER = "BrainSense JSON (*.json);;All files (*)"

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        caption: str = "",
        directory: str = "",
    ):
        super().__init__(parent, caption, directory, self.JSON_FILTER)

        # Force Qt's own dialog so a single picker can return a file OR a folder.
        self.setOption(QFileDialog.Option.DontUseNativeDialog, True)
        self.setFileMode(QFileDialog.FileMode.ExistingFile)
        self.setAcceptMode(QFileDialog.AcceptMode.AcceptOpen)

        self._relax_selection_modes()

    def _relax_selection_modes(self) -> None:
        """
        Allow a directory row to be highlighted so it can be chosen.

        Wrapped defensively: the internal view layout differs across Qt builds,
        so if the views can't be found the dialog simply degrades to a plain
        file picker rather than raising.
        """
        try:
            for view in self.findChildren(QListView) + self.findChildren(QTreeView):
                view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        except Exception:  # pragma: no cover - defensive against Qt internals
            pass

    def accept(self) -> None:  # noqa: N802 - Qt override
        """
        Choose a highlighted directory instead of navigating into it.

        The base ``accept()`` would ``cd`` into a selected directory (because the
        file mode is ``ExistingFile``); we intercept that so a single-clicked
        directory is returned as the result. Files fall through to normal
        handling.
        """
        selected = self.selectedFiles()
        if selected and Path(selected[0]).is_dir():
            self.done(QFileDialog.DialogCode.Accepted)
            return
        super().accept()

    def selected_path(self) -> Optional[Path]:
        """Return the selected file or directory, or None if there is none."""
        selected = self.selectedFiles()
        return Path(selected[0]) if selected else None

    @classmethod
    def get_file_or_directory(
        cls,
        parent: Optional[QWidget] = None,
        caption: str = "",
        directory: str = "",
    ) -> Optional[Path]:
        """
        Show the dialog modally and return the chosen path.

        Args:
            parent: Parent widget for modality.
            caption: Dialog title.
            directory: Initial directory.

        Returns:
            The selected ``Path`` (a file or a directory), or ``None`` if the
            user cancelled.
        """
        dialog = cls(parent, caption, directory)
        clamp_to_screen(dialog)
        if dialog.exec() == QFileDialog.DialogCode.Accepted:
            return dialog.selected_path()
        return None
