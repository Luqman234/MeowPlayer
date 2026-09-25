import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path


LOGGER_NAME = "meowplayer"
DEFAULT_MAX_BYTES = 2 * 1024 * 1024
DEFAULT_BACKUP_COUNT = 3


def _xdg_state_home():
    value = os.environ.get("XDG_STATE_HOME")
    if value:
        path = Path(value).expanduser()
        if path.is_absolute():
            return path
    return Path.home() / ".local" / "state"


def default_debug_log_path():
    return _xdg_state_home() / "meowplayer" / "debug.log"


def mpv_debug_log_path(debug_log):
    path = Path(debug_log).expanduser()
    suffix = path.suffix or ".log"
    stem = (
        path.name[:-len(suffix)]
        if path.name.endswith(suffix)
        else path.name
    )
    return path.with_name(f"{stem}.mpv{suffix}")


def configure_debug_logging(
    enabled=False,
    log_file=None,
    *,
    max_bytes=DEFAULT_MAX_BYTES,
    backup_count=DEFAULT_BACKUP_COUNT,
):
    """Configure file-only debug logging that is safe around curses."""

    logger = logging.getLogger(LOGGER_NAME)
    logger.propagate = False

    for handler in list(logger.handlers):
        try:
            handler.close()
        finally:
            logger.removeHandler(handler)

    active = bool(enabled or log_file)
    if not active:
        logger.setLevel(logging.CRITICAL + 1)
        logger.addHandler(logging.NullHandler())
        return None

    path = (
        Path(log_file).expanduser()
        if log_file
        else default_debug_log_path()
    ).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)

    handler = RotatingFileHandler(
        path,
        maxBytes=max(1, int(max_bytes)),
        backupCount=max(0, int(backup_count)),
        encoding="utf-8",
    )
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s.%(msecs)03d "
            "[%(process)d:%(threadName)s] "
            "%(levelname)s %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )

    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    logger.debug("Debug logging initialized: %s", path)
    return path


def shutdown_debug_logging():
    logger = logging.getLogger(LOGGER_NAME)
    for handler in list(logger.handlers):
        try:
            handler.flush()
            handler.close()
        finally:
            logger.removeHandler(handler)
    logger.addHandler(logging.NullHandler())
