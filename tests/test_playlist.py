"""Aspect matching, favourite weighting and the paging of a shuffled pass."""

import pytest
from photoframe.library import LANDSCAPE, PORTRAIT, orientation_from, photo_id_of


@pytest.fixture
def client(app):
    app.app.config["TESTING"] = True
    return app.app.test_client()


def ids_of(app, *relatives):
    return {photo_id_of(rel) for rel in relatives}


def test_orientation_is_derived_from_the_ratio(app):
    assert orientation_from(1.78) == LANDSCAPE
    assert orientation_from(1.0) == LANDSCAPE  # square counts as landscape
    assert orientation_from(0.67) == PORTRAIT


def test_ratios_come_from_the_header_not_a_decode(app):
    assert app.library.ratio_of(photo_id_of("Trip/Day1/beach.avif")) == pytest.approx(1.78, abs=0.01)
    assert app.library.ratio_of(photo_id_of("Trip/Day1/tower.avif")) == pytest.approx(0.67, abs=0.01)
    assert app.library.ratio_of(photo_id_of("Trip/Day2/pano.avif")) == pytest.approx(3.0, abs=0.01)


def test_a_landscape_screen_gets_every_landscape_photo(client, app):
    """Orientation, not a band around the screen's own ratio.

    The panorama (3:1) and the 3:2 both belong on a landscape screen: matching more
    finely than landscape/portrait sorted the library by the shape of the camera that
    took each photo — 3:2 from the camera, 16:9 from the phone — which is not a
    distinction worth making. `cover` crops the difference either way.
    """
    body = client.get("/api/playlist?ratio=1.7778&limit=100").get_json()
    served = set(body["ids"])
    assert served >= ids_of(app, "wide.avif", "Trip/Day1/beach.avif", "Trip/Day2/pano.avif")
    assert served.isdisjoint(ids_of(app, "Trip/Day1/tower.avif"))
    assert body["matchedOn"] == "orientation"


def test_a_square_photo_belongs_on_either_screen(client, app):
    square = ids_of(app, "Trip/Day2/square.avif")
    for ratio in ("1.7778", "0.5625"):
        served = set(client.get(f"/api/playlist?ratio={ratio}&limit=100").get_json()["ids"])
        assert served >= square, f"the square photo is missing at ratio {ratio}"


def test_a_portrait_screen_gets_portrait_photos(client, app):
    served = set(client.get("/api/playlist?ratio=0.5625&limit=100").get_json()["ids"])
    assert served >= ids_of(app, "Trip/Day1/tower.avif")
    assert served.isdisjoint(ids_of(app, "Trip/Day1/beach.avif"))


def test_an_impossible_ratio_falls_back_to_orientation_rather_than_nothing(client):
    body = client.get("/api/playlist?ratio=8&limit=100").get_json()
    assert body["count"] > 0
    assert body["matchedOn"].startswith("orientation")


@pytest.mark.parametrize("value", ["NaN", "inf", "-2", "abc", ""])
def test_a_nonsense_ratio_is_ignored_rather_than_disabling_the_filter_silently(client, value):
    body = client.get(f"/api/playlist?ratio={value}&limit=100").get_json()
    assert body["ratio"] is None
    assert body["matchedOn"] == "none"


def test_orientation_still_works_for_a_client_that_sends_no_ratio(client, app):
    served = set(client.get("/api/playlist?orientation=portrait&limit=100").get_json()["ids"])
    assert served == ids_of(app, "Trip/Day1/tower.avif")


def test_rating_gives_one_ticket_per_point_and_five_when_unrated(make_app):
    app = make_app({"weightByRating": True, "ratingFilter": "all"})
    wide = photo_id_of("wide.avif")
    beach = photo_id_of("Trip/Day1/beach.avif")
    app.library.set_rating(wide, 9)
    # Trip/Day1/beach.avif stays unrated -> 5 tickets
    body = app.app.test_client().get("/api/playlist?ratio=1.7778&limit=0").get_json()
    counts = {pid: body["ids"].count(pid) for pid in set(body["ids"])}
    assert counts[wide] == 9
    assert counts[beach] == 5


