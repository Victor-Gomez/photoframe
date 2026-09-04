"""The settings someone sets from a screen: quiet hours, and how the frame paces itself.

They live in photos.db rather than in config.json — config.json describes the machine and
is only ever edited by hand, so a tap on a page must not be able to rewrite it.
"""

import logging
from datetime import datetime

import pytest
import store
from photoframe.library import photo_id_of
from photoframe.preferences import PREFIX, is_quiet


@pytest.fixture
def client(app):
    app.app.config["TESTING"] = True
    return app.app.test_client()


def stored(app, name):
    with app.db.lock:
        return store.meta_get(app.db.borrow(), PREFIX + name)


def test_settings_fall_back_to_config_json_until_something_is_written(app, client):
    """Nothing is written on first run, so a deployment keeps its own starting point."""
    shown = client.get("/api/settings").get_json()

    assert shown["slideSeconds"] == app.settings.slide_seconds == 15
    assert shown["favoriteWeight"] == app.settings.favorite_weight == 10
    assert shown["quietFrom"] == shown["quietTo"] == ""
    assert stored(app, "slideSeconds") is None


def test_saving_writes_the_database_and_comes_back(app, client):
    saved = client.post("/api/settings", json={
        "slideSeconds": 45, "quietFrom": "23:30", "quietTo": "07:00"}).get_json()

    assert saved["slideSeconds"] == 45
    assert saved["quietFrom"] == "23:30"
    assert saved["favoriteWeight"] == 10        # untouched by a partial save
    assert stored(app, "quietFrom") == "23:30"
    assert client.get("/api/settings").get_json() == saved


def test_the_frame_paces_itself_by_what_was_saved(app, client):
    """The setting has to reach the page that uses it, not just the database."""
    client.post("/api/settings", json={"slideSeconds": 42, "favoriteWeight": 3})

    playlist = client.get("/api/playlist?ratio=1.5").get_json()
    assert playlist["slideSeconds"] == 42
    assert playlist["favoriteWeight"] == 3


def test_impossible_values_are_refused_rather_than_stored(app, client):
    for body in ({"quietFrom": "25:00", "quietTo": "07:00"},
                 {"quietFrom": "23:00"},                      # a window needs both ends
                 {"slideSeconds": "pronto"},
                 {"slidSeconds": 30}):                        # a typo, not a new setting
        answer = client.post("/api/settings", json=body)
        assert answer.status_code == 400, body
        assert "error" in answer.get_json()
    assert stored(app, "quietFrom") is None


def test_absurd_but_meaningful_values_are_clamped(app, client):
    saved = client.post("/api/settings", json={
        "slideSeconds": 1, "favoriteWeight": 10_000}).get_json()

    assert saved["slideSeconds"] == 3
    assert saved["favoriteWeight"] == 100


def test_settings_cannot_be_changed_while_the_database_is_on_loan(app, client):
    """Same rule as favouriting: 503 rather than a success that recorded nothing."""
    client.post("/api/db/release")
    try:
        assert client.post("/api/settings", json={"slideSeconds": 30}).status_code == 503
        assert client.get("/api/settings").get_json()["slideSeconds"] == 15   # still served
    finally:
        client.post("/api/db/resume")


def test_the_quiet_window_wraps_past_midnight():
    """The obvious implementation — start <= now < end — is dark all day and lit all night."""
    night = ("23:00", "07:00")
    assert is_quiet(*night, datetime(2026, 1, 1, 2, 30))
    assert is_quiet(*night, datetime(2026, 1, 1, 23, 30))
    assert not is_quiet(*night, datetime(2026, 1, 1, 12, 0))
    assert not is_quiet("", "", datetime(2026, 1, 1, 2, 30))     # not set is not "all day"


def test_photos_served_untouched_are_counted_apart_from_renders(app, client):
    """A phone and a PC are handed the file itself, and never reach a decoder. Counting
    only renders made the frame look like it re-encodes everything it serves."""
    pid = photo_id_of("Trip/Day1/beach.avif")
    client.get(f"/img/{pid}")                  # as it sits on disk
    client.get(f"/img/{pid}?w=320&h=200")      # to the size of a screen

    traffic = client.get("/api/render-stats").get_json()["traffic"]
    assert traffic["original"]["requests"] == 1
    assert traffic["rendered"]["requests"] == 1
    assert traffic["originalShare"] == "50%"


