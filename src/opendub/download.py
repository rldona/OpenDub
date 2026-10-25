"""Phase 1: download the video, audio and subtitles with yt-dlp."""

from __future__ import annotations

import copy
import json
import re
from typing import Any

import yt_dlp
from rich.progress import BarColumn, DownloadColumn, TransferSpeedColumn

from . import media
from .config import Settings
from .log import Progress, console, log
from .media import ffmpeg, probe
from .workdir import WorkDir, write_text_atomic

media.adopt_ytdlp()  # its ffmpeg children, too, stay out of the web server's Ctrl+C

_YT_ID = re.compile(r"(?:v=|youtu\.be/|shorts/|embed/|live/)([\w-]{11})")
_BASE_OPTS: dict[str, Any] = {"quiet": True, "no_warnings": True, "noprogress": True}


BOT_CHECK = "Sign in to confirm"


def explain(e: Exception) -> SystemExit:
    """A clear message for a failed YouTube request: a bot check, no connection, or the rest."""
    text = str(e)
    first = next((line for line in text.splitlines() if line.strip()), text)
    if BOT_CHECK in text:
        return SystemExit("YouTube asked to confirm this isn't a bot and refused the download. It is a temporary "
                          "block of this connection (often after many downloads in a short time): wait a while "
                          "and try again.")
    network = ("Unable to download", "getaddrinfo", "Name or service not known", "timed out",
               "Connection", "Network is unreachable", "Temporary failure in name resolution")
    if any(n in text for n in network):
        return SystemExit(f"Can't reach YouTube: is there an internet connection? ({first.strip()[:160]})")
    return SystemExit(f"YouTube download failed: {first.strip()[:200]}")


def video_id(url_or_id: str) -> str:
    """Extract the id from a YouTube URL (or return it as is if it already is an id)."""
    if re.fullmatch(r"[\w-]{11}", url_or_id):
        return url_or_id
    if m := _YT_ID.search(url_or_id):
        return m.group(1)
    with yt_dlp.YoutubeDL(_BASE_OPTS) as ydl:
        return ydl.extract_info(url_or_id, download=False, process=False)["id"]


def _pick_track(tracks: dict[str, Any], lang: str) -> str | None:
    """Pick the subtitle track that best matches the language."""
    keys = [k for k in tracks if k != "live_chat"]
    base = lang.split("-")[0]
    for candidate in (lang, base):
        if candidate in keys:
            return candidate
    return next((k for k in keys if k.split("-")[0] == base), None)


def _pick_auto_track(tracks: dict[str, Any], lang: str) -> str | None:
    # "<lang>-orig" is the ASR in the original language; the rest are machine translations
    base = lang.split("-")[0]
    if f"{base}-orig" in tracks:
        return f"{base}-orig"
    return _pick_track(tracks, lang)


class _ProgressHook:
    def __init__(self, progress: Progress):
        self.progress = progress
        self.tasks: dict[str, Any] = {}

    def __call__(self, d: dict[str, Any]) -> None:
        name = d.get("info_dict", {}).get("format_id", "?")
        total = d.get("total_bytes") or d.get("total_bytes_estimate")
        if name not in self.tasks:
            self.tasks[name] = self.progress.add_task(f"format {name}", total=total)
        self.progress.update(self.tasks[name], completed=d.get("downloaded_bytes", 0), total=total)


