"""One process on the GPU at a time, across the CLI and the web server.

A video's own lock (WorkDir.lock) keeps two processes off the same files, but two
dubs of different videos, one from the CLI and one from the web, could still load
their models side by side: Chatterbox's two workers (3.6 GB each), whisper and
demucs don't fit twice in 16 GB, and the second one to run out of memory fails
mid-dub. So the phases that use the GPU run under this machine-wide lock, held
from the first such phase to the last; the other process waits, says so, and can
still be cancelled while it waits.

Models stay loaded between clips and phases, so releasing the lock frees their
memory first (`on_release`, pipeline.release_models): a lock given up with the
GPU still full would let the next process in to fail. Nested holds in one process
(a dub's phases) share the outer one.
"""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from .log import check_cancelled, log

POLL_S = 1.0  # how often a waiting process tries again (and checks for a cancel)

_depth = 0  # this process's nested holds
_mutex = threading.Lock()


def lock_path() -> Path:
    """~/.cache/opendub/gpu.lock, or $OPENDUB_GPU_LOCK (the tests point it into their own folder)."""
    if path := os.environ.get("OPENDUB_GPU_LOCK"):
        return Path(path)
    return Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "opendub" / "gpu.lock"


def holder() -> str | None:
    """Who holds the GPU ("pid 123, opendub dub abc…"), or None if nobody does."""
    import fcntl

    path = lock_path()
    if not path.exists():
        return None
    fd = os.open(path, os.O_RDONLY)
    try:
        fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
    except BlockingIOError:
        return path.read_text(encoding="utf-8").strip() or "another process"
    else:
        fcntl.flock(fd, fcntl.LOCK_UN)
        return None
    finally:
        os.close(fd)


@contextmanager
def hold(what: str, on_release: Callable[[], None] = lambda: None) -> Iterator[None]:
    """Hold the GPU for `what`, waiting while another process has it; free its memory and let go at the end."""
    import fcntl

    global _depth
    with _mutex:
        if _depth:  # already ours: a phase inside a dub
            _depth += 1
            nested = True
        else:
            nested = False
    if nested:
        try:
            yield
        finally:
            with _mutex:
                _depth -= 1
        return

    path = lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        waited = None
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if waited is None:
                    waited = time.monotonic()
                    log.info(f"Waiting for the GPU: another OpenDub process is using it ({holder() or 'unknown'})…")
                check_cancelled()  # a cancel while waiting stops the job here, holding nothing
                time.sleep(POLL_S)
        if waited is not None:
            log.info(f"GPU free after {time.monotonic() - waited:.0f}s of waiting")
        os.ftruncate(fd, 0)
        os.write(fd, f"pid {os.getpid()}, {what}".encode())
        with _mutex:
            _depth = 1
        try:
            yield
        finally:
            try:
                on_release()
            finally:
                with _mutex:
                    _depth = 0
                os.ftruncate(fd, 0)
                fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)
