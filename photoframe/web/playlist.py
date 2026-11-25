"""The shuffled pass over the library that the slideshow walks."""

import math
import random
import secrets

from flask import Blueprint, jsonify, request

from ..library import ORIENTATIONS, orientation_from
from ..preferences import device_id_from

PAGE_DEFAULT = 300
DEFAULT_RATING_WEIGHT = 5
MAX_RATING_WEIGHT = 10
MAX_SEGMENTS = MAX_RATING_WEIGHT + 1


def weighted_shuffle(
    ids: list[str],
    ratings: dict[str, int | None],
    enabled: bool,
    favorites: set[str] | None = None,
) -> list[str]:
    """Shuffle a pass where each rating point gives an image one raffle ticket (+1 if favourite).

    Unrated images default to 5 tickets; 0-rated non-favourite images get 0 tickets.
    Spreading a photo's tickets across 11 segments avoids adjacent duplicates.
    """
    if not enabled:
        random.shuffle(ids)
        return ids

    n_segments = MAX_SEGMENTS if favorites else MAX_RATING_WEIGHT
    segments: list[list[str]] = [[] for _ in range(n_segments)]
    for pid in ids:
        raw = ratings.get(pid)
        base = DEFAULT_RATING_WEIGHT if raw is None else max(0, min(MAX_RATING_WEIGHT, int(raw)))
        weight = base + (1 if favorites and pid in favorites else 0)
        if weight == 0:
            continue
        start = random.randrange(n_segments)
        for k in range(weight):
            segments[(start + (k * n_segments) // weight) % n_segments].append(pid)

    for segment in segments:
        random.shuffle(segment)
    return [pid for segment in segments for pid in segment]


def blueprint(frame):
    bp = Blueprint("playlist", __name__)
    library, rules, prefs = frame.library, frame.rules, frame.prefs

    def page_of(token, ids, offset, limit, dev_prefs, **extra):
        chunk = ids[offset:offset + limit] if limit else ids[offset:]
        return jsonify(
            token=token,
            total=len(ids),
            offset=offset,
            count=len(chunk),
            ids=chunk,
            weightByRating=dev_prefs["weightByRating"],
            slideSeconds=dev_prefs["slideSeconds"],
            indexing=not library.probe_done.is_set(),
            **extra,
        )

    def filtered_ids(
        dev_prefs: dict, screen: float, want: str = "",
    ) -> tuple[list[str], dict[str, int | None], dict[str, str], str, str]:
        ofilter = dev_prefs["orientationFilter"]
        matched_on = "none"
        target: str | None = None
        squares = True
        if want in ORIENTATIONS:
            # Asked for by name, so taken literally: no near-square photos folded in.
            target = want
            squares = False
            matched_on = "orientation"
        elif ofilter == "any":
            want = "any"
        elif ofilter in ORIENTATIONS:
            target = want = ofilter
            squares = False
            matched_on = "orientation"
        elif screen > 0:
            # Orientation, not a band around the exact ratio: matching more finely just
            # sorts the library by the shape of the camera that took each photo.
            target = want = orientation_from(screen)
            matched_on = "orientation"

        ids, ratings, relatives, fell_back = library.filtered_ids(
            target,
            squares=squares,
            folder_filter=dev_prefs["folderFilter"],
            rating_filter=dev_prefs["ratingFilter"],
            threshold_enabled=dev_prefs["ratingThresholdEnabled"],
            threshold=dev_prefs["ratingThreshold"],
            fallback_all=True,
        )
        if fell_back:
            matched_on = "nothing yet (still indexing)"
        return ids, ratings, relatives, want, matched_on

    def parse_screen() -> float:
        try:
            screen = float(request.args.get("ratio", 0))
            # "nan" and "inf" parse happily as floats and a negative is meaningless; all of
            # them mean "no ratio given" rather than a filter that silently does nothing.
            return screen if math.isfinite(screen) and screen > 0 else 0.0
        except ValueError:
            return 0.0

    @bp.get("/api/playlist/count")
    def playlist_count():
        dev_prefs = prefs.for_device(device_id_from(request))
        ids, _, _, _, _ = filtered_ids(dev_prefs, parse_screen())
        return jsonify(count=len(ids))

    @bp.get("/api/playlist")
    def playlist():
        """A full shuffled pass, so nothing repeats until everything has shown.

        `?ratio=1.78` — the client's own width/height — is read only for its orientation.
        `?orientation=landscape|portrait` says the same directly. Neither means the whole
        library.
        """
        dev_prefs = prefs.for_device(device_id_from(request))
        limit = request.args.get("limit", type=int)
        limit = PAGE_DEFAULT if limit is None else max(0, limit)

        # Paging through a pass already built: no reshuffle, no rebuild, just a slice.
        token = request.args.get("token", "")
        if token:
            existing = library.passes.get(token)
            if existing is None:
                return jsonify(error="playlist expired"), 404
            offset = max(0, request.args.get("offset", type=int) or 0)
            return page_of(token, existing, offset, limit, dev_prefs, photos=len(existing))

        want = request.args.get("orientation", "").lower()
        screen = parse_screen()
        ids, ratings, relatives, want, matched_on = filtered_ids(dev_prefs, screen, want)
        ofilter = dev_prefs["orientationFilter"]
        rfilter = dev_prefs["ratingFilter"]

        favorite = rules.favorite_check()   # one snapshot for the whole pass
        favorites = {pid for pid in ids if favorite(relatives.get(pid, ""), pid)}
        ids = weighted_shuffle(ids, ratings, dev_prefs["weightByRating"], favorites)

        token = secrets.token_urlsafe(9)
        library.passes.add(token, ids)
        return page_of(
            token, ids, offset=0, limit=limit, dev_prefs=dev_prefs,
            photos=len(ids),
            favorites=len(favorites),
            ratingFilter=rfilter,
            ratingThresholdEnabled=dev_prefs["ratingThresholdEnabled"],
            ratingThreshold=dev_prefs["ratingThreshold"],
            folderFilter=dev_prefs["folderFilter"],
            orientationFilter=ofilter,
            ratio=screen or None,
            matchedOn=matched_on,
            orientation=want if want in ORIENTATIONS else "any",
        )

    return bp
