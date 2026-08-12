"""The photo list the frame serves from, and how it is built and kept current.

Built from photos.db, which scan.py fills in: every photo with its ratio and tags, so
starting needs neither a walk of the disk nor a single decode. Walking the library is the
fallback, and it is much more expensive — see load().
"""

import hashlib
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path, PurePosixPath

from .imaging import EXTENSIONS, lowered, probe
from .priority import background_io, worker_background

log = logging.getLogger(__name__)

SKIP_DIRS = {"@eaDir", "#recycle", "__pycache__"}

# Orientation is a coarse reading of the aspect ratio, for the API and for clients that do
# not send their own. Squares count as landscape.
LANDSCAPE, PORTRAIT = "landscape", "portrait"
ORIENTATIONS = (LANDSCAPE, PORTRAIT)

# A photo close enough to square reads as neither, and crops acceptably both ways -- so it
# belongs in both passes rather than being forced into one by a rounding error.
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
    """Which photos exist, where they are, what shape they are and what they are tagged.

    Everything here is in memory and rebuilt from photos.db, so the frame keeps serving
    while the database is released for maintenance.
    """

    def __init__(self, root: Path, db, rules, probe_workers: int = 4):
        self.root = root
        self.db = db
        self.rules = rules
        self.probe_workers = probe_workers

        self._lock = threading.Lock()
        self._paths: dict[str, Path] = {}
        # pid -> the path relative to the root, lowercased. Kept because deriving it with
        # Path.relative_to costs 0.6s across a large playlist on a slow CPU.
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

        `squares` is the difference between a screen asking by its own ratio and a caller
        naming an orientation outright. A real screen gets the near-square photos in both
        passes, since they crop acceptably either way; a caller that asked for "portrait"
        gets what is actually portrait.
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

        scan.py already recorded every photo with its ratio and tags, so the frame has
        nothing to work out for itself. This is also what makes startup independent of how
        fast the filesystem happens to be that morning.
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
            # Applied here as well, so editing the blacklist takes effect on the next
            # restart without the database being touched.
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
            # Pruned here rather than filtered afterwards: a blacklisted folder is never
            # descended into at all.
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

        Only reached when photos.db gave nothing. Normally load() sets every ratio without
        opening a single file — this reads every header off the disk, which takes over a
        minute. Nothing is cached: the database is the cache, and a second copy of the same
        facts is what this replaced.
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
                # Also the true-case paths, or a hidden photo goes on being offered as a
                # neighbour by /api/neighbors long after it left the library.
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

        The failsafe for building the list from photos.db without a walk: a deleted file is
        noticed when something tries to serve it, removed from the index in memory, and the
        frame moves on rather than showing an error. The database is left alone — scan.py
        owns it, and the next rescan reconciles.
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

    def rescan_loop(self, minutes: int) -> None:
        while True:
            time.sleep(minutes * 60)
            if not self.db.is_open:
                log.info("skipping the rescan: the database is released")
                continue
            try:
                self.scan()
                self.probe_all()
            except Exception:
                log.exception("rescan failed")


class Passes:
    """The shuffled passes clients are paging through.

    A pass is a snapshot of the library, kept server-side because shipping every id up
    front costs seconds on a slow CPU and the frame only needs the first two to start.
    Once photos leave the index any client still walking an older pass would be handed ids
    that no longer exist, so a change throws them all away and clients start a fresh one.
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
