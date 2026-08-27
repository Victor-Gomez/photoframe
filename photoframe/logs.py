"""Where the server's output goes.

Configured before anything else, because parsing the settings is itself worth being able
to log.
"""

import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

# "error" writes failures only, which on a healthy frame means no file at all. "info"
# brings back the running commentary; "off" writes nothing, tracebacks included.
LEVELS = {"off": None, "error": logging.WARNING, "info": logging.INFO}

ROOT = "photoframe"   # every module logs through a child of this, so one handler covers all

# Where start() was pointed. Module-level because logging itself is: with the level at
# "off" there are no handlers left to ask where the file was.
_started: tuple = ()


def level_from(config_file: Path, env_value: str | None) -> int | None:
    """Straight from the file: Settings is not built yet, and parsing it is worth logging."""
    choice = env_value
    if not choice:
        try:
            choice = json.loads(config_file.read_text(encoding="utf-8-sig")).get("logLevel")
        except (OSError, ValueError, AttributeError):
            choice = None
    return LEVELS.get(str(choice or "error").lower(), logging.WARNING)


def tail(lines: int = 200) -> list[str]:
    """The end of the log, for the status page. The file is capped at 1 MB by rotation,
    so it is read whole rather than seeked."""
    for handler in logging.getLogger(ROOT).handlers:
        path = getattr(handler, "baseFilename", None)
        if not path:
            continue        # NullHandler: logging is off, and there is no file to read
        try:
            text = Path(path).read_text(encoding="utf-8", errors="replace")
        except FileNotFoundError:
            return []       # delay=True, so no file at all means nothing has failed yet
        except OSError as exc:
            return [f"no se pudo leer {path}: {exc}"]
        return text.splitlines()[-lines:]
    return []


def set_level(name: str) -> None:
    """Change the level of a running frame, from the settings page.

    Rebuilt rather than adjusted: "off" leaves no file handler to raise the level of.
    """
    if not _started:
        return
    log_file, extra = _started
    start(log_file, LEVELS.get(str(name).lower(), logging.WARNING), extra)


def start(log_file: Path, level: int | None, extra_loggers=()) -> None:
    """Log to a file. Under pythonw.exe there is no stderr at all, so without this every
    warning and traceback the server produces goes nowhere."""
    global _started
    _started = (log_file, tuple(extra_loggers))
    for logger in (logging.getLogger(ROOT), *extra_loggers):
        # Loggers are global and outlive a re-import, so without this a second import
        # stacks a second handler and every line is written twice, then three times.
        for existing in list(logger.handlers):
            logger.removeHandler(existing)
            existing.close()
        if level is None:
            # NullHandler and no propagation: bare loggers fall back to stderr, which
            # under pythonw.exe does not exist.
            logger.addHandler(logging.NullHandler())
            logger.propagate = False
            logger.setLevel(logging.CRITICAL + 1)
            continue
        # delay=True: no file until there is something to put in it, so its presence
        # alone means something went wrong.
        handler = RotatingFileHandler(
            log_file, maxBytes=1_000_000, backupCount=3, encoding="utf-8", delay=True)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(level)
