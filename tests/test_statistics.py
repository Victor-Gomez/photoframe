def _seed_photos(app):
    conn = app.db.borrow()
    with app.db.lock:
        conn.execute(
            "INSERT OR REPLACE INTO photo (rel, width, height, taken, model, category, location, "
            "score_overall, score_aesthetic, score_composition, score_tech_sharpness, user_rating, is_hero, is_cull) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("Trip/Day1/beach.avif", 1600, 900, "2025-07-10T12:00:00", "ILCE-7M3", "travel", "Mallorca",
             8.2, 8.5, 8.0, 7.9, 9, 1, 0),
        )
        conn.execute(
            "INSERT OR REPLACE INTO photo (rel, width, height, taken, model, category, location, "
            "score_overall, score_aesthetic, score_composition, score_tech_sharpness, user_rating, is_hero, is_cull) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("Trip/Day1/tower.avif", 600, 900, "2025-07-10T14:00:00", "ILCE-7M4", "architecture", "Palma",
             5.4, 5.6, 5.2, 5.4, 6, 0, 0),
        )
        conn.execute(
            "INSERT OR REPLACE INTO photo (rel, width, height, taken, model, category, location, "
            "score_overall, score_aesthetic, score_composition, score_tech_sharpness, user_rating, is_hero, is_cull) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("Screenshots/shot.png", 1200, 800, "2024-03-01T09:00:00", "Pixel 10 Pro", "art", "Madrid",
             3.1, 3.0, 3.2, 3.1, 2, 0, 1),
        )
        conn.execute("INSERT INTO person (id, name) VALUES (1, 'Victor')")
        conn.execute("INSERT INTO face (rel, idx, person_id) VALUES ('Trip/Day1/beach.avif', 0, 1)")
        conn.commit()


def test_statistics_page_renders(app):
    client = app.app.test_client()
    res = client.get("/statistics")
    assert res.status_code == 200
    body = res.get_data(as_text=True)
    assert 'id="catalogFilter"' in body
    assert 'id="userRatingsChart"' in body
    assert 'id="aiScoresChart"' in body
    assert 'id="topAlbumsUserList"' in body
    assert 'id="aiSubscoresList"' in body


def test_statistics_api_all_and_filtered(app):
    _seed_photos(app)
    client = app.app.test_client()

    res = client.get("/api/statistics")
    assert res.status_code == 200
    data = res.get_json()
    assert data["databaseOpen"] is True
    assert data["summary"]["total"] == 3
    assert data["summary"]["userRated"] == 3
    assert data["summary"]["aiScored"] == 3
    assert data["summary"]["heroes"] == 1
    assert data["summary"]["culls"] == 1
    assert data["summary"]["landscape"] == 2
    assert data["summary"]["portrait"] == 1

    user_by_score = {b["score"]: b["count"] for b in data["userRatings"]}
    assert user_by_score[9] == 1
    assert user_by_score[6] == 1
    assert user_by_score[2] == 1

    ai_by_score = {b["score"]: b["count"] for b in data["aiScores"]}
    assert ai_by_score[8] == 1
    assert ai_by_score[5] == 1
    assert ai_by_score[3] == 1

    # Quality average over time + best-scored albums + people/places + subscores
    years = {y["year"]: y for y in data["years"]}
    assert years["2025"]["userAvg"] == 7.5
    assert years["2025"]["aiAvg"] == 6.8
    assert data["topAlbumsUser"][0]["catalog"] == "Trip"
    assert data["topAlbumsUser"][0]["avg"] == 7.5
    assert data["people"][0]["name"] == "Victor"
    assert len(data["places"]) == 3
    assert len(data["aiSubscores"]) == 3

    # Filtered to Trip catalog only
    res_trip = client.get("/api/statistics?catalog=Trip")
    assert res_trip.status_code == 200
    trip = res_trip.get_json()
    assert trip["catalog"] == "Trip"
    assert trip["summary"]["total"] == 2
    assert trip["summary"]["landscape"] == 1
    assert trip["summary"]["portrait"] == 1
    assert trip["topAlbumsUser"] == []
    trip_user = {b["score"]: b["count"] for b in trip["userRatings"]}
    assert trip_user[9] == 1
    assert trip_user[6] == 1
    assert trip_user[2] == 0


def test_statistics_api_when_db_released(app):
    client = app.app.test_client()
    assert client.post("/api/db/release").status_code == 200
    res = client.get("/api/statistics")
    assert res.status_code == 200
    assert res.get_json()["databaseOpen"] is False
    assert client.post("/api/db/resume").status_code == 200
