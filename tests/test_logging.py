"""What reaches photoframe.log.

The frame runs unattended under pythonw.exe, where there is no stderr at all: whatever the
log does not keep is simply gone. So the level is worth pinning down rather than assuming.
"""

import importlib
import json
import sys


def build(tmp_path, library, monkeypatch, **settings):
    """Import a fresh app with its own config and log file, and return both."""
    config_file = tmp_path / "config.json"
    log_file = tmp_path / "photoframe.log"
    config_file.write_text(json.dumps({"photoDir": str(library), **settings}), encoding="utf-8")
    monkeypatch.setenv("CONFIG_FILE", str(config_file))
    monkeypatch.setenv("LOG_FILE", str(log_file))
    monkeypatch.setenv("DB_FILE", str(tmp_path / "photos.db"))
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    monkeypatch.delenv("PHOTO_DIR", raising=False)
    sys.modules.pop("app", None)
    return importlib.import_module("app"), log_file


def test_the_routine_commentary_is_not_written(tmp_path, library, monkeypatch):
    """The default. A fortnight of INFO was 2.5MB of routine lines and no errors."""
    app, log_file = build(tmp_path, library, monkeypatch)

    app.app.logger.info("loaded N photos")
    # Asserted on content rather than on the file being absent: the test library has no
    # photos.db behind it, so starting up here legitimately logs the fallback error and
    # creates the file. In production, with a real database, nothing is written and the
    # handler's delay=True means the file never appears at all.
    assert "loaded N photos" not in log_file.read_text(encoding="utf-8")


def test_failures_are_still_written(tmp_path, library, monkeypatch):
    """Quiet is not the same as blind: a stable frame produces no lines, and a broken one
    still says why. This is the whole reason the default is "error" rather than "off"."""
    app, log_file = build(tmp_path, library, monkeypatch)

    app.app.logger.error("avifdec failed on beach.avif")
    app.app.logger.warning("release ran past 900s")
    written = log_file.read_text(encoding="utf-8")
    assert "avifdec failed" in written
    assert "release ran past" in written


def test_off_writes_no_file_at_all(tmp_path, library, monkeypatch):
    app, log_file = build(tmp_path, library, monkeypatch, logLevel="off")

    app.app.logger.error("avifdec failed on beach.avif")
    assert not log_file.exists()
    # Without this the record would fall through to stderr, which under pythonw.exe is
    # None — and writing to it raises rather than merely being lost. Asserted on the
    # package logger: every module logs through a child of it, and that is where the chain
    # is cut.
    import logging
    assert logging.getLogger("photoframe").propagate is False


def test_info_can_be_turned_back_on_for_diagnosing(tmp_path, library, monkeypatch):
    app, log_file = build(tmp_path, library, monkeypatch, logLevel="info")

    app.app.logger.info("loaded N photos")
    assert "loaded N photos" in log_file.read_text(encoding="utf-8")


def test_an_unrecognised_level_keeps_failures_rather_than_losing_them(tmp_path, library,
                                                                     monkeypatch):
    """A typo in the config must not silently disable the only record of what went wrong."""
    app, log_file = build(tmp_path, library, monkeypatch, logLevel="verbose")

    app.app.logger.error("avifdec failed on beach.avif")
    assert "avifdec failed" in log_file.read_text(encoding="utf-8")
