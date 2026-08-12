"""The shuffled pass over the library that the slideshow walks."""

import math
import random
import secrets

from flask import Blueprint, jsonify, request

from ..library import ORIENTATIONS, orientation_from

PAGE_DEFAULT = 300


def weighted_shuffle(ids: list[str], favorites: set[str], weight: int) -> list[str]:
    """Shuffle a pass in which favourites appear `weight` times each.

    Cutting the pass into `weight` segments and giving each segment one copy of every
    favourite keeps the odds right without ever putting two copies close together: a
    favourite turns up about once per segment, not twice in a row.
    """
    plain = [pid for pid in ids if pid not in favorites]
    starred = [pid for pid in ids if pid in favorites]
    if weight <= 1 or not starred:
        random.shuffle(ids)
        return ids

    random.shuffle(plain)
    segments: list[list[str]] = [[] for _ in range(weight)]
    for position, pid in enumerate(plain):
        segments[position % weight].append(pid)
    for segment in segments:
        segment.extend(starred)
        random.shuffle(segment)
    return [pid for segment in segments for pid in segment]


def blueprint(frame):
    bp = Blueprint("playlist", __name__)
    library, rules, settings = frame.library, frame.rules, frame.settings

    def page_of(token, ids, offset, limit, **extra):
        chunk = ids[offset:offset + limit] if limit else ids[offset:]
        return jsonify(
            token=token,
            total=len(ids),
            offset=offset,
            count=len(chunk),
            ids=chunk,
            favoriteWeight=settings.favorite_weight,
            slideSeconds=settings.slide_seconds,
            indexing=not library.probe_done.is_set(),
            **extra,
        )

    @bp.get("/api/playlist")
    def playlist():
        """A full shuffled pass, so nothing repeats until everything has shown.

        `?ratio=1.78` — the client's own width/height — is read only for its orientation: a
        landscape screen gets landscape photos, a portrait one portrait, and anything close
        to square belongs to both. `?orientation=landscape|portrait` says the same directly.
        Neither means the whole library.

        It used to match a band around the screen's exact ratio, which sorted the library
        by the shape of the camera that took each photo — 3:2 from the camera, 16:9 from
        the phone — a distinction nobody wanted. `object-fit: cover` crops the difference.

        Favourites are not a separate mode: they simply appear `favoriteWeight` times in
        the pass, so they come round that much more often than everything else.
        """
        limit = request.args.get("limit", type=int)
        limit = PAGE_DEFAULT if limit is None else max(0, limit)

        # Paging through a pass already built: no reshuffle, no rebuild, just a slice.
        token = request.args.get("token", "")
        if token:
            existing = library.passes.get(token)
            if existing is not None:
                offset = max(0, request.args.get("offset", type=int) or 0)
                return page_of(token, existing, offset, limit, photos=len(existing))

        want = request.args.get("orientation", "").lower()
        try:
            screen = float(request.args.get("ratio", 0))
            # "nan" and "inf" parse happily as floats and a negative is meaningless; all of
            # them mean "no ratio given" rather than a filter that silently does nothing.
            if not math.isfinite(screen) or screen <= 0:
                screen = 0.0
        except ValueError:
            screen = 0.0

        matched_on = "none"
        if screen > 0:
            # Orientation, not a band around the screen's exact ratio. A screen is either
            # landscape or portrait, and so is a photo; matching more finely than that only
            # sorts the library by how the camera happened to be shaped.
            want = want if want in ORIENTATIONS else orientation_from(screen)
            items = library.matching(want)
            matched_on = "orientation"
        elif want in ORIENTATIONS:
            # Asked for by name rather than by a screen's shape, so it is taken literally:
            # no near-square photos folded in.
            items = library.matching(want, squares=False)
            matched_on = "orientation"
        else:
            items = library.items()

        # The orientation filter reads the aspect index, which is built in the background
        # when the database gave nothing — so for the first minute after such a restart
        # every filter matches nothing and the frame is told the library is empty. Showing
        # unfiltered photos until it catches up beats showing "no photos found".
        if not items and not library.probe_done.is_set():
            items = library.items()
            matched_on = "nothing yet (still indexing)"

        ids = [pid for pid, _ in items]
        favorite = rules.favorite_check()   # one snapshot for the whole pass
        relatives = library.rel_lower_map()
        favorites = {pid for pid in ids if favorite(relatives.get(pid, ""), pid)}
        ids = weighted_shuffle(ids, favorites, settings.favorite_weight)

        token = secrets.token_urlsafe(9)
        library.passes.add(token, ids)
        return page_of(
            token, ids, offset=0, limit=limit,
            photos=len(items),
            favorites=len(favorites),
            ratio=screen or None,
            matchedOn=matched_on,
            orientation=want if want in ORIENTATIONS else "any",
        )

    return bp
