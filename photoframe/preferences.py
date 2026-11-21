"""What a person chose, kept in photos.db beside the rules.

config.json describes the machine — ports, paths, threads — and is never written from a
screen, so a hand edit cannot be lost to a tap. This is the other
half: the few settings someone sets from a page. They belong to the library rather than to
the box serving it, so they live in the database and follow it between machines.
"""

import logging
import re
import threading
import uuid

import store

from .database import Database
from .i18n import LANGUAGES, Invalid

log = logging.getLogger(__name__)

# The meta table is shared with the library tools, so the frame's keys say whose they are.
PREFIX = "frame."
DEVICE_PREFIX = PREFIX + "device."
DEVICE_COOKIE = "frame_device"
DEVICE_ID_RE = re.compile(r"^[a-f0-9]{16,64}$")
HHMM = re.compile(r"([01]\d|2[0-3]):[0-5]\d")

DEVICE_KEYS = frozenset({
    "weightByRating",
    "showRating",
    "ratingFilter",
    "ratingThresholdEnabled",
    "ratingThreshold",
    "folderFilter",
    "imageFit",
})


def device_id_from(request) -> str | None:
    """Return the validated device ID from the request cookie, or None."""
    raw = request.cookies.get(DEVICE_COOKIE, "")
    return raw if DEVICE_ID_RE.fullmatch(raw) else None


def resolve_device(request) -> tuple[str, bool]:
    """Return (device_id, is_new), minting a fresh hex UUID when absent or invalid."""
    existing = device_id_from(request)
    if existing:
        return existing, False
    return uuid.uuid4().hex, True


def set_device_cookie(response, device_id: str) -> None:
    response.set_cookie(
        DEVICE_COOKIE,
        device_id,
        max_age=10 * 365 * 86400,
        samesite="Lax",
        path="/",
    )

QUIET = ("quietFrom", "quietTo")
BOOLEANS = ("weightByRating", "showRating", "ratingThresholdEnabled")
LOG_LEVELS = ("off", "error", "info")
RATING_FILTERS = ("all", "above", "unscored")
IMAGE_FITS = ("cover", "fit")
CHOICES = {
    "language": LANGUAGES,
    "logLevel": LOG_LEVELS,
    "ratingFilter": RATING_FILTERS,
    "imageFit": IMAGE_FITS,
}


def clean(name: str, raw, default):
    """One value as it will be stored, or Invalid naming what is wrong with it."""
    if name in CHOICES:
        value = str(raw or "").strip().lower()
        if value not in CHOICES[name]:
            raise Invalid("error.choice", name=name, value=value or "''")
        return value
    if name in QUIET:
        text = str(raw or "").strip()
        if text and not HHMM.fullmatch(text):
            raise Invalid("error.time", name=name)
        return text
    if name in BOOLEANS:
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, (int, float)):
            return bool(raw)
        text = str(raw).strip().lower()
        if text in ("1", "true", "yes", "on"):
            return True
        if text in ("0", "false", "no", "off", ""):
            return False
        raise Invalid("error.choice", name=name, value=str(raw))
    if name == "folderFilter":
        return str(raw or "").strip().replace("\\", "/").strip("/").removeprefix("./")
    try:
        number = int(raw)
    except (TypeError, ValueError):
        raise Invalid("error.number", name=name) from None
    if name == "slideSeconds":
        return max(3, min(3600, number))
    if name == "ratingThreshold":
        return max(0, min(10, number))
    return default


def minutes(hhmm: str) -> int:
    hours, _, mins = hhmm.partition(":")
    return int(hours) * 60 + int(mins)


def is_quiet(start: str, end: str, now) -> bool:
    """Whether a clock time falls in the window, which usually wraps past midnight."""
    if not start or not end:
        return False
    here, opens, closes = now.hour * 60 + now.minute, minutes(start), minutes(end)
    if opens <= closes:
        return opens <= here < closes
    return here >= opens or here < closes


