"""The blacklist and the favourites: four lists of patterns, held in photos.db.

Paths are relative to the library root, case-insensitive, and may use either slash. Globs
work — "*/Screenshots", "*.png". A folder entry covers everything under it; so does a
favourites entry naming a folder. A bare name with no slash ("Screenshots", "DSC01.avif")
matches at any depth.
"""

import logging
import threading
from fnmatch import fnmatch

import store

from .database import Database

log = logging.getLogger(__name__)

TAG_PREFIX = "tag:"
GLOB_CHARS = "*?["

# Which rule kind in photos.db backs each of the four lists the frame matches against.
SECTION_KIND = {
    "folders": "blacklist_folder",
    "files": "blacklist_file",
    "favorites": "favorite",
    "unfavorites": "unfavorite",
}
FAVORITE_SECTIONS = {"favorites": "favoriteTags", "unfavorites": "unfavoriteTags"}
SECTIONS = (*SECTION_KIND, *FAVORITE_SECTIONS.values())


def normalise_entry(raw: str) -> str:
    """Both slash flavours, any leading ./ and any trailing / mean the same thing here."""
    return str(raw).strip().replace("\\", "/").strip("/").removeprefix("./")


class Matcher:
    """Tests paths against one list, prepared once instead of per path.

    fnmatch compiles a regex per pattern, and calling it tens of thousands of times to
    check a handful of plain paths was most of the cost of building a playlist. Plain
    entries — nearly all of them — become set lookups and one startswith over a tuple.
    """

    __slots__ = ("exact", "prefixes", "names", "globs", "empty")

    def __init__(self, entries: list[str]):
        plain = [e for e in entries if not any(c in e for c in GLOB_CHARS)]
        self.exact = set(plain)
        self.prefixes = tuple(e + "/" for e in plain)  # everything under a listed folder
        # A bare name matches any segment, so "Screenshots" catches it at any depth.
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


class Rules:
    """The four lists and the matchers built from them, kept in step with the database."""

    def __init__(self, db: Database, tags_for=None):
        self.db = db
        # How to find a photo's tags. Injected because a favourite can be a tag rule, and
        # the tags belong to the library rather than here.
        self.tags_for = tags_for or (lambda: {})
        self._lock = threading.RLock()
        # `_raw` is what was written and what gets reported back; `_lists` is lowercased
        # for matching. Report the normalised form and "Trip/Day1" comes back "trip/day1".
        # Whether these lists ever came from a database. Empty because nothing is hidden
        # and empty because nothing could be read are the same four lists and opposite
        # facts, and the walk must be able to tell them apart.
        self.loaded = False
        self._raw: dict[str, list[str]] = {name: [] for name in SECTION_KIND}
        self._lists: dict[str, list[str]] = {name: [] for name in SECTIONS}
        self._matchers = {name: Matcher([]) for name in SECTIONS}
        self.reload()

    def reload(self) -> None:
        """Re-read the blacklist and favourites from the database.

        With no database open the rules in memory stay in force. Rebuilding them as empty
        would silently unhide every blacklisted photo, which is the one failure this must
        never have.
        """
        conn = self.db.borrow()
        if conn is None:
            log.info("no database open; keeping the rules already loaded")
            return

        with self.db.lock:
            raw = {section: store.rules(conn, kind) for section, kind in SECTION_KIND.items()}

        with self._lock:
            lists = {
                name: [normalise_entry(e).lower() for e in entries if normalise_entry(e)]
                for name, entries in raw.items()
            }
            # "tag:holiday" favours every photo carrying that XMP keyword, which beats
            # listing forty paths. The prefix disambiguates it from a folder of that name.
            for section, tag_section in FAVORITE_SECTIONS.items():
                paths, patterns = [], []
                for entry in lists[section]:
                    if entry.startswith(TAG_PREFIX):
                        patterns.append(entry[len(TAG_PREFIX):].strip())
                    else:
                        paths.append(entry)
                lists[section], lists[tag_section] = paths, patterns
            self._raw = raw
            self._lists = lists
            self._matchers = {name: Matcher(entries) for name, entries in lists.items()}
            self.loaded = True

    def matcher(self, section: str) -> Matcher:
        with self._lock:
            return self._matchers[section]

    def snapshot(self, section: str) -> list[str]:
        with self._lock:
            return list(self._lists[section])

    def as_dict(self) -> dict:
        """What /api/config reports — from here, not config.json, which holds no rules."""
        with self._lock:
            return {
                "blacklist": {
                    "folders": list(self._raw["folders"]),
                    "files": list(self._raw["files"]),
                },
                "favorites": list(self._raw["favorites"]),
                "unfavorites": list(self._raw["unfavorites"]),
            }

    def favorite_count(self) -> int:
        """Every favourite rule, tag rules included — what the frame reports after a tap."""
        with self._lock:
            return len(self._raw["favorites"])

    def blacklisted_dir(self, rel: str) -> bool:
        return self.matcher("folders")(rel.lower())

    def blacklisted_file(self, rel: str) -> bool:
        low = rel.lower()
        return self.matcher("files")(low) or self.matcher("folders")(low)

    def favorite_check(self):
        """Build a favourites test with the rules and the tag map snapshotted once.

        `unfavorites` wins over `favorites`, so a single photo can be taken back out of a
        sweeping rule like `tag:album_japon_2` without unpicking the rule itself.

        Build it once per pass: it copies the whole tag map.
        """
        by_path, not_by_path = self.matcher("favorites"), self.matcher("unfavorites")
        tag_patterns = self.snapshot("favoriteTags")
        excluded_tags = self.snapshot("unfavoriteTags")
        tags_by_pid = self.tags_for()

        def tagged(tags, patterns) -> bool:
            return any(tag == want or fnmatch(tag, want)
                       for tag in tags for want in patterns)

        def check(rel_lower: str, pid: str) -> bool:
            tags = tags_by_pid.get(pid, ())
            if not_by_path(rel_lower) or tagged(tags, excluded_tags):
                return False
            return by_path(rel_lower) or tagged(tags, tag_patterns)

        return check

    def is_favorite(self, rel: str, pid: str | None = None) -> bool:
        """One photo. For a whole pass use favorite_check() once instead — this rebuilds it."""
        from .library import photo_id_of
        return self.favorite_check()(rel.lower(), pid if pid is not None else photo_id_of(rel))

    def add(self, section: str, entry: str) -> None:
        """Record a rule, ignoring duplicates."""
        conn = self.db.require()
        with self.db.lock:
            store.add_rule(conn, SECTION_KIND[section], entry)
            conn.commit()
        self.reload()

    def remove(self, section: str, entry: str) -> None:
        conn = self.db.require()
        with self.db.lock:
            store.remove_rule(conn, SECTION_KIND[section], entry)
            conn.commit()
        self.reload()
