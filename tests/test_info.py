"""/api/info: what the details overlay reads out of photos.db."""
import pytest

import store


@pytest.fixture
def client(app):
    app.app.config["TESTING"] = True
    return app.app.test_client()


@pytest.fixture
def exif(app):
    """Fill in a photo's EXIF the way scan.py would."""
    rel = "Trip/Day1/beach.avif"
    with app._db_lock:
        app._db.execute(
            "INSERT INTO photo (rel, taken, make, model, lens, aperture, shutter, iso, "
            "focal_length, focal_length_35, gps_lat, gps_lon, altitude, width, height, size) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(rel) DO UPDATE SET taken=excluded.taken, make=excluded.make, "
            "model=excluded.model, lens=excluded.lens, aperture=excluded.aperture, "
            "shutter=excluded.shutter, iso=excluded.iso, focal_length=excluded.focal_length, "
            "focal_length_35=excluded.focal_length_35, gps_lat=excluded.gps_lat, "
            "gps_lon=excluded.gps_lon, altitude=excluded.altitude, width=excluded.width, "
            "height=excluded.height, size=excluded.size",
            (rel, "2023-06-05T17:35:42", "SONY", "ILCE-7M3", "FE 24-70mm", 2.8, 0.004,
             400, 35.0, 52.0, 40.9701, -5.6635, 802.0, 1600, 900, 1234567),
        )
        app._db.commit()
    return rel


def test_details_come_back_from_the_database(app, client, exif):
    pid = app.photo_id_of(exif)
    info = client.get(f"/api/info/{pid}").get_json()

    assert info["file"] == "beach.avif"
    assert info["folder"] == "Trip/Day1"
    assert info["taken"] == "2023-06-05T17:35:42"
    assert info["make"] == "SONY"
    assert info["model"] == "ILCE-7M3"
    assert info["aperture"] == 2.8
    assert info["shutter"] == 0.004
    assert info["iso"] == 400
    assert info["gps_lat"] == 40.9701
    assert info["gps_lon"] == -5.6635
    assert info["fullPath"].endswith("beach.avif")


def test_fields_the_camera_did_not_record_are_left_out(app, client):
    """Absent rather than null, so the overlay can list only what is known."""
    pid = app.photo_id_of("Trip/Day2/pano.avif")
    info = client.get(f"/api/info/{pid}").get_json()
    assert "gps_lat" not in info
    assert "iso" not in info
    # The things that come from the index rather than the database are always there.
    assert info["file"] == "pano.avif"
    assert info["fullPath"]


def test_a_photo_with_no_database_row_still_reports_its_path(app, client):
    pid = app.photo_id_of("wide.avif")
    info = client.get(f"/api/info/{pid}").get_json()
    assert info["file"] == "wide.avif"
    assert info["folder"] == ""
    assert info["fullPath"].endswith("wide.avif")


def test_unknown_photo_is_404(client):
    assert client.get("/api/info/nosuchphoto").status_code == 404


def test_a_hidden_photo_has_no_details(app, client):
    pid = app.photo_id_of("Trip/Day1/tower.avif")
    assert client.get(f"/api/info/{pid}").status_code == 200
    client.post("/api/blacklist", json={"id": pid, "scope": "photo"})
    assert client.get(f"/api/info/{pid}").status_code == 404


def test_named_people_are_listed(app, client, exif):
    """The face pass fills these in; the overlay names who is in the photo."""
    with app._db_lock:
        app._db.execute("INSERT INTO person (id, name) VALUES ('p1', 'Trini')")
        app._db.execute("INSERT INTO cluster (id, person_id, ci) VALUES ('c1', 'p1', 1)")
        app._db.execute(
            "INSERT INTO face (rel, idx, cluster_id) VALUES (?, 0, 'c1')", (exif,)
        )
        app._db.commit()

    info = client.get(f"/api/info/{app.photo_id_of(exif)}").get_json()
    assert info["people"] == ["Trini"]


def test_the_resolved_place_and_google_link_are_returned(app, client, exif):
    """geocode.py fills `location`; the Google Photos import fills `google_url`."""
    with app._db_lock:
        app._db.execute(
            "UPDATE photo SET location = ?, google_url = ? WHERE rel = ?",
            ("Calle Arrabal, Olmedo, España", "https://photos.google.com/lr/photo/abc", exif),
        )
        app._db.commit()

    info = client.get(f"/api/info/{app.photo_id_of(exif)}").get_json()
    assert info["location"] == "Calle Arrabal, Olmedo, España"
    assert info["google_url"] == "https://photos.google.com/lr/photo/abc"


def test_a_photo_without_them_omits_them(app, client):
    info = client.get(f"/api/info/{app.photo_id_of('Trip/Day2/pano.avif')}").get_json()
    assert "location" not in info
    assert "google_url" not in info
