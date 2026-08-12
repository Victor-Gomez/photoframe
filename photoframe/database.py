"""The connection to photos.db, and the ability to hand the file over and take it back.

The frame does not own this database — scan.py and the other library tools do. It reads
the photo list from it and writes only the blacklist and favourites. That is why a tool
can ask for the file: see release() below.
"""

import logging
import threading
import time
from pathlib import Path

import store

log = logging.getLogger(__name__)

# How long a release may last before the frame takes its database back. A tool that
# crashes mid-run must not leave the frame unable to record a favourite for ever.
RELEASE_TIMEOUT = 15 * 60


class DatabaseUnavailable(RuntimeError):
    """Raised instead of quietly dropping a write while the database is not open."""


class Database:
    """Owns the sqlite connection and the lock that guards it.

    Callers reach the connection through `borrow()` rather than holding it, so nothing can
    keep using a connection that release() has closed underneath it.
    """

    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.RLock()
        self._conn = None
        self._released_at = None
        # Run after the file comes back, in order. This is how the index and the rules are
        # rebuilt without database.py having to know they exist — it is also the one place
        # the module graph would otherwise have a cycle.
        self._on_reopen = []
        try:
            self._conn = store.open_db(path)   # creates and migrates an empty one if need be
        except Exception:
            log.exception("could not open %s; blacklist and favourites are unavailable", path)

    @property
    def is_open(self) -> bool:
        with self._lock:
            return self._conn is not None

    def on_reopen(self, callback) -> None:
        self._on_reopen.append(callback)

    def borrow(self):
        """The connection and its lock, for a caller that is about to use both.

        Returns None when the file is not held, which every caller must handle: releasing
        it is a normal state, not a failure.
        """
        with self._lock:
            return self._conn

    @property
    def lock(self):
        return self._lock

    def require(self):
        """The connection, or refuse. For writes, which cannot be deferred or faked."""
        with self._lock:
            if self._conn is None:
                raise DatabaseUnavailable
            return self._conn

    def release(self) -> bool:
        """Close the database and let go of the file. Serving carries on regardless.

        Everything the slideshow needs is already in memory — the photo list, the ratios,
        the tags and the rules — so the frame keeps showing photos throughout. Only writes
        and the info panel need the file, and those say so rather than pretending.
        """
        with self._lock:
            if self._conn is None:
                return False
            # Closing the last connection checkpoints and removes -wal/-shm.
            self._conn.close()
            self._conn = None
            self._released_at = time.time()
        log.info("database released: %s is free", self.path)
        return True

    def reopen(self) -> None:
        """Take the database back, then let everything rebuilt from it catch up."""
        with self._lock:
            if self._conn is None:
                self._conn = store.open_db(self.path)
            self._released_at = None
        for callback in self._on_reopen:
            callback()

    def state(self) -> dict:
        with self._lock:
            held = self._conn is not None
            since = self._released_at
        return {
            "open": held,
            "file": str(self.path),
            "releasedFor": round(time.time() - since) if since else 0,
            "timeout": RELEASE_TIMEOUT,
        }

    def watch(self) -> None:
        """Take the file back if whoever asked for it never gave it up."""
        while True:
            time.sleep(30)
            with self._lock:
                overdue = (self._released_at is not None
                           and time.time() - self._released_at > RELEASE_TIMEOUT)
            if overdue:
                log.warning("release ran past %ds; taking the database back", RELEASE_TIMEOUT)
                try:
                    self.reopen()
                except Exception:
                    log.exception("could not reopen %s", self.path)

    def start_watchdog(self) -> None:
        threading.Thread(target=self.watch, daemon=True).start()
