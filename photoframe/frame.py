"""Everything the server is made of, wired together in one place.

The only module that knows the whole graph:

    Database  <-  Rules  <-  Library
    RenderCache <- Renderer

Reopening the database is the one place that would otherwise be a cycle — it has to
rebuild the rules and the index above it, so it calls back rather than imports.
"""

import logging
import time

from .database import Database
from .imaging import RenderCache, Renderer
from .library import Library
from .rules import Rules
from .settings import Settings

log = logging.getLogger(__name__)


class Frame:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.started = time.time()   # what /status reports: "did it restart in the night?"
        self.db = Database(settings.db_file)
        self.rules = Rules(self.db)
        self.library = Library(
            settings.photo_dir, self.db, self.rules, settings.probe_workers)
        # Set here, not in the constructor: the library does not exist until the rules
        # it filters with do.
        self.rules.tags_for = self.library.all_tags
        self.cache = RenderCache(settings.cache_budget)
        self.renderer = Renderer(settings, self.cache)

        self.db.on_reopen(self.rules.reload)
        self.db.on_reopen(self._reload_index)

    def _reload_index(self) -> None:
        count = self.library.load()   # new photos, renames and removals, without a restart
        log.info("database reopened: %d photos", count)

    def start(self) -> None:
        """Read the photo list, once.

        photos.db is the library tools' to write, so nothing here re-walks the disk on a
        timer. A photo deleted since is dropped when it is next asked for; new ones arrive
        when the database is handed back (/api/db/resume) or on /api/rescan.
        """
        self.db.start_watchdog()
        self.library.refresh()