class Preferences:
    """The settings the frame writes, cached in memory so a released database still serves.

    Whatever is not set falls back to config.json, which is how a deployment keeps its own
    starting point without anything having to be written first.
    """

    def __init__(self, db: Database, settings):
        self.db = db
        self.settings = settings
        self._lock = threading.RLock()
        self._values: dict = self.defaults()
        self._devices: dict[str, dict] = {}
        self.reload()

    def defaults(self) -> dict:
        return {
            "slideSeconds": self.settings.slide_seconds,
            "weightByRating": self.settings.weight_by_rating,
            "showRating": self.settings.show_rating,
            "ratingFilter": self.settings.rating_filter,
            "ratingThresholdEnabled": self.settings.rating_threshold_enabled,
            "ratingThreshold": self.settings.rating_threshold,
            "folderFilter": self.settings.folder_filter,
            "imageFit": self.settings.image_fit,
            "quietFrom": "",
            "quietTo": "",
            "language": self.settings.language,
            "logLevel": self.settings.log_level,
        }

    def reload(self) -> None:
        """Re-read the settings. With no database open, the ones in memory stay in force."""
        conn = self.db.borrow()
        if conn is None:
            log.info("no database open; keeping the settings already loaded")
            return
        defaults = self.defaults()
        with self.db.lock:
            stored = {name: store.meta_get(conn, PREFIX + name) for name in defaults}
            device_rows = conn.execute(
                "SELECT key, value FROM meta WHERE key LIKE ?",
                (DEVICE_PREFIX + "%",),
            ).fetchall()

        values = {}
        for name, default in defaults.items():
            if stored[name] is None:
                values[name] = default
                continue
            try:
                values[name] = clean(name, stored[name], default)
            except Invalid as exc:
                # Hand-edited, or written by an older frame. Refusing to start over one bad
                # row would be worse than falling back to what config.json says.
                log.warning("ignoring %s in %s (%s)", PREFIX + name, self.db.path.name, exc)
                values[name] = default

        devices: dict[str, dict] = {}
        for row in device_rows:
            rest = row["key"][len(DEVICE_PREFIX):]
            dev_id, sep, name = rest.partition(".")
            if not sep or name not in DEVICE_KEYS or not DEVICE_ID_RE.fullmatch(dev_id):
                continue
            try:
                devices.setdefault(dev_id, {})[name] = clean(name, row["value"], defaults[name])
            except Invalid as exc:
                log.warning("ignoring %s in %s (%s)", row["key"], self.db.path.name, exc)

        with self._lock:
            self._values = values
            self._devices = devices

    def as_dict(self) -> dict:
        with self._lock:
            return dict(self._values)

    def for_device(self, device_id: str | None) -> dict:
        with self._lock:
            if not device_id or device_id not in self._devices:
                return dict(self._values)
            return {**self._values, **self._devices[device_id]}

    def __getitem__(self, name: str):
        with self._lock:
            return self._values[name]

    @property
    def slide_seconds(self) -> int:
        return self["slideSeconds"]

    @property
    def weight_by_rating(self) -> bool:
        return self["weightByRating"]

    @property
    def show_rating(self) -> bool:
        return self["showRating"]

    @property
    def rating_filter(self) -> str:
        return self["ratingFilter"]

    @property
    def rating_threshold_enabled(self) -> bool:
        return self["ratingThresholdEnabled"]

    @property
    def rating_threshold(self) -> int:
        return self["ratingThreshold"]

    @property
    def folder_filter(self) -> str:
        return self["folderFilter"]

    @property
    def image_fit(self) -> str:
        return self["imageFit"]

    @property
    def language(self) -> str:
        return self["language"]

    @property
    def quiet_hours(self) -> tuple[str, str]:
        return self["quietFrom"], self["quietTo"]

    def update(self, incoming: dict, device_id: str | None = None) -> dict:
        """Write what someone changed, and nothing else.

        Per-device keys are scoped to `device_id` when provided; global keys apply to all
        devices. An unknown key is refused rather than dropped.
        """
        conn = self.db.require()          # 503 while the database is on loan
        defaults = self.defaults()
        unknown = sorted(set(incoming) - set(defaults))
        if unknown:
            raise Invalid("error.unknownSetting", names=", ".join(unknown))

        cleaned = {name: clean(name, value, defaults[name]) for name, value in incoming.items()}
        merged = {**self.for_device(device_id), **cleaned}
        if bool(merged["quietFrom"]) != bool(merged["quietTo"]):
            raise Invalid("error.quietEnds")

        with self.db.lock:
            for name, value in cleaned.items():
                key = (
                    f"{DEVICE_PREFIX}{device_id}.{name}"
                    if device_id and name in DEVICE_KEYS
                    else PREFIX + name
                )
                store.meta_set(conn, key, str(value))
            conn.commit()
        log.info("settings changed (device=%s): %s", device_id or "global", cleaned)
        self.reload()
        return self.for_device(device_id)
