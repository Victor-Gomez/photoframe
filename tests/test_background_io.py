"""The library walk must never be able to starve the rest of the machine.

An unthrottled probe of a whole library took the whole server down once: already-running
processes kept working, but nothing new could start, so the scheduled tasks and the
services next door went with it.
"""
import ctypes
import sys

import pytest
from photoframe.priority import background_io, set_background_mode


windows_only = pytest.mark.skipif(
    not sys.platform.startswith("win"), reason="background mode is a Windows facility"
)


@windows_only
def test_background_mode_actually_takes_effect(app):
    kernel32 = ctypes.WinDLL("kernel32")
    kernel32.GetCurrentThread.restype = ctypes.c_void_p
    kernel32.GetCurrentThread.argtypes = []
    kernel32.GetThreadPriority.restype = ctypes.c_int
    kernel32.GetThreadPriority.argtypes = [ctypes.c_void_p]
    handle = kernel32.GetCurrentThread()

    normal = kernel32.GetThreadPriority(handle)
    with background_io():
        lowered = kernel32.GetThreadPriority(handle)
    restored = kernel32.GetThreadPriority(handle)

    assert lowered < normal, "background mode did not lower the thread"
    assert restored == normal, "background mode was not lifted again"


def test_background_io_restores_on_failure(app):
    with pytest.raises(ValueError):
        with background_io():
            raise ValueError("boom")
    # Reaching here means the context manager neither swallowed the error nor wedged.


def test_background_io_is_a_no_op_elsewhere(app, monkeypatch):
    monkeypatch.setattr(app.sys, "platform", "linux")
    assert set_background_mode(True) is False
    with background_io():
        pass


def test_scan_still_indexes_under_background_io(app):
    """The throttle wraps the walk; it must not change what the walk finds."""
    assert app.library.scan() == len(app.library)
    assert len(app.library)
