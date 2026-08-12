"""Everything the server is made of, wired together in one place.

This is the only module that knows the whole graph. Each piece below is handed exactly
the collaborators it needs and nothing else:

    Database  <-  Rules  <-  Library
                  Renderer <- RenderCache

The one place that would otherwise be a cycle is reopening the database: it has to rebuild
the rules and the index, which both sit above it. Database calls back instead of importing
them, and the callbacks are registered here.
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
        # Closed here rather than passed into Rules' constructor: the tag map belongs to
        # the library, which does not exist until the rules it filters with do.
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

        photos.db already lists every photo with its ratio and tags, so the frame needs
        neither a walk nor a decode to start: the whole library is ready in a couple of
        seconds. Files deleted since the last scan are handled as they are hit, and a walk
        still happens on the periodic rescan, which is how new photos arrive.
        """
        self.db.start_watchdog()
        if not self.library.load():
            # The database is missing, empty, or has no rel column filled in. Say so
            # loudly: walking the library is far more expensive — on a slow morning it cost
            # 25 minutes serving nothing, and once took the whole box down with it.
            log.error("%s gave no photos — falling back to a full walk of the library",
                      self.settings.db_file.name)
            self.library.scan()
            self.library.probe_in_background()
        threading.Thread(
            target=self.library.rescan_loop,
            args=(self.settings.rescan_minutes,),
            daemon=True,
        ).start()
