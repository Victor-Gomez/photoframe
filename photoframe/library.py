"""The photo list the frame serves from, and how it is built and kept current.

Built from photos.db, which scan.py fills in: every photo with its ratio and tags, so
starting needs neither a walk nor a decode. Walking is the fallback, and far slower.
"""

import hashlib
import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path, PurePosixPath

from .imaging import EXTENSIONS, lowered, probe
from .priority import background_io, worker_background

log = logging.getLogger(__name__)

SKIP_DIRS = {"@eaDir", "#recycle", "__pycache__"}

# A coarse reading of the aspect ratio, for clients that do not send their own.
LANDSCAPE, PORTRAIT = "landscape", "portrait"
ORIENTATIONS = (LANDSCAPE, PORTRAIT)

# Near-square crops acceptably both ways, so it belongs in both passes rather than being
# forced into one by a rounding error.
SQUARE_BAND = 0.05


def orientation_from(ratio: float) -> str:
    return PORTRAIT if ratio < 1 else LANDSCAPE


def is_square(ratio: float) -> bool:
    return abs(ratio - 1) <= SQUARE_BAND


def fits(ratio: float, want: str) -> bool:
    """Whether a photo of this shape belongs on a screen of that orientation."""
    return is_square(ratio) or orientation_from(ratio) == want


def photo_id_of(rel: str) -> str:
    """Stable id derived from the path, so ids survive a rescan and leak no disk layout."""
    return hashlib.sha1(rel.encode("utf-8")).hexdigest()[:16]


def ancestors(rel: PurePosixPath) -> list[str]:
    """Every folder between the library root and the photo, shallowest first: A, A/B."""
    return [p.as_posix() for p in reversed(rel.parents) if p.as_posix() != "."]


