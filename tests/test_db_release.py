"""Handing the database file over to another tool without restarting the frame.

sync_frame_rules.py rewrites photos.db wholesale. It used to stop the scheduled task and
start it again, which costs a restart and a reindex; releasing and resuming does the same
job while the frame keeps showing photos.
"""
import pytest


@pytest.fixture
def client(app):
    app.app.config["TESTING"] = True
    return app.app.test_client()


def test_release_closes_the_file_and_resume_takes_it_back(app, client):
    assert client.get("/api/db").get_json()["open"] is True

    released = client.post("/api/db/release").get_json()
    assert released["open"] is False
    assert released["alreadyReleased"] is False
    assert app._db is None

    before = dict(app._index)
    resumed = client.post("/api/db/resume").get_json()
    assert resumed["open"] is True
    assert app._db is not None
    # This fixture's database carries rules but no photo rows, so the reindex finds
    # nothing — and must therefore leave the live index alone rather than emptying it.
    assert app._index == before


def test_releasing_twice_is_harmless(client):
    client.post("/api/db/release")
    again = client.post("/api/db/release").get_json()
    assert again["alreadyReleased"] is True
    assert again["open"] is False
    client.post("/api/db/resume")


def test_photos_keep_being_served_while_released(app, client):
    """The whole point: the frame does not stop for maintenance."""
    pid = app.photo_id_of("Trip/Day1/beach.avif")
    client.post("/api/db/release")
    try:
        assert client.get("/api/playlist?ratio=1.7778").get_json()["ids"]
        assert client.get(f"/img/{pid}?w=64&h=64").status_code == 200
        assert client.get(f"/api/neighbors/{pid}").status_code == 200
    finally:
        client.post("/api/db/resume")


def test_the_blacklist_still_applies_while_released(app, client):
    """A rescan during a release must not quietly unhide everything.

    load_rules() used to rebuild the lists as empty when there was no database, which
    would have put every blacklisted photo back on screen.
    """
    victim = app.photo_id_of("Trip/Day1/tower.avif")
    client.post("/api/blacklist", json={"id": victim, "scope": "photo"})
    hidden = app.matcher("files")

    client.post("/api/db/release")
    try:
        app.load_rules()                      # what a rescan would trigger
        assert app.matcher("files").exact == hidden.exact
        assert app.blacklisted_file("trip/day1/tower.avif")
    finally:
        client.post("/api/db/resume")
    assert app.blacklisted_file("trip/day1/tower.avif")


def test_writes_fail_loudly_rather_than_silently(app, client):
    """Answering 200 to a favourite that was never recorded is the worst outcome."""
    pid = app.photo_id_of("Trip/Day2/pano.avif")
    client.post("/api/db/release")
    try:
        for path, body in (
            ("/api/favorite", {"id": pid, "favorite": True}),
            ("/api/blacklist", {"id": pid, "scope": "photo"}),
            ("/api/blacklist/undo", {"entry": "Trip/Day2/pano.avif", "scope": "photo"}),
        ):
            response = client.post(path, json=body)
            assert response.status_code == 503, path
            assert "error" in response.get_json()
    finally:
        client.post("/api/db/resume")


def test_the_info_panel_degrades_instead_of_failing(app, client):
    pid = app.photo_id_of("Trip/Day1/beach.avif")
    client.post("/api/db/release")
    try:
        info = client.get(f"/api/info/{pid}").get_json()
        assert info["file"] == "beach.avif"      # from the in-memory index
        assert info["databaseOpen"] is False
    finally:
        client.post("/api/db/resume")


def test_resume_picks_up_rules_written_while_it_was_away(app, client):
    """The reason the endpoint exists: another tool rewrote the file underneath."""
    import store
    client.post("/api/db/release")
    conn = store.open_db(app.DB_FILE)          # only possible because the file is free
    store.add_rule(conn, "favorite", "Trip/Day2/pano.avif")
    conn.commit()
    conn.close()

    client.post("/api/db/resume")
    assert app.is_favorite("Trip/Day2/pano.avif")