def test_rating_zero_gets_zero_tickets_when_weighted(make_app):
    app = make_app({"weightByRating": True, "ratingFilter": "all"})
    wide = photo_id_of("wide.avif")
    app.library.set_rating(wide, 0)
    body = app.app.test_client().get("/api/playlist?ratio=1.7778&limit=0").get_json()
    assert wide not in body["ids"]


def test_weighting_can_be_switched_off(make_app):
    app = make_app({"weightByRating": False, "ratingFilter": "all"})
    wide = photo_id_of("wide.avif")
    app.library.set_rating(wide, 10)
    body = app.app.test_client().get("/api/playlist?ratio=1.7778&limit=0").get_json()
    assert body["ids"].count(wide) == 1


def test_copies_of_a_rated_photo_are_spread_out_rather_than_adjacent():
    import random

    from photoframe.web.playlist import weighted_shuffle

    random.seed(7)
    ids = [f"p{i:05d}" for i in range(2000)]
    ratings = {"p00007": 10}
    pass_ = weighted_shuffle(list(ids), ratings, True)

    positions = [i for i, pid in enumerate(pass_) if pid == "p00007"]
    assert len(positions) == 10
    gaps = [b - a for a, b in zip(positions, positions[1:])]
    # One copy per segment, so consecutive copies are never crammed together.
    assert min(gaps) > len(pass_) / 40


def test_the_pass_is_paged_and_a_token_keeps_its_order(client):
    first = client.get("/api/playlist?ratio=1.7778&limit=2").get_json()
    assert first["count"] == 2
    assert first["total"] >= 2

    second = client.get(
        f"/api/playlist?token={first['token']}&offset=2&limit=2"
    ).get_json()
    assert second["token"] == first["token"]
    assert set(second["ids"]).isdisjoint(first["ids"])

    again = client.get(f"/api/playlist?token={first['token']}&offset=0&limit=2").get_json()
    assert again["ids"] == first["ids"]  # same pass, not a reshuffle


def test_an_unknown_token_starts_a_fresh_pass_instead_of_failing(client):
    body = client.get("/api/playlist?token=nonsense&ratio=1.7778&limit=2").get_json()
    assert body["count"] == 2
    assert body["token"] != "nonsense"


def test_a_library_still_being_indexed_serves_photos_rather_than_nothing(app):
    """The aspect index is built in the background; an empty filter result during that
    window means "not ready", not "no photos". Answering with an empty list makes the
    frame announce that a full library is empty."""
    app.library._ratio.clear()          # as it is for the first minute after a restart
    app.library.probe_done.clear()
    client = app.app.test_client()

    body = client.get("/api/playlist?ratio=1.7778&limit=100").get_json()
    assert body["count"] > 0
    assert body["indexing"] is True
    assert "indexing" in body["matchedOn"]


def test_an_empty_library_still_reports_empty_once_indexed(make_app):
    app = make_app({"blacklist": {"folders": ["Trip", "Screenshots", "zTools"], "files": ["*"]}})
    body = app.app.test_client().get("/api/playlist?ratio=1.7778&limit=100").get_json()
    assert body["count"] == 0
    assert body["indexing"] is False


