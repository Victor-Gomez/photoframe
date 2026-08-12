"""The blacklist / favourites matching rules, which are what the config file promises."""

import pytest
from photoframe.library import ancestors, photo_id_of
from photoframe.rules import Matcher, normalise_entry


def test_normalise_entry_accepts_either_slash_and_strips_decoration(app):
    assert normalise_entry("  Trip\\Day1  ") == "Trip/Day1"
    assert normalise_entry("./Trip/Day1/") == "Trip/Day1"
    assert normalise_entry("Trip/Day1") == "Trip/Day1"


def test_photo_id_is_stable_and_derived_from_the_relative_path(app):
    assert photo_id_of("Trip/Day1/beach.avif") == photo_id_of("Trip/Day1/beach.avif")
    assert photo_id_of("Trip/Day1/beach.avif") != photo_id_of("Trip/Day2/pano.avif")


def test_ancestors_lists_every_level_outermost_first(app):
    from pathlib import PurePosixPath

    assert ancestors(PurePosixPath("a/b/c/photo.avif")) == ["a", "a/b", "a/b/c"]
    assert ancestors(PurePosixPath("photo.avif")) == []


@pytest.mark.parametrize(
    "entries, path, expected",
    [
        (["trip/day1"], "trip/day1/beach.avif", True),  # under a listed folder
        (["trip/day1"], "trip/day1", True),  # the folder itself
        (["trip/day1"], "trip/day10/beach.avif", False),  # not a prefix match on names
        (["trip/day1/beach.avif"], "trip/day1/beach.avif", True),  # one photo
        (["trip/day1/beach.avif"], "trip/day1/tower.avif", False),
        (["screenshots"], "screenshots/shot.png", True),  # bare name, at the top
        (["day2"], "trip/day2/pano.avif", True),  # bare name, at any depth
        (["*.png"], "screenshots/shot.png", True),  # glob on extension
        (["*.png"], "wide.avif", False),
        (["*/day2"], "trip/day2", True),  # glob across a level
        ([], "anything.avif", False),  # an empty list matches nothing
    ],
)
def test_matcher_rules(app, entries, path, expected):
    assert Matcher(entries)(path) is expected


def test_matching_is_case_insensitive(app):
    assert Matcher(["trip/day1"])("trip/day1/beach.avif") is True
    assert app.rules.matcher("folders")("TRIP/Day1/Beach.avif".lower()) is False  # nothing configured


def test_blacklisted_folder_hides_everything_under_it(make_app):
    app = make_app({"blacklist": {"folders": ["Trip/Day1"], "files": []}})
    indexed = set(app.library.rel_lower_map().values())
    assert "trip/day1/beach.avif" not in indexed
    assert "trip/day1/tower.avif" not in indexed
    assert "trip/day2/pano.avif" in indexed


def test_blacklisted_file_hides_only_that_photo(make_app):
    app = make_app({"blacklist": {"folders": [], "files": ["Trip/Day1/beach.avif"]}})
    indexed = set(app.library.rel_lower_map().values())
    assert "trip/day1/beach.avif" not in indexed
    assert "trip/day1/tower.avif" in indexed


def test_blacklist_glob_hides_a_whole_file_type(make_app):
    app = make_app({"blacklist": {"folders": [], "files": ["*.png"]}})
    assert not [rel for rel in app.library.rel_lower_map().values() if rel.endswith(".png")]
    assert [rel for rel in app.library.rel_lower_map().values() if rel.endswith(".avif")]


def test_favorite_by_name_and_by_folder(make_app):
    app = make_app({"favorites": ["Trip/Day1/beach.avif", "Trip/Day2"]})
    assert app.rules.is_favorite("Trip/Day1/beach.avif") is True
    assert app.rules.is_favorite("Trip/Day2/pano.avif") is True  # covered by the folder
    assert app.rules.is_favorite("Trip/Day1/tower.avif") is False


def test_favorite_by_tag(make_app):
    app = make_app({"favorites": ["tag:album_japan"]})
    pid = photo_id_of("Trip/Day1/tower.avif")
    app.library.set_tags(pid, ("album_japan",))
    assert app.rules.is_favorite("Trip/Day1/tower.avif", pid) is True
    assert app.rules.is_favorite("Trip/Day1/beach.avif") is False


def test_favorite_by_tag_glob(make_app):
    app = make_app({"favorites": ["tag:album_*"]})
    pid = photo_id_of("Trip/Day1/tower.avif")
    app.library.set_tags(pid, ("album_japan",))
    assert app.rules.is_favorite("Trip/Day1/tower.avif", pid) is True


def test_unfavorites_override_a_tag(make_app):
    app = make_app(
        {"favorites": ["tag:album_japan"], "unfavorites": ["Trip/Day1/tower.avif"]}
    )
    pid = photo_id_of("Trip/Day1/tower.avif")
    app.library.set_tags(pid, ("album_japan",))
    assert app.rules.is_favorite("Trip/Day1/tower.avif", pid) is False


def test_unfavorites_override_a_folder(make_app):
    app = make_app({"favorites": ["Trip"], "unfavorites": ["Trip/Day2/pano.avif"]})
    assert app.rules.is_favorite("Trip/Day1/beach.avif") is True
    assert app.rules.is_favorite("Trip/Day2/pano.avif") is False


def test_unfavorite_tag_excludes_a_favorited_folder(make_app):
    app = make_app({"favorites": ["Trip"], "unfavorites": ["tag:blurry"]})
    pid = photo_id_of("Trip/Day1/tower.avif")
    app.library.set_tags(pid, ("blurry",))
    assert app.rules.is_favorite("Trip/Day1/tower.avif", pid) is False
    assert app.rules.is_favorite("Trip/Day1/beach.avif") is True


def test_a_malformed_config_falls_back_to_defaults_without_rewriting_it(
    tmp_path, library, monkeypatch
):
    import importlib
    import sys

    broken = tmp_path / "config.json"
    broken.write_text("{ not json", encoding="utf-8")
    monkeypatch.setenv("CONFIG_FILE", str(broken))
    monkeypatch.setenv("PHOTO_DIR", str(library))
    # Its own empty database, or the test opens the real library's one.
    monkeypatch.setenv("DB_FILE", str(tmp_path / "photos.db"))
    sys.modules.pop("app", None)
    app = importlib.import_module("app")

    assert app.settings.photo_dir == library.resolve()
    assert broken.read_text(encoding="utf-8") == "{ not json"  # never clobbered


def test_a_config_with_a_byte_order_mark_still_parses(tmp_path, library, monkeypatch):
    import importlib
    import json
    import sys

    with_bom = tmp_path / "config.json"
    body = json.dumps({"photoDir": str(library), "slideSeconds": 42})
    with_bom.write_bytes(b"\xef\xbb\xbf" + body.encode("utf-8"))
    monkeypatch.setenv("CONFIG_FILE", str(with_bom))
    # Its own empty database. Without this the test opens the real library's one.
    monkeypatch.setenv("DB_FILE", str(tmp_path / "photos.db"))
    monkeypatch.delenv("PHOTO_DIR", raising=False)
    sys.modules.pop("app", None)
    app = importlib.import_module("app")

    # Checked against a setting rather than a rule: the lists live in photos.db now, so a
    # favourites entry in config.json is ignored by design and would prove nothing here.
    assert app.settings.values["slideSeconds"] == 42
    assert app.settings.slide_seconds == 42
