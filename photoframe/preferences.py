"""What a person chose, kept in photos.db beside the rules.

config.json describes the machine — ports, paths, threads, where avifdec lives — and is
never written from a screen, so a hand edit cannot be lost to a tap. This is the other
half: the few settings someone sets from a page. They belong to the library rather than to
the box serving it, so they live in the database and follow it between machines.
"""

import logging
import re
import threading

import store

from .database import Database
from .i18n import LANGUAGES, Invalid

log = logging.getLogger(__name__)

# The meta table is shared with the library tools, so the frame's keys say whose they are.
PREFIX = "frame."
HHMM = re.compile(r"([01]\d|2[0-3]):[0-5]\d")

QUIET = ("quietFrom", "quietTo")
LOG_LEVELS = ("off", "error", "info")
CHOICES = {"language": LANGUAGES, "logLevel": LOG_LEVELS}


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
    try:
        number = int(raw)
    except (TypeError, ValueError):
        raise Invalid("error.number", name=name) from None
    if name == "slideSeconds":
        return max(3, min(3600, number))
    if name == "favoriteWeight":
        return max(1, min(100, number))
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
        self.reload()

    def defaults(self) -> dict:
        return {
            "slideSeconds": self.settings.slide_seconds,
            "favoriteWeight": self.settings.favorite_weight,
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
        with self._lock:
            self._values = values

    def as_dict(self) -> dict:
        with self._lock:
            return dict(self._values)

    def __getitem__(self, name: str):
        with self._lock:
            return self._values[name]

    @property
    def slide_seconds(self) -> int:
        return self["slideSeconds"]

    @property
    def favorite_weight(self) -> int:
        return self["favoriteWeight"]

    @property
    def language(self) -> str:
        return self["language"]

    @property
    def quiet_hours(self) -> tuple[str, str]:
        return self["quietFrom"], self["quietTo"]

    def update(self, incoming: dict) -> dict:
        """Write what someone changed, and nothing else.

        An unknown key is refused rather than dropped: a settings form that silently
        ignores half of what it sent is worse than one that says so.
        """
        conn = self.db.require()          # 503 while the database is on loan
        defaults = self.defaults()
        unknown = sorted(set(incoming) - set(defaults))
        if unknown:
            raise Invalid("error.unknownSetting", names=", ".join(unknown))

        cleaned = {name: clean(name, value, defaults[name]) for name, value in incoming.items()}
        merged = {**self.as_dict(), **cleaned}
        if bool(merged["quietFrom"]) != bool(merged["quietTo"]):
            raise Invalid("error.quietEnds")

        with self.db.lock:
            for name, value in cleaned.items():
                store.meta_set(conn, PREFIX + name, str(value))
            conn.commit()
        log.info("settings changed: %s", cleaned)
        self.reload()
        return self.as_dict()
