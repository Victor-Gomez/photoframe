"""Library statistics: score distributions, trends, albums, cameras, people, and places."""

import logging
import sqlite3

from flask import Blueprint, jsonify, render_template, request

from .. import i18n

log = logging.getLogger(__name__)

CAMERA_NAMES = {
    "ILCE-7M3": "α7 III",
    "ILCE-7M4": "α7 IV",
    "ILCE-6700": "α6700",
    "ILCA-68": "α68",
    "2107113SG": "11T Pro",
    "M2012K11AG": "POCO F3",
}


def _camera_label(model: str) -> str:
    if model in CAMERA_NAMES:
        return CAMERA_NAMES[model]
    if model.startswith("ILCE-"):
        return "α" + model[5:]
    return model


def _catalogs(library) -> list[str]:
    return sorted(
        {rel.partition("/")[0] for rel in library.rel_true_map().values() if "/" in rel},
        key=str.casefold,
    )


def _favorites_count(frame, catalog: str) -> int:
    favorite = frame.rules.favorite_check()
    prefix = f"{catalog}/" if catalog else ""
    count = 0
    for pid, rel in frame.library.rel_true_map().items():
        if prefix and not rel.startswith(prefix):
            continue
        if favorite(rel.lower(), pid):
            count += 1
    return count


def _round2(val) -> float | None:
    return round(float(val), 2) if val is not None else None