def test_rating_filter_modes_filter_playlist(make_app):
    app = make_app()
    client = app.app.test_client()
    p_unscored = photo_id_of("wide.avif")
    p_low = photo_id_of("Trip/Day1/beach.avif")
    p_high = photo_id_of("Trip/Day1/tower.avif")

    assert client.post("/api/rating", json={"id": p_low, "rating": 3}).status_code == 200
    assert client.post("/api/rating", json={"id": p_high, "rating": 8}).status_code == 200

    # Default is unscored: excludes both rated photos.
    unscored_ids = set(client.get("/api/playlist").get_json()["ids"])
    assert p_unscored in unscored_ids
    assert p_low not in unscored_ids
    assert p_high not in unscored_ids

    # Scored only, threshold disabled: includes both rated photos.
    assert client.post("/api/settings", json={"ratingFilter": "above", "ratingThresholdEnabled": False}).status_code == 200
    scored_ids = set(client.get("/api/playlist").get_json()["ids"])
    assert scored_ids == {p_low, p_high}

    # Scored only, threshold 5 enabled: only p_high.
    assert client.post("/api/settings", json={"ratingFilter": "above", "ratingThresholdEnabled": True, "ratingThreshold": 5}).status_code == 200
    above_ids = set(client.get("/api/playlist").get_json()["ids"])
    assert above_ids == {p_high}

    # All, threshold 5 enabled: excludes p_low (3), keeps p_unscored and p_high.
    assert client.post("/api/settings", json={"ratingFilter": "all", "ratingThresholdEnabled": True, "ratingThreshold": 5}).status_code == 200
    all_filtered_ids = set(client.get("/api/playlist").get_json()["ids"])
    assert p_unscored in all_filtered_ids
    assert p_high in all_filtered_ids
    assert p_low not in all_filtered_ids

    # All, threshold disabled: includes all three.
    assert client.post("/api/settings", json={"ratingFilter": "all", "ratingThresholdEnabled": False}).status_code == 200
    all_ids = set(client.get("/api/playlist").get_json()["ids"])
    assert {p_unscored, p_low, p_high} <= all_ids


def test_folder_filter_restricts_playlist_to_matching_folder(make_app):
    app = make_app()
    client = app.app.test_client()
    p_day1_a = photo_id_of("Trip/Day1/beach.avif")
    p_day1_b = photo_id_of("Trip/Day1/tower.avif")
    p_day2 = photo_id_of("Trip/Day2/square.avif")
    p_root = photo_id_of("wide.avif")

    assert client.post("/api/settings", json={"folderFilter": "Trip/Day1/"}).status_code == 200
    filtered = set(client.get("/api/playlist").get_json()["ids"])
    assert filtered == {p_day1_a, p_day1_b}
    assert p_day2 not in filtered
    assert p_root not in filtered

    # Blank clears the filter.
    assert client.post("/api/settings", json={"folderFilter": ""}).status_code == 200
    unfiltered = set(client.get("/api/playlist").get_json()["ids"])
    assert {p_day1_a, p_day1_b, p_day2, p_root} <= unfiltered


def test_orientation_filter_controls_which_shapes_are_served(make_app):
    app = make_app()
    client = app.app.test_client()
    p_land = photo_id_of("Trip/Day1/beach.avif")
    p_port = photo_id_of("Trip/Day1/tower.avif")
    p_square = photo_id_of("Trip/Day2/square.avif")

    # Default is "device": ?ratio=1.78 (landscape) keeps landscape + near-square, drops portrait.
    dev_ids = set(client.get("/api/playlist?ratio=1.78").get_json()["ids"])
    assert p_land in dev_ids and p_square in dev_ids and p_port not in dev_ids

    # "any": ignores device ratio and returns all orientations.
    assert client.post("/api/settings", json={"orientationFilter": "any"}).status_code == 200
    any_ids = set(client.get("/api/playlist?ratio=1.78").get_json()["ids"])
    assert {p_land, p_port, p_square} <= any_ids

    # "landscape": only horizontal photos regardless of device ratio.
    assert client.post("/api/settings", json={"orientationFilter": "landscape"}).status_code == 200
    land_ids = set(client.get("/api/playlist?ratio=0.56").get_json()["ids"])
    assert p_land in land_ids and p_port not in land_ids

    # "portrait": only vertical photos regardless of device ratio.
    assert client.post("/api/settings", json={"orientationFilter": "portrait"}).status_code == 200
    port_ids = set(client.get("/api/playlist?ratio=1.78").get_json()["ids"])
    assert p_port in port_ids and p_land not in port_ids
