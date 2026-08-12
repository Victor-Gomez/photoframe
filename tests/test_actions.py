"""Hiding, undoing and favouriting: everything that writes a rule into photos.db."""

import json

import pytest
from photoframe.imaging import MAX_RENDER_EDGE
from photoframe.library import photo_id_of


@pytest.fixture
def client(app):
    app.app.config["TESTING"] = True
    return app.app.test_client()


def config_of(app):
    return json.loads(app.config_file.read_text(encoding="utf-8"))


def rules_of(app, kind):
    """The blacklist/favourite rules as the database holds them."""
    import store
    with app.db.lock:
        return store.rules(app.db.borrow(), kind)


def post(client, path, **body):
    return client.post(path, json=body)


def seed_photos(app, ratios):
    """Put rows in photos.db the way scan.py would, so index_from_db has something to read.

    The test library is built on disk, but nothing walks it into the database — that is
    scan.py's job and it lives outside this project.
    """
    with app.db.lock:
        for rel, ratio in ratios.items():
            app.db.borrow().execute(
                "INSERT OR REPLACE INTO photo (rel, ratio) VALUES (?, ?)", (rel, ratio))
        app.db.borrow().commit()


def test_hiding_a_photo_writes_it_and_drops_it_from_the_library(client, app):
    pid = photo_id_of("Trip/Day1/beach.avif")
    body = post(client, "/api/blacklist", id=pid, scope="photo").get_json()

    assert body["entry"] == "Trip/Day1/beach.avif"
    assert body["removed"] == [pid]
    assert rules_of(app, "blacklist_file") == ["Trip/Day1/beach.avif"]
    assert client.get(f"/img/{pid}").status_code == 404


def test_hiding_a_folder_takes_everything_under_it(client, app):
    pid = photo_id_of("Trip/Day1/beach.avif")
    body = post(client, "/api/blacklist", id=pid, scope="folder", folder="Trip/Day1").get_json()

    assert body["entry"] == "Trip/Day1"
    assert set(body["removed"]) == {pid, photo_id_of("Trip/Day1/tower.avif")}
    assert rules_of(app, "blacklist_folder") == ["Trip/Day1"]


def test_a_folder_that_does_not_contain_the_photo_is_refused(client, app):
    pid = photo_id_of("Trip/Day1/beach.avif")
    for folder in ["Screenshots", "", "../..", "/etc"]:
        response = post(client, "/api/blacklist", id=pid, scope="folder", folder=folder)
        assert response.status_code == 400, folder
    assert rules_of(app, "blacklist_folder") == []


def test_an_unknown_scope_is_refused(client, app):
    pid = photo_id_of("wide.avif")
    assert post(client, "/api/blacklist", id=pid, scope="everything").status_code == 400


def test_an_unknown_photo_is_a_404(client):
    assert post(client, "/api/blacklist", id="0" * 16, scope="photo").status_code == 404


def test_undo_restores_the_photo_and_leaves_no_entry_behind(client, app):
    pid = photo_id_of("Trip/Day1/beach.avif")
    post(client, "/api/blacklist", id=pid, scope="photo")

    body = post(client, "/api/blacklist/undo", entry="Trip/Day1/beach.avif", scope="photo").get_json()
    assert body["id"] == pid
    assert rules_of(app, "blacklist_file") == []
    assert client.get(f"/img/{pid}").status_code == 200
    assert app.library.ratio_of(pid) == pytest.approx(1.78, abs=0.01)  # re-probed, not left blank


def test_undo_of_a_folder_rebuilds_the_index(client, app):
    pid = photo_id_of("Trip/Day1/beach.avif")
    post(client, "/api/blacklist", id=pid, scope="folder", folder="Trip/Day1")
    post(client, "/api/blacklist/undo", entry="Trip/Day1", scope="folder")

    assert rules_of(app, "blacklist_folder") == []
    assert client.get(f"/img/{pid}").status_code == 200


def test_favouriting_by_name_and_removing_it_again(client, app):
    pid = photo_id_of("wide.avif")

    assert post(client, "/api/favorite", id=pid, favorite=True).get_json()["coveredBy"] == "name"
    assert rules_of(app, "favorite") == ["wide.avif"]

    assert post(client, "/api/favorite", id=pid, favorite=False).get_json()["favorite"] is False
    assert rules_of(app, "favorite") == []
    assert rules_of(app, "unfavorite") == []  # nothing left behind


