"""config.json: the settings, and only the settings.

The blacklist and favourites used to live here too. They belong to the library rather
than to this program and now live in photos.db — see rules.py.
"""

import json
import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)

# Also the file written on first run, so the shape of every section is self-evident.
DEFAULTS = {
    "photoDir": r"D:\Fotos",
    "host": "0.0.0.0",
    "port": 8080,
    "frameToken": "",
    "logLevel": "error",
    "language": "es",
    "slideSeconds": 60,
    "probeWorkers": 4,
    "favoriteWeight": 10,
    "jpegQuality": 85,
    "encodeThreads": 2,
    # Megabytes of rendered JPEGs held in memory. 0 turns the cache off entirely.
    "renderCacheMB": 96,
    "avifdec": "",
    "avifdecShare": 0.5,
    "avifdecTimeout": 30,
    # photos.db: the photo list, ratios, tags and capture dates that scan.py records, plus
    # this frame's own blacklist and favourites. config.json keeps only the settings.
    # It lives with the library; there is deliberately no copy in this folder.
    "dbFile": r"D:\Fotos\zTools\metadata\photos.db",
}


class Settings:
    """The merged configuration, with every scalar overridable by environment variable.

    The environment wins so a service definition can run a second instance off one file.
    """

    def __init__(self, config_file: Path):
        self.file = config_file
        self.values: dict = {}
        self.reload()

        self.photo_dir = Path(self("photoDir", "PHOTO_DIR")).resolve()
        self.db_file = Path(self("dbFile", "DB_FILE")).resolve()
        self.token = self("frameToken", "FRAME_TOKEN")
        self.host = self("host", "HOST")
        self.port = self("port", "PORT", int)
        self.slide_seconds = self("slideSeconds", "SLIDE_SECONDS", int)
        # Only the starting points: /settings overrides both in photos.db.
        self.language = self("language", "LANGUAGE")
        self.log_level = self("logLevel", "LOG_LEVEL")
        self.probe_workers = self("probeWorkers", "PROBE_WORKERS", int)
        self.favorite_weight = max(1, self("favoriteWeight", "FAVORITE_WEIGHT", int))
        self.jpeg_quality = min(95, max(40, self("jpegQuality", "JPEG_QUALITY", int)))
        self.encode_threads = max(1, self("encodeThreads", "ENCODE_THREADS", int))
        self.cache_budget = max(0, self("renderCacheMB", "RENDER_CACHE_MB", int)) * 1024 * 1024
        # libavif's avifdec, if installed: its dav1d decoder is multithreaded, Pillow's
        # is not. `avifdecShare` is the fraction of renders it takes, so both get measured.
        self.avifdec = self("avifdec", "AVIFDEC")
        self.avifdec_share = min(1.0, max(0.0, self("avifdecShare", "AVIFDEC_SHARE", float)))
        # A hung decoder must not hold an encode slot for ever: one wedged avifdec parks
        # a slot, the rest queue behind it, and the frame stops serving anything at all.
        self.avifdec_timeout = max(5, self("avifdecTimeout", "AVIFDEC_TIMEOUT", int))

    def __call__(self, key: str, env: str, cast=str):
        raw = os.environ.get(env)
        return cast(raw) if raw not in (None, "") else cast(self.values.get(key, DEFAULTS[key]))

    def reload(self) -> None:
        """Re-read the file, so a hand edit is picked up without a restart."""
        self.values = read_config_file(self.file)


def read_config_file(config_file: Path) -> dict:
    """The file as it is on disk right now, merged over the defaults."""
    try:
        # utf-8-sig, not utf-8: Notepad and Windows PowerShell both write a BOM, and a
        # BOM left in place makes json.loads fail.
        raw = json.loads(config_file.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        config_file.write_text(json.dumps(DEFAULTS, indent=2) + "\n", encoding="utf-8")
        log.info("wrote a starting config to %s", config_file)
        raw = {}
    except ValueError as exc:
        # Never overwrite a file we could not parse — it is hand-written, and the typo is
        # far easier to fix than to retype the whole thing.
        log.error("%s is not valid JSON (%s); using defaults", config_file, exc)
        raw = {}
    except OSError as exc:
        log.error("could not read %s (%s); using defaults", config_file, exc)
        raw = {}

    merged = dict(DEFAULTS)
    merged.update(raw if isinstance(raw, dict) else {})
    return merged
