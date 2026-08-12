"""Standalone photo-frame server: a fullscreen slideshow for a wall-mounted device.

Run it with `python app.py`. Everything is configured through config.json, which is
created on first run — see README.md.
"""

import hashlib
import io
import json
import logging
import math
import os
import re
import random
import contextlib
import ctypes
import secrets
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from collections import OrderedDict
from logging.handlers import RotatingFileHandler
from concurrent.futures import ThreadPoolExecutor
from fnmatch import fnmatch
from pathlib import Path, PurePosixPath

from flask import Flask, abort, jsonify, render_template, request, send_file
from PIL import Image, ImageOps

# The library and everything that describes it live with the photos, not with the frame.
# This project only shows them: it reads photos.db and writes nothing to it but the
# blacklist and favourites below. Keeping one database rather than a copy here is what
# stops the two drifting apart, which they already did once.
# Overridable by environment, like every other path here, because this default is only
# right on the machine that holds the library. Deploying elsewhere means setting
# LIBRARY_TOOLS and DB_FILE to wherever metadata/ is reachable from there.
LIBRARY_TOOLS = Path(os.environ.get("LIBRARY_TOOLS") or r"D:\Fotos\zTools\metadata")
if not (LIBRARY_TOOLS / "store.py").is_file():
    raise SystemExit(
        f"store.py not found in {LIBRARY_TOOLS}. It lives in the library's metadata folder; "
        "set LIBRARY_TOOLS to point at it.")
sys.path.insert(0, str(LIBRARY_TOOLS))

import store

# One folder for the three files the browser needs. It is both the template folder and
# the static root, which keeps the boundary that matters — everything in web/ is public,
# everything outside it (config.json, this file) is not.
app = Flask(__name__, template_folder="web", static_folder="web", static_url_path="/static")
# The page, its stylesheet and its script are read from disk on every request, so editing
# them takes effect without restarting anything. The frame itself notices too — see
# /api/assets below.
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0  # revalidate, rather than serve a stale asset
app.jinja_env.auto_reload = True

CONFIG_FILE = Path(os.environ.get("CONFIG_FILE", "./config.json")).resolve()
LOG_FILE = Path(os.environ.get("LOG_FILE", "./photoframe.log")).resolve()


# How much reaches the log. The frame is stable and nothing ever read the running
# commentary — a fortnight of it was 2.5MB of routine lines and not one error — so
# the default keeps failures only, and in practice writes nothing at all. "info" brings the
# commentary back when something needs diagnosing; "off" writes no file whatsoever.
LOG_LEVELS = {"off": None, "error": logging.WARNING, "info": logging.INFO}


def start_logging() -> None:
    """Log to a file. Under pythonw.exe there is no stderr at all, so without this every
    warning and traceback the server produces goes nowhere.

    The level is read straight from the file rather than through setting(): the settings are
    parsed further down, and parsing them is itself worth being able to log.
    """
    choice = os.environ.get("LOG_LEVEL")
    if not choice:
        try:
            choice = json.loads(CONFIG_FILE.read_text(encoding="utf-8-sig")).get("logLevel")
        except (OSError, ValueError, AttributeError):
            choice = None
    level = LOG_LEVELS.get(str(choice or "error").lower(), logging.WARNING)

    for logger in (app.logger, logging.getLogger("waitress")):
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
            LOG_FILE, maxBytes=1_000_000, backupCount=3, encoding="utf-8", delay=True)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(level)


start_logging()

# Also the file written on first run, so the shape of every section is self-evident.
DEFAULTS = {
    "photoDir": r"D:\Fotos",
    "host": "0.0.0.0",
    "port": 8080,
    "frameToken": "",
    "logLevel": "error",
    "slideSeconds": 60,
    "rescanMinutes": 60,
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
    "blacklist": {
        "folders": [],
        "files": [],
    },
    "favorites": [],
    "unfavorites": [],
}

# Paths in the three lists are relative to photoDir, case-insensitive, and may use either
# slash. Globs work — "*/Screenshots", "*.png". A folder entry covers everything under it;
# so does a favorites entry that names a folder. A bare name with no slash ("Screenshots",
# "DSC01.avif") matches at any depth.
TAG_PREFIX = "tag:"
_config: dict = json.loads(json.dumps(DEFAULTS))
_match: dict[str, list[str]] = {
    "folders": [],
    "files": [],
    "favorites": [],
    "favoriteTags": [],
    "unfavorites": [],
    "unfavoriteTags": [],
}
_config_lock = threading.RLock()

# The photo database: the photo list, ratios and tags scan.py records, plus this
# frame's blacklist and favourites. Opened once the settings are known; None until
# then, and if it cannot be opened at all.
_db = None
_db_lock = threading.RLock()


GLOB_CHARS = "*?["


class Matcher:
    """Tests paths against one config list, prepared once instead of per path.

    fnmatch compiles and caches a regex per pattern, but calling it tens of thousands of
    times to check a handful of plain paths is most of the cost of building a playlist.
    Plain entries — which is nearly all of them — become set lookups and one startswith
    over a tuple.
    """

    __slots__ = ("exact", "prefixes", "names", "globs", "empty")

    def __init__(self, entries: list[str]):
        plain = [e for e in entries if not any(c in e for c in GLOB_CHARS)]
        self.exact = set(plain)
        self.prefixes = tuple(e + "/" for e in plain)  # everything under a listed folder
        # A bare name matches any segment, so "Screenshots" catches both a top-level
        # folder and Trip/Day2/Screenshots, and does so whether it is tested as a folder
        # during the walk or as part of a full photo path afterwards.
        self.names = {e for e in plain if "/" not in e}
        self.globs = [e for e in entries if any(c in e for c in GLOB_CHARS)]
        self.empty = not entries

    def __call__(self, rel_lower: str) -> bool:
        if self.empty:
            return False
        if rel_lower in self.exact:
            return True
        if self.prefixes and rel_lower.startswith(self.prefixes):
            return True
        if self.names and any(part in self.names for part in rel_lower.split("/")):
            return True
        return any(fnmatch(rel_lower, pattern) for pattern in self.globs)


_matchers: dict[str, Matcher] = {}
FAVORITE_SECTIONS = {"favorites": "favoriteTags", "unfavorites": "unfavoriteTags"}


def read_config_file() -> dict:
    """The file as it is on disk right now, merged over the defaults."""
    try:
        # utf-8-sig, not utf-8: Notepad and Windows PowerShell both write a BOM, and a
        # BOM left in place makes json.loads fail — which would drop every list here.
        raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        CONFIG_FILE.write_text(json.dumps(DEFAULTS, indent=2) + "\n", encoding="utf-8")
        app.logger.info("wrote a starting config to %s", CONFIG_FILE)
        raw = {}
    except ValueError as exc:
        # Never overwrite a file we could not parse — it is hand-written, and the typo is
        # far easier to fix than to retype the whole thing.
        app.logger.error("%s is not valid JSON (%s); using defaults", CONFIG_FILE, exc)
        raw = {}
    except OSError as exc:
        app.logger.error("could not read %s (%s); using defaults", CONFIG_FILE, exc)
        raw = {}

    merged = json.loads(json.dumps(DEFAULTS))
    merged.update(raw if isinstance(raw, dict) else {})
    blacklist = merged.get("blacklist")
    merged["blacklist"] = blacklist if isinstance(blacklist, dict) else {}
    for section in ("folders", "files"):
        merged["blacklist"].setdefault(section, [])
    merged.setdefault("favorites", [])
    merged.setdefault("unfavorites", [])
    return merged