def test_unfavouriting_a_photo_a_tag_covers_records_an_exception(make_app):
    app = make_app({"favorites": ["tag:album_japan"]})
    client = app.app.test_client()
    pid = photo_id_of("Trip/Day1/tower.avif")
    app.library.set_tags(pid, ("album_japan",))

    body = post(client, "/api/favorite", id=pid, favorite=False).get_json()
    assert body["coveredBy"] == "rule"
    assert rules_of(app, "unfavorite") == ["Trip/Day1/tower.avif"]
    assert app.rules.is_favorite("Trip/Day1/tower.avif", pid) is False


def test_favouriting_it_again_drops_the_exception_rather_than_adding_a_duplicate(make_app):
    app = make_app({"favorites": ["tag:album_japan"], "unfavorites": ["Trip/Day1/tower.avif"]})
    client = app.app.test_client()
    pid = photo_id_of("Trip/Day1/tower.avif")
    app.library.set_tags(pid, ("album_japan",))

    post(client, "/api/favorite", id=pid, favorite=True)
    assert rules_of(app, "unfavorite") == []
    assert rules_of(app, "favorite") == ["tag:album_japan"]  # the rule alone still covers it
    assert app.rules.is_favorite("Trip/Day1/tower.avif", pid) is True


def test_favouriting_never_rewrites_config_json(client, app):
    """Settings and rules are separate now: config.json is only ever read by the frame,
    so a hand-edited setting cannot be lost to a tap on the device."""
    before = app.config_file.read_bytes()
    post(client, "/api/favorite", id=photo_id_of("wide.avif"), favorite=True)
    assert app.config_file.read_bytes() == before
    assert rules_of(app, "favorite") == ["wide.avif"]


def test_rendering_returns_exactly_the_requested_size_as_jpeg(client, app):
    from io import BytesIO

    from PIL import Image

    pid = photo_id_of("Trip/Day1/beach.avif")
    response = client.get(f"/img/{pid}?w=320&h=200")
    assert response.mimetype == "image/jpeg"
    assert Image.open(BytesIO(response.data)).size == (320, 200)


def test_rendering_never_touches_the_original(client, app):
    original = app.settings.photo_dir / "Trip/Day1/beach.avif"
    before = original.stat().st_mtime_ns, original.read_bytes()

    pid = photo_id_of("Trip/Day1/beach.avif")
    client.get(f"/img/{pid}?w=320&h=200")
    client.get(f"/img/{pid}")

    assert (original.stat().st_mtime_ns, original.read_bytes()) == before


def test_without_a_size_the_original_is_served_byte_for_byte(client, app):
    pid = photo_id_of("Trip/Day1/beach.avif")
    response = client.get(f"/img/{pid}")
    assert response.data == (app.settings.photo_dir / "Trip/Day1/beach.avif").read_bytes()


def test_an_absurd_size_is_clamped_rather_than_allocated(client, app):
    from io import BytesIO

    from PIL import Image

    pid = photo_id_of("Trip/Day1/beach.avif")
    response = client.get(f"/img/{pid}?w=99999&h=10")
    assert Image.open(BytesIO(response.data)).size == (MAX_RENDER_EDGE, 64)


def test_a_token_protected_frame_refuses_anonymous_requests(make_app):
    app = make_app({"frameToken": "sesame"})
    client = app.app.test_client()

    assert client.get("/api/playlist").status_code == 403
    assert client.get("/api/playlist?k=sesame").status_code == 200


def test_hiding_invalidates_passes_a_client_is_still_paging_through(client, app):
    """A pass built before the hide must not keep handing out the hidden photos.

    The frame pages through a shuffled pass by token. Without this, a hide only affects
    the pages not yet fetched from a *new* pass — the token it is currently walking still
    yields the hidden ids, and the browser may even have them in its own cache, so they
    reappear minutes after being hidden.
    """
    first = client.get("/api/playlist?limit=1").get_json()
    token, total = first["token"], first["total"]

    pid = photo_id_of("Trip/Day1/beach.avif")
    hidden = set(
        client.post("/api/blacklist", json={"id": pid, "scope": "folder", "folder": "Trip/Day1"})
        .get_json()["removed"]
    )

    rest = client.get(f"/api/playlist?token={token}&offset=0&limit={total}").get_json()
    assert set(rest["ids"]).isdisjoint(hidden)


