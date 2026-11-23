"""Everything the server is made of, wired together in one place.

The only module that knows the whole graph:

    Database  <-  Rules  <-  Library
    RenderCache <- Renderer

Reopening the database is the one place that would otherwise be a cycle — it has to
rebuild the rules and the index above it, so it calls back rather than imports.
"""

import atexit
import json
import logging
import sqlite3
import threading
import time

import store

from . import logs
from .database import Database
from .imaging import RenderCache, Renderer, Traffic
from .library import Library
from .preferences import Preferences
from .rules import Rules
from .settings import Settings

log = logging.getLogger(__name__)
STATS_META_KEY = "frame.stats"
STATS_FLUSH_SECONDS = 30


def _load_stats(db: Database) -> dict:
    conn = db.borrow()
    if conn is None:
        return {}
    try:
        with db.lock:
            raw = store.meta_get(conn, STATS_META_KEY)
        data = json.loads(raw) if raw else {}
        return data if isinstance(data, dict) else {}
    except (sqlite3.Error, ValueError):
        return {}


class Frame:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.started = time.time()   # what /status reports: "did it restart in the night?"
        self.db = Database(settings.db_file)
        saved_stats = _load_stats(self.db)
        saved_cache = saved_stats.get("cache") or {}

        self.rules = Rules(self.db)
        self.library = Library(
            settings.photo_dir, self.db, self.rules, settings.probe_workers)
        # Set here, not in the constructor: the library does not exist until the rules
        # it filters with do.
        self.rules.tags_for = self.library.all_tags
        self.prefs = Preferences(self.db, settings)
        self.cache = RenderCache(
            settings.cache_budget,
            hits=saved_cache.get("hits", 0),
            misses=saved_cache.get("misses", 0),
        )
        self.renderer = Renderer(settings, self.cache)
        self.traffic = Traffic(saved_stats.get("traffic"))
        self._stats_lock = threading.Lock()
        self._last_saved_stats: dict | None = None
        atexit.register(self.save_stats)

        self.db.on_reopen(self.rules.reload)
        self.db.on_reopen(self.prefs.reload)
        self.db.on_reopen(self.apply_prefs)
        self.apply_prefs()

    def apply_prefs(self) -> None:
        """The settings that are not simply read where they are used."""
        logs.set_level(self.prefs["logLevel"])
        self.db.on_reopen(self._reload_index)

    def _reload_index(self) -> None:
        count = self.library.load()   # new photos, renames and removals, without a restart
        log.info("database reopened: %d photos", count)

    def save_stats(self) -> None:
        """Persist lifetime traffic and cache counters in photos.db when changed."""
        payload = {
            "traffic": self.traffic.snapshot(),
            "cache": self.cache.snapshot(),
        }
        with self._stats_lock:
            if payload == self._last_saved_stats:
                return
            conn = self.db.borrow()
            if conn is None:
                return
            try:
                with self.db.lock:
                    store.meta_set(conn, STATS_META_KEY, json.dumps(payload))
                    conn.commit()
                self._last_saved_stats = payload
            except sqlite3.Error:
                log.debug("could not persist stats to %s", self.db.path, exc_info=True)

    def _stats_loop(self) -> None:
        while True:
            time.sleep(STATS_FLUSH_SECONDS)
            self.save_stats()

    def start(self) -> None:
        """Read the photo list, once.

        photos.db is the library tools' to write, so nothing here re-walks the disk on a
        timer. A photo deleted since is dropped when it is next asked for; new ones arrive
        when the database is handed back (/api/db/resume) or on /api/rescan.
        """
        self.db.start_watchdog()
        self.library.refresh()
        threading.Thread(target=self._stats_loop, name="stats-flush", daemon=True).start()
