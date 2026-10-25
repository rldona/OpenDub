"""Cloning engines that run as a separate process in their own venv (IndexTTS, CosyVoice).

Their pins (Python, torch, transformers…) can't share a venv with the rest of
OpenDub, so each one has a worker script (workers/<engine>_worker.py) run
with its venv's python. The worker loads the model once and speaks JSON lines
over stdin/stdout:

    worker → {"ready": true, "device": "...", "load_s": 12.3, ...}
    client → {"id": 1, "text": "...", "ref": "/abs/ref.wav", "out": "/abs/out.wav",
              "duration_factor": 1.0, "seed": 0, ...}
    worker → {"id": 1, "ok": true, "seconds": 2.1} or {"id": 1, "ok": false, "error": "..."}

This module is the client side, shared by every such engine: starting the
process (through media.popen, so the web server can keep it out of a stray
Ctrl+C), the handshake, one request at a time, and stopping it to free its GPU
memory. One worker per engine is kept alive between clips.
"""

from __future__ import annotations

import atexit
import json
import math
import select
import struct
import subprocess
import wave
from pathlib import Path

from . import media
from .log import log

WORKERS_DIR = Path(__file__).parent / "workers"

_workers: dict[str, Worker] = {}


class WorkerTimeout(RuntimeError):
    """A worker didn't answer a request in time (hung on the GPU, stuck in a loop)."""


def clip_timeout(text: str) -> float:
    """Seconds a clip may take before its worker counts as hung: far above the 1–20 s they take."""
    return 120.0 + 2.0 * len(text)


class Worker:
    """A long-lived engine process: loads the model once, then serves clips."""

    def __init__(self, name: str, python: Path, script: Path, args: list[str], cwd: Path, log_path: Path):
        self.name = name
        log_path.parent.mkdir(parents=True, exist_ok=True)
        self.log_path = log_path
        self._stderr = log_path.open("a", encoding="utf-8")
        log.info(f"Starting {name} in its own process (log in {log_path})…")
        self.proc = media.popen(
            [str(python), "-I", str(script), *args], cwd=cwd,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self._stderr, text=True, bufsize=1,
        )
        hello = self._read()
        accel = ", accelerated" if hello.get("accel") else ""
        log.info(f"{name} loaded in {hello['load_s']}s ({hello['device']}{accel})")
        self._next_id = 0

    def _read(self, timeout: float | None = None) -> dict:
        if timeout is not None:
            # one request, one reply line: nothing is left buffered between them, so select is reliable
            ready, _, _ = select.select([self.proc.stdout], [], [], timeout)
            if not ready:
                raise WorkerTimeout(f"The {self.name} worker didn't answer in {timeout:.0f} s")
        line = self.proc.stdout.readline()
        if not line:
            raise RuntimeError(f"The {self.name} worker stopped (see {self.log_path})")
        return json.loads(line)

    def request(self, text: str, ref: Path, out: Path, factor: float, seed: int, timeout: float | None = None,
                **extra) -> None:
        self._next_id += 1
        req = {"id": self._next_id, "text": text, "ref": str(ref.resolve()), "out": str(out.resolve()),
               "duration_factor": factor, "seed": seed, **extra}
        self.proc.stdin.write(json.dumps(req, ensure_ascii=False) + "\n")
        self.proc.stdin.flush()
        reply = self._read(timeout)
        if not reply.get("ok"):
            raise RuntimeError(f"{self.name} failed on {text[:40]!r}: {reply.get('error')} (see {self.log_path})")

    def kill(self) -> None:
        if self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait()
        self._stderr.close()

    def close(self) -> None:
        if self.proc.poll() is None:
            self.proc.stdin.close()
            try:
                self.proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self._stderr.close()


def worker(key: str, start) -> Worker:
    """The running worker for `key`, started with `start()` the first time."""
    if key not in _workers:
        _workers[key] = start()
        atexit.register(_workers[key].close)
    return _workers[key]


def speak(key: str, start, text: str, ref: Path, out: Path, factor: float, seed: int, **extra) -> bool:
    """Speak one clip with the worker for `key`. A worker that doesn't answer in clip_timeout()
    is killed and started again once; if it hangs again, the clip is left as a 0.1 s beep, which
    the quality check finds abnormal and redoes (another seed…), instead of the whole job hanging.
    Returns whether the clip was spoken."""
    for attempt in (1, 2):
        w = worker(key, start)
        try:
            w.request(text, ref, out, factor, seed, timeout=clip_timeout(text), **extra)
            return True
        except WorkerTimeout as e:
            w.kill()
            _workers.pop(key, None)
            log.warning(f"{e}: restarting it" + (" and trying again" if attempt == 1 else ""))
    _beep(out)
    log.warning(f"{key} hung twice on {text[:40]!r}: left for the quality check to redo")
    return False


def _beep(out: Path, seconds: float = 0.1, rate: int = 24000) -> None:
    n = int(seconds * rate)
    samples = (int(3000 * math.sin(2 * math.pi * 1000 * i / rate)) for i in range(n))
    with wave.open(str(out), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(struct.pack(f"<{n}h", *samples))


def shutdown(key: str | None = None) -> None:
    """Stop one worker (or all of them) and free its GPU memory; the next clip starts a new one."""
    for k in [key] if key else list(_workers):
        if (w := _workers.pop(k, None)) is not None:
            w.close()


def fit_factor(duration: float, slot: float, factor: float = 1.0, floor: float = 0.5,
               ceiling: float | None = None) -> float:
    """Duration factor that makes a clip of `duration` (spoken at `factor`) fit `slot`, with a 3% margin.

    Both engines scale the duration almost exactly with it. Never below `floor`;
    never above `ceiling`, which defaults to `factor` (only shorten) and can be
    1.0 to also let a clip that has room relax towards its natural pace.
    """
    ceiling = factor if ceiling is None else ceiling
    return round(min(max(factor * slot * 0.97 / duration, floor), ceiling), 3)
