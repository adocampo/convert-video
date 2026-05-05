from __future__ import annotations

import glob
import logging
import os
import sys
import time as _time
from logging.handlers import TimedRotatingFileHandler

# ANSI color codes
GREEN_COLOR = '\033[0;32m'
YELLOW_COLOR = '\033[1;33m'
RED_COLOR = '\033[0;31m'
RESET_COLOR = '\033[0m'
CYAN_COLOR = '\033[0;36m'
BLUE_COLOR = '\033[0;34m'
MAGENTA_COLOR = '\033[0;35m'

# Central logger for the application
logger = logging.getLogger("clutch")
logger.propagate = False
# Prevent Python's lastResort handler from printing bare WARNING+ messages to
# stderr when no file handler has been configured yet (e.g. plain CLI use).
logger.addHandler(logging.NullHandler())

# Reference to the file handler so we can reconfigure it at runtime
_file_handler: TimedRotatingFileHandler | None = None
_log_dir: str | None = None
_retention_days: int = 30
_console_level: int = logging.INFO


def _resolve_level(level: str) -> int:
    return getattr(logging, str(level).upper(), logging.INFO)


def set_console_log_level(level: str) -> None:
    """Set the minimum level for console output helpers."""
    global _console_level
    _console_level = _resolve_level(level)


def setup_file_logging(log_dir: str, level: str = "INFO", retention_days: int = 30):
    """Configure daily-rotating file logging under *log_dir*.

    Safe to call more than once — subsequent calls reconfigure the handler.
    """
    global _file_handler, _log_dir, _retention_days

    # Ensure the process honours the TZ environment variable (important in Docker)
    if hasattr(_time, "tzset"):
        _time.tzset()

    os.makedirs(log_dir, exist_ok=True)
    _log_dir = log_dir
    _retention_days = max(1, min(365, retention_days))

    log_path = os.path.join(log_dir, "clutch.log")

    if _file_handler is not None:
        logger.removeHandler(_file_handler)
        _file_handler.close()

    handler = TimedRotatingFileHandler(
        log_path, when="midnight", backupCount=_retention_days, utc=False, encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)-5s] %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    ))
    numeric_level = _resolve_level(level)
    handler.setLevel(numeric_level)
    logger.addHandler(handler)
    logger.setLevel(min(logger.level or numeric_level, numeric_level))
    _file_handler = handler

    # Clean up old rotated files beyond _retention_days
    cleanup_old_logs()


def set_log_level(level: str):
    """Change the file handler level at runtime."""
    if _file_handler is None:
        return
    numeric = _resolve_level(level)
    _file_handler.setLevel(numeric)
    logger.setLevel(min(logger.level or numeric, numeric))


def cleanup_old_logs():
    """Remove rotated log files older than the configured retention."""
    if not _log_dir:
        return
    pattern = os.path.join(_log_dir, "clutch.log.*")
    files = sorted(glob.glob(pattern))
    # TimedRotatingFileHandler names files as clutch.log.YYYY-MM-DD
    # Keep only the newest _retention_days files
    for old_file in files[:-_retention_days] if len(files) > _retention_days else []:
        try:
            os.remove(old_file)
        except OSError:
            pass


def get_log_dir() -> str | None:
    """Return the active log directory, or None if file logging is not set up."""
    return _log_dir


# -- Console output helpers (keep coloured terminal output + route to logger) --

def _status(label: str, color: str, msg: str, *, stream=sys.stdout):
    print(f"[{color}{label}{RESET_COLOR}] {msg}", file=stream)


def _emit_console(level: int) -> bool:
    return level >= _console_level


def info(msg: str):
    if _emit_console(logging.INFO):
        print(f"{CYAN_COLOR}{msg}{RESET_COLOR}")
    logger.info(msg)


def warning(msg: str):
    if _emit_console(logging.WARNING):
        _status("WARN", YELLOW_COLOR, msg)
    logger.warning(msg)


def debug(msg: str):
    if _emit_console(logging.DEBUG):
        _status("DBG ", MAGENTA_COLOR, msg)
    logger.debug(msg)


def error(msg: str):
    if _emit_console(logging.ERROR):
        _status("FAIL", RED_COLOR, msg, stream=sys.stderr)
    logger.error(msg)


def success(msg: str):
    if _emit_console(logging.INFO):
        _status(" OK ", GREEN_COLOR, msg)
    logger.info(msg)


def skip(msg: str):
    if _emit_console(logging.INFO):
        _status("SKIP", BLUE_COLOR, msg)
    logger.info(msg)


def deleted(msg: str):
    if _emit_console(logging.INFO):
        _status("DEL ", MAGENTA_COLOR, msg)
    logger.info(msg)