class Library:
    """Which photos exist, where they are, their shape and their tags.

    All in memory and rebuilt from photos.db, so the frame keeps serving while the
    database is released.
    """

    def __init__(self, root: Path, db, rules, probe_workers: int = 4):
        self.root = root
        self.db = db
        self.rules = rules
        self.probe_workers = probe_workers

        self._lock = threading.Lock()
        self._paths: dict[str, Path] = {}
        # Kept rather than derived: Path.relative_to costs 0.6s across a large playlist.
        self._rel_lower: dict[str, str] = {}
        # The same paths with their real capitalisation, which is what photos.db is keyed by.
        self._rel_true: dict[str, str] = {}

        self._shape_lock = threading.Lock()
        self._ratio: dict[str, float] = {}
        self._tags: dict[str, tuple[str, ...]] = {}
        self._probe_lock = threading.Lock()   # whole passes, not individual photos
        self.probe_done = threading.Event()

        self.passes = Passes()

    # -- reading -------------------------------------------------------------------

    def __len__(self) -> int:
        with self._lock:
            return len(self._paths)

    def path_of(self, pid: str) -> Path | None:
        with self._lock:
            return self._paths.get(pid)

    def rel_of(self, pid: str) -> str | None:
        """The path as photos.db spells it, which is what the database is keyed by."""
        with self._lock:
            return self._rel_true.get(pid)

    def items(self) -> list[tuple[str, Path]]:
        with self._lock:
            return list(self._paths.items())

    def rel_lower_map(self) -> dict[str, str]:
        with self._lock:
            return dict(self._rel_lower)

    def rel_true_map(self) -> dict[str, str]:
        with self._lock:
            return dict(self._rel_true)

    def ratio_of(self, pid: str) -> float | None:
        with self._shape_lock:
            return self._ratio.get(pid)

    def tags_of(self, pid: str) -> tuple[str, ...]:
        with self._shape_lock:
            return self._tags.get(pid, ())

    def set_tags(self, pid: str, tags) -> None:
        """Used where a photo's tags are known without reading it — and by the tests."""
        with self._shape_lock:
            self._tags[pid] = lowered(tags)

    def all_tags(self) -> dict[str, tuple[str, ...]]:
        """A snapshot for the favourites check, which needs the whole map at once."""
        with self._shape_lock:
            return dict(self._tags)

    def matching(self, want: str, squares: bool = True) -> list[tuple[str, Path]]:
        """Only the photos whose shape suits a screen of that orientation.

        A real screen gets the near-square photos either way; a caller that named an
        orientation outright gets what is actually that shape.
        """
        with self._shape_lock:
            ratios = dict(self._ratio)
        keep = fits if squares else (lambda ratio, w: orientation_from(ratio) == w)
        return [(pid, p) for pid, p in self.items()
                if pid in ratios and keep(ratios[pid], want)]

    def orientation_counts(self) -> dict[str, int]:
        with self._shape_lock:
            ratios = list(self._ratio.values())
        return {o: sum(1 for r in ratios if orientation_from(r) == o) for o in ORIENTATIONS}

    # -- building ------------------------------------------------------------------

    def load(self) -> int:
        """Build the photo list from photos.db: no walk, no decoding.

        scan.py recorded every ratio and tag already, which is what makes startup
        independent of how fast the filesystem happens to be.
        """
        conn = self.db.borrow()
        if conn is None:
            return 0
        with self.db.lock:
            rows = conn.execute("SELECT rel, ratio FROM photo WHERE rel IS NOT NULL").fetchall()
            tag_rows = conn.execute("SELECT rel, tag FROM photo_tag").fetchall()
        if not rows:
            return 0

        found: dict[str, Path] = {}
        relatives: dict[str, str] = {}
        true_paths: dict[str, str] = {}
        ratios: dict[str, float] = {}
        for row in rows:
            rel = row["rel"]
            lower = rel.lower()
            # Applied here too, so editing the blacklist takes effect on the next restart.
            if self.rules.blacklisted_file(lower) or any(
                self.rules.blacklisted_dir(part)
                for part in ancestors(PurePosixPath(lower))
            ):
                continue
            pid = photo_id_of(rel)
            found[pid] = self.root / rel
            relatives[pid] = lower
            true_paths[pid] = rel
            if isinstance(row["ratio"], (int, float)) and row["ratio"] > 0:
                ratios[pid] = float(row["ratio"])

        tags: dict[str, tuple[str, ...]] = {}
        for row in tag_rows:
            pid = photo_id_of(row["rel"])
            if pid in found and row["tag"]:
                tags[pid] = tags.get(pid, ()) + (str(row["tag"]).lower(),)

        self._replace(found, relatives, true_paths)
        with self._shape_lock:
            self._ratio = ratios
            self._tags = tags
        self.probe_done.set()      # nothing left to probe: the database already knows
        self.passes.forget()
        log.info("loaded %d photos from %s (%d with a ratio, %d tagged)",
                 len(found), self.db.path.name, len(ratios), len(tags))
        return len(found)

    def refresh(self) -> int:
        """The photo list again from photos.db, walking only if it gives nothing.

        scan.py keeps the database current, so a rescan is a reload. Walking re-reads
        every header and empties the aspect index while it runs, and a playlist built in
        that window matches nothing and comes back unfiltered.
        """
        count = self.load()
        if not count:
            # Missing, empty, or no rel column. Said loudly because the walk is far more
            # expensive and has taken the whole box down with it.
            log.error("%s gave no photos — falling back to a full walk of the library",
                      self.db.path.name)
            count = self.scan()
            self.probe_in_background()
        return count

    def scan(self) -> int:
        """Walk the disk instead. Only reached when the database gave nothing."""
        with background_io():
            return self._scan()

    def _scan(self) -> int:
        self.rules.reload()   # picks up any hand edits
        found: dict[str, Path] = {}
        relatives: dict[str, str] = {}
        true_paths: dict[str, str] = {}
        for root, dirs, files in os.walk(self.root):
            rel_root = Path(root).relative_to(self.root).as_posix()
            prefix = "" if rel_root == "." else rel_root + "/"
            # Pruned rather than filtered: a hidden folder is never descended into.
            dirs[:] = [
                d for d in dirs
                if not d.startswith(".")
                and d not in SKIP_DIRS
                and not self.rules.blacklisted_dir(prefix + d)
            ]
            for name in files:
                if (Path(name).suffix.lower() in EXTENSIONS
                        and not self.rules.blacklisted_file(prefix + name)):
                    path = Path(root, name)
                    pid = photo_id_of((prefix + name))
                    found[pid] = path
                    relatives[pid] = (prefix + name).lower()
                    true_paths[pid] = prefix + name
        self._replace(found, relatives, true_paths)
        self.passes.forget()   # the library just changed under any pass in flight
        log.info("indexed %d photos under %s", len(found), self.root)
        return len(found)

    def _replace(self, paths, relatives, true_paths) -> None:
        with self._lock:
            self._paths = paths
            self._rel_lower = relatives
            self._rel_true = true_paths

    def probe_all(self) -> None:
        """Read the orientation of every indexed photo out of its header.

        Only reached when photos.db gave nothing: load() normally sets every ratio without
        opening a file. Nothing is cached here — the database is the cache.
        """
        with self._probe_lock, background_io():
            self.probe_done.clear()
            items = self.items()
            with self._shape_lock:
                self._ratio.clear()
                self._tags.clear()

            def work(item: tuple[str, Path]):
                pid, path = item
                try:
                    ratio, tags = probe(path)
                    return pid, round(ratio, 4), lowered(tags)
                except Exception:
                    log.warning("could not read the header of %s", path)
                    return None

            log.info("probing %d photos", len(items))
            done = 0
            with ThreadPoolExecutor(self.probe_workers, initializer=worker_background) as pool:
                for result in pool.map(work, items):
                    if result is None:
                        continue
                    pid, ratio, tags = result
                    with self._shape_lock:
                        self._ratio[pid] = ratio
                        if tags:
                            self._tags[pid] = tags
                    done += 1
                    if done % 2000 == 0:
                        log.info("probed %d/%d", done, len(items))

            self.probe_done.set()
            log.info("aspect index ready: %s", self.orientation_counts())

    def probe_in_background(self) -> None:
        threading.Thread(target=self.probe_all, daemon=True).start()

    # -- changing ------------------------------------------------------------------

    def drop_blacklisted(self) -> list[str]:
        """Remove newly blacklisted photos from the live index without re-walking the disk."""
        hidden_file = self.rules.matcher("files")
        hidden_folder = self.rules.matcher("folders")
        with self._lock:
            gone = [pid for pid, rel in self._rel_lower.items()
                    if hidden_file(rel) or hidden_folder(rel)]
            for pid in gone:
                del self._paths[pid]
                self._rel_lower.pop(pid, None)
                # The true-case paths too, or /api/neighbors goes on offering it.
                self._rel_true.pop(pid, None)
        with self._shape_lock:
            for pid in gone:
                self._ratio.pop(pid, None)
                self._tags.pop(pid, None)
        if gone:
            self.passes.forget()
        return gone

    def forget(self, pid: str) -> None:
        """Drop a photo the index knows about but the disk does not.

        The failsafe for starting without a walk: noticed on use, forgotten, moved past.
        The database is left alone — scan.py owns it and the next rescan reconciles.
        """
        with self._lock:
            self._paths.pop(pid, None)
            self._rel_lower.pop(pid, None)
            rel = self._rel_true.pop(pid, None)
        with self._shape_lock:
            self._ratio.pop(pid, None)
            self._tags.pop(pid, None)
        if rel:
            log.info("dropped %s: no longer on disk", rel)
        self.passes.forget()

    def restore(self, rel: str, path: Path) -> str:
        """Put one photo back after its blacklist entry was undone, without a rescan."""
        pid = photo_id_of(rel)
        with self._lock:
            self._paths[pid] = path
            self._rel_lower[pid] = rel.lower()
            self._rel_true[pid] = rel
        self.passes.forget()   # so the restored photo can come round again
        try:  # one header read, rather than a whole rescan for a single photo
            ratio, tags = probe(path)
            with self._shape_lock:
                self._ratio[pid] = ratio
                if tags:
                    self._tags[pid] = lowered(tags)
        except Exception:
            log.warning("restored %s but could not read its header", path)
        return pid

class Passes:
    """The shuffled passes clients are paging through.

    Kept server-side because shipping every id up front costs seconds and the frame needs
    only the first two to start. A change to the library throws them all away, or a client
    still walking an old pass would be handed ids that no longer exist.
    """

    KEPT = 4

    def __init__(self):
        self._passes: dict[str, list[str]] = {}
        self._lock = threading.Lock()

    def get(self, token: str) -> list[str] | None:
        with self._lock:
            return self._passes.get(token)

    def add(self, token: str, ids: list[str]) -> None:
        with self._lock:
            self._passes[token] = ids
            while len(self._passes) > self.KEPT:   # only the newest few are reachable
                self._passes.pop(next(iter(self._passes)))

    def forget(self) -> None:
        with self._lock:
            self._passes.clear()
