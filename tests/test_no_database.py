"""What the frame does when photos.db cannot be read at all.

Not the same as the database being lent out — that is test_db_release.py, and everything is
already in memory there. Here nothing was ever loaded: no photo list, and no blacklist.
"""

from pathlib import Path

import pytest
from photoframe.database import Database
from photoframe.library import Library, photo_id_of, tools_folder


class InsideTheLibrary:
    """A database where the real one lives: in a folder of the library it describes."""

    def __init__(self, root):
        self.path = Path(root) / "zTools" / "metadata" / "photos.db"

    def borrow(self):
        return None


def test_the_walk_never_descends_into_the_librarys_own_tools(app, library):
    """zTools holds the thumbnails the face tools write. Indexing them as photos once took
    the library from 35,299 to 43,551, and no rule was needed to do it — this walk runs
    when the database, and so the blacklist, gave nothing."""
    walked = Library(library, InsideTheLibrary(library), app.rules)

    walked.scan()

    assert photo_id_of("zTools/icon.png") not in dict(walked.items())
    assert photo_id_of("wide.avif") in dict(walked.items())


def test_the_tools_folder_is_found_from_the_database_rather_than_named():
    root = Path("D:/Fotos")
    assert tools_folder(root, "D:/Fotos/zTools/metadata/photos.db") == "zTools"
    assert tools_folder(root, "D:/Elsewhere/photos.db") is None   # outside: nothing to skip
    assert tools_folder(root, None) is None


def test_a_library_whose_blacklist_could_not_be_read_is_not_walked(app, monkeypatch):
    """Walking with no rules in force puts every hidden photo back on the wall. An empty
    frame that says so is the better failure: the watchdog reopens and this runs again."""
    walked = []
    monkeypatch.setattr(app.rules, "loaded", False)
    monkeypatch.setattr(app.library, "scan", lambda: walked.append(True))

    assert app.library.refresh() == 0
    assert not walked


def test_the_database_is_taken_back_once_it_becomes_readable(tmp_path):
    """The open that fails at startup: without this nothing would ever try again, and the
    frame would refuse to walk for as long as it ran."""
    later = tmp_path / "not-yet" / "photos.db"
    db = Database(later)
    assert not db.is_open

    later.parent.mkdir()
    assert db.ensure_open()
    assert db.is_open


def test_a_database_on_loan_is_not_snatched_back_by_the_retry(app):
    """ensure_open runs every 30 seconds; a release is not a failure to open."""
    app.db.release()
    try:
        assert app.db.ensure_open() is False
        assert not app.db.is_open
    finally:
        app.db.reopen()


@pytest.mark.parametrize("hidden", ["Trip/Day1", "Screenshots"])
def test_the_walk_still_honours_the_rules_it_does_have(make_app, hidden):
    app = make_app({"blacklist": {"folders": [hidden], "files": []}})

    assert app.library.scan() == len(app.library)
    assert not any(str(path).replace("\\", "/").split("photos/")[1].startswith(hidden)
                   for _, path in app.library.items())
