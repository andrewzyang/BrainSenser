"""
Atomic file writer utility.

Ensures file operations are atomic - either complete successfully or leave no trace.

Author: iEEG BrainSense Development Team
Created: 2025-10-08
"""

import json
import logging
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Callable, Optional

logger = logging.getLogger(__name__)


class AtomicFileWriter:
    """
    Utility for atomic file write operations.

    Uses temporary file pattern to ensure operations are atomic:
    1. Write to temp file
    2. Perform validation/database operations
    3. Rename temp file to final location (atomic on POSIX)
    4. Clean up temp file if any step fails

    Example:
        writer = AtomicFileWriter()
        with writer.atomic_write('/path/to/file.json') as temp_path:
            # Write to temp_path
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump(data, f)

            # If this succeeds, temp file is renamed
            # If exception occurs, temp file is deleted
    """

    def __init__(self, temp_suffix: str = '.tmp'):
        """
        Initialize atomic file writer.

        Args:
            temp_suffix: Suffix for temporary files (default: '.tmp')
        """
        self.temp_suffix = temp_suffix

    @contextmanager
    def atomic_write(self, target_path: Path, cleanup_on_error: bool = True):
        """
        Context manager for atomic file write.

        Args:
            target_path: Final destination path
            cleanup_on_error: If True, delete temp file on exception

        Yields:
            Path to temporary file (write to this path)

        Raises:
            Any exception from the context block

        Example:
            with writer.atomic_write(Path('data.json')) as temp_path:
                temp_path.write_text('{"key": "value"}')
                # Automatic rename on success
        """
        target_path = Path(target_path)
        temp_path = target_path.with_suffix(target_path.suffix + self.temp_suffix)

        try:
            # Ensure parent directory exists without relying on Path.stat (tests patch it)
            os.makedirs(target_path.parent, exist_ok=True)

            # Yield temp path for writing
            yield temp_path

            # Success - rename temp to target (atomic on POSIX)
            temp_path.replace(target_path)

        except Exception as e:
            # Error occurred - clean up temp file
            if cleanup_on_error and temp_path.exists():
                try:
                    temp_path.unlink()
                except Exception as cleanup_error:
                    # Log but don't mask original exception
                    logger.warning(f"Failed to clean up temp file {temp_path}: {cleanup_error}")

            # Re-raise original exception
            raise e

    def write_json_atomic(self, target_path: Path, data: Dict[str, Any],
                          pre_commit_hook: Optional[Callable[[Path], None]] = None) -> Path:
        """
        Write JSON data atomically with optional pre-commit hook.

        Args:
            target_path: Final destination path
            data: JSON-serializable data
            pre_commit_hook: Optional function called after file write,
                             before rename. Receives temp file path.
                             Can be used for database operations.
                             If raises exception, file is not renamed.

        Returns:
            Path to created file (same as target_path)

        Raises:
            Exception if write fails or pre_commit_hook raises

        Example:
            def store_in_db(file_path: Path):
                # Compute checksum, store in database
                checksum = compute_checksum(file_path)
                db.insert(file_path, checksum)

            writer.write_json_atomic(
                Path('data.json'),
                {'key': 'value'},
                pre_commit_hook=store_in_db
            )
        """
        with self.atomic_write(target_path) as temp_path:
            # Write JSON to temp file
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)

            # Call pre-commit hook if provided
            if pre_commit_hook:
                pre_commit_hook(temp_path)

            # If we get here, success - temp file will be renamed

        return target_path

    def write_numpy_atomic(self, target_path: Path, array: 'np.ndarray',
                           pre_commit_hook: Optional[Callable[[Path], None]] = None) -> Path:
        """
        Write NumPy array atomically with optional pre-commit hook.

        Args:
            target_path: Final destination path
            array: NumPy array to save
            pre_commit_hook: Optional function called after write, before rename

        Returns:
            Path to created file
        """
        import numpy as np

        with self.atomic_write(target_path) as temp_path:
            # Write numpy array to temp file
            np.save(temp_path, array)

            # Call pre-commit hook if provided
            if pre_commit_hook:
                pre_commit_hook(temp_path)

        return target_path


# Convenience functions
def write_json_atomic(target_path: Path, data: Dict[str, Any],
                      pre_commit_hook: Optional[Callable[[Path], None]] = None) -> Path:
    """Convenience function for atomic JSON write."""
    writer = AtomicFileWriter()
    return writer.write_json_atomic(target_path, data, pre_commit_hook)


def write_numpy_atomic(target_path: Path, array: 'np.ndarray',
                       pre_commit_hook: Optional[Callable[[Path], None]] = None) -> Path:
    """Convenience function for atomic NumPy write."""
    writer = AtomicFileWriter()
    return writer.write_numpy_atomic(target_path, array, pre_commit_hook)
