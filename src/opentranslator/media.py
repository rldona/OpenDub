"""ffmpeg/ffprobe helpers, and the one place the pipeline starts child processes from."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

# The web server sets it: children then run in their own session, so the Ctrl+C
# typed in the server's terminal doesn't kill a running dub's ffmpeg or claude
# call; the server decides what to do with it (web.app.Server) and stops them itself.
CHILD_SESSION = False
_children: set[subprocess.Popen] = set()
_lock = threading.Lock()


def popen(cmd: list[str], **kwargs: Any) -> subprocess.Popen:
    """subprocess.Popen, registered so stop_children() can end it."""
    proc = subprocess.Popen(cmd, start_new_session=CHILD_SESSION, **kwargs)
    with _lock:
        _children.add(proc)
    return proc


def run(cmd: list[str], *, input: Any = None, timeout: float | None = None, check: bool = False,
        capture_output: bool = False, **kwargs: Any) -> subprocess.CompletedProcess:
    """subprocess.run through popen()."""
    if capture_output:
        kwargs.update(stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if input is not None:
        kwargs["stdin"] = subprocess.PIPE
    proc = popen(cmd, **kwargs)
    try:
        out, err = proc.communicate(input, timeout=timeout)
    except BaseException:
        proc.kill()
        proc.wait()
        raise
    finally:
        with _lock:
            _children.discard(proc)
    if check and proc.returncode:
        raise subprocess.CalledProcessError(proc.returncode, cmd, out, err)
    return subprocess.CompletedProcess(cmd, proc.returncode, out, err)


def stop_children() -> None:
    """Terminate the children still running (the web server, on a confirmed Ctrl+C)."""
    with _lock:
        procs = list(_children)
    for proc in procs:
        if proc.poll() is None:
            proc.terminate()

INSTALL_FFMPEG = "brew install ffmpeg" if sys.platform == "darwin" else "sudo apt install ffmpeg"


def require_ffmpeg() -> None:
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            raise SystemExit(f"{tool} not found. Install it with: {INSTALL_FFMPEG}")


def ffmpeg(*args: str) -> None:
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args]
    result = run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {' '.join(cmd)}\n{result.stderr}")


def probe(path: Path) -> dict:
    out = run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
        capture_output=True, text=True, check=True,
    )
    return json.loads(out.stdout)


def duration(path: Path) -> float:
    return float(probe(path)["format"]["duration"])
