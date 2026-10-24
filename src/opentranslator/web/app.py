"""Local web frontend for OpenTranslator (FastAPI): `opentranslator web`.

Only meant for this computer: it listens on 127.0.0.1 and only answers requests
addressed to localhost (no DNS rebinding). It drives the existing pipeline and
its cache in work/; it adds no logic of its own to the phases.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .. import download
from ..workdir import WorkDir
from . import videos
from .jobs import ACTIVE, VIDEO_ID, JobManager, JobOptions, Runner

STATIC = Path(__file__).parent / "static"
KEEPALIVE_S = 15.0


class JobRequest(BaseModel):
    url: str = Field(min_length=1)
    separate: bool = True
    tts: Literal["edge", "clone"] = "clone"
    engine: Literal["auto", "chatterbox", "indextts"] = "auto"
    voice: str = "es-ES-AlvaroNeural"
    bg_volume: float = Field(0.0, ge=-40.0, le=12.0)


class SegmentEdit(BaseModel):
    id: int
    text: str = Field(min_length=1)


def check_id(vid: str) -> str:
    if not VIDEO_ID.fullmatch(vid):
        raise HTTPException(404, "Unknown video")
    return vid


def create_app(work_root: Path = Path("work"), runner: Runner | None = None,
               allowed_hosts: tuple[str, ...] = ("127.0.0.1", "localhost")) -> FastAPI:
    work_root = work_root.resolve()
    work_root.mkdir(parents=True, exist_ok=True)
    manager = JobManager(work_root, runner) if runner else JobManager(work_root)
    app = FastAPI(title="OpenTranslator", docs_url=None, redoc_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(allowed_hosts))
    app.state.manager = manager
    app.state.work_root = work_root

    # --- jobs --------------------------------------------------------------
    @app.post("/jobs")
    def create_job(req: JobRequest) -> dict:
        try:
            job = manager.submit(JobOptions(**req.model_dump()))
        except Exception as e:  # not a YouTube URL or id
            raise HTTPException(422, f"Not a YouTube video: {e}") from e
        return {"id": job.id, **job.summary()}

    @app.get("/jobs")
    def list_jobs() -> list[dict]:
        """Running job first, then the queue: what the page reconnects to after a reload."""
        return [j.summary() for j in manager.active()]

    @app.get("/jobs/{vid}")
    def get_job(vid: str) -> dict:
        job = manager.get(check_id(vid))
        if job:
            return job.summary()
        saved = manager.saved(vid)
        if not saved:
            raise HTTPException(404, "No job for this video")
        return saved

    @app.get("/jobs/{vid}/events")
    def job_events(vid: str, request: Request) -> StreamingResponse:
        """Server-sent events: everything since the start (or since Last-Event-ID), then live, until the job ends."""
        job = manager.get(check_id(vid))
        if not job:
            raise HTTPException(404, "No job for this video in this server run")
        last = request.headers.get("last-event-id")
        since = int(last) + 1 if last and last.isdigit() else 0

        def stream():
            seq = since
            yield "retry: 2000\n\n"
            while True:
                events, over = job.wait(seq, KEEPALIVE_S)
                for event in events:
                    yield f"id: {event['seq']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
                    seq = event["seq"] + 1
                if over and not events:
                    yield "event: end\ndata: {}\n\n"
                    return
                if not events:
                    yield ": keepalive\n\n"

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # --- videos ------------------------------------------------------------
    def folder(vid: str) -> WorkDir:
        wd = WorkDir(work_root, check_id(vid), create=False)  # unknown ids must not create folders
        if not wd.meta.exists():
            raise HTTPException(404, "Unknown video")
        return wd

    @app.get("/videos")
    def list_videos() -> list[dict]:
        return videos.list_videos(work_root, manager)

    @app.get("/videos/{vid}")
    def get_video(vid: str) -> dict:
        return videos.summary(folder(vid), manager)

    @app.get("/videos/{vid}/thumbnail")
    def thumbnail(vid: str) -> FileResponse:
        wd = folder(vid)
        if vid not in no_thumbnail and not download.thumbnail(wd):  # videos downloaded before thumbnails
            no_thumbnail.add(vid)
        if not wd.thumbnail.exists():
            raise HTTPException(404, "No thumbnail")
        return FileResponse(wd.thumbnail, media_type="image/jpeg")

    no_thumbnail: set[str] = set()  # don't ask YouTube again in this server run

    @app.get("/videos/{vid}/output.mp4")
    def output(vid: str) -> FileResponse:
        """The dubbed video; FileResponse answers Range requests (206), so the player can seek."""
        wd = folder(vid)
        if not wd.output.exists():
            raise HTTPException(404, "Not dubbed yet")
        return FileResponse(wd.output, media_type="video/mp4", filename=f"{vid}.es.mp4",
                            content_disposition_type="inline")

    @app.get("/videos/{vid}/translation")
    def get_translation(vid: str) -> dict:
        data = videos.translation(folder(vid), manager)
        if data is None:
            raise HTTPException(404, "Not translated yet")
        return data

    @app.put("/videos/{vid}/translation")
    def put_translation(vid: str, edits: list[SegmentEdit]) -> dict:
        wd = folder(vid)
        job = manager.get(vid)
        if job and job.status in ACTIVE:
            raise HTTPException(409, "This video is being dubbed; edit it when the job ends")
        if not wd.translation.exists():
            raise HTTPException(404, "Not translated yet")
        try:
            videos.save_translation(wd, [e.model_dump() for e in edits])
        except KeyError as e:
            raise HTTPException(422, f"No segment {e.args[0]}") from e
        return videos.translation(wd, manager)

    @app.get("/videos/{vid}/issues")
    def get_issues(vid: str) -> list[dict]:
        return videos.issues(folder(vid))

    @app.get("/videos/{vid}/tts/{name}")
    def clip(vid: str, name: str) -> FileResponse:
        wd = folder(vid)
        if not re.fullmatch(r"\d{4}\.wav", name) or not (wd.tts_dir / name).exists():
            raise HTTPException(404, "No such clip")
        return FileResponse(wd.tts_dir / name, media_type="audio/wav")

    # --- page --------------------------------------------------------------
    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app