def normalise_entry(raw: str) -> str:
    """Both slash flavours, any leading ./ and any trailing / mean the same thing here."""
    return str(raw).strip().replace("\\", "/").strip("/").removeprefix("./")


# Which rule kind in photos.db backs each of the four lists the frame matches against.
SECTION_KIND = {
    "folders": "blacklist_folder",
    "files": "blacklist_file",
    "favorites": "favorite",
    "unfavorites": "unfavorite",
}


def load_config() -> None:
    """Settings from config.json; blacklist and favourites from photos.db."""
    merged = read_config_file()
    with _config_lock:
        _config.clear()
        _config.update(merged)
    load_rules()


def load_rules() -> None:
    """Re-read the blacklist and favourites from the database.

    With no database open — released for maintenance, or it failed to open at all — the
    rules already in memory stay in force. Rebuilding them as empty would silently unhide
    every blacklisted photo, which is the one failure this must never have: a rescan
    during a release would put all 468 of them back on the wall.
    """
    if _db is None:
        app.logger.info("no database open; keeping the rules already loaded")
        return

    lists = {section: [] for section in SECTION_KIND}
    with _db_lock:
        for section, kind in SECTION_KIND.items():
            lists[section] = store.rules(_db, kind)

    with _config_lock:
        for name, entries in lists.items():
            _match[name] = [
                normalise_entry(e).lower() for e in entries if normalise_entry(e)
            ]
        # "tag:album_japon_2" favors every photo carrying that XMP keyword, which beats
        # listing forty paths. The prefix keeps it unambiguous against a folder of the
        # same name. Globs work here too: "tag:album_*".
        for section, tag_section in FAVORITE_SECTIONS.items():
            paths, tag_patterns = [], []
            for entry in _match[section]:
                if entry.startswith(TAG_PREFIX):
                    tag_patterns.append(entry[len(TAG_PREFIX) :].strip())
                else:
                    paths.append(entry)
            _match[section], _match[tag_section] = paths, tag_patterns
        for name, entries in _match.items():
            _matchers[name] = Matcher(entries)

        # Keep _config in step with the database. It is what /api/config reports and what
        # favorite_set() counts, and until now it described config.json instead — which
        # held a stale copy of the rules, and since that file was cleaned out holds none
        # at all. The frame matched correctly throughout (that runs off _matchers above);
        # it was only ever the reported numbers that were wrong.
        _config["blacklist"] = {
            "folders": list(lists["folders"]),
            "files": list(lists["files"]),
        }
        _config["favorites"] = list(lists["favorites"])
        _config["unfavorites"] = list(lists["unfavorites"])


def setting(key: str, env: str, cast=str):
    """Environment first, so a service definition can override the file per instance."""
    raw = os.environ.get(env)
    return cast(raw) if raw not in (None, "") else cast(_config.get(key, DEFAULTS[key]))


load_config()

PHOTO_DIR = Path(setting("photoDir", "PHOTO_DIR")).resolve()
TOKEN = setting("frameToken", "FRAME_TOKEN")
HOST = setting("host", "HOST")
PORT = setting("port", "PORT", int)
SLIDE_SECONDS = setting("slideSeconds", "SLIDE_SECONDS", int)
RESCAN_MINUTES = setting("rescanMinutes", "RESCAN_MINUTES", int)
PROBE_WORKERS = setting("probeWorkers", "PROBE_WORKERS", int)
FAVORITE_WEIGHT = max(1, setting("favoriteWeight", "FAVORITE_WEIGHT", int))
JPEG_QUALITY = min(95, max(40, setting("jpegQuality", "JPEG_QUALITY", int)))
# libavif's avifdec, if it is installed. Its dav1d decoder is multithreaded, which Pillow's
# AVIF path is not, and on a slow CPU that is worth more than the process it costs to start.
# `avifdecShare` is the fraction of renders it handles, so the two can be compared live.
AVIFDEC = setting("avifdec", "AVIFDEC")
AVIFDEC_SHARE = min(1.0, max(0.0, setting("avifdecShare", "AVIFDEC_SHARE", float)))
# A hung decoder must not hold an encode slot for ever. Without this a single wedged
# avifdec parks one of the two slots permanently; the next requests queue on the semaphore
# until every request thread is blocked, and the frame stops serving anything at all --
# including the stylesheet. Seen in the wild: a process alive for 15 minutes having written
# zero bytes and used zero CPU.
AVIFDEC_TIMEOUT = max(5, setting("avifdecTimeout", "AVIFDEC_TIMEOUT", int))
# Each in-flight encode holds a full decoded photo, so the number of them is capped
# well below the pool of request threads.
_encode_slots = threading.Semaphore(max(1, setting("encodeThreads", "ENCODE_THREADS", int)))
CACHE_BUDGET = max(0, setting("renderCacheMB", "RENDER_CACHE_MB", int)) * 1024 * 1024
DB_FILE = Path(setting("dbFile", "DB_FILE")).resolve()
try:
    _db = store.open_db(DB_FILE)          # creates and migrates an empty one if need be
    load_rules()                          # config.json held these until the v4 migration
except Exception:
    app.logger.exception("could not open %s; blacklist and favourites are unavailable", DB_FILE)
    _db = None

# Originals are always served byte for byte, so the library is limited to the formats a
# browser renders itself. HEIC, TIFF and BMP are left out of the index entirely rather
# than transcoded — Chrome cannot display them, and nothing here re-encodes anything.
SOURCE_MIME = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".avif": "image/avif",
    ".webp": "image/webp",
    ".gif": "image/gif",
}
EXTENSIONS = set(SOURCE_MIME)

# A ceiling on what a client may ask to be rendered, so a stray query parameter cannot
# make the server allocate an enormous image. Not a setting: there is nothing to tune.
MAX_RENDER_EDGE = 4096
SKIP_DIRS = {"@eaDir", "#recycle", "__pycache__"}

# Orientation is just a coarse reading of the aspect ratio, kept for the API and for
# clients that do not send their own. Squares count as landscape.
LANDSCAPE, PORTRAIT = "landscape", "portrait"
ORIENTATIONS = (LANDSCAPE, PORTRAIT)


def orientation_from(ratio: float) -> str:
    return PORTRAIT if ratio < 1 else LANDSCAPE


# A photo close enough to square reads as neither, and crops acceptably both ways -- so it
# belongs in both passes rather than being forced into one by a rounding error.
SQUARE_BAND = 0.05


def is_square(ratio: float) -> bool:
    return abs(ratio - 1) <= SQUARE_BAND


def fits(ratio: float, want: str) -> bool:
    """Whether a photo of this shape belongs on a screen of that orientation."""
    return is_square(ratio) or orientation_from(ratio) == want


_index: dict[str, Path] = {}
_index_lock = threading.Lock()

# pid -> the photo's path relative to PHOTO_DIR, lowercased. Kept because deriving it
# with Path.relative_to costs 0.6s across a large playlist on a slow CPU.
_rel_lower: dict[str, str] = {}
# The same paths with their real capitalisation, which is what photos.db is keyed by.
_rel_true: dict[str, str] = {}
# pid -> width/height, and pid -> lowercased tags, for the photos probed so far.
_ratio: dict[str, float] = {}
_tags: dict[str, tuple[str, ...]] = {}
_ratio_lock = threading.Lock()
_probe_lock = threading.Lock()  # serialises whole probe passes, not individual photos
_probe_done = threading.Event()