def compute_statistics(frame, catalog: str = "") -> dict:
    """Aggregate score distributions and library breakdowns, optionally for one catalog."""
    catalog = (catalog or "").strip()
    catalogs = _catalogs(frame.library)
    conn = frame.db.borrow()
    if conn is None:
        return {
            "databaseOpen": False,
            "catalog": catalog,
            "catalogs": catalogs,
        }

    where = "WHERE substr(rel, 1, instr(rel, '/') - 1) = ?" if catalog else ""
    and_where = f"{where} AND " if where else "WHERE "
    params = (catalog,) if catalog else ()

    def q_all(sql: str):
        with frame.db.lock:
            return conn.execute(sql, params).fetchall()

    def q_one(sql: str):
        with frame.db.lock:
            return conn.execute(sql, params).fetchone()

    try:
        summary_row = q_one(
            f"""
            SELECT
                COUNT(*) AS total,
                COUNT(user_rating) AS user_rated,
                AVG(user_rating) AS user_avg,
                COUNT(score_overall) AS ai_scored,
                AVG(score_overall) AS ai_avg,
                SUM(CASE WHEN COALESCE(is_hero, 0) != 0 THEN 1 ELSE 0 END) AS heroes,
                SUM(CASE WHEN COALESCE(is_cull, 0) != 0 THEN 1 ELSE 0 END) AS culls,
                SUM(CASE WHEN width IS NOT NULL AND height IS NOT NULL AND width >= height THEN 1 ELSE 0 END) AS landscape,
                SUM(CASE WHEN width IS NOT NULL AND height IS NOT NULL AND width < height THEN 1 ELSE 0 END) AS portrait
            FROM photo
            {where}
            """
        )

        user_buckets = {i: 0 for i in range(11)}
        for row in q_all(
            f"""
            SELECT CAST(user_rating AS INTEGER) AS score, COUNT(*) AS n
            FROM photo
            {and_where}user_rating IS NOT NULL
            GROUP BY 1
            """
        ):
            s = max(0, min(10, int(row["score"])))
            user_buckets[s] += int(row["n"])

        ai_buckets = {i: 0 for i in range(11)}
        for row in q_all(
            f"""
            SELECT CAST(ROUND(score_overall) AS INTEGER) AS score, COUNT(*) AS n
            FROM photo
            {and_where}score_overall IS NOT NULL
            GROUP BY 1
            """
        ):
            s = max(0, min(10, int(row["score"])))
            ai_buckets[s] += int(row["n"])

        sub_row = q_one(
            f"""
            SELECT
                AVG(score_aesthetic) AS aesthetic,
                AVG(score_composition) AS composition,
                AVG(score_tech_sharpness) AS sharpness,
                AVG(CASE WHEN score_eye_sharpness > 0 THEN score_eye_sharpness END) AS eyes,
                AVG(CASE WHEN score_face_quality > 0 THEN score_face_quality END) AS faces
            FROM photo
            {and_where}score_overall IS NOT NULL
            """
        )
        ai_subscores = [
            {"key": k, "avg": _round2(sub_row[k])}
            for k in ("aesthetic", "composition", "sharpness", "eyes", "faces")
            if sub_row is not None and sub_row[k] is not None
        ]

        categories = [
            {"name": row["category"], "count": int(row["n"])}
            for row in q_all(
                f"""
                SELECT category, COUNT(*) AS n
                FROM photo
                {and_where}category IS NOT NULL AND category != ''
                GROUP BY category
                ORDER BY n DESC, category ASC
                LIMIT 12
                """
            )
        ]

        cameras = [
            {
                "name": row["model"],
                "label": _camera_label(row["model"]),
                "count": int(row["n"]),
                "userAvg": _round2(row["user_avg"]),
                "aiAvg": _round2(row["ai_avg"]),
            }
            for row in q_all(
                f"""
                SELECT
                    model,
                    COUNT(*) AS n,
                    AVG(user_rating) AS user_avg,
                    AVG(score_overall) AS ai_avg
                FROM photo
                {and_where}model IS NOT NULL AND model != ''
                GROUP BY model
                ORDER BY n DESC, model ASC
                LIMIT 10
                """
            )
        ]

        years = [
            {
                "year": row["yr"],
                "count": int(row["n"]),
                "userAvg": _round2(row["user_avg"]),
                "aiAvg": _round2(row["ai_avg"]),
            }
            for row in q_all(
                f"""
                SELECT
                    substr(taken, 1, 4) AS yr,
                    COUNT(*) AS n,
                    AVG(user_rating) AS user_avg,
                    AVG(score_overall) AS ai_avg
                FROM photo
                {and_where}taken IS NOT NULL AND length(taken) >= 4
                GROUP BY yr
                ORDER BY yr DESC
                LIMIT 15
                """
            )
        ]

        places = [
            {"name": row["location"], "count": int(row["n"])}
            for row in q_all(
                f"""
                SELECT location, COUNT(*) AS n
                FROM photo
                {and_where}location IS NOT NULL AND location != ''
                GROUP BY location
                ORDER BY n DESC, location ASC
                LIMIT 10
                """
            )
        ]

        ph_where = "WHERE substr(ph.rel, 1, instr(ph.rel, '/') - 1) = ?" if catalog else ""
        ph_and = f"{ph_where} AND " if ph_where else "WHERE "
        people = [
            {"name": row["name"], "count": int(row["n"])}
            for row in q_all(
                f"""
                SELECT p.name AS name, COUNT(DISTINCT f.rel) AS n
                FROM face f
                LEFT JOIN cluster c ON c.id = f.cluster_id
                JOIN person p ON p.id = COALESCE(f.person_id, c.person_id)
                JOIN photo ph ON ph.rel = f.rel
                {ph_and}p.name IS NOT NULL AND p.name != ''
                GROUP BY p.id, p.name
                ORDER BY n DESC, p.name ASC
                LIMIT 10
                """
            )
        ]

        top_albums_user: list[dict] = []
        top_albums_ai: list[dict] = []
        if not catalog:
            user_rated_total = int(summary_row["user_rated"] or 0)
            ai_scored_total = int(summary_row["ai_scored"] or 0)
            min_user = 10 if user_rated_total >= 50 else 1
            min_ai = 10 if ai_scored_total >= 50 else 1

            top_albums_user = [
                {"catalog": row["cat"], "count": int(row["n"]), "avg": _round2(row["avg_score"])}
                for row in q_all(
                    f"""
                    SELECT substr(rel, 1, instr(rel, '/') - 1) AS cat,
                           COUNT(user_rating) AS n,
                           AVG(user_rating) AS avg_score
                    FROM photo
                    WHERE user_rating IS NOT NULL AND instr(rel, '/') > 0
                    GROUP BY cat
                    HAVING n >= {min_user}
                    ORDER BY avg_score DESC, n DESC
                    LIMIT 10
                    """
                )
            ]
            top_albums_ai = [
                {"catalog": row["cat"], "count": int(row["n"]), "avg": _round2(row["avg_score"])}
                for row in q_all(
                    f"""
                    SELECT substr(rel, 1, instr(rel, '/') - 1) AS cat,
                           COUNT(score_overall) AS n,
                           AVG(score_overall) AS avg_score
                    FROM photo
                    WHERE score_overall IS NOT NULL AND instr(rel, '/') > 0
                    GROUP BY cat
                    HAVING n >= {min_ai}
                    ORDER BY avg_score DESC, n DESC
                    LIMIT 10
                    """
                )
            ]
    except sqlite3.Error:
        log.exception("could not compute statistics for catalog %r", catalog)
        return {
            "databaseOpen": False,
            "catalog": catalog,
            "catalogs": catalogs,
        }

    total = int(summary_row["total"] or 0)
    return {
        "databaseOpen": True,
        "catalog": catalog,
        "catalogs": catalogs,
        "summary": {
            "total": total,
            "userRated": int(summary_row["user_rated"] or 0),
            "userAvg": _round2(summary_row["user_avg"]),
            "aiScored": int(summary_row["ai_scored"] or 0),
            "aiAvg": _round2(summary_row["ai_avg"]),
            "favorites": _favorites_count(frame, catalog),
            "heroes": int(summary_row["heroes"] or 0),
            "culls": int(summary_row["culls"] or 0),
            "landscape": int(summary_row["landscape"] or 0),
            "portrait": int(summary_row["portrait"] or 0),
        },
        "userRatings": [{"score": s, "count": user_buckets[s]} for s in range(11)],
        "aiScores": [{"score": s, "count": ai_buckets[s]} for s in range(11)],
        "aiSubscores": ai_subscores,
        "categories": categories,
        "cameras": cameras,
        "years": years,
        "places": places,
        "people": people,
        "topAlbumsUser": top_albums_user,
        "topAlbumsAi": top_albums_ai,
    }


