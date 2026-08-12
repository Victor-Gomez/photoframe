"""What the frame knows about one photo: its name, its metadata, and its neighbours."""

import logging
import re
import sqlite3
from pathlib import PurePosixPath

from flask import Blueprint, abort, jsonify, request

from ..library import ancestors

log = logging.getLogger(__name__)

INFO_COLUMNS = (
    "taken", "tz", "make", "model", "lens", "aperture", "shutter", "iso",
    "focal_length", "focal_length_35", "compensation", "exposure_display",
    "gps_lat", "gps_lon", "altitude", "width", "height", "size", "rating",
    # Filled in by geocode.py from the `place` table, and by the Google Photos import.
    "location", "google_url",
)


def natural_key(name: str):
    """Sort DSC_9 before DSC_10, which a plain string sort gets backwards."""
    return [int(part) if part.isdigit() else part.lower()
            for part in re.split(r"(\d+)", name)]


def blueprint(frame):
    bp = Blueprint("photos", __name__)
    library, rules, db = frame.library, frame.rules, frame.db

    @bp.get("/api/photo/<pid>")
    def photo_info(pid: str):
        """What the menu needs to name what it is about to hide or favourite."""
        src = library.path_of(pid)
        if src is None:
            abort(404)
        rel = PurePosixPath(src.relative_to(library.root).as_posix())
        parent = rel.parent.as_posix()
        return jsonify(
            file=rel.name,
            folder="" if parent == "." else parent,
            folders=ancestors(rel),
            # The path as it exists on this machine, for copy-to-clipboard: the same
            # information the relative path carries, in a form a file manager accepts.
            fullPath=str(src),
            favorite=rules.favorite_check()(rel.as_posix().lower(), pid),
            tags=sorted(library.tags_of(pid)),
            ratio=library.ratio_of(pid),
        )

    @bp.get("/api/info/<pid>")
    def photo_details(pid: str):
        """Everything scan.py read out of the file, for the info overlay.

        Separate from /api/photo because that one runs on every slide and this is a
        database round trip nobody needs until the overlay is actually opened.
        """
        source = library.path_of(pid)
        rel = library.rel_of(pid)
        if source is None or rel is None:
            abort(404)

        info = {
            "file": rel.rpartition("/")[2],
            "folder": rel.rpartition("/")[0],
            "fullPath": str(source),
            "tags": sorted(library.tags_of(pid)),
        }
        conn = db.borrow()
        info["databaseOpen"] = conn is not None
        if conn is not None:
            try:
                with db.lock:
                    row = conn.execute(
                        f"SELECT {', '.join(INFO_COLUMNS)} FROM photo WHERE rel = ?",
                        (rel,),
                    ).fetchone()
                if row is not None:
                    # Nulls are dropped rather than sent: the overlay lists what is known
                    # and says nothing about what the camera did not record.
                    info.update({c: row[c] for c in INFO_COLUMNS if row[c] is not None})
                    with db.lock:
                        people = conn.execute(
                            "SELECT DISTINCT p.name FROM face f "
                            "JOIN cluster c ON c.id = f.cluster_id "
                            "JOIN person p ON p.id = c.person_id "
                            "WHERE f.rel = ? AND p.name IS NOT NULL ORDER BY p.name",
                            (rel,),
                        ).fetchall()
                    if people:
                        info["people"] = [r["name"] for r in people]
            except sqlite3.Error:
                log.exception("could not read the details for %s", rel)
        return jsonify(info)

    @bp.get("/api/neighbors/<pid>")
    def neighbors(pid: str):
        """The photos either side of this one *in its own folder*, in filename order.

        What the gallery grid shows. Deliberately not drawn from the playlist: that is
        shuffled and filtered by shape, and the point here is to see a burst the way the
        camera wrote it. Blacklisted photos are already absent from the index.
        """
        # No span means the whole folder: scrolling out to the ends of a shoot is the
        # point, and the grid only ever loads the tiles you actually scroll to.
        span = request.args.get("span", type=int)
        rel = library.rel_of(pid)
        if rel is None:
            abort(404)
        folder = rel.rpartition("/")[0]
        siblings = [
            (other_rel.rpartition("/")[2], other_pid)
            for other_pid, other_rel in library.rel_true_map().items()
            if other_rel.rpartition("/")[0] == folder
        ]

        siblings.sort(key=lambda pair: natural_key(pair[0]))
        here = next((i for i, (_, other) in enumerate(siblings) if other == pid), None)
        if here is None:
            abort(404)
        if span and span > 0:
            lo, hi = max(0, here - span), min(len(siblings), here + span + 1)
        else:
            lo, hi = 0, len(siblings)

        # Once for the whole folder: it snapshots the entire tag map, and rebuilding it
        # per photo costs seconds on a big shoot.
        favorite = rules.favorite_check()

        photos = []
        for name, other_pid in siblings[lo:hi]:
            entry = f"{folder}/{name}" if folder else name
            # Kept small: a big folder pays for every field thousands of times. The
            # blacklist entry is folder + name, so the grid rebuilds it rather than be sent it.
            photo = {"id": other_pid, "file": name}
            if favorite(entry.lower(), other_pid):
                photo["favorite"] = True
            if other_pid == pid:
                photo["current"] = True
            photos.append(photo)
        return jsonify(
            folder=folder, current=pid, photos=photos,
            position=here - lo, total=len(siblings),
        )

    return bp
