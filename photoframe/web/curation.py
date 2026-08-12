"""Hiding and favouriting: the two things the frame writes.

Hiding records a rule in photos.db and drops the photo from the index in memory. The file
is never moved, renamed or deleted.
"""

import logging
from pathlib import PurePosixPath

from flask import Blueprint, abort, jsonify, request

from ..imaging import EXTENSIONS
from ..library import ancestors, photo_id_of
from ..rules import normalise_entry

log = logging.getLogger(__name__)


def blueprint(frame):
    bp = Blueprint("curation", __name__)
    library, rules = frame.library, frame.rules

    def indexed_photo(data: dict):
        src = library.path_of(data.get("id", ""))
        if src is None:
            abort(404)
        return src

    @bp.post("/api/blacklist")
    def blacklist_add():
        """Hide a photo or one of its parent folders, and drop it from the library right
        away — no rescan needed."""
        data = request.get_json(silent=True) or {}
        scope = data.get("scope", "photo")
        rel = PurePosixPath(indexed_photo(data).relative_to(library.root).as_posix())

        if scope == "folder":
            # Only a folder this photo sits in, so the endpoint cannot be talked into
            # hiding an arbitrary path. The match also gives the folder's real spelling.
            wanted = normalise_entry(data.get("folder", "")).lower()
            entry = next((a for a in ancestors(rel) if a.lower() == wanted), None)
            if entry is None:
                return jsonify(error="that folder does not contain this photo"), 400
            section = "folders"
        elif scope == "photo":
            entry, section = rel.as_posix(), "files"
        else:
            return jsonify(error="scope must be 'photo' or 'folder'"), 400

        rules.add(section, entry)
        removed = library.drop_blacklisted()
        log.info("blacklist add %r (%s) by %s — %d photos removed",
                 entry, scope, request.remote_addr, len(removed))
        return jsonify(entry=entry, scope=scope, removed=removed, count=len(library))

    @bp.post("/api/blacklist/undo")
    def blacklist_undo():
        """Take an entry back out of the blacklist and return the photo to the library.

        A swipe hides a photo with one careless gesture, so the frame offers a few seconds
        of Undo rather than leaving the database as the only way back.
        """
        data = request.get_json(silent=True) or {}
        entry = normalise_entry(data.get("entry", ""))
        scope = data.get("scope", "photo")
        if not entry or scope not in ("photo", "folder"):
            return jsonify(error="nothing to undo"), 400

        log.info("blacklist undo requested %r (%s) by %s", entry, scope, request.remote_addr)
        rules.remove("files" if scope == "photo" else "folders", entry)

        if scope == "folder":
            # A folder was pruned from the walk entirely, so the index has to be rebuilt.
            count = library.scan()
            library.probe_in_background()
            return jsonify(entry=entry, scope=scope, count=count)

        path = library.root / entry
        if not path.is_file() or path.suffix.lower() not in EXTENSIONS:
            return jsonify(error="that photo is no longer there"), 404
        if rules.blacklisted_file(entry):
            return jsonify(error="another entry still hides it"), 409

        pid = library.restore(entry, path)
        log.info("blacklist UNDO %r (%s) by %s", entry, scope, request.remote_addr)
        return jsonify(entry=entry, scope=scope, id=pid, count=len(library))

    @bp.post("/api/favorite")
    def favorite_set():
        """Add or remove the current photo from the favourites.

        A photo can be a favourite by name or because a folder, glob or tag covers it.
        Un-favouriting drops any entry naming it and, if a broader rule still catches it,
        records an exception — otherwise the button does nothing on a tagged photo.
        """
        data = request.get_json(silent=True) or {}
        rel = PurePosixPath(indexed_photo(data).relative_to(library.root).as_posix())
        entry = rel.as_posix()
        pid = photo_id_of(entry)
        wanted = bool(data.get("favorite", True))

        log.info("favorite %s %r by %s",
                 "add" if wanted else "remove", entry, request.remote_addr)
        if wanted:
            rules.remove("unfavorites", entry)   # an exception no longer applies
            if not rules.favorite_check()(entry.lower(), pid):
                rules.add("favorites", entry)
            covered_by = "rule" if not rules.matcher("favorites")(entry.lower()) else "name"
        else:
            rules.remove("favorites", entry)
            covered_by = "name"
            if rules.favorite_check()(entry.lower(), pid):  # a tag or folder still catches it
                rules.add("unfavorites", entry)
                covered_by = "rule"

        return jsonify(entry=entry, favorite=wanted, coveredBy=covered_by,
                       count=rules.favorite_count())

    return bp
