"""The HTTP surface. One blueprint per group of endpoints, each given what it needs.

web/ is both the template folder and the static root: everything in it is public, and
everything outside it is not.
"""

import secrets
from pathlib import Path

from flask import Flask, abort, jsonify, request

from ..database import DatabaseUnavailable
from ..frame import Frame
from . import admin, curation, pages, photos, playlist

WEB_DIR = Path(__file__).resolve().parent.parent.parent / "web"


def create_app(frame: Frame) -> Flask:
    app = Flask(
        __name__,
        template_folder=str(WEB_DIR),
        static_folder=str(WEB_DIR),
        static_url_path="/static",
    )
    # Read from disk per request, so editing them needs no restart — and the frame
    # notices too, see /api/assets.
    app.config["TEMPLATES_AUTO_RELOAD"] = True
    app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0   # revalidate rather than serve a stale asset
    app.jinja_env.auto_reload = True
    app.extensions["frame"] = frame

    token = frame.settings.token

    @app.before_request
    def require_token():
        if not token:
            return None
        supplied = request.args.get("k") or request.cookies.get("frame_token") or ""
        if secrets.compare_digest(supplied, token):
            return None
        abort(403)

    @app.after_request
    def persist_token(response):
        if token and request.args.get("k"):
            response.set_cookie(
                "frame_token", token, max_age=60 * 60 * 24 * 365, samesite="Lax")
        return response

    @app.errorhandler(DatabaseUnavailable)
    def database_unavailable(_):
        """Every rule write funnels through Rules.add/remove, so one handler covers them.

        503 rather than a silent success: what you starred while the database was on loan,
        you know was not recorded.
        """
        return jsonify(
            error="la base de datos está en mantenimiento; inténtalo en un momento"), 503

    for module in (pages, playlist, photos, curation, admin):
        app.register_blueprint(module.blueprint(frame))
    return app
