"""Dub jobs for the web frontend: a one-at-a-time queue and a replayable event feed per job.

One worker thread runs the jobs in order (the GPU can't run two TTS phases at
once). While a job runs, the pipeline's own reports reach it untouched: log
records through a handler on the `opendub` logger, and phase and
progress events through log.subscribe(). Every event is kept in the job, so a
page that reconnects replays it from the start or from the last id it saw.
The job's options and final state are saved in work/<id>/job.json.
"""

from __future__ import annotations

import json
import logging
import queue
import re
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .. import media, pipeline
from ..config import Settings
from ..download import video_id
from ..errors import PhaseError
from ..log import Cancelled, clear_cancel, log, plain, request_cancel, subscribe
from ..workdir import write_text_atomic

VIDEO_ID = re.compile(r"[\w-]{11}")
ACTIVE = ("queued", "running")


@dataclass
class JobOptions:
    url: str
    separate: bool = True  # keep the music: mix over the separated background
    tts: str = "clone"  # edge | clone
    engine: str = "auto"  # auto (CosyVoice with several voices, Chatterbox with one) | chatterbox | indextts | cosyvoice
    voice: str = "es-ES-AlvaroNeural"  # edge-tts voice (also the cloned voice's last resort)
    bg_volume: float = 0.0  # dB of the background: the separated one, or the original audio
    keep_translation: bool = False  # another engine on the same translation: only TTS and mix are redone
    retouch: list[int] | None = None  # a retouch: edited sentences and these new takes (see pipeline.retouch)
    multi_speaker: bool = False  # several voices: diarize and give each speaker their own voice
    review: bool = False  # stop after the translation: the job ends "review", to edit it and go on

    def settings(self, work_root: Path) -> Settings:
        # the one volume the page sets: the separated background's, or the original audio's
        music = self.bg_volume if self.separate else Settings.music_volume_db
        original = Settings.bg_volume_db if self.separate else self.bg_volume
        return Settings(work_root=work_root, separate=self.separate, tts=self.tts, engine=self.engine,
                        voice=self.voice, keep_translation=self.keep_translation, multi_speaker=self.multi_speaker,
                        retouch=tuple(self.retouch) if self.retouch is not None else None, review=self.review,
                        music_volume_db=music, bg_volume_db=original)


Runner = Callable[[str, Settings], Any]


@dataclass
class Job:
    id: str
    options: JobOptions
    status: str = "queued"  # queued | running | done | review | error | cancelled
    error: str | None = None  # the English message (the CLI's)
    error_code: str | None = None  # errors.PhaseError: what the page says in its own language
    error_params: dict[str, Any] | None = None
    created: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    finished: str | None = None
    events: list[dict[str, Any]] = field(default_factory=list, repr=False)
    cancelling: bool = field(default=False, repr=False)

    def __post_init__(self) -> None:
        self._cond = threading.Condition()

    def add(self, event: dict[str, Any]) -> None:
        with self._cond:
            self.events.append({**event, "seq": len(self.events), "t": round(time.time(), 3)})
            self._cond.notify_all()

    def set_status(self, status: str, error: str | None = None, code: str | None = None,
                   params: dict[str, Any] | None = None) -> None:
        self.status, self.error, self.error_code, self.error_params = status, error, code, params
        if status in ("done", "review", "error", "cancelled"):
            self.finished = datetime.now().isoformat(timespec="seconds")
        coded = {"error_code": code, "error_params": params or {}} if code else {}
        self.add({"type": "status", "status": status, **({"error": error} if error else {}), **coded})

    def wait(self, since: int, timeout: float) -> tuple[list[dict[str, Any]], bool]:
        """Events from `since` on, waiting up to `timeout` for new ones; and whether the job is over."""
        with self._cond:
            if len(self.events) <= since and self.status in ACTIVE:
                self._cond.wait(timeout)
            return self.events[since:], self.status not in ACTIVE

    def summary(self) -> dict[str, Any]:
        return {"id": self.id, "status": self.status, "error": self.error, "error_code": self.error_code,
                "error_params": self.error_params, "created": self.created, "finished": self.finished,
                "options": asdict(self.options)}


class _JobLogHandler(logging.Handler):
    """Forwards the pipeline's log records to the running job, without rich markup."""

    def __init__(self, job: Job):
        super().__init__(level=logging.INFO)
        self.job = job

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.job.add({"type": "log", "level": record.levelname.lower(), "message": plain(record.getMessage())})
        except Exception:
            self.handleError(record)