def _download_subs(raw: dict[str, Any], wd: WorkDir, kind: str, key: str) -> str | None:
    opts = {
        **_BASE_OPTS,
        "skip_download": True,
        "writesubtitles": kind == "manual",
        "writeautomaticsub": kind == "auto",
        "subtitleslangs": [key],
        "subtitlesformat": "json3/vtt/best",
        "outtmpl": str(wd.path / f"subs.{kind}.%(ext)s"),
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.process_ie_result(copy.deepcopy(raw), download=True)
    found = sorted(wd.path.glob(f"subs.{kind}.*"))
    return found[0].name if found else None


def thumbnail(wd: WorkDir) -> bool:
    """Save the video's thumbnail as thumbnail.jpg (for the web frontend); False if it can't."""
    if wd.thumbnail.exists():
        return True
    opts = {
        **_BASE_OPTS,
        "skip_download": True,
        "writethumbnail": True,
        "outtmpl": str(wd.path / "thumbnail.%(ext)s"),
        # skip_download: postprocessors must run before the (skipped) download
        "postprocessors": [{"key": "FFmpegThumbnailsConvertor", "format": "jpg", "when": "before_dl"}],
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([f"https://www.youtube.com/watch?v={wd.path.name}"])
    except Exception as e:  # cosmetic: never fail a phase over it
        log.warning(f"Could not get the thumbnail: {e}")
    return wd.thumbnail.exists()


def _info(url: str) -> dict[str, Any]:
    log.info("Fetching video info…")
    try:
        with yt_dlp.YoutubeDL(_BASE_OPTS) as ydl:
            return ydl.sanitize_info(ydl.extract_info(url, download=False, process=False))
    except yt_dlp.utils.DownloadError as e:
        raise explain(e) from None


def _fetch_media(raw: dict[str, Any], wd: WorkDir, settings: Settings) -> None:
    """The video (H.264 up to --max-height when there is one) and its 16 kHz mono audio for whisper."""
    h = settings.max_height
    opts = {
        **_BASE_OPTS,
        "format": (
            f"bv*[vcodec^=avc1][height<={h}]+ba[ext=m4a]"
            f"/bv*[height<={h}]+ba/b[height<={h}]/b"
        ),
        "merge_output_format": "mp4",
        "outtmpl": str(wd.path / "video.%(ext)s"),
        "overwrites": True,
    }
    with Progress(
        "[progress.description]{task.description}", BarColumn(), DownloadColumn(),
        TransferSpeedColumn(), console=console, transient=True,
    ) as progress:
        opts["progress_hooks"] = [_ProgressHook(progress)]
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.process_ie_result(copy.deepcopy(raw), download=True)
        except yt_dlp.utils.DownloadError as e:
            raise explain(e) from None
    v = next(s for s in probe(wd.video)["streams"] if s["codec_type"] == "video")
    log.info(f"Video: {v['codec_name']} {v['width']}x{v['height']}")
    log.info("Extracting audio (16 kHz mono for whisper)…")
    ffmpeg("-i", str(wd.video), "-vn", "-ac", "1", "-ar", "16000", str(wd.audio))


def run(url: str, wd: WorkDir, settings: Settings, force: bool = False) -> dict[str, Any]:
    params = {"max_height": settings.max_height, "source_lang": settings.source_lang}
    if not force and wd.is_done("download", params) and wd.meta.exists():
        if wd.video.exists() and wd.audio.exists():
            log.info("Download cached, skipping")
        else:  # deleted to save space (storage.py): fetch the media again, nothing else changes
            log.info("The original video was deleted to save space: downloading it again…")
            _fetch_media(_info(url), wd, settings)
        return json.loads(wd.meta.read_text())

    for old in wd.path.glob("subs.*"):
        old.unlink()

    raw = _info(url)
    lang = settings.source_lang or raw.get("language")  # None: whisper will detect it
    log.info(f"[bold]{raw['title']}[/] · {raw.get('duration', 0)}s · language {lang or '?'}")
    _fetch_media(raw, wd, settings)

    subs: dict[str, str | None] = {"manual": None, "auto": None}
    if key := _pick_track(raw.get("subtitles") or {}, lang or "en"):
        subs["manual"] = _download_subs(raw, wd, "manual", key)
    if key := _pick_auto_track(raw.get("automatic_captions") or {}, lang or "en"):
        subs["auto"] = _download_subs(raw, wd, "auto", key)
    log.info(f"Manual subtitles: {subs['manual'] or '—'} · auto-generated: {subs['auto'] or '—'}")

    meta = {
        "id": raw["id"],
        "title": raw["title"],
        "duration": raw.get("duration"),
        "uploader": raw.get("uploader"),
        "language": lang,
        "subs": subs,
    }
    write_text_atomic(wd.meta, json.dumps(meta, ensure_ascii=False, indent=2))
    thumbnail(wd)
    wd.mark_done("download", params)
    return meta
