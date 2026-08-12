"""A throwaway photo library and a freshly imported app pointed at it.

The app configures itself at import time, so every test module gets its own copy via
importlib rather than sharing module-level state.
"""

import importlib
import json
import sys
from pathlib import Path

import pytest
from PIL import Image
from photoframe.library import photo_id_of

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# store.py lives with the library now, not with the frame; app.py finds it the same way.
sys.path.insert(0, r"D:\Fotos\zTools\metadata")

# name -> (width, height). Ratios chosen to sit either side of the aspect tolerance:
# 3:2 and 16:9 pass for a landscape screen, 2:3 and 9:16 for a portrait one, and the
# panorama and the square fall outside both.
LIBRARY = {
    "wide.avif": (900, 600),  # 1.50
    "Trip/Day1/beach.avif": (1600, 900),  # 1.78
    "Trip/Day1/tower.avif": (600, 900),  # 0.67
    "Trip/Day2/pano.avif": (1800, 600),  # 3.00
    "Trip/Day2/square.avif": (800, 800),  # 1.00
    "Screenshots/shot.png": (1200, 800),  # 1.50
    "zTools/icon.png": (64, 64),  # 1.00
}


@pytest.fixture
def library(tmp_path):
    root = tmp_path / "photos"
    for name, (width, height) in LIBRARY.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (width, height), (90, 120, 150)).save(
            path, "AVIF" if path.suffix == ".avif" else "PNG"
        )
    return root


@pytest.fixture
def make_app(tmp_path, library, monkeypatch):
    """Import a fresh app instance against `config`, with the index already built."""

    def build(config=None):
        config_file = tmp_path / "config.json"
        settings = {
            "photoDir": str(library),
            "slideSeconds": 15,
            "favoriteWeight": 10,
            "blacklist": {"folders": [], "files": []},
            "favorites": [],
            "unfavorites": [],
        }
        settings.update(config or {})

        # Blacklist and favourites live in photos.db now, not in config.json. They are
        # seeded here the way the frame itself would write them, so the tests exercise the
        # same path the device does.
        db_file = tmp_path / "photos.db"
        settings["dbFile"] = str(db_file)
        rules = {
            "blacklist_folder": settings.get("blacklist", {}).get("folders", []),
            "blacklist_file": settings.get("blacklist", {}).get("files", []),
            "favorite": settings.get("favorites", []),
            "unfavorite": settings.get("unfavorites", []),
        }
        settings.pop("blacklist", None)
        settings.pop("favorites", None)
        settings.pop("unfavorites", None)
        config_file.write_text(json.dumps(settings), encoding="utf-8")

        import store
        conn = store.open_db(db_file)
        for kind, entries in rules.items():
            for entry in entries:
                store.add_rule(conn, kind, entry)
        conn.commit()
        conn.close()

        monkeypatch.setenv("CONFIG_FILE", str(config_file))
        # Not next to the code: run from a deployed folder the suite would append to the
        # frame's own log, where a file existing at all is meant to mean something failed.
        monkeypatch.setenv("LOG_FILE", str(tmp_path / "photoframe.log"))
        for leftover in ("PHOTO_DIR", "FRAME_TOKEN", "DB_FILE", "LOG_LEVEL"):
            monkeypatch.delenv(leftover, raising=False)

        sys.modules.pop("app", None)
        app = importlib.import_module("app")
        app.library.probe_all()  # synchronously, so ratios and tags are ready to assert on
        app.config_file = config_file
        return app

    return build


@pytest.fixture
def app(make_app):
    return make_app()


def photo_id(app, relative):
    return photo_id_of(relative)