class JobManager:
    def __init__(self, work_root: Path, runner: Runner = pipeline.dub):
        self.work_root = work_root
        self.runner = runner
        self._jobs: dict[str, Job] = {}
        self._queue: queue.Queue[Job] = queue.Queue()
        self._lock = threading.Lock()
        self._mark_interrupted()
        self._worker = threading.Thread(target=self._work, name="dub-worker", daemon=True)
        self._worker.start()

    # --- persistence -------------------------------------------------------
    def _job_file(self, vid: str) -> Path:
        return self.work_root / vid / "job.json"

    def _save(self, job: Job) -> None:
        path = self._job_file(job.id)
        path.parent.mkdir(parents=True, exist_ok=True)
        write_text_atomic(path, json.dumps(job.summary(), ensure_ascii=False, indent=1))

    def saved(self, vid: str) -> dict[str, Any] | None:
        """job.json of a video: the options and outcome of its last job."""
        path = self._job_file(vid)
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    def _mark_interrupted(self) -> None:
        """Jobs left queued or running by a previous server run did not finish."""
        for path in self.work_root.glob("*/job.json"):
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("status") in ACTIVE:
                data.update(status="error", error="Interrupted: the server stopped before it finished")
                write_text_atomic(path, json.dumps(data, ensure_ascii=False, indent=1))

    # --- queue -------------------------------------------------------------
    def submit(self, options: JobOptions) -> Job:
        """Queue a dub; if that video already has a job queued or running, return that one."""
        vid = video_id(options.url)
        with self._lock:
            existing = self._jobs.get(vid)
            if existing and existing.status in ACTIVE:
                return existing
            job = Job(vid, options)
            self._jobs[vid] = job
            job.set_status("queued")
            self._save(job)
            self._queue.put(job)
            return job

    def get(self, vid: str) -> Job | None:
        return self._jobs.get(vid)

    def active(self) -> list[Job]:
        """The running job first, then the queued ones in order."""
        jobs = [j for j in self._jobs.values() if j.status in ACTIVE]
        return sorted(jobs, key=lambda j: (j.status != "running", j.created))

    def status(self, vid: str) -> str | None:
        job = self._jobs.get(vid)
        if job:
            return job.status
        saved = self.saved(vid)
        return saved.get("status") if saved else None

    def cancel(self, vid: str) -> Job | None:
        """Cancel a video's job: a queued one never runs; a running one stops at its next progress
        tick, phase or Claude call, its child processes (ffmpeg, claude, the engines) terminated.
        What it had done stays cached, so dubbing it again goes on from there."""
        with self._lock:
            job = self._jobs.get(vid)
            if not job or job.status not in ACTIVE:
                return job
            if job.status == "queued":
                job.set_status("cancelled")
                self._save(job)
                return job
            job.cancelling = True
        request_cancel()
        media.stop_children()
        return job

    def _work(self) -> None:
        while True:
            job = self._queue.get()
            if job.status == "cancelled":  # cancelled while it waited
                self._queue.task_done()
                continue
            try:
                self._run(job)
            finally:
                self._queue.task_done()

    def _run(self, job: Job) -> None:
        handler = _JobLogHandler(job)
        log.addHandler(handler)
        unsubscribe = subscribe(job.add)
        clear_cancel()
        job.set_status("running")
        self._save(job)
        try:
            self.runner(job.options.url, job.options.settings(self.work_root))
        except pipeline.ReviewPending:
            job.set_status("review")
        except Cancelled:
            job.set_status("cancelled")
        except SystemExit as e:  # the phases stop with SystemExit and a readable message
            if job.cancelling:
                job.set_status("cancelled")
            elif isinstance(e, PhaseError):  # a common failure: the page says it in its language
                job.set_status("error", str(e), e.error_code, e.params)
            else:
                job.set_status("error", str(e) or "Stopped")
        except Exception as e:
            if job.cancelling:  # a child killed by the cancel failed the step it was in
                job.set_status("cancelled")
            else:
                log.exception("Job failed")
                job.set_status("error", f"{type(e).__name__}: {e}")
        else:
            job.set_status("done")
        finally:
            clear_cancel()
            unsubscribe()
            log.removeHandler(handler)
            self._save(job)
            pipeline.release_models()  # don't keep GPU memory between jobs
