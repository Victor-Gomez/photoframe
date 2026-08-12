"""Standalone photo-frame server: a fullscreen slideshow for a wall-mounted device.

Run it with `python app.py`. Everything is configured through config.json, which is
created on first run — see README.md.

This file only wires things up. What each piece does lives in photoframe/.
"""

import os
import sys
from pathlib import Path

# The library and everything that describes it live with the photos, not with the frame.
# This project only shows them: it reads photos.db and writes nothing to it but the
# blacklist and favourites. Keeping one database rather than a copy here is what stops the
# two drifting apart, which they already did once.
# Overridable by environment, like every other path here, because this default is only
# right on the machine that holds the library.
LIBRARY_TOOLS = Path(os.environ.get("LIBRARY_TOOLS") or r"D:\Fotos\zTools\metadata")
if not (LIBRARY_TOOLS / "store.py").is_file():
    raise SystemExit(
        f"store.py not found in {LIBRARY_TOOLS}. It lives in the library's metadata folder; "
        "set LIBRARY_TOOLS to point at it.")
sys.path.insert(0, str(LIBRARY_TOOLS))

import logging  # noqa: E402  -- after the path is set, like everything below it

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

# Handy names for the tests and for anything poking at a running instance.
library = frame.library
rules = frame.rules
db = frame.db
renderer = frame.renderer
cache = frame.cache


if __name__ != "__main__":
    # Imported rather than run — tests and tooling expect a ready module, with the photo
    # list already built so a freshly created library is visible.
    frame.start()


if __name__ == "__main__":
    import threading

    from waitress import serve

    # Bind first, index second. The indexing used to run before serve(), so a filesystem
    # having a bad day meant no frame at all rather than a frame with nothing in it yet:
    # one morning it took over 25 minutes, during which the device could not even fetch
    # the stylesheet. /api/playlist already reports `indexing` while the index is empty,
    # and the frame says "preparing the library..." and retries, which is the right
    # failure: visibly not ready, rather than dead.
    threading.Thread(target=frame.start, daemon=True).start()

    # Started with pythonw.exe there is no console at all and sys.stdout is None, which
    # turns a plain print() into an unhandled error before the server ever starts.
    if sys.stdout is not None:
        print(f"photo frame on http://{settings.host}:{settings.port}")
    serve(app, host=settings.host, port=settings.port, threads=8)
