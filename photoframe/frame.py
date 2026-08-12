"""Everything the server is made of, wired together in one place.

The only module that knows the whole graph:

    Database  <-  Rules  <-  Library
    RenderCache <- Renderer

Reopening the database is the one place that would otherwise be a cycle — it has to
rebuild the rules and the index above it, so it calls back rather than imports.
"""

import logging
import threading

from .database import Database
from .imaging import RenderCache, Renderer
from .library import Library
from .rules import Rules
from .settings import Settings

log = logging.getLogger(__name__)


class Frame:
    def __init__(self, settings: Settings):
        self.settings = settings
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
        """Get the photo list, then keep it current.

        Files deleted since the last scan are handled as they are hit; new ones arrive on
        the periodic rescan.
        """
        self.db.start_watchdog()
        if not self.library.load():
            # Missing, empty, or no rel column. Said loudly because the walk below is far
            # more expensive and has taken the whole box down with it.
            log.error("%s gave no photos — falling back to a full walk of the library",
                      self.settings.db_file.name)
            self.library.scan()
            self.library.probe_in_background()
        threading.Thread(
            target=self.library.rescan_loop,
            args=(self.settings.rescan_minutes,),
            daemon=True,
        ).start()
