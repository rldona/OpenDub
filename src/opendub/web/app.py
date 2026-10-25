"""Local web frontend for OpenDub (FastAPI): `opendub web`.

Only meant for this computer: it listens on 127.0.0.1 and only answers requests
addressed to localhost (no DNS rebinding). It drives the existing pipeline and
its cache in work/; it adds no logic of its own to the phases.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Literal

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .. import download, mix
from ..workdir import WorkDir
from . import videos
from .jobs import ACTIVE, VIDEO_ID, JobManager, JobOptions, Runner

STATIC = Path(__file__).parent / "static"
KEEPALIVE_S = 15.0


class JobRequest(BaseModel):
    url: str = Field(min_length=1)
    separate: bool = True
    tts: Literal["edge", "clone"] = "clone"
    engine: Literal["auto", "chatterbox", "indextts", "cosyvoice"] = "auto"
    voice: str = "es-ES-AlvaroNeural"
    bg_volume: float = Field(0.0, ge=-40.0, le=12.0)
    # reuse the translation made for another engine: only TTS and the mix are redone
    keep_translation: bool = False


class RetouchRequest(BaseModel):
    takes: list[int] = []  # sentences to speak again with another take; edited ones always are


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
    app = FastAPI(title="OpenDub", docs_url=None, redoc_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(allowed_hosts))
    app.state.manager = manager

    @app.middleware("http")
    async def revalidate_page(request: Request, call_next):
        """The page and its files change with the code: make the browser revalidate them on every load."""
        response = await call_next(request)
        if request.url.path == "/" or request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-cache"
        return response

    app.state.work_root = work_root

    # --- jobs --------------------------------------------------------------
    @app.get("/status")
    def status() -> dict:
        """What the footer shows: the app version, the work folder and the jobs."""
        from importlib.metadata import version

        active = manager.active()
        return {"version": version("opendub"), "work_root": work_root.name,
                "running": sum(j.status == "running" for j in active),
                "queued": sum(j.status == "queued" for j in active)}

    @app.get("/engines")
    def list_engines() -> list[dict]:
        """The cloning engines, whether each one is ready to use and how to install it if not."""
        return videos.engines()

    @app.post("/jobs")
    def create_job(req: JobRequest) -> dict:
        if req.tts == "clone":
            engine = next(e for e in videos.engines() if e["id"] == req.engine)
            if not engine["installed"]:
                raise HTTPException(422, f"{engine['name']} is not installed. Install it with: {engine['setup']}")
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

    @app.delete("/videos/{vid}/outputs/{version}")
    def delete_version(vid: str, version: str) -> dict:
        """Delete one of the kept dubs; the latest one stays (output.mp4 and the page's issues are its)."""
        wd = folder(vid)
        try:
            videos.delete_output(wd, version)
        except LookupError:
            raise HTTPException(404, "No such dub")
        except ValueError as e:
            raise HTTPException(409, str(e))
        return {"outputs": videos.outputs(wd)}

    @app.get("/videos/{vid}/outputs/{version}.mp4")
    def output_version(vid: str, version: str) -> FileResponse:
        """One of the dubs kept by mix.archive (videos.outputs lists them), with Range support."""
        wd = folder(vid)
        path = wd.outputs_dir / f"{version}.mp4"
        if not mix.VERSION.fullmatch(version) or not path.exists():
            raise HTTPException(404, "No such dub")
        return FileResponse(path, media_type="video/mp4", filename=f"{vid}.es.{version}.mp4",
                            content_disposition_type="inline")

    @app.get("/videos/{vid}/outputs/{version}/export/{fmt}")
    def export_version(vid: str, version: str, fmt: str) -> FileResponse:
        """A version as subtitles (srt, srt-orig), an MKV with both audio tracks, or its audio
        (m4a): made on first request, in seconds, and kept. "latest" is output.mp4's version."""
        from .. import export

        wd = folder(vid)
        if fmt not in export.FORMATS:
            raise HTTPException(404, "Unknown format")
        job = manager.get(vid)
        if version == "latest" and job and job.status == "running":
            raise HTTPException(409, "This video is being dubbed; export it when the job ends")
        try:
            path = export.export(wd, fmt, version)
        except LookupError:
            raise HTTPException(404, "No such dub")
        media_type = {"mkv": "video/x-matroska", "m4a": "audio/mp4"}.get(fmt, "application/x-subrip")
        return FileResponse(path, media_type=media_type, filename=f"{vid}.{path.name}")

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

    @app.post("/videos/{vid}/retouch")
    def retouch(vid: str, req: RetouchRequest) -> dict:
        """Queue a retouch of the latest dub: its edited sentences and the takes asked for."""
        wd = folder(vid)
        job = manager.get(vid)
        if job and job.status in ACTIVE:
            raise HTTPException(409, "This video is being dubbed; retouch it when the job ends")
        try:
            pending = videos.retouchable(wd, req.takes)
        except LookupError as e:
            raise HTTPException(404 if not e.args else 422, str(e.args[0]) if e.args else "No dub yet") from e
        if not pending:
            raise HTTPException(422, "Nothing to retouch: no edited sentence and no take asked for")
        saved = (manager.saved(vid) or {}).get("options") or {}
        fields = {f for f in JobOptions.__dataclass_fields__} - {"url", "retouch"}
        options = JobOptions(url=vid, **{k: v for k, v in saved.items() if k in fields}, retouch=sorted(set(req.takes)))
        engine = videos.dub_engine(wd)
        if engine != "edge":
            info = next(e for e in videos.engines() if e["id"] == engine)
            if not info["installed"]:
                raise HTTPException(422, f"{info['name']} is not installed. Install it with: {info['setup']}")
        job = manager.submit(options)
        return {"id": job.id, **job.summary(), "segments": pending}

    @app.get("/style")
    def get_style() -> dict:
        """The style every video is translated with (work/style.json)."""
        return videos.style.read(work_root / videos.style.FILE).to_json()

    @app.put("/style")
    def put_style(data: dict = Body()) -> dict:
        """Body: style.json's shape (see opendub.style); checked there."""
        try:
            videos.save_style(work_root / videos.style.FILE, data)
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
        return get_style()

    @app.get("/videos/{vid}/style")
    def get_video_style(vid: str) -> dict:
        return videos.video_style(folder(vid))

    @app.put("/videos/{vid}/style")
    def put_video_style(vid: str, data: dict = Body()) -> dict:
        wd = folder(vid)
        try:
            videos.save_style(wd.path / videos.style.FILE, data)
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
        return videos.video_style(wd)

    @app.get("/videos/{vid}/issues")
    def get_issues(vid: str, version: str | None = None) -> list[dict]:
        try:
            return videos.issues(folder(vid), version)
        except LookupError:
            raise HTTPException(404, "No such dub")

    @app.get("/videos/{vid}/versions/{version}")
    def get_version(vid: str, version: str) -> dict:
        """A kept dub's numbers, issues and clips; "latest" is output.mp4's."""
        try:
            return videos.version_detail(folder(vid), version)
        except LookupError:
            raise HTTPException(404, "No such dub")

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


CONFIRM_S = 5.0  # a second Ctrl+C within this window stops a running dub


class ExitGuard:
    """Decides whether a Ctrl+C stops the server: not the first one while a dub is running."""

    def __init__(self, manager: JobManager, window: float = CONFIRM_S, clock=None):
        import time

        self.manager, self.window, self.clock = manager, window, clock or time.monotonic
        self.warned_at: float | None = None

    def allow(self, exiting: bool) -> bool:
        running = [j for j in self.manager.active() if j.status == "running"]
        now = self.clock()
        if running and not exiting and (self.warned_at is None or now - self.warned_at > self.window):
            from ..log import log

            self.warned_at = now
            log.warning(f"A dub is running ({running[0].id}): press Ctrl+C again within "
                        f"{self.window:.0f} s to stop it and the server")
            return False
        return True


def serve(app: FastAPI, port: int) -> None:
    """Run the app with uvicorn on 127.0.0.1, guarding a running dub against a stray Ctrl+C.

    Children (ffmpeg, the claude CLI, the IndexTTS worker) run in their own session,
    so the terminal's Ctrl+C reaches only the server: with a dub running, the first
    one only warns; a second within CONFIRM_S seconds stops the children and exits.
    The interrupted job is marked as such on the next start.
    """
    import uvicorn

    from .. import media

    media.CHILD_SESSION = True
    guard = ExitGuard(app.state.manager)

    class Server(uvicorn.Server):
        def handle_exit(self, sig, frame) -> None:
            if not guard.allow(self.should_exit):
                return
            media.stop_children()
            super().handle_exit(sig, frame)

    # a paused <video> keeps its connection open: don't let it hold the exit forever
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", timeout_graceful_shutdown=3)
    Server(config).run()
