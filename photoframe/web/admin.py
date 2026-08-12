"""Endpoints for looking after the frame rather than for showing photos."""

import logging

from flask import Blueprint, jsonify, request

log = logging.getLogger(__name__)


def blueprint(frame):
    bp = Blueprint("admin", __name__)
    library, rules, db, settings = frame.library, frame.rules, frame.db, frame.settings

    @bp.post("/api/rescan")
    def rescan_now():
        count = library.scan()
        library.probe_in_background()
        return jsonify(count=count)

    @bp.get("/api/config")
    def config_view():
        """The live configuration. The token is the one thing worth not handing out."""
        settings.reload()
        shown = dict(settings.values)
        shown.update(rules.as_dict())
        shown["frameToken"] = "(set)" if settings.token else ""
        shown["file"] = str(settings.file)
        return jsonify(shown)

    @bp.get("/api/render-stats")
    def render_stats():
        return jsonify(frame.renderer.stats())

    @bp.post("/api/db/release")
    def db_release():
        """Hand the database file over to a tool that wants to rewrite it.

        The frame keeps serving photos. Favourites and hiding return 503 until it comes
        back, and it comes back on its own after the timeout if nobody asks.
        """
        already = not db.release()
        log.info("release requested by %s%s", request.remote_addr,
                 " (already released)" if already else "")
        return jsonify(**db.state(), alreadyReleased=already)

    @bp.post("/api/db/resume")
    def db_resume():
        """Reopen the database and reload the index and rules from it."""
        try:
            db.reopen()
        except Exception as exc:
            log.exception("could not reopen %s", db.path)
            return jsonify(error=str(exc), **db.state()), 500
        log.info("resume requested by %s", request.remote_addr)
        return jsonify(photos=len(library), **db.state())

    @bp.get("/api/db")
    def db_status():
        return jsonify(**db.state())

    return bp
