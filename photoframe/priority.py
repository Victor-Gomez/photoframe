"""Running library I/O without letting it monopolise the disk."""

import contextlib
import ctypes
import sys

_THREAD_MODE_BACKGROUND_BEGIN = 0x00010000
_THREAD_MODE_BACKGROUND_END = 0x00020000


def set_background_mode(begin: bool) -> bool:
    """Windows background mode for the calling thread: idle CPU *and* lowest-priority I/O.

    The I/O half is the point. Walking the library opens tens of thousands of file headers,
    and at normal priority that is enough to starve every other service on the box -- new
    processes could not even start, so other services went down while the frame itself,
    already running, carried on answering. Background mode makes the walk yield to anything
    else that wants the disk: it takes longer and nothing else notices.
    """
    if not sys.platform.startswith("win"):
        return False
    try:
        kernel32 = ctypes.WinDLL("kernel32")
        # The pseudo-handle is (HANDLE)-2. Without these the default int marshalling
        # truncates it on 64-bit and the call silently does nothing.
        kernel32.GetCurrentThread.restype = ctypes.c_void_p
        kernel32.GetCurrentThread.argtypes = []
        kernel32.SetThreadPriority.restype = ctypes.c_int
        kernel32.SetThreadPriority.argtypes = [ctypes.c_void_p, ctypes.c_int]
        mode = _THREAD_MODE_BACKGROUND_BEGIN if begin else _THREAD_MODE_BACKGROUND_END
        return bool(kernel32.SetThreadPriority(kernel32.GetCurrentThread(), mode))
    except Exception:
        return False


@contextlib.contextmanager
def background_io():
    started = set_background_mode(True)
    try:
        yield
    finally:
        if started:
            set_background_mode(False)


def worker_background():
    set_background_mode(True)  # per-thread, so each pool worker has to ask for itself