def test_the_status_page_shows_the_quiet_hours(app, client):
    client.post("/api/settings", json={"quietFrom": "23:30", "quietTo": "07:15"})

    page = client.get("/status").get_data(as_text=True)
    assert "23:30" in page and "07:15" in page


def test_the_language_reaches_every_surface(app, client):
    """Set once, and the frame, both admin pages and the errors all move together."""
    client.post("/api/settings", json={"language": "en"})

    assert 'lang="en"' in client.get("/").get_data(as_text=True)
    assert "Photos served" in client.get("/status").get_data(as_text=True)
    assert "This device" in client.get("/settings").get_data(as_text=True)
    refused = client.post("/api/settings", json={"quietFrom": "25:00", "quietTo": "07:00"})
    assert refused.get_json()["error"] == "quietFrom: expected HH:MM"


def test_a_language_nobody_wrote_is_refused(app, client):
    assert client.post("/api/settings", json={"language": "fr"}).status_code == 400
    assert client.get("/api/settings").get_json()["language"] == "es"


def test_the_refusal_speaks_the_language_the_page_was_in(app, client):
    """Changing to a language *and* sending something invalid must not answer in the
    language that was never accepted."""
    answer = client.post("/api/settings", json={"language": "en", "slideSeconds": "pronto"})

    assert answer.get_json()["error"] == "slideSeconds: se espera un número"
    assert client.get("/api/settings").get_json()["language"] == "es"   # nothing was written


def test_the_log_level_takes_effect_without_a_restart(app, client):
    """Turning the log up used to mean editing config.json and restarting the frame —
    on a machine across the house, over ssh."""
    logger = logging.getLogger("photoframe")

    client.post("/api/settings", json={"logLevel": "info"})
    assert logger.level == logging.INFO
    assert logger.handlers and getattr(logger.handlers[0], "baseFilename", None)

    client.post("/api/settings", json={"logLevel": "off"})
    assert logger.level > logging.CRITICAL      # and nothing is written at all


def test_a_device_can_speak_a_language_of_its_own(app, client):
    """The frame is in Spanish; the phone reading /status is not. Both are right."""
    client.set_cookie("frame_lang", "en", domain="localhost")

    assert "Photos served" in client.get("/status").get_data(as_text=True)
    assert 'lang="en"' in client.get("/").get_data(as_text=True)
    # Even a refusal, which is read on the device that asked for it.
    refused = client.post("/api/settings", json={"quietFrom": "24:99", "quietTo": "07:00"})
    assert refused.get_json()["error"] == "quietFrom: expected HH:MM"
    # And the frame itself is untouched: this was never written anywhere.
    assert client.get("/api/settings").get_json()["language"] == "es"


def test_a_cookie_naming_a_language_nobody_wrote_is_ignored(app, client):
    client.set_cookie("frame_lang", "fr", domain="localhost")

    assert "Fotos servidas" in client.get("/status").get_data(as_text=True)


def test_the_two_admin_pages_are_one_page_with_two_tabs(app, client):
    """Same header on both, the tab you are on marked, and the way back to the photos is a
    chevron with no words in it."""
    for path, here in (("/settings", "settings"), ("/status", "status")):
        page = client.get(path).get_data(as_text=True)
        assert '<a href="/settings"' in page and '<a href="/status"' in page
        assert f'href="/{here}" class="here"' in page
        assert '<a class="back" href="/" aria-label="Marco"' in page
        assert ">Marco</a>" not in page          # the chevron says it; nothing spells it


def test_both_tabs_wear_the_frames_own_icon(app, client):
    """A blank favicon made the two tabs indistinguishable from anything else open on a
    phone. Same glyph as the frame, inline for the same reason."""
    for path, title in (("/settings", "ajustes"), ("/status", "estado")):
        page = client.get(path).get_data(as_text=True)
        assert 'href="data:image/svg+xml,<svg' in page
        assert "data:," not in page
        assert f"Marco de fotos · {title}" in page     # the shared head still titles each tab
