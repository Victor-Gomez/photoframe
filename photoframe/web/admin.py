"""Endpoints for looking after the frame rather than for showing photos."""

import logging
import time
from datetime import datetime

from flask import Blueprint, jsonify, render_template, request

from .. import i18n, logs, preferences

log = logging.getLogger(__name__)

LOG_LINES = 200


def uptime(started: float) -> str:
    """In the largest unit that still says something: "3 d 4 h", not 273,600 s."""
    seconds = int(time.time() - started)
    minutes, hours = seconds // 60, seconds // 3600
    if seconds < 90:
        return f"{seconds} s"
    if hours < 1:
        return f"{minutes} min"
    if hours < 48:
        return f"{hours} h {minutes % 60} min"
    return f"{hours // 24} d {hours % 24} h"


def blueprint(frame):
    bp = Blueprint("admin", __name__)
    library, rules, db, settings = frame.library, frame.rules, frame.db, frame.settings
    prefs = frame.prefs

    @bp.post("/api/rescan")
    def rescan_now():
        """Pick up whatever scan.py has recorded since: a reload, not a walk."""
        return jsonify(count=library.refresh())

    def verdict(renders: dict, t) -> str:
        """Which decoder won, said in words. The JSON endpoint keeps the English original."""
        pillow, avifdec = renders["pillow"], renders["avifdec"]
        if min(pillow.get("renders", 0), avifdec.get("renders", 0)) < 20:
            return t("verdict.waiting")
        median, other = pillow["medianMs"], avifdec["medianMs"]
        percent = round(abs(median - other) / max(median, 1) * 100)
        return t("verdict.slower" if other > median else "verdict.faster", percent=percent)

    def report() -> dict:
        settings.reload()
        shown = dict(settings.values)
        shown["frameToken"] = "(set)" if settings.token else ""
        language = i18n.chosen(request.cookies.get(i18n.COOKIE), prefs.language)
        t = i18n.translator(language)
        renders = frame.renderer.stats()
        return {
            "uptime": uptime(frame.started),
            "photos": len(library),
            "orientations": library.orientation_counts(),
            "indexing": not library.probe_done.is_set(),
            "root": str(settings.photo_dir),
            "db": db.state(),
            "t": t,
            "lang": language,
            "languages": i18n.NAMES,
            "verdict": verdict(renders, t),
            "prefs": prefs.as_dict(),
            "quiet": preferences.is_quiet(*prefs.quiet_hours, datetime.now()),
            "renders": renders,
            "traffic": frame.traffic.stats(),
            "rules": rules.as_dict(),
            "settings": shown,
            "log": logs.tail(LOG_LINES),
        }

    @bp.get("/status")
    def status_page():
        """Everything the JSON endpoints below report, on one page.

        The frame runs headless on a machine across the house; answering "is it still
        up, and did anything go wrong?" used to mean an ssh session and a log file.
        """
        return render_template("status.html", tab="status", **report())

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
        """The decoders, and what never reached them: originals go out untouched."""
        return jsonify(**frame.renderer.stats(), traffic=frame.traffic.stats())

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
