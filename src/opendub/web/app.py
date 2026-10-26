"""Local web frontend for OpenDub (FastAPI): `opendub web`.

By default only for this computer: it listens on 127.0.0.1 and only answers requests
addressed to localhost (no DNS rebinding). With `opendub web --lan` it listens on every
interface and answers any host name, but only to requests carrying the token printed
in the terminal (in the link, then in a cookie, or as a bearer token); there is no
mode open to the network without it. It drives the existing pipeline and its cache in
work/; it adds no logic of its own to the phases.
"""

from __future__ import annotations

import hmac
import json
import re
from pathlib import Path
from typing import Literal

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .. import download, mix, storage
from .. import speakers as speakers_mod
from ..workdir import WorkDir
from . import videos
from .jobs import ACTIVE, VIDEO_ID, JobManager, JobOptions, Runner

STATIC = Path(__file__).parent / "static"
KEEPALIVE_S = 15.0
COOKIE = "opendub_token"
# what a browser without the token sees in --lan mode: the only page served without it
ENTRY_PAGE = """<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>OpenDub</title>
<body style="font-family: system-ui, sans-serif; max-width: 34rem; margin: 15vh auto; padding: 0 16px; line-height: 1.5">
<h1>OpenDub</h1>
<p>Open the link printed in the terminal where <code>opendub web --lan</code> runs: it carries the access token.</p>
<p lang="es">Abre el enlace que muestra el terminal donde corre <code>opendub web --lan</code>: lleva el token de acceso.</p>
</body></html>"""


class JobRequest(BaseModel):
    url: str = Field(min_length=1)
    separate: bool = True
    tts: Literal["edge", "clone"] = "clone"
    # as the CLI: auto, CosyVoice when several people speak and Chatterbox for one voice
    engine: Literal["auto", "chatterbox", "indextts", "cosyvoice"] = "auto"
    voice: str = "es-ES-AlvaroNeural"
    bg_volume: float = Field(0.0, ge=-40.0, le=12.0)
    # reuse the translation made for another engine: only TTS and the mix are redone
    keep_translation: bool = False
    multi_speaker: bool = False  # several voices (needs `setup-engine nemotron`)
    review: bool = False  # stop after the translation, to edit it before the voice
    # engines to dub with after `engine`, one after another, each its own version (several at once)
    then: list[Literal["chatterbox", "indextts", "cosyvoice"]] = Field(default_factory=list, max_length=3)


class SubtitlesUpload(BaseModel):
    name: str = Field(min_length=1, max_length=200)  # its extension says the format (.ass, .vtt, .srt)
    text: str = Field(max_length=5_000_000)


class EnginesRequest(BaseModel):
    engines: list[Literal["chatterbox", "indextts", "cosyvoice"]] = Field(min_length=1, max_length=3)


class RetouchRequest(BaseModel):
    takes: list[int] = []  # sentences to speak again with another take; edited ones always are


class SpeakerChange(BaseModel):
    id: int
    speaker: str = Field(min_length=1, max_length=2)


class SpeakerName(BaseModel):
    name: str = Field(max_length=60)


class SpeakerMerge(BaseModel):
    into: str = Field(min_length=1, max_length=2)


class SegmentEdit(BaseModel):
    id: int
    text: str = Field(min_length=1)


def fail(status: int, code: str, message: str, **params) -> HTTPException:
    """An API error the page can translate: `code` names it (the page's err_<code> text, filled with
    `params`), `message` is the English, technical text it shows only as a detail."""
    return HTTPException(status, {"code": code, "message": message, "params": params})


def check_id(vid: str) -> str:
    if not VIDEO_ID.fullmatch(vid):
        raise fail(404, "unknown_video", "Unknown video")
    return vid


