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


def level_from(config_file: Path, env_value: str | None) -> int | None:
    """Straight from the file: Settings is not built yet, and parsing it is worth logging."""
    choice = env_value
    if not choice:
        try:
            choice = json.loads(config_file.read_text(encoding="utf-8-sig")).get("logLevel")
        except (OSError, ValueError, AttributeError):
            choice = None
    return LEVELS.get(str(choice or "error").lower(), logging.WARNING)


def start(log_file: Path, level: int | None, extra_loggers=()) -> None:
    """Log to a file. Under pythonw.exe there is no stderr at all, so without this every
    warning and traceback the server produces goes nowhere."""
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