def test_photo_info_carries_the_path_as_it_exists_on_this_machine(client, app):
    pid = photo_id_of("Trip/Day1/beach.avif")
    body = client.get(f"/api/photo/{pid}").get_json()

    assert body["folder"] == "Trip/Day1"
    assert body["file"] == "beach.avif"
    assert body["fullPath"] == str(app.settings.photo_dir / "Trip" / "Day1" / "beach.avif")


def test_a_broken_avifdec_falls_back_to_pillow_rather_than_failing(make_app):
    app = make_app({"avifdec": "no-such-binary.exe", "avifdecShare": 1.0})
    client = app.app.test_client()
    from io import BytesIO

    from PIL import Image

    pid = photo_id_of("Trip/Day1/beach.avif")
    response = client.get(f"/img/{pid}?w=320&h=200")
    assert response.status_code == 200
    assert Image.open(BytesIO(response.data)).size == (320, 200)
    assert app.renderer.stats()["pillow"]["renders"]  # recorded as a Pillow render, not an avifdec one


def test_render_stats_reports_each_decoder(client, app):
    pid = photo_id_of("Trip/Day1/beach.avif")
    client.get(f"/img/{pid}?w=320&h=200")

    body = client.get("/api/render-stats").get_json()
    assert body["pillow"]["renders"] >= 1
    assert body["pillow"]["medianMs"] >= 0
    assert body["avifdec"]["renders"] == 0  # not configured in the test library
    assert "not enough renders yet" in body["verdict"]


def test_the_database_can_stand_in_for_a_walk(make_app):
    """photos.db is the only startup path: scan.py has already recorded every photo with
    its ratio, so the frame opens the library without reading a single file header.
    Walking the whole library on every start once cost 25 minutes of downtime."""
    app = make_app()
    seed_photos(app, {"Trip/Day1/beach.avif": 1.5, "Trip/Day2/pano.avif": 2.0})

    assert app.library.load() == len(app.library)
    pid = photo_id_of("Trip/Day1/beach.avif")
    assert pid in dict(app.library.items())
    assert app.library.ratio_of(pid) == 1.5          # taken from the database, not probed
    assert app.library.probe_done.is_set()        # and nothing is left to read off the disk


def test_a_photo_deleted_from_disk_is_dropped_when_it_is_next_wanted(app):
    """The failsafe for starting from the database without a walk: notice on use, forget,
    and move on rather than showing an error."""
    client = app.app.test_client()
    pid = photo_id_of("Trip/Day1/beach.avif")
    (app.settings.photo_dir / "Trip/Day1/beach.avif").unlink()

    assert client.get(f"/img/{pid}").status_code == 404
    assert pid not in dict(app.library.items())          # forgotten, not merely refused


def test_the_blacklist_still_applies_when_starting_from_the_database(make_app):
    """The blacklist lives beside the photo list in photos.db but is applied again on the
    way in, so editing it takes effect on the next restart without the database being
    touched at all."""
    app = make_app({"blacklist": {"folders": ["Trip/Day1"], "files": []}})
    seed_photos(app, {"Trip/Day1/beach.avif": 1.5, "Trip/Day2/pano.avif": 2.0})

    app.library.load()
    assert photo_id_of("Trip/Day1/beach.avif") not in dict(app.library.items())
    assert photo_id_of("Trip/Day2/pano.avif") in dict(app.library.items())


def test_api_config_reports_the_rules_the_frame_is_enforcing(client, app):
    """config.json holds no rules any more, so this has to come from photos.db.

    load_rules() used to fill only the matchers, leaving _config describing the file —
    which meant /api/config reported whatever stale lists happened to be in it, and the
    favourite count came from the same place.
    """
    shown = client.get("/api/config").get_json()
    assert sorted(shown["blacklist"]["folders"]) == sorted(rules_of(app, "blacklist_folder"))
    assert sorted(shown["blacklist"]["files"]) == sorted(rules_of(app, "blacklist_file"))
    assert sorted(shown["favorites"]) == sorted(rules_of(app, "favorite"))
    assert sorted(shown["unfavorites"]) == sorted(rules_of(app, "unfavorite"))


def test_the_favourite_count_follows_the_database(client, app):
    pid = photo_id_of("Trip/Day2/pano.avif")
    before = len(rules_of(app, "favorite"))
    data = post(client, "/api/favorite", id=pid, favorite=True).get_json()
    assert data["count"] == before + 1 == len(rules_of(app, "favorite"))