def create_app(work_root: Path = Path("work"), runner: Runner | None = None,
               allowed_hosts: tuple[str, ...] = ("127.0.0.1", "localhost"), token: str | None = None) -> FastAPI:
    """`token`: the --lan mode. Every host name is accepted (the computer's LAN address or name), and every
    request needs the token instead."""
    work_root = work_root.resolve()
    work_root.mkdir(parents=True, exist_ok=True)
    manager = JobManager(work_root, runner) if runner else JobManager(work_root)
    app = FastAPI(title="OpenDub", docs_url=None, redoc_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["*"] if token else list(allowed_hosts))
    app.state.manager = manager

    if token:
        def carries_token(request: Request) -> bool:
            bearer = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
            given = request.cookies.get(COOKIE) or bearer
            return bool(given) and hmac.compare_digest(given.encode(), token.encode())

        @app.middleware("http")
        async def require_token(request: Request, call_next):
            """401 without the token. The link's ?token= is swapped for a cookie (and taken out of the address
            bar); the entry page is the only thing answered without it."""
            given = request.query_params.get("token")
            if given is not None:
                if not hmac.compare_digest(given.encode(), token.encode()):
                    return HTMLResponse(ENTRY_PAGE, status_code=401)
                rest = request.url.remove_query_params("token")
                response = RedirectResponse(rest.path + (f"?{rest.query}" if rest.query else ""), status_code=303)
                response.set_cookie(COOKIE, token, httponly=True, samesite="strict", max_age=30 * 24 * 3600)
                return response
            if carries_token(request):
                return await call_next(request)
            if request.method == "GET" and request.url.path == "/":
                return HTMLResponse(ENTRY_PAGE, status_code=200)
            return JSONResponse({"detail": {"code": "unauthorized", "message": "Open the link with the token "
                                            "printed in the terminal", "params": {}}}, status_code=401)

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
                "queued": sum(j.status == "queued" for j in active),
                "diarizer": videos.diarizer()}

    @app.get("/engines")
    def list_engines() -> list[dict]:
        """The cloning engines, whether each one is ready to use and how to install it if not."""
        return videos.engines()

    @app.post("/jobs")
    def create_job(req: JobRequest) -> dict:
        if req.tts == "clone":
            for choice in [req.engine, *req.then]:
                engine = next(e for e in videos.engines() if e["id"] == choice)
                if not engine["installed"]:
                    raise fail(422, "not_installed",
                               f"{engine['name']} is not installed. Install it with: {engine['setup']}",
                               engine=engine["name"], cmd=engine["setup"])
        elif req.then:
            raise fail(422, "not_cloned", "Dubbing with several engines needs the cloned voice")
        if req.multi_speaker and not videos.diarizer()["installed"]:
            raise fail(422, "no_diarizer", f"Several voices need Nemotron 3 Diarization. Install it with: "
                                          f"{videos.diarizer()['setup']}", cmd=videos.diarizer()["setup"])
        try:
            job = manager.submit(JobOptions(**req.model_dump()))
        except Exception as e:  # not a YouTube URL or id
            raise fail(422, "not_youtube", f"Not a YouTube video: {e}") from e
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
            raise fail(404, "no_job", "No job for this video")
        return saved

    @app.post("/jobs/{vid}/then")
    def queue_after(vid: str, req: EnginesRequest) -> dict:
        """More engines for a video being dubbed: dubbed after its job, one after another, with its options."""
        for choice in req.engines:
            engine = next(e for e in videos.engines() if e["id"] == choice)
            if not engine["installed"]:
                raise fail(422, "not_installed",
                           f"{engine['name']} is not installed. Install it with: {engine['setup']}",
                           engine=engine["name"], cmd=engine["setup"])
        running = manager.get(check_id(vid))
        if running and running.options.tts != "clone":
            raise fail(422, "not_cloned", "Dubbing with several engines needs the cloned voice")
        job = manager.queue_after(vid, list(req.engines))
        if not job:
            raise fail(404, "no_job", "No job for this video")
        return job.summary()

    @app.post("/jobs/{vid}/cancel")
    def cancel_job(vid: str) -> dict:
        """Cancel a video's queued or running job; what it had done stays cached."""
        job = manager.cancel(check_id(vid))
        if not job:
            raise fail(404, "no_job", "No job for this video")
        return job.summary()

    @app.get("/jobs/{vid}/events")
    def job_events(vid: str, request: Request) -> StreamingResponse:
        """Server-sent events: everything since the start (or since Last-Event-ID), then live, until the job ends."""
        job = manager.get(check_id(vid))
        if not job:
            raise fail(404, "no_job", "No job for this video in this server run")
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
    def ensure_free(wd: WorkDir) -> None:
        """409 when another process (the CLI, or this server's running job) holds the video."""
        if holder := wd.holder():
            raise fail(409, "busy", f"Another OpenDub process is working on this video ({holder}): edit it when it ends",
                       holder=holder)

    def folder(vid: str) -> WorkDir:
        wd = WorkDir(work_root, check_id(vid), create=False)  # unknown ids must not create folders
        if not wd.meta.exists():
            raise fail(404, "unknown_video", "Unknown video")
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
            raise fail(404, "no_thumbnail", "No thumbnail")
        return FileResponse(wd.thumbnail, media_type="image/jpeg")

    no_thumbnail: set[str] = set()  # don't ask YouTube again in this server run

    @app.get("/videos/{vid}/output.mp4")
    def output(vid: str) -> FileResponse:
        """The dubbed video; FileResponse answers Range requests (206), so the player can seek."""
        wd = folder(vid)
        if not wd.output.exists():
            raise fail(404, "not_dubbed", "Not dubbed yet")
        return FileResponse(wd.output, media_type="video/mp4", filename=f"{vid}.es.mp4",
                            content_disposition_type="inline")

    @app.delete("/videos/{vid}/outputs/{version}")
    def delete_version(vid: str, version: str) -> dict:
        """Delete one of the kept dubs; the latest one stays (output.mp4 and the page's issues are its)."""
        wd = folder(vid)
        ensure_free(wd)
        try:
            videos.delete_output(wd, version)
        except LookupError:
            raise fail(404, "no_dub", "No such dub")
        except ValueError as e:
            raise fail(409, "cannot_delete_latest", str(e))
        return {"outputs": videos.outputs(wd)}

    @app.get("/videos/{vid}/outputs/{version}.mp4")
    def output_version(vid: str, version: str) -> FileResponse:
        """One of the dubs kept by mix.archive (videos.outputs lists them), with Range support."""
        wd = folder(vid)
        path = wd.outputs_dir / f"{version}.mp4"
        if not mix.VERSION.fullmatch(version) or not path.exists():
            raise fail(404, "no_dub", "No such dub")
        return FileResponse(path, media_type="video/mp4", filename=f"{vid}.es.{version}.mp4",
                            content_disposition_type="inline")

    @app.get("/videos/{vid}/outputs/{version}/export/{fmt}")
    def export_version(vid: str, version: str, fmt: str) -> FileResponse:
        """A version as subtitles (srt, srt-orig), an MKV with both audio tracks, or its audio
        (m4a): made on first request, in seconds, and kept. "latest" is output.mp4's version."""
        from .. import export

        wd = folder(vid)
        if fmt not in export.FORMATS:
            raise fail(404, "unknown_format", "Unknown format")
        job = manager.get(vid)
        if version == "latest" and job and job.status == "running":
            raise fail(409, "dubbing", "This video is being dubbed; export it when the job ends")
        try:
            path = export.export(wd, fmt, version)
        except LookupError:
            raise fail(404, "no_dub", "No such dub")
        except ValueError as e:  # the original video was deleted to save space
            raise fail(409, "needs_video", str(e)) from e
        media_type = {"mkv": "video/x-matroska", "m4a": "audio/mp4"}.get(fmt, "application/x-subrip")
        return FileResponse(path, media_type=media_type, filename=f"{vid}.{path.name}")

    @app.get("/videos/{vid}/translation")
    def get_translation(vid: str) -> dict:
        data = videos.translation(folder(vid), manager)
        if data is None:
            raise fail(404, "not_translated", "Not translated yet")
        return data

    @app.get("/videos/{vid}/translation/export/{fmt}")
    def export_translation(vid: str, fmt: str) -> FileResponse:
        """The translation as subtitles with who says each sentence (ass, vtt) or without (srt)."""
        from .. import subtitles

        wd = folder(vid)
        if fmt not in subtitles.FORMATS:
            raise fail(404, "unknown_format", "Unknown format")
        if not wd.translation.exists():
            raise fail(404, "not_translated", "Not translated yet")
        path = subtitles.export(wd, fmt)
        media_type = {"ass": "text/x-ssa", "vtt": "text/vtt"}.get(fmt, "application/x-subrip")
        return FileResponse(path, media_type=media_type, filename=f"{vid}.{path.name}")

    @app.post("/videos/{vid}/translation/import")
    def import_translation(vid: str, upload: SubtitlesUpload) -> dict:
        """Corrected subtitles back into the translation: texts as hand edits, names as speakers."""
        from .. import subtitles

        wd = folder(vid)
        job = manager.get(vid)
        if job and job.status in ACTIVE:
            raise fail(409, "dubbing", "This video is being dubbed; edit it when the job ends")
        if not wd.translation.exists():
            raise fail(404, "not_translated", "Not translated yet")
        ensure_free(wd)
        try:
            done = subtitles.import_cues(wd, subtitles.parse(upload.name, upload.text.lstrip("\ufeff")))
        except ValueError as e:  # an unknown format, a cue with no sentence, a name that is no speaker
            raise fail(422, "bad_subtitles", str(e)) from e
        return {"imported": done, "translation": videos.translation(wd, manager),
                "speakers": videos.speakers_info(wd)}

    @app.put("/videos/{vid}/translation")
    def put_translation(vid: str, edits: list[SegmentEdit]) -> dict:
        wd = folder(vid)
        job = manager.get(vid)
        if job and job.status in ACTIVE:
            raise fail(409, "dubbing", "This video is being dubbed; edit it when the job ends")
        if not wd.translation.exists():
            raise fail(404, "not_translated", "Not translated yet")
        ensure_free(wd)
        try:
            videos.save_translation(wd, [e.model_dump() for e in edits])
        except KeyError as e:
            raise fail(422, "no_segment", f"No segment {e.args[0]}", id=e.args[0]) from e
        data = videos.translation(wd, manager)
        if data is None:  # its files went away meanwhile
            raise fail(404, "not_translated", "Not translated yet")
        return data

    @app.post("/videos/{vid}/retouch")
    def retouch(vid: str, req: RetouchRequest) -> dict:
        """Queue a retouch of the latest dub: its edited sentences and the takes asked for."""
        wd = folder(vid)
        job = manager.get(vid)
        if job and job.status in ACTIVE:
            raise fail(409, "dubbing", "This video is being dubbed; retouch it when the job ends")
        ensure_free(wd)
        try:
            pending = videos.retouchable(wd, req.takes)
        except LookupError as e:
            raise (fail(422, "cannot_retouch", str(e.args[0])) if e.args else fail(404, "not_dubbed", "No dub yet")) from e
        if not pending:
            raise fail(422, "nothing_to_retouch", "Nothing to retouch: no edited sentence and no take asked for")
        saved = (manager.saved(vid) or {}).get("options") or {}
        fields = {f for f in JobOptions.__dataclass_fields__} - {"url", "retouch"}
        options = JobOptions(url=vid, **{k: v for k, v in saved.items() if k in fields}, retouch=sorted(set(req.takes)))
        engine = videos.dub_engine(wd)
        if engine != "edge":
            info = next(e for e in videos.engines() if e["id"] == engine)
            if not info["installed"]:
                raise fail(422, "not_installed", f"{info['name']} is not installed. Install it with: {info['setup']}",
                           engine=info["name"], cmd=info["setup"])
        job = manager.submit(options)
        return {"id": job.id, **job.summary(), "segments": pending}

    # --- speakers (several voices) ---------------------------------------------
    def editable(vid: str) -> WorkDir:
        wd = folder(vid)
        job = manager.get(vid)
        if job and job.status in ACTIVE:
            raise fail(409, "dubbing", "This video is being dubbed; edit it when the job ends")
        if not wd.translation.exists():
            raise fail(404, "not_translated", "Not translated yet")
        ensure_free(wd)
        return wd

    @app.get("/videos/{vid}/speakers")
    def get_speakers(vid: str) -> list[dict]:
        return videos.speakers_info(folder(vid))

    @app.get("/videos/{vid}/speakers/{speaker}.wav")
    def speaker_sample(vid: str, speaker: str) -> FileResponse:
        path = videos.speaker_sample(folder(vid), speaker)
        if path is None:
            raise fail(404, "no_sample", "No sample of that speaker")
        return FileResponse(path, media_type="audio/wav")

    @app.put("/videos/{vid}/speakers/{speaker}")
    def rename_speaker(vid: str, speaker: str, req: SpeakerName) -> list[dict]:
        wd = folder(vid)
        try:
            speakers_mod.rename(wd, speaker, req.name)
        except ValueError as e:
            raise fail(404, "no_speaker", str(e)) from e
        return videos.speakers_info(wd)

    @app.post("/videos/{vid}/speakers/{speaker}/merge")
    def merge_speaker(vid: str, speaker: str, req: SpeakerMerge) -> dict:
        wd = editable(vid)
        try:
            moved = speakers_mod.merge(wd, speaker, req.into)
        except ValueError as e:
            raise fail(422, "invalid_speakers", str(e)) from e
        return {"moved": moved, "speakers": videos.speakers_info(wd), "translation": videos.translation(wd, manager)}

    @app.put("/videos/{vid}/segments/speakers")
    def change_speakers(vid: str, changes: list[SpeakerChange]) -> dict:
        wd = editable(vid)
        try:
            speakers_mod.reassign(wd, {c.id: c.speaker for c in changes})
        except ValueError as e:
            raise fail(422, "invalid_speakers", str(e)) from e
        except KeyError as e:
            raise fail(422, "no_segment", f"No segment {e.args[0]}", id=e.args[0]) from e
        return {"speakers": videos.speakers_info(wd), "translation": videos.translation(wd, manager)}

    # --- storage ------------------------------------------------------------------
    @app.get("/videos/{vid}/storage")
    def get_storage(vid: str) -> dict:
        """What the video takes on disk: the groups that can be deleted, and what always stays."""
        return storage.usage(folder(vid))

    @app.delete("/videos/{vid}/storage/{group}")
    def delete_storage(vid: str, group: str) -> dict:
        wd = folder(vid)
        job = manager.get(vid)
        if job and job.status in ACTIVE:
            raise fail(409, "dubbing", "This video is being dubbed; free its space when the job ends")
        ensure_free(wd)
        if group not in storage.GROUPS:
            raise fail(404, "unknown_group", "Unknown group")
        freed = storage.delete(wd, group)
        return {"freed": freed, **storage.usage(wd)}

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
            raise fail(422, "invalid_style", str(e)) from e
        return get_style()

    @app.get("/videos/{vid}/style")
    def get_video_style(vid: str) -> dict:
        return videos.video_style(folder(vid))

    @app.put("/videos/{vid}/style")
    def put_video_style(vid: str, data: dict = Body()) -> dict:
        wd = folder(vid)
        ensure_free(wd)
        try:
            videos.save_style(wd.path / videos.style.FILE, data)
        except ValueError as e:
            raise fail(422, "invalid_style", str(e)) from e
        return videos.video_style(wd)

    @app.get("/videos/{vid}/issues")
    def get_issues(vid: str, version: str | None = None) -> list[dict]:
        try:
            return videos.issues(folder(vid), version)
        except LookupError:
            raise fail(404, "no_dub", "No such dub")

    @app.get("/videos/{vid}/versions/{version}")
    def get_version(vid: str, version: str) -> dict:
        """A kept dub's numbers, issues and clips; "latest" is output.mp4's."""
        try:
            return videos.version_detail(folder(vid), version)
        except LookupError:
            raise fail(404, "no_dub", "No such dub")

    @app.get("/videos/{vid}/tts/{name}")
    def clip(vid: str, name: str) -> FileResponse:
        wd = folder(vid)
        if not re.fullmatch(r"\d{4}\.wav", name) or not (wd.tts_dir / name).exists():
            raise fail(404, "no_clip", "No such clip")
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


def serve(app: FastAPI, port: int, host: str = "127.0.0.1") -> None:
    """Run the app with uvicorn on `host` (every interface in --lan mode), guarding a running dub against a stray Ctrl+C.

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
    config = uvicorn.Config(app, host=host, port=port, log_level="warning", timeout_graceful_shutdown=3)
    Server(config).run()