# A shuffled pass is kept server-side so the client can page through it: shipping every id
# up front costs seconds on a slow CPU, and the frame only needs the first two to start.
_passes: dict[str, list[str]] = {}
_passes_lock = threading.Lock()
PASSES_KEPT = 4
PAGE_DEFAULT = 300


def matcher(section: str) -> Matcher:
    with _config_lock:
        return _matchers[section]


def snapshot(section: str) -> list[str]:
    with _config_lock:
        return list(_match[section])


def matches(rel: str, section: str) -> bool:
    return matcher(section)(rel.lower())


def blacklisted_dir(rel: str) -> bool:
    return matches(rel, "folders")


def blacklisted_file(rel: str) -> bool:
    return matches(rel, "files") or matches(rel, "folders")


def favorite_check():
    """Build a favorites test with the config and tag map snapshotted once.

    `unfavorites` wins over `favorites`, so a single photo can be taken back out of a
    sweeping rule like `tag:album_japon_2` without unpicking the rule itself.
    """
    by_path, not_by_path = matcher("favorites"), matcher("unfavorites")
    tag_patterns, excluded_tags = snapshot("favoriteTags"), snapshot("unfavoriteTags")
    with _ratio_lock:
        tags_by_pid = dict(_tags)

    def tagged(tags, patterns) -> bool:
        return any(tag == want or fnmatch(tag, want) for tag in tags for want in patterns)

    def check(rel_lower: str, pid: str) -> bool:
        tags = tags_by_pid.get(pid, ())
        if not_by_path(rel_lower) or tagged(tags, excluded_tags):
            return False
        return by_path(rel_lower) or tagged(tags, tag_patterns)

    return check


def is_favorite(rel: str, pid: str | None = None) -> bool:
    """A photo is a favorite by path, or by carrying a favorited tag."""
    return favorite_check()(rel.lower(), pid if pid is not None else photo_id_of(rel))


class DatabaseUnavailable(RuntimeError):
    """Raised instead of quietly dropping a write while the database is not open."""


def add_entry(section: str, entry: str) -> None:
    """Record a rule, ignoring duplicates."""
    if _db is None:
        raise DatabaseUnavailable
    with _db_lock:
        store.add_rule(_db, SECTION_KIND[section], entry)
        _db.commit()
    load_rules()


def remove_entry(section: str, entry: str) -> None:
    if _db is None:
        raise DatabaseUnavailable
    with _db_lock:
        store.remove_rule(_db, SECTION_KIND[section], entry)
        _db.commit()
    load_rules()


def forget_passes() -> None:
    """Throw away the shuffled passes clients are paging through.

    A pass is a snapshot of the library. Once photos leave the index, any client still
    walking an older pass would be handed ids that no longer exist — and having rendered
    them minutes ago, its own cache may still draw them. Clients recover by starting a
    fresh pass when their token is gone.
    """
    with _passes_lock:
        _passes.clear()


def drop_blacklisted() -> list[str]:
    """Remove newly blacklisted photos from the live index without re-walking the disk."""
    hidden_file, hidden_folder = matcher("files"), matcher("folders")
    with _index_lock:
        gone = [
            pid
            for pid, rel in _rel_lower.items()
            if hidden_file(rel) or hidden_folder(rel)
        ]
        for pid in gone:
            del _index[pid]
            _rel_lower.pop(pid, None)
            # Also the true-case paths, or a hidden photo goes on being offered as a
            # neighbour by /api/neighbors long after it left the library.
            _rel_true.pop(pid, None)
    with _ratio_lock:
        for pid in gone:
            _ratio.pop(pid, None)
            _tags.pop(pid, None)
    if gone:
        forget_passes()
    return gone


_XMP_SUBJECT = re.compile(rb"<dc:subject[^>]*>(.*?)</dc:subject>", re.S)
_XMP_ITEM = re.compile(rb"<rdf:li[^>]*>(.*?)</rdf:li>", re.S)


def tags_of(im: Image.Image) -> list[str]:
    """Keywords from the XMP packet — `dc:subject`, what most taggers write.

    The packet rides along with the header read, so this costs nothing extra.
    """
    packet = im.info.get("xmp")
    if not packet:
        return []
    found = _XMP_SUBJECT.search(packet)
    if not found:
        return []
    items = [item.strip() for item in _XMP_ITEM.findall(found.group(1))]
    return [
        tag
        for tag in (item.decode("utf-8", "replace").strip() for item in items)
        if tag
    ]


# How long each decoder takes, so the two can be compared after a day of real use.
_render_times: dict[str, list[float]] = {"pillow": [], "avifdec": []}
_render_lock = threading.Lock()
RENDER_SAMPLES = 500


def record_render(method: str, milliseconds: float) -> None:
    with _render_lock:
        samples = _render_times.setdefault(method, [])
        samples.append(milliseconds)
        del samples[:-RENDER_SAMPLES]  # a rolling window, not a growing list


def fit_and_encode(im: Image.Image, width: int, height: int) -> io.BytesIO:
    # The orientation lives in EXIF and is lost on re-encode, so apply it first.
    im = ImageOps.exif_transpose(im)
    fitted = ImageOps.fit(im, (width, height), method=Image.LANCZOS, centering=(0.5, 0.5))
    buffer = io.BytesIO()
    fitted.convert("RGB").save(
        buffer, "JPEG", quality=JPEG_QUALITY, optimize=True, progressive=True
    )
    buffer.seek(0)
    return buffer


def render_with_pillow(source: Path, width: int, height: int) -> io.BytesIO:
    with Image.open(source) as im:
        return fit_and_encode(im, width, height)


