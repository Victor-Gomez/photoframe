"""Standalone photo-frame server: a fullscreen slideshow for a wall-mounted device.

Run it with `python app.py`. Everything is configured through config.json, which is
created on first run — see README.md.

This file only wires things up. What each piece does lives in photoframe/.
"""

import os
import sys
from pathlib import Path

# The library and everything describing it live with the photos, not with the frame. One
# database rather than a copy here: the two drifted apart for a week once.
LIBRARY_TOOLS = Path(os.environ.get("LIBRARY_TOOLS") or r"D:\Fotos\zTools\metadata")
if not (LIBRARY_TOOLS / "store.py").is_file():
    raise SystemExit(
        f"store.py not found in {LIBRARY_TOOLS}. It lives in the library's metadata folder; "
        "set LIBRARY_TOOLS to point at it.")
sys.path.insert(0, str(LIBRARY_TOOLS))

import logging  # noqa: E402  -- everything below needs the path set first

from photoframe import logs  # noqa: E402
from photoframe.frame import Frame  # noqa: E402
from photoframe.settings import Settings  # noqa: E402
from photoframe.web import create_app  # noqa: E402

CONFIG_FILE = Path(os.environ.get("CONFIG_FILE", "./config.json")).resolve()
LOG_FILE = Path(os.environ.get("LOG_FILE", "./photoframe.log")).resolve()

logs.start(
    LOG_FILE,
    logs.level_from(CONFIG_FILE, os.environ.get("LOG_LEVEL")),
    extra_loggers=[logging.getLogger("waitress")],
)

settings = Settings(CONFIG_FILE)
frame = Frame(settings)
app = create_app(frame)

# For the tests, and for poking at a running instance.
library = frame.library
rules = frame.rules
db = frame.db
renderer = frame.renderer
cache = frame.cache


if __name__ != "__main__":
    frame.start()   # imported: tests and tooling expect a ready module


if __name__ == "__main__":
    import threading

    from waitress import serve

    # Bind first, index second. Indexing used to run before serve(), so a slow filesystem
    # meant no frame at all rather than one with nothing in it yet — one morning that was
    # 25 minutes during which the device could not even fetch the stylesheet.
    threading.Thread(target=frame.start, daemon=True).start()

    # Under pythonw.exe sys.stdout is None, and print() would raise before serve() runs.
    if sys.stdout is not None:
        print(f"photo frame on http://{settings.host}:{settings.port}")
    serve(app, host=settings.host, port=settings.port, threads=8)
