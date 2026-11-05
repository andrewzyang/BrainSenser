"""The application log file: a rotating log in ``<data dir>/logs``.

The packaged app has no console, so without a file the log that error dialogs
point to would not exist. :func:`configure_logging` adds the file to the root
logger; it is called once at the start of ``main()`` and never at import time,
so importing this module (tests, tools) writes nothing.
"""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

from src.core.path_resolver import default_app_data_dir

LOG_FILE_NAME = "brainsenser.log"
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

# Up to 1 MiB per file plus five rotated files: at most 6 MiB on disk.
_MAX_BYTES = 1024 * 1024
_BACKUP_COUNT = 5

# Name of the root-logger handler this module installs (its single source of truth).
_HANDLER_NAME = "brainsenser_log_file"

logger = logging.getLogger(__name__)


def log_directory() -> Path:
    """The folder holding the log files (honours ``BRAINSENSER_DATA_DIR``)."""
    return default_app_data_dir() / "logs"


def configure_logging() -> Optional[Path]:
    """Send the root logger's records to the rotating log file as well.

    Idempotent. Returns the log file, or None when it cannot be created; the
    reason is then logged to the handlers that already exist.
    """
    current = active_log_file()
    if current is not None:
        return current
    path = log_directory() / LOG_FILE_NAME
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(path, maxBytes=_MAX_BYTES, backupCount=_BACKUP_COUNT,
                                      encoding="utf-8")
    except OSError:
        logger.warning("Cannot write the log file %s", path, exc_info=True)
        return None
    handler.set_name(_HANDLER_NAME)
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    logging.getLogger().addHandler(handler)
    return path


def active_log_file() -> Optional[Path]:
    """The file :func:`configure_logging` logs to, or None if it is not configured."""
    for handler in logging.getLogger().handlers:
        if handler.get_name() == _HANDLER_NAME:
            return Path(handler.baseFilename)
    return None
