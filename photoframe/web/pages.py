"""The page itself, its assets, and the photos."""

import io
import logging
from pathlib import Path

from flask import Blueprint, abort, jsonify, render_template, request, send_file

from ..imaging import MAX_RENDER_EDGE, SOURCE_MIME

log = logging.getLogger(__name__)


def blueprint(frame):
    bp = Blueprint("pages", __name__)
    web_dir = Path(__file__).resolve().parent.parent.parent / "web"
    assets = {name: web_dir / f"frame.{name}" for name in ("css", "js", "html")}

    def asset_versions() -> dict[str, int]:
        """Modification times, used both to bust the browser cache and to spot edits."""
        versions = {}
        for name, path in assets.items():
            try:
                versions[name] = int(path.stat().st_mtime)
            except OSError:
                versions[name] = 0
        return versions

    @bp.get("/")
    def index():
        return render_template("frame.html", assets=asset_versions())

    @bp.get("/api/assets")
    def asset_list():
        """The frame polls this and reloads itself when the page, CSS or script changes on
        disk — editing the look of a wall-mounted device should not mean walking over."""
        response = jsonify(**asset_versions())
        response.headers["Cache-Control"] = "no-store"
        return response

    @bp.get("/img/<pid>")
    def img(pid: str):
        """The photo, either untouched or re-encoded to exactly the size the screen shows.

        `?w=1920&h=1080` returns a JPEG of precisely those pixels, cropped to fill them the
        way `object-fit: cover` would. Nothing is written to disk: it is decoded, scaled and
        encoded per request. A 24 MP original costs a low-powered device ~96 MB of bitmap
        to decode; the same photo at screen size about 8 MB, which is the difference
        between a frame that runs for weeks and one the browser kills.

        Without w and h the original file is sent byte for byte.
        """
        source = frame.library.path_of(pid)
        if source is None:
            abort(404)
        if not source.exists():
            # Starting from photos.db without a walk means a file can be gone while the
            # list still names it.
            frame.library.forget(pid)
            abort(404)

        width, height = request.args.get("w", type=int), request.args.get("h", type=int)
        if not width or not height:
            # Explicit mimetype: the Windows mime registry has no .webp/.avif entry and
            # would otherwise fall back to application/octet-stream.
            return send_file(
                source,
                mimetype=SOURCE_MIME[source.suffix.lower()],
                conditional=True,
                max_age=86400,
            )

        width = max(64, min(width, MAX_RENDER_EDGE))
        height = max(64, min(height, MAX_RENDER_EDGE))
        try:
            data = frame.renderer.render(source, width, height)
        except Exception:
            log.exception("could not render %s", source)
            abort(415)

        response = send_file(io.BytesIO(data), mimetype="image/jpeg")
        # Worth caching in the browser — stepping back through the history reuses it — but
        # it is never written to disk here.
        response.headers["Cache-Control"] = "private, max-age=3600"
        return response

    return bp
