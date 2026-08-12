"""The neighbours endpoint behind the gallery grid, and the in-memory render cache."""
import pytest
from photoframe.imaging import RenderCache
from photoframe.library import photo_id_of
from photoframe.web.photos import natural_key


@pytest.fixture
def client(app):
    app.app.config["TESTING"] = True
    return app.app.test_client()


def ids_of(payload):
    return [photo["id"] for photo in payload["photos"]]


def files_of(payload):
    return [photo["file"] for photo in payload["photos"]]


def test_neighbours_are_the_same_folder_in_filename_order(app, client):
    pid = photo_id_of("Trip/Day1/beach.avif")
    rel = app.library.rel_of(pid)
    folder = rel.rpartition("/")[0]

    payload = client.get(f"/api/neighbors/{pid}").get_json()

    assert payload["folder"] == folder
    assert pid in ids_of(payload)
    # Every photo returned lives in the same folder as the one asked about.
    for other in ids_of(payload):
        assert app.library.rel_of(other).rpartition("/")[0] == folder
    assert files_of(payload) == sorted(files_of(payload), key=natural_key)


def test_exactly_one_photo_is_marked_current(app, client):
    pid = photo_id_of("Trip/Day1/beach.avif")
    payload = client.get(f"/api/neighbors/{pid}").get_json()
    # `current` and `favorite` are only present when true — the payload carries one entry
    # per photo and the largest folder here has over six thousand.
    current = [photo for photo in payload["photos"] if photo.get("current")]
    assert [photo["id"] for photo in current] == [pid]
    assert "entry" not in payload["photos"][0]  # rebuilt from the folder, not sent twice


def test_span_bounds_the_result(app, client):
    pid = photo_id_of("Trip/Day1/beach.avif")
    payload = client.get(f"/api/neighbors/{pid}?span=1").get_json()
    assert len(payload["photos"]) <= 3  # itself plus one either side


def test_unknown_photo_is_404(client):
    assert client.get("/api/neighbors/nosuchphoto").status_code == 404


def test_blacklisted_photos_never_appear(app, client):
    pid = photo_id_of("Trip/Day1/beach.avif")
    folder = app.library.rel_of(pid).rpartition("/")[0]
    victim = photo_id_of("Trip/Day1/tower.avif")
    assert victim in ids_of(client.get(f"/api/neighbors/{pid}").get_json())
    assert client.post("/api/blacklist", json={"id": victim, "scope": "photo"}).status_code == 200

    after = ids_of(client.get(f"/api/neighbors/{pid}").get_json())
    assert victim not in after
    assert app.library.rel_of(pid).rpartition("/")[0] == folder  # unrelated photos stay put


def test_natural_order_puts_9_before_10(app):
    names = ["DSC_10.avif", "DSC_9.avif", "DSC_100.avif"]
    assert sorted(names, key=natural_key) == ["DSC_9.avif", "DSC_10.avif", "DSC_100.avif"]


# ---- the render cache -------------------------------------------------------

def test_second_render_of_the_same_photo_is_a_cache_hit(app, client):
    pid = photo_id_of("Trip/Day1/beach.avif")
    before = client.get("/api/render-stats").get_json()["cache"]["hits"]

    first = client.get(f"/img/{pid}?w=320&h=240")
    second = client.get(f"/img/{pid}?w=320&h=240")

    assert first.status_code == second.status_code == 200
    assert first.data == second.data
    after = client.get("/api/render-stats").get_json()["cache"]
    assert after["hits"] > before
    assert after["entries"] >= 1


def test_a_different_size_is_a_different_entry(app, client):
    pid = photo_id_of("Trip/Day1/beach.avif")
    client.get(f"/img/{pid}?w=320&h=240")
    entries = client.get("/api/render-stats").get_json()["cache"]["entries"]
    client.get(f"/img/{pid}?w=160&h=120")
    assert client.get("/api/render-stats").get_json()["cache"]["entries"] == entries + 1


def test_a_changed_file_is_not_served_from_the_cache(app, client, tmp_path):
    """The key carries the file's mtime and size, so a synced-over photo re-renders."""
    pid = photo_id_of("Trip/Day1/beach.avif")
    source = app.library.path_of(pid)
    first = client.get(f"/img/{pid}?w=320&h=240").data

    key_before = RenderCache.key(source, 320, 240)
    source.touch()
    import os
    os.utime(source, (0, 0))
    assert RenderCache.key(source, 320, 240) != key_before
    assert app.cache.get(RenderCache.key(source, 320, 240)) is None

    again = client.get(f"/img/{pid}?w=320&h=240")
    assert again.status_code == 200
    assert first  # the original render happened at all


def test_the_cache_stays_inside_its_budget():
    """Its own cache rather than the running app's: a budget is a constructor argument,
    so this needs no patching of anything global."""
    cache = RenderCache(1000)
    for i in range(20):
        cache.put((f"photo{i}", 1, 1, 0, 0), b"x" * 200)

    assert cache.nbytes <= 1000
    # And it is the oldest that went, not the newest.
    assert ("photo19", 1, 1, 0, 0) in cache
    assert ("photo0", 1, 1, 0, 0) not in cache


def test_a_zero_budget_disables_it():
    cache = RenderCache(0)
    cache.put(("nope", 1, 1, 0, 0), b"data")

    assert len(cache) == 0
    assert cache.get(("nope", 1, 1, 0, 0)) is None


def test_undo_puts_the_photo_back_among_its_neighbours(app, client):
    pid = photo_id_of("Trip/Day1/beach.avif")
    victim = photo_id_of("Trip/Day1/tower.avif")
    client.post("/api/blacklist", json={"id": victim, "scope": "photo"})
    assert victim not in ids_of(client.get(f"/api/neighbors/{pid}").get_json())

    undone = client.post("/api/blacklist/undo",
                         json={"entry": "Trip/Day1/tower.avif", "scope": "photo"})
    assert undone.status_code == 200
    assert victim in ids_of(client.get(f"/api/neighbors/{pid}").get_json())


def test_no_span_returns_the_whole_folder(app, client):
    pid = photo_id_of("Trip/Day1/beach.avif")
    payload = client.get(f"/api/neighbors/{pid}").get_json()
    in_folder = [rel for rel in app.library.rel_true_map().values() if rel.rpartition("/")[0] == "Trip/Day1"]
    assert len(payload["photos"]) == len(in_folder) == payload["total"]
