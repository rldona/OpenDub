"""Fase 1: descarga de vídeo, audio y subtítulos con yt-dlp."""

from __future__ import annotations

import copy
import json
import re
from typing import Any

import yt_dlp
from rich.progress import BarColumn, DownloadColumn, Progress, TransferSpeedColumn

from .config import Settings
from .log import console, log
from .media import ffmpeg, probe
from .workdir import WorkDir

_YT_ID = re.compile(r"(?:v=|youtu\.be/|shorts/|embed/|live/)([\w-]{11})")
_BASE_OPTS: dict[str, Any] = {"quiet": True, "no_warnings": True, "noprogress": True}


def video_id(url_or_id: str) -> str:
    """Extrae el id de una URL de YouTube (o lo devuelve tal cual si ya es un id)."""
    if re.fullmatch(r"[\w-]{11}", url_or_id):
        return url_or_id
    if m := _YT_ID.search(url_or_id):
        return m.group(1)
    with yt_dlp.YoutubeDL(_BASE_OPTS) as ydl:
        return ydl.extract_info(url_or_id, download=False, process=False)["id"]


def _pick_track(tracks: dict[str, Any], lang: str) -> str | None:
    """Elige la pista de subtítulos que mejor encaja con el idioma."""
    keys = [k for k in tracks if k != "live_chat"]
    base = lang.split("-")[0]
    for candidate in (lang, base):
        if candidate in keys:
            return candidate
    return next((k for k in keys if k.split("-")[0] == base), None)


def _pick_auto_track(tracks: dict[str, Any], lang: str) -> str | None:
    # "<lang>-orig" es el ASR en el idioma original; el resto son traducciones automáticas
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
            self.tasks[name] = self.progress.add_task(f"formato {name}", total=total)
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


def run(url: str, wd: WorkDir, settings: Settings, force: bool = False) -> dict[str, Any]:
    params = {"max_height": settings.max_height, "source_lang": settings.source_lang}
    if not force and wd.is_done("download", params) and wd.meta.exists():
        log.info("Descarga en caché, la salto")
        return json.loads(wd.meta.read_text())

    for old in wd.path.glob("subs.*"):
        old.unlink()

    log.info("Obteniendo información del vídeo…")
    with yt_dlp.YoutubeDL(_BASE_OPTS) as ydl:
        raw = ydl.sanitize_info(ydl.extract_info(url, download=False, process=False))
    lang = settings.source_lang or raw.get("language")  # None: lo detectará whisper
    log.info(f"[bold]{raw['title']}[/] · {raw.get('duration', 0)}s · idioma {lang or '¿?'}")

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
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.process_ie_result(copy.deepcopy(raw), download=True)
    v = next(s for s in probe(wd.video)["streams"] if s["codec_type"] == "video")
    log.info(f"Vídeo: {v['codec_name']} {v['width']}x{v['height']}")

    log.info("Extrayendo audio (16 kHz mono para whisper)…")
    ffmpeg("-i", str(wd.video), "-vn", "-ac", "1", "-ar", "16000", str(wd.audio))

    subs: dict[str, str | None] = {"manual": None, "auto": None}
    if key := _pick_track(raw.get("subtitles") or {}, lang or "en"):
        subs["manual"] = _download_subs(raw, wd, "manual", key)
    if key := _pick_auto_track(raw.get("automatic_captions") or {}, lang or "en"):
        subs["auto"] = _download_subs(raw, wd, "auto", key)
    log.info(f"Subtítulos manuales: {subs['manual'] or '—'} · automáticos: {subs['auto'] or '—'}")

    meta = {
        "id": raw["id"],
        "title": raw["title"],
        "duration": raw.get("duration"),
        "uploader": raw.get("uploader"),
        "language": lang,
        "subs": subs,
    }
    wd.meta.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    wd.mark_done("download", params)
    return meta