def render_with_avifdec(source: Path, width: int, height: int) -> io.BytesIO:
    """Decode with avifdec into a temporary JPEG, then scale that.

    The intermediate is deliberately JPEG rather than PNG: it is a tenth of the bytes to
    write and read, and Pillow's `draft` can then decode it at a reduced DCT scale, which
    costs almost nothing. It lives in the system temp directory and is deleted straight
    away — nothing is ever written next to the photos.
    """
    handle, temporary = tempfile.mkstemp(suffix=".jpg", prefix="photoframe-")
    os.close(handle)
    temporary = Path(temporary)
    try:
        # subprocess.run kills the child if the timeout expires, so the slot is released
        # either way. TimeoutExpired is an Exception, so render() falls back to Pillow.
        subprocess.run(
            [AVIFDEC, "-j", "all", "-q", "92", str(source), str(temporary)],
            check=True,
            capture_output=True,
            timeout=AVIFDEC_TIMEOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        with Image.open(temporary) as im:
            im.draft("RGB", (width, height))  # decode at a reduced scale where it can
            return fit_and_encode(im, width, height)
    finally:
        temporary.unlink(missing_ok=True)


# Rendered JPEGs, most recently used last. Memory only -- never written to disk.
_cache: "OrderedDict[tuple, bytes]" = OrderedDict()
_cache_lock = threading.Lock()
_cache_bytes = 0
_cache_hits = _cache_misses = 0


def cache_key(source: Path, width: int, height: int):
    """Includes the file's own stamp, so a photo replaced by the sync is never served stale."""
    try:
        stat = source.stat()
    except OSError:
        return None
    return (str(source), width, height, stat.st_mtime_ns, stat.st_size)


def cached_render(key) -> bytes | None:
    if key is None or not CACHE_BUDGET:
        return None
    global _cache_hits, _cache_misses
    with _cache_lock:
        data = _cache.get(key)
        if data is None:
            _cache_misses += 1
            return None
        _cache.move_to_end(key)  # freshly used, so last to be evicted
        _cache_hits += 1
        return data


def remember_render(key, data: bytes) -> None:
    """Keep the encoded JPEG in memory, dropping the least recently used to stay in budget.

    Memory only, by design: the photos themselves are never touched and nothing is written
    beside them or anywhere else on disk. Re-viewing a photo -- stepping back and forward,
    or opening the carousel over the same run of a burst -- is the case this exists for. A
    photo being seen for the first time still pays the full decode; nothing can avoid that.
    """
    if key is None or not CACHE_BUDGET or len(data) > CACHE_BUDGET:
        return
    global _cache_bytes
    with _cache_lock:
        if key in _cache:
            _cache_bytes -= len(_cache.pop(key))
        _cache[key] = data
        _cache_bytes += len(data)
        while _cache_bytes > CACHE_BUDGET and _cache:
            _cache_bytes -= len(_cache.popitem(last=False)[1])


def render(source: Path, width: int, height: int) -> io.BytesIO:
    """Scale and crop to exactly width x height, encoded as JPEG in memory."""
    use_avifdec = (
        AVIFDEC
        and source.suffix.lower() == ".avif"
        and random.random() < AVIFDEC_SHARE
    )
    started = time.perf_counter()
    try:
        if use_avifdec:
            result = render_with_avifdec(source, width, height)
        else:
            result = render_with_pillow(source, width, height)
    except Exception:
        if not use_avifdec:
            raise
        app.logger.exception("avifdec failed on %s; falling back to Pillow", source)
        result = render_with_pillow(source, width, height)
        use_avifdec = False
    record_render("avifdec" if use_avifdec else "pillow", (time.perf_counter() - started) * 1000)
    return result


def lowered(tags) -> tuple[str, ...]:
    return tuple(str(tag).strip().lower() for tag in tags if str(tag).strip())


def probe(path: Path) -> tuple[float, list[str]]:
    """Aspect ratio and tags, from the header only — the file is never decoded."""
    with Image.open(path) as im:
        width, height = im.size
        if im.getexif().get(274, 1) >= 5:  # EXIF orientation swaps width and height
            width, height = height, width
        return (width / height if height else 1.0), tags_of(im)


def index_from_db() -> int:
    """Build the photo list from photos.db: no walk, no decoding.

    scan.py already recorded every photo with its ratio and tags, so the frame has nothing
    to work out for itself. This is also what makes startup independent of how fast the
    filesystem happens to be that morning.
    """
    if _db is None:
        return 0
    with _db_lock:
        rows = _db.execute(
            "SELECT rel, ratio FROM photo WHERE rel IS NOT NULL").fetchall()
        tag_rows = _db.execute("SELECT rel, tag FROM photo_tag").fetchall()
    if not rows:
        return 0

    found: dict[str, Path] = {}
    relatives: dict[str, str] = {}
    true_paths: dict[str, str] = {}
    ratios: dict[str, float] = {}
    for row in rows:
        rel = row["rel"]
        lower = rel.lower()
        # Applied here as well, so editing the blacklist takes effect on the next restart
        # without the database being touched.
        if blacklisted_file(lower) or any(
            blacklisted_dir(part) for part in ancestors(PurePosixPath(lower))
        ):
            continue
        pid = photo_id_of(rel)
        found[pid] = PHOTO_DIR / rel
        relatives[pid] = lower
        true_paths[pid] = rel
        if isinstance(row["ratio"], (int, float)) and row["ratio"] > 0:
            ratios[pid] = float(row["ratio"])

    tags: dict[str, tuple[str, ...]] = {}
    for row in tag_rows:
        pid = photo_id_of(row["rel"])
        if pid in found and row["tag"]:
            tags[pid] = tags.get(pid, ()) + (str(row["tag"]).lower(),)

    with _index_lock:
        _index.clear()
        _index.update(found)
        _rel_lower.clear()
        _rel_lower.update(relatives)
        _rel_true.clear()
        _rel_true.update(true_paths)
    with _ratio_lock:
        _ratio.clear()
        _ratio.update(ratios)
        _tags.clear()
        _tags.update(tags)
    _probe_done.set()          # nothing left to probe: the database already knows
    forget_passes()
    app.logger.info("loaded %d photos from %s (%d with a ratio, %d tagged)",
                    len(found), DB_FILE.name, len(ratios), len(tags))
    return len(found)


def forget_missing(pid: str) -> None:
    """Drop a photo the index knows about but the disk does not.

    The failsafe for building the list from photos.db without a walk: a deleted file is
    noticed when something tries to serve it, removed from the index in memory, and the
    frame moves on to the next photo rather than showing an error. The database itself is
    left alone — scan.py owns it, and the next rescan reconciles.
    """
    with _index_lock:
        _index.pop(pid, None)
        _rel_lower.pop(pid, None)
        rel = _rel_true.pop(pid, None)
    with _ratio_lock:
        _ratio.pop(pid, None)
        _tags.pop(pid, None)
    if rel:
        app.logger.info("dropped %s: no longer on disk", rel)
    forget_passes()


_THREAD_MODE_BACKGROUND_BEGIN = 0x00010000
_THREAD_MODE_BACKGROUND_END = 0x00020000


def _set_background_mode(begin: bool) -> bool:
    """Windows background mode for the calling thread: idle CPU *and* lowest-priority I/O.

    The I/O half is the point. Walking the library opens tens of thousands of file headers,
    and at normal priority that is enough to starve every other service on the box -- new
    processes could not even start, so the thermostat and its tasks went down while the frame
    itself, already running, carried on answering. Background mode makes the walk yield to
    anything else that wants the disk: it takes longer and nothing else notices.
    """
    if not sys.platform.startswith("win"):
        return False
    try:
        kernel32 = ctypes.WinDLL("kernel32")
        # The pseudo-handle is (HANDLE)-2. Without these the default int marshalling
        # truncates it on 64-bit and the call silently does nothing.
        kernel32.GetCurrentThread.restype = ctypes.c_void_p
        kernel32.GetCurrentThread.argtypes = []
        kernel32.SetThreadPriority.restype = ctypes.c_int
        kernel32.SetThreadPriority.argtypes = [ctypes.c_void_p, ctypes.c_int]
        mode = _THREAD_MODE_BACKGROUND_BEGIN if begin else _THREAD_MODE_BACKGROUND_END
        return bool(kernel32.SetThreadPriority(kernel32.GetCurrentThread(), mode))
    except Exception:
        return False


@contextlib.contextmanager
def background_io():
    """Run a block of library I/O without letting it monopolise the disk."""
    started = _set_background_mode(True)
    try:
        yield
    finally:
        if started:
            _set_background_mode(False)


def _worker_background():
    _set_background_mode(True)  # per-thread, so each pool worker has to ask for itself


def probe_all() -> None:
    """Read the orientation of every indexed photo out of its header.

    Only reached when photos.db gave nothing. Normally scan.py has already recorded every
    ratio and index_from_db() sets them all without opening a single file — this reads every
    headers off the disk, which takes over a minute. Nothing is cached: the database is the
    cache, and a second copy of the same facts is what this replaced.

    Runs in a background thread, so the frame starts showing photos immediately and the
    filtered playlist simply grows as this progresses.
    """
    with _probe_lock, background_io():
        _probe_done.clear()
        with _index_lock:
            items = list(_index.items())

        with _ratio_lock:
            _ratio.clear()
            _tags.clear()

        def work(item: tuple[str, Path]):
            pid, path = item
            try:
                ratio, tags = probe(path)
                return pid, round(ratio, 4), lowered(tags)
            except Exception:
                app.logger.warning("could not read the header of %s", path)
                return None

        app.logger.info("probing %d photos", len(items))
        done = 0
        with ThreadPoolExecutor(PROBE_WORKERS, initializer=_worker_background) as pool:
            for result in pool.map(work, items):
                if result is None:
                    continue
                pid, ratio, tags = result
                with _ratio_lock:
                    _ratio[pid] = ratio
                    if tags:
                        _tags[pid] = tags
                done += 1
                if done % 2000 == 0:
                    app.logger.info("probed %d/%d", done, len(items))

        _probe_done.set()
        with _ratio_lock:
            counts = {
                o: sum(1 for r in _ratio.values() if orientation_from(r) == o)
                for o in ORIENTATIONS
            }
        app.logger.info("aspect index ready: %s", counts)


def probe_in_background() -> None:
    threading.Thread(target=probe_all, daemon=True).start()


def photo_id_of(rel: str) -> str:
    return hashlib.sha1(rel.encode("utf-8")).hexdigest()[:16]


def photo_id(path: Path) -> str:
    """Stable id derived from the path, so ids survive a rescan and leak no filesystem layout."""
    return photo_id_of(path.relative_to(PHOTO_DIR).as_posix())


def ancestors(rel: PurePosixPath) -> list[str]:
    """Every folder between PHOTO_DIR and the photo, shallowest first: A, A/B, A/B/C."""
    return [p.as_posix() for p in reversed(rel.parents) if p.as_posix() != "."]


def scan() -> int:
    with background_io():
        return _scan()


def _scan() -> int:
    load_config()  # picks up any hand edits to the lists
    found: dict[str, Path] = {}
    relatives: dict[str, str] = {}
    true_paths: dict[str, str] = {}
    for root, dirs, files in os.walk(PHOTO_DIR):
        rel_root = Path(root).relative_to(PHOTO_DIR).as_posix()
        prefix = "" if rel_root == "." else rel_root + "/"
        # Pruning here rather than filtering afterwards: a blacklisted folder is never
        # descended into at all.
        dirs[:] = [
            d
            for d in dirs
            if not d.startswith(".")
            and d not in SKIP_DIRS
            and not blacklisted_dir(prefix + d)
        ]
        for name in files:
            if Path(name).suffix.lower() in EXTENSIONS and not blacklisted_file(
                prefix + name
            ):
                path = Path(root, name)
                pid = photo_id(path)
                found[pid] = path
                relatives[pid] = (prefix + name).lower()
                true_paths[pid] = prefix + name
    with _index_lock:
        _index.clear()
        _index.update(found)
        _rel_lower.clear()
        _rel_lower.update(relatives)
        _rel_true.clear()
        _rel_true.update(true_paths)
    forget_passes()  # the library just changed under any pass in flight
    app.logger.info("indexed %d photos under %s", len(found), PHOTO_DIR)
    return len(found)


def rescan_loop() -> None:
    while True:
        time.sleep(RESCAN_MINUTES * 60)
        if _db is None:
            app.logger.info("skipping the rescan: the database is released")
            continue
        try:
            scan()
            probe_all()
        except Exception:
            app.logger.exception("rescan failed")


@app.before_request
def require_token():
    if not TOKEN:
        return None
    supplied = request.args.get("k") or request.cookies.get("frame_token") or ""
    if secrets.compare_digest(supplied, TOKEN):
        return None
    abort(403)


@app.after_request
def persist_token(response):
    if TOKEN and request.args.get("k"):
        response.set_cookie(
            "frame_token", TOKEN, max_age=60 * 60 * 24 * 365, samesite="Lax"
        )
    return response


WEB_DIR = Path(app.static_folder)
ASSETS = {name: WEB_DIR / f"frame.{name}" for name in ("css", "js", "html")}


def asset_versions() -> dict[str, int]:
    """Modification times, used both to bust the browser cache and to spot edits."""
    versions = {}
    for name, path in ASSETS.items():
        try:
            versions[name] = int(path.stat().st_mtime)
        except OSError:
            versions[name] = 0
    return versions


@app.get("/")
def frame():
    return render_template("frame.html", assets=asset_versions())


@app.get("/api/assets")
def assets():
    """The frame polls this and reloads itself when the page, CSS or script changes on
    disk — editing the look of a wall-mounted device should not mean walking over to it."""
    response = jsonify(**asset_versions())
    response.headers["Cache-Control"] = "no-store"
    return response


def weighted_shuffle(ids: list[str], favorites: set[str], weight: int) -> list[str]:
    """Shuffle a pass over the library in which favorites appear `weight` times each.

    Cutting the pass into `weight` segments and giving each segment one copy of every
    favorite keeps the odds right without ever putting two copies close together: a
    favorite turns up about once per segment, not twice in a row.
    """
    plain = [pid for pid in ids if pid not in favorites]
    starred = [pid for pid in ids if pid in favorites]
    if weight <= 1 or not starred:
        random.shuffle(ids)
        return ids

    random.shuffle(plain)
    segments: list[list[str]] = [[] for _ in range(weight)]
    for position, pid in enumerate(plain):
        segments[position % weight].append(pid)
    for segment in segments:
        segment.extend(starred)
        random.shuffle(segment)
    return [pid for segment in segments for pid in segment]


@app.get("/api/playlist")
def playlist():
    """A full shuffled pass over the library, so nothing repeats until everything has shown.

    `?ratio=1.78` — the client's own width/height — is read only for its orientation: a
    landscape screen gets landscape photos, a portrait one portrait, and anything close to
    square belongs to both. `?orientation=landscape|portrait` says the same thing directly.
    Neither means the whole library.

    It used to match a band around the screen's exact ratio, which sorted the library by
    the shape of the camera that took each photo — 3:2 from the camera, 16:9 from the
    phone — a distinction nobody wanted. `object-fit: cover` crops the difference.

    While the aspect index is still building the list is short and simply grows: the
    client re-requests it whenever it runs off the end.

    Favorites are not a separate mode: they simply appear `favoriteWeight` times in the
    pass, so they come round that much more often than everything else.
    """
    limit = request.args.get("limit", type=int)
    limit = PAGE_DEFAULT if limit is None else max(0, limit)

    # Paging through a pass already built: no reshuffle, no rebuild, just a slice.
    token = request.args.get("token", "")
    if token:
        with _passes_lock:
            existing = _passes.get(token)
        if existing is not None:
            offset = max(0, request.args.get("offset", type=int) or 0)
            return page_of(token, existing, offset, limit, photos=len(existing))

    want = request.args.get("orientation", "").lower()
    try:
        screen = float(request.args.get("ratio", 0))
        # "nan" and "inf" parse happily as floats, and a negative is meaningless; all of
        # them mean "no ratio given" rather than a filter that silently does nothing.
        if not math.isfinite(screen) or screen <= 0:
            screen = 0.0
    except ValueError:
        screen = 0.0

    with _index_lock:
        items = list(_index.items())
    matched_on = "none"

    if screen > 0:
        # Orientation, not a band around the screen's exact ratio. A screen is either
        # landscape or portrait, and so is a photo; matching more finely than that only
        # sorts the library by how the camera happened to be shaped -- 3:2 from the
        # camera, 16:9 from the phone -- which is not a distinction anyone asked for.
        # `cover` crops the difference either way.
        want = want if want in ORIENTATIONS else orientation_from(screen)
        with _ratio_lock:
            items = [
                (pid, p) for pid, p in items
                if pid in _ratio and fits(_ratio[pid], want)
            ]
        matched_on = "orientation"
    elif want in ORIENTATIONS:
        with _ratio_lock:
            items = [
                (pid, p)
                for pid, p in items
                if pid in _ratio and orientation_from(_ratio[pid]) == want
            ]
        matched_on = "orientation"

    # Both the ratio filter and the orientation fallback read the aspect index, which is
    # built in the background — so for the first minute after a restart every filter
    # matches nothing and the frame is told the library is empty. Showing unfiltered
    # photos until the index catches up beats showing "no photos found" over a whole library.
    if not items and not _probe_done.is_set():
        with _index_lock:
            items = list(_index.items())
        matched_on = "nothing yet (still indexing)"

    ids = [pid for pid, _ in items]
    # One snapshot of the config for the whole pass, not one per photo.
    favorite = favorite_check()
    with _index_lock:
        relatives = _rel_lower
        favorites = {pid for pid, _ in items if favorite(relatives.get(pid, ""), pid)}
    ids = weighted_shuffle(ids, favorites, FAVORITE_WEIGHT)

    token = secrets.token_urlsafe(9)
    with _passes_lock:
        _passes[token] = ids
        while len(_passes) > PASSES_KEPT:  # only the newest few passes are reachable
            _passes.pop(next(iter(_passes)))
    return page_of(
        token,
        ids,
        offset=0,
        limit=limit,
        photos=len(items),
        favorites=len(favorites),
        ratio=screen or None,
        matchedOn=matched_on,
        orientation=want if want in ORIENTATIONS else "any",
    )


def page_of(token, ids, offset, limit, **extra):
    chunk = ids[offset : offset + limit] if limit else ids[offset:]
    return jsonify(
        token=token,
        total=len(ids),
        offset=offset,
        count=len(chunk),
        ids=chunk,
        favoriteWeight=FAVORITE_WEIGHT,
        slideSeconds=SLIDE_SECONDS,
        indexing=not _probe_done.is_set(),
        **extra,
    )


@app.post("/api/rescan")
def rescan_now():
    count = scan()
    probe_in_background()
    return jsonify(count=count)


@app.get("/api/config")
def config_view():
    """The live configuration. The token is the one thing worth not handing out."""
    with _config_lock:
        shown = json.loads(json.dumps(_config))
    shown["frameToken"] = "(set)" if TOKEN else ""
    shown["file"] = str(CONFIG_FILE)
    return jsonify(shown)


# How long a release may last before the frame takes its database back. A tool that
# crashes mid-run must not leave the frame unable to record a favourite for ever.
RELEASE_TIMEOUT = 15 * 60
_released_at = None


def release_db() -> bool:
    """Close the database and let go of the file. Serving carries on regardless.

    Everything the slideshow needs is already in memory — the photo list, the ratios, the
    tags and the rules — so the frame keeps showing photos throughout. Only writes and the
    info panel need the file, and those say so rather than pretending.
    """
    global _db, _released_at
    with _db_lock:
        if _db is None:
            return False
        _db.close()          # closing the last connection checkpoints and removes -wal/-shm
        _db = None
        _released_at = time.time()
    app.logger.info("database released: %s is free", DB_FILE)
    return True


def reopen_db() -> int:
    """Take the database back and pick up whatever changed while it was gone."""
    global _db, _released_at
    with _db_lock:
        if _db is None:
            _db = store.open_db(DB_FILE)
        _released_at = None
    load_rules()
    count = index_from_db()   # new photos, renames and removals, without a restart
    app.logger.info("database reopened: %d photos", count)
    return count


def _release_watchdog() -> None:
    while True:
        time.sleep(30)
        with _db_lock:
            overdue = _released_at is not None and time.time() - _released_at > RELEASE_TIMEOUT
        if overdue:
            app.logger.warning("release ran past %ds; taking the database back", RELEASE_TIMEOUT)
            try:
                reopen_db()
            except Exception:
                app.logger.exception("could not reopen %s", DB_FILE)


def db_state() -> dict:
    with _db_lock:
        held = _db is not None
        since = _released_at
    return {
        "open": held,
        "file": str(DB_FILE),
        "releasedFor": round(time.time() - since) if since else 0,
        "timeout": RELEASE_TIMEOUT,
    }


@app.post("/api/db/release")
def db_release():
    """Hand the database file over to a tool that wants to rewrite it.

    The frame keeps serving photos. Favourites and hiding return 503 until it comes back,
    and it comes back on its own after RELEASE_TIMEOUT if nobody asks.
    """
    already = not release_db()
    app.logger.info("release requested by %s%s", request.remote_addr,
                    " (already released)" if already else "")
    return jsonify(**db_state(), alreadyReleased=already)


@app.post("/api/db/resume")
def db_resume():
    """Reopen the database and reload the index and rules from it."""
    try:
        count = reopen_db()
    except Exception as exc:
        app.logger.exception("could not reopen %s", DB_FILE)
        return jsonify(error=str(exc), **db_state()), 500
    app.logger.info("resume requested by %s", request.remote_addr)
    return jsonify(photos=count, **db_state())


@app.get("/api/db")
def db_status():
    return jsonify(**db_state())


@app.get("/api/render-stats")
def render_stats():
    """How the two decoders are actually doing, over the last few hundred renders each."""
    with _render_lock:
        samples = {name: sorted(times) for name, times in _render_times.items()}

    def summarise(times: list[float]) -> dict:
        if not times:
            return {"renders": 0}
        return {
            "renders": len(times),
            "medianMs": round(times[len(times) // 2]),
            "meanMs": round(sum(times) / len(times)),
            "p90Ms": round(times[min(len(times) - 1, int(len(times) * 0.9))]),
            "fastestMs": round(times[0]),
            "slowestMs": round(times[-1]),
        }

    report = {name: summarise(times) for name, times in samples.items()}
    both = [r for r in report.values() if r.get("renders")]
    if len(both) == 2 and all(r["renders"] >= 20 for r in report.values()):
        pillow, avifdec = report["pillow"]["medianMs"], report["avifdec"]["medianMs"]
        report["verdict"] = (
            f"avifdec is {abs(pillow - avifdec) / max(pillow, 1):.0%} "
            f"{'faster' if avifdec < pillow else 'slower'} at the median"
        )
    else:
        report["verdict"] = "not enough renders yet (20 each)"
    report["avifdec"] = report.get("avifdec", {"renders": 0})
    report["avifdecShare"] = AVIFDEC_SHARE
    report["avifdecPath"] = AVIFDEC or "(not configured)"
    report["tempDir"] = tempfile.gettempdir()
    with _cache_lock:
        looked_up = _cache_hits + _cache_misses
        report["cache"] = {
            "entries": len(_cache),
            "mb": round(_cache_bytes / 1048576, 1),
            "budgetMB": CACHE_BUDGET // 1048576,
            "hits": _cache_hits,
            "misses": _cache_misses,
            "hitRate": f"{_cache_hits / looked_up:.0%}" if looked_up else "n/a",
        }
    return jsonify(report)


@app.get("/api/photo/<pid>")
def photo_info(pid: str):
    """What the menu needs to name what it is about to hide or favorite."""
    with _index_lock:
        src = _index.get(pid)
    if src is None:
        abort(404)
    rel = PurePosixPath(src.relative_to(PHOTO_DIR).as_posix())
    parent = rel.parent.as_posix()
    return jsonify(
        file=rel.name,
        folder="" if parent == "." else parent,
        folders=ancestors(rel),
        # The path as it exists on this machine, for the frame's copy-to-clipboard: the
        # same information the relative path already carries, in a form that can be
        # pasted into a file manager.
        fullPath=str(src),
        favorite=is_favorite(rel.as_posix(), pid),
        tags=sorted(_tags.get(pid, ())),
        ratio=_ratio.get(pid),
    )


INFO_COLUMNS = (
    "taken", "tz", "make", "model", "lens", "aperture", "shutter", "iso",
    "focal_length", "focal_length_35", "compensation", "exposure_display",
    "gps_lat", "gps_lon", "altitude", "width", "height", "size", "rating",
    # Filled in by geocode.py from the `place` table, and by the Google Photos import.
    "location", "google_url",
)


@app.get("/api/info/<pid>")
def photo_details(pid: str):
    """Everything scan.py read out of the file, for the info overlay.

    Separate from /api/photo because that one runs on every slide and this is a database
    round trip nobody needs until the overlay is actually opened.
    """
    with _index_lock:
        source = _index.get(pid)
        rel = _rel_true.get(pid)
    if source is None or rel is None:
        abort(404)

    info = {
        "file": rel.rpartition("/")[2],
        "folder": rel.rpartition("/")[0],
        "fullPath": str(source),
        "tags": sorted(_tags.get(pid, ())),
    }
    info["databaseOpen"] = _db is not None
    if _db is not None:
        try:
            with _db_lock:
                row = _db.execute(
                    f"SELECT {', '.join(INFO_COLUMNS)} FROM photo WHERE rel = ?", (rel,)
                ).fetchone()
            if row is not None:
                # Nulls are dropped rather than sent: the overlay lists what is known and
                # says nothing at all about what the camera did not record.
                info.update({c: row[c] for c in INFO_COLUMNS if row[c] is not None})
                # Who is in it, if the face pass has run over this photo.
                with _db_lock:
                    people = _db.execute(
                        "SELECT DISTINCT p.name FROM face f "
                        "JOIN cluster c ON c.id = f.cluster_id "
                        "JOIN person p ON p.id = c.person_id "
                        "WHERE f.rel = ? AND p.name IS NOT NULL ORDER BY p.name",
                        (rel,),
                    ).fetchall()
                if people:
                    info["people"] = [r["name"] for r in people]
        except sqlite3.Error:
            app.logger.exception("could not read the details for %s", rel)
    return jsonify(info)


def natural_key(name: str):
    """Sort DSC_9 before DSC_10, which a plain string sort gets backwards."""
    return [int(part) if part.isdigit() else part.lower()
            for part in re.split(r"(\d+)", name)]


@app.get("/api/neighbors/<pid>")
def neighbors(pid: str):
    """The photos either side of this one *in its own folder*, in filename order.

    What the gallery grid shows. Deliberately not drawn from the playlist: that is shuffled
    and filtered by shape, and the point here is to see a burst the way the camera wrote
    it. Blacklisted photos are already absent from the index, so they never appear.
    """
    # No span means the whole folder: scrolling out to the ends of a shoot is the point,
    # and the grid only ever loads the tiles you actually scroll to. A span is still
    # accepted for a window around the photo.
    span = request.args.get("span", type=int)
    with _index_lock:
        rel = _rel_true.get(pid)
        if rel is None:
            abort(404)
        folder = rel.rpartition("/")[0]
        siblings = [
            (other_rel.rpartition("/")[2], other_pid)
            for other_pid, other_rel in _rel_true.items()
            if other_rel.rpartition("/")[0] == folder
        ]

    siblings.sort(key=lambda pair: natural_key(pair[0]))
    here = next((i for i, (_, other) in enumerate(siblings) if other == pid), None)
    if here is None:
        abort(404)
    if span and span > 0:
        lo, hi = max(0, here - span), min(len(siblings), here + span + 1)
    else:
        lo, hi = 0, len(siblings)

    # Built once for the whole folder. is_favorite() would rebuild it per photo, and it
    # snapshots the entire tag map each time -- six thousand times over on a big shoot.
    favorite = favorite_check()

    photos = []
    for name, other_pid in siblings[lo:hi]:
        entry = f"{folder}/{name}" if folder else name
        # Kept deliberately small: the largest folder here holds over six thousand photos,
        # and every field is paid for six thousand times. The blacklist entry is just
        # folder + name, so the grid rebuilds it rather than being sent it twice.
        photo = {"id": other_pid, "file": name}
        if favorite(entry.lower(), other_pid):
            photo["favorite"] = True
        if other_pid == pid:
            photo["current"] = True
        photos.append(photo)
    return jsonify(
        folder=folder, current=pid, photos=photos,
        position=here - lo, total=len(siblings),
    )


def indexed_photo(data: dict) -> Path:
    with _index_lock:
        src = _index.get(data.get("id", ""))
    if src is None:
        abort(404)
    return src


@app.errorhandler(DatabaseUnavailable)
def database_unavailable(_):
    """Every rule write funnels through add_entry/remove_entry, so one handler covers them.

    503 rather than a silent success: the device shows the failure, and whatever you
    starred while the database was out on loan you know was not recorded.
    """
    return jsonify(error="la base de datos está en mantenimiento; inténtalo en un momento"), 503


@app.post("/api/blacklist")
def blacklist_add():
    """Add a photo or one of its parent folders to the blacklist, and drop it from the
    library right away — no rescan needed."""
    data = request.get_json(silent=True) or {}
    scope = data.get("scope", "photo")
    rel = PurePosixPath(indexed_photo(data).relative_to(PHOTO_DIR).as_posix())

    if scope == "folder":
        # Only a folder this photo actually sits in, so the endpoint can never be talked
        # into blacklisting an arbitrary path — or the whole library. The match also
        # supplies the folder's real spelling, which is what gets written to the file.
        wanted = normalise_entry(data.get("folder", "")).lower()
        entry = next((a for a in ancestors(rel) if a.lower() == wanted), None)
        if entry is None:
            return jsonify(error="that folder does not contain this photo"), 400
        section = "folders"
    elif scope == "photo":
        entry, section = rel.as_posix(), "files"
    else:
        return jsonify(error="scope must be 'photo' or 'folder'"), 400

    add_entry(section, entry)
    removed = drop_blacklisted()
    app.logger.info(
        "blacklist add %r (%s) by %s — %d photos removed",
        entry, scope, request.remote_addr, len(removed),
    )
    with _index_lock:
        remaining = len(_index)
    return jsonify(entry=entry, scope=scope, removed=removed, count=remaining)


@app.post("/api/blacklist/undo")
def blacklist_undo():
    """Take an entry back out of the blacklist and return the photo to the library.

    A swipe hides a photo with one careless gesture, and without this the only way back
    is hand-editing config.json — so the frame offers an Undo for a few seconds.
    """
    data = request.get_json(silent=True) or {}
    entry = normalise_entry(data.get("entry", ""))
    scope = data.get("scope", "photo")
    if not entry or scope not in ("photo", "folder"):
        return jsonify(error="nothing to undo"), 400

    app.logger.info("blacklist undo requested %r (%s) by %s", entry, scope, request.remote_addr)
    remove_entry("files" if scope == "photo" else "folders", entry)

    if scope == "folder":
        # A folder was pruned from the walk entirely, so the index has to be rebuilt.
        count = scan()
        probe_in_background()
        return jsonify(entry=entry, scope=scope, count=count)

    path = PHOTO_DIR / entry
    if not path.is_file() or path.suffix.lower() not in EXTENSIONS:
        return jsonify(error="that photo is no longer there"), 404
    if blacklisted_file(entry.lower()):
        return jsonify(error="another entry still hides it"), 409

    pid = photo_id_of(entry)
    with _index_lock:
        _index[pid] = path
        _rel_lower[pid] = entry.lower()
        _rel_true[pid] = entry
    forget_passes()  # so the restored photo can come round again
    try:  # one header read, rather than a whole rescan for a single photo
        ratio, tags = probe(path)
        with _ratio_lock:
            _ratio[pid] = ratio
            if tags:
                _tags[pid] = lowered(tags)
    except Exception:
        app.logger.warning("restored %s but could not read its header", path)
    with _index_lock:
        remaining = len(_index)
    app.logger.info("blacklist UNDO %r (%s) by %s", entry, scope, request.remote_addr)
    return jsonify(entry=entry, scope=scope, id=pid, count=remaining)


@app.post("/api/favorite")
def favorite_set():
    """Add or remove the current photo from the favorites.

    A photo can be a favorite because it is listed by name, or because a folder, glob or
    tag covers it. Un-favoriting therefore drops any entry naming it and, if a broader
    rule still catches it, records an exception in `unfavorites` — the alternative is a
    button that silently does nothing on a tagged photo.
    """
    data = request.get_json(silent=True) or {}
    rel = PurePosixPath(indexed_photo(data).relative_to(PHOTO_DIR).as_posix())
    entry = rel.as_posix()
    pid = photo_id_of(entry)
    wanted = bool(data.get("favorite", True))

    app.logger.info(
        "favorite %s %r by %s", "add" if wanted else "remove", entry, request.remote_addr
    )
    if wanted:
        remove_entry("unfavorites", entry)  # an exception no longer applies
        if not favorite_check()(entry.lower(), pid):
            add_entry("favorites", entry)
        covered_by = "rule" if not matcher("favorites")(entry.lower()) else "name"
    else:
        remove_entry("favorites", entry)
        covered_by = "name"
        if favorite_check()(entry.lower(), pid):  # a tag or folder still catches it
            add_entry("unfavorites", entry)
            covered_by = "rule"

    with _config_lock:
        total = len(_config["favorites"])
    return jsonify(
        entry=entry, favorite=wanted, coveredBy=covered_by, count=total
    )


@app.get("/img/<pid>")
def img(pid: str):
    """The photo, either untouched or re-encoded to exactly the size the screen shows.

    `?w=1920&h=1080` returns a JPEG of precisely those pixels, cropped to fill them the
    way `object-fit: cover` would. Nothing is written to disk: it is decoded, scaled and
    encoded per request. A 24 MP original costs a device ~96 MB of bitmap to decode; the
    same photo at screen size costs about 8 MB, which is the difference between a frame
    that runs for weeks and one the browser kills.

    Without w and h the original file is sent byte for byte, as before.
    """
    with _index_lock:
        source = _index.get(pid)
    if source is None:
        abort(404)
    if not source.exists():
        # Starting from photos.db without a walk means a file can be gone while the list
        # still names it.
        forget_missing(pid)
        abort(404)

    width, height = request.args.get("w", type=int), request.args.get("h", type=int)
    if not width or not height:
        # Explicit mimetype: the Windows mime registry has no .webp/.avif entry and would
        # otherwise fall back to application/octet-stream.
        return send_file(
            source,
            mimetype=SOURCE_MIME[source.suffix.lower()],
            conditional=True,
            max_age=86400,
        )

    width = max(64, min(width, MAX_RENDER_EDGE))
    height = max(64, min(height, MAX_RENDER_EDGE))

    # Looked up before the semaphore: a hit costs nothing, and queueing it behind four
    # real renders would throw away the whole point of having it.
    key = cache_key(source, width, height)
    data = cached_render(key)
    if data is None:
        try:
            # Decoding a 24 MP photo needs a few hundred MB for a moment. Letting eight
            # request threads do that at once is how the server itself falls over.
            with _encode_slots:
                # Another thread may have rendered exactly this while we queued.
                data = cached_render(key)
                if data is None:
                    data = render(source, width, height).getvalue()
                    remember_render(key, data)
        except Exception:
            app.logger.exception("could not render %s", source)
            abort(415)

    response = send_file(io.BytesIO(data), mimetype="image/jpeg")
    # Worth caching in the browser — stepping back through the history reuses it — but
    # it is never written to disk here.
    response.headers["Cache-Control"] = "private, max-age=3600"
    return response


threading.Thread(target=_release_watchdog, daemon=True).start()


def startup() -> None:
    """Get the photo list, then keep it current.

    photos.db already lists every photo with its ratio and tags, so the frame needs neither
    a walk nor a decode to start: the whole library is ready in a couple of seconds. Files deleted
    since the last scan are handled by forget_missing() as they are hit, and a walk still
    happens on the periodic rescan, which is how new photos arrive.
    """
    if index_from_db():
        threading.Thread(target=rescan_loop, daemon=True).start()
        return

    # Getting here means the database is missing, empty, or has no rel column filled in.
    # Say so loudly: walking the library is far more expensive — on a slow morning it cost
    # 25 minutes serving nothing, and once took the whole box down with it.
    app.logger.error("%s gave no photos — falling back to a full walk of the library",
                     DB_FILE.name)
    scan()
    probe_in_background()
    threading.Thread(target=rescan_loop, daemon=True).start()


if __name__ != "__main__":
    # Imported rather than run — tests and tooling expect a ready module, and want the
    # walk to have happened so a freshly built library is visible.
    startup()


if __name__ == "__main__":
    from waitress import serve

    # Bind first, index second. The walk used to run before serve(), so a filesystem
    # having a bad day meant no frame at all rather than a frame with nothing in it yet:
    # one morning it took over 25 minutes, during which the device could not even fetch
    # the stylesheet. /api/playlist already reports `indexing` while the index is empty,
    # and the frame says "preparing the library..." and retries, which is the right
    # failure: visibly not ready, rather than dead.
    threading.Thread(target=startup, daemon=True).start()

    # Started with pythonw.exe there is no console at all and sys.stdout is None, which
    # turns a plain print() into an unhandled error before the server ever starts.
    if sys.stdout is not None:
        print(f"photo frame on http://{HOST}:{PORT}")
    serve(app, host=HOST, port=PORT, threads=8)