def blueprint(frame):
    bp = Blueprint("statistics", __name__)

    @bp.get("/statistics")
    def statistics_page():
        language = i18n.chosen(request.cookies.get(i18n.COOKIE), frame.prefs.language)
        t = i18n.translator(language)
        catalog = request.args.get("catalog", "").strip()
        stats = compute_statistics(frame, catalog)
        return render_template(
            "statistics.html",
            tab="statistics",
            t=t,
            lang=language,
            stats=stats,
            js_text={
                "allCatalogs": t("stats.allCatalogs"),
                "noData": t("stats.noData"),
                "photos": t("stats.photosUnit"),
                "landscape": t("row.landscape"),
                "portrait": t("row.portrait"),
                "dbBusy": t("db.busy"),
                "avg": t("stats.avg"),
                "ratedOf": t("stats.ofTotal"),
                "scoreLabel": t("stats.scoreLabel"),
                "sub": {
                    "aesthetic": t("stats.sub.aesthetic"),
                    "composition": t("stats.sub.composition"),
                    "sharpness": t("stats.sub.sharpness"),
                    "eyes": t("stats.sub.eyes"),
                    "faces": t("stats.sub.faces"),
                },
            },
        )

    @bp.get("/api/statistics")
    def statistics_api():
        catalog = request.args.get("catalog", "").strip()
        response = jsonify(compute_statistics(frame, catalog))
        response.headers["Cache-Control"] = "no-store"
        return response

    return bp
