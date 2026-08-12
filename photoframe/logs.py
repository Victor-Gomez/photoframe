"""Where the server's output goes.

Configured before anything else, because parsing the settings is itself worth being able
to log.
"""

import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

# How much reaches the log. The frame is stable and nothing ever read the running
# commentary — a fortnight of it was 2.5MB of routine lines and not one error — so the
# default keeps failures only, and in practice writes nothing at all. "info" brings the
# commentary back when something needs diagnosing; "off" writes no file whatsoever.
LEVELS = {"off": None, "error": logging.WARNING, "info": logging.INFO}

# Every module logs through a child of this one, so a single handler covers them all.
ROOT = "photoframe"


def level_from(config_file: Path, env_value: str | None) -> int | None:
    """Read straight from the file rather than through Settings, which is not built yet."""
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
        if level is None:
            # A NullHandler and no propagation, rather than simply no handler: otherwise
            # logging falls back to stderr, which under pythonw.exe does not exist.
            logger.addHandler(logging.NullHandler())
            logger.propagate = False
            logger.setLevel(logging.CRITICAL + 1)
            continue
        # delay=True: no file until there is something to put in it, so on a healthy frame
        # the log does not exist at all and its mere presence means something went wrong.
        handler = RotatingFileHandler(
            log_file, maxBytes=1_000_000, backupCount=3, encoding="utf-8", delay=True)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(level)
