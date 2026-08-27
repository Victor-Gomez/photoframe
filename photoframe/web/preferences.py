"""The settings page, and the settings behind it.

Two kinds, and the page keeps them apart: what everyone sees, which lives in photos.db,
and what this one device does, which lives in its own browser and never reaches the server.
"""

import logging

from flask import Blueprint, jsonify, render_template, request

from .. import i18n
from ..preferences import LOG_LEVELS

log = logging.getLogger(__name__)


def blueprint(frame):
    bp = Blueprint("preferences", __name__)
    prefs = frame.prefs

    @bp.get("/settings")
    def settings_page():
        language = i18n.chosen(request.cookies.get(i18n.COOKIE), prefs.language)
        t = i18n.translator(language)
        return render_template(
            "settings.html",
            t=t, lang=language, languages=i18n.NAMES, logLevels=LOG_LEVELS,
            settings=prefs.as_dict(), db=frame.db.state(),
            # Empty means this device has not asked for one and follows the frame.
            deviceLanguage=request.cookies.get(i18n.COOKIE, ""),
            # The page's own script says a few things of its own, and cannot call t().
            js_text={
                "language": language,
                "deviceLanguage": request.cookies.get(i18n.COOKIE, ""),
                "saved": t("saved"),
                "noStorage": t("device.nostorage"),
                "originals": t("images.originals"),
                "reencoded": t("images.reencoded"),
                # Handed over with its placeholders intact, for the script to fill in.
                "guess": t("device.guess", choice="{choice}", cores="{cores}", memory="{memory}"),
            },
        )

    @bp.get("/api/settings")
    def settings_read():
        """Polled by the frame, so a change to the quiet hours reaches the wall without
        anyone reloading the page."""
        response = jsonify(**prefs.as_dict())
        response.headers["Cache-Control"] = "no-store"
        return response

    @bp.post("/api/settings")
    def settings_write():
        """Only the keys sent are written. A database on loan answers 503, as writes do."""
        was = i18n.chosen(request.cookies.get(i18n.COOKIE), prefs.language)
        try:
            saved = prefs.update(request.get_json(silent=True) or {})
        except i18n.Invalid as exc:
            # In the language the page was in, not the one that was just refused.
            return jsonify(error=i18n.say(was, exc)), 400
        frame.apply_prefs()
        return jsonify(**saved)

    return bp
