"""What the web frontend shows about each video, read from its work folder.

Nothing here runs a phase: it reads the files the pipeline already writes
(meta.json, segments.json, translation.json, tts.json, overflow.log,
manifest.json) and, for translation edits, writes translation.json and
invalidates the phases that depend on it.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from .. import translate, tts
from ..config import Settings
from ..models import load_segments, save_segments
from ..workdir import WorkDir
from .jobs import ACTIVE, VIDEO_ID, JobManager

# overflow.log lines (see tts.run and mix.run)
_ISSUE_LINES = [
    ("overflow", re.compile(r"^#(\d+) @([\d.]+)s: (lasts .*?\(\+[\d.]+s\)) · (.*)$")),
    ("abnormal", re.compile(r"^#(\d+) @([\d.]+)s: (abnormal duration after regenerating .*?) · (.*)$")),
    ("fallback", re.compile(r"^#(\d+) @([\d.]+)s: (cloned voice failed the quality check, used edge-tts) · (.*)$")),
    ("floor", re.compile(r"^#(\d+) @([\d.]+)s: (did not fit even shortened, duration[_ ]factor .*?) · (.*)$")),
]
ENGINE_NAMES = {"chatterbox": "Chatterbox V3", "indextts": "IndexTTS-2.5", "cosyvoice": "CosyVoice 3"}


def engines(settings: Settings | None = None) -> list[dict[str, Any]]:
    """The cloning engines for the selector: ready to use or not, and the command that installs them.

    Automatic uses Chatterbox and IndexTTS (tts.resolve_engine), so it needs both.
    """
    import importlib.util

    from .. import cosyvoice, indextts

    settings = settings or Settings()
    _, ix_python, ix_checkpoints = indextts.paths(settings.indextts_dir)
    ready = {
        "chatterbox": importlib.util.find_spec("chatterbox") is not None,
        "indextts": ix_python.exists() and (ix_checkpoints / "config.yaml").exists(),
        "cosyvoice": cosyvoice.installed(settings.cosyvoice_dir),
    }
    setup = {
        "chatterbox": "uv sync --extra clone",
        "indextts": "uv run opendub setup-engine indextts",
        "cosyvoice": "uv run opendub setup-engine cosyvoice",
    }
    auto_missing = [e for e in ("chatterbox", "indextts") if not ready[e]]
    out = [{"id": "auto", "name": "Automatic", "installed": not auto_missing,
            "setup": " && ".join(setup[e] for e in auto_missing) or None}]
    for e in tts.CLONE_ENGINES:
        out.append({"id": e, "name": ENGINE_NAMES[e], "installed": ready[e], "setup": None if ready[e] else setup[e]})
    return out


_DELAYED = re.compile(r"^#(\d+) (delayed [\d.]+s in the mix)$")


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _tts_index(wd: WorkDir) -> dict[str, Any] | None:
    data = _read_json(wd.tts_index)
    if isinstance(data, list):  # runs before tts.json had metadata
        return {"engine": None, "reference_f0_hz": None, "clips": data}
    return data


def video_ids(work_root: Path) -> list[str]:
    return sorted(p.parent.name for p in work_root.glob("*/meta.json") if VIDEO_ID.fullmatch(p.parent.name))


def status(wd: WorkDir, manager: JobManager) -> tuple[str, str | None]:
    """(pending | queued | running | done | error, error message)."""
    job = manager.get(wd.path.name)
    saved = manager.saved(wd.path.name)
    state = job.status if job else (saved or {}).get("status")
    error = job.error if job else (saved or {}).get("error")
    finished = wd.has("mix") and wd.output.exists()
    if state in ACTIVE:
        return state, None
    if state == "error" and not (finished and wd.output.stat().st_mtime > wd.job.stat().st_mtime):
        return "error", error
    return ("done" if finished else "pending"), None


def summary(wd: WorkDir, manager: JobManager) -> dict[str, Any]:
    meta = _read_json(wd.meta) or {}
    state, error = status(wd, manager)
    index = _tts_index(wd) or {}
    clips = index.get("clips") or []
    date = None
    for path in (wd.output, wd.job, wd.meta):
        if path.exists():
            date = datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")
            break
    translation = {s.id: s.text for s in load_segments(wd.translation)} if wd.translation.exists() else {}
    return {
        "id": wd.path.name,
        "title": meta.get("title"),
        "duration": meta.get("duration"),
        "uploader": meta.get("uploader"),
        "status": state,
        "error": error,
        "date": date,
        "engine": index.get("engine"),
        "reference_f0_hz": index.get("reference_f0_hz"),
        "clips": len(clips),
        "sped_up": sum(1 for c in clips if c.get("tempo", 1.0) > 1.0),
        "shortened": sum(1 for c in clips if c["id"] in translation and c.get("text") != translation[c["id"]]),
        "issues": len(issues(wd)) if state == "done" else 0,
        "options": (manager.saved(wd.path.name) or {}).get("options"),
        "outputs": outputs(wd),
    }


def outputs(wd: WorkDir) -> list[dict[str, Any]]:
    """The dubs kept per engine (mix.archive), newest first, and which one output.mp4 is."""
    if not wd.outputs_dir.exists():
        return []
    found = []
    for video in wd.outputs_dir.glob("*.mp4"):
        found.append({
            "engine": video.stem,
            "date": datetime.fromtimestamp(video.stat().st_mtime).isoformat(timespec="seconds"),
            "current": wd.output.exists() and video.samefile(wd.output),
        })
    return sorted(found, key=lambda o: o["date"], reverse=True)


def list_videos(work_root: Path, manager: JobManager) -> list[dict[str, Any]]:
    videos = [summary(WorkDir(work_root, vid, create=False), manager) for vid in video_ids(work_root)]
    order = {"running": 0, "queued": 1}  # then the rest, newest first
    return sorted(videos, key=lambda v: (order.get(v["status"], 2), _neg_date(v["date"])))


def _neg_date(date: str | None) -> float:
    return -datetime.fromisoformat(date).timestamp() if date else 0.0


# --- translation --------------------------------------------------------------
def _speaking_rate(wd: WorkDir, manager: JobManager) -> tts.Pace | None:
    """The calibrated rate the translation was capped with, if it was measured."""
    options = (manager.saved(wd.path.name) or {}).get("options") or {}
    index = _tts_index(wd) or {}
    engine = index.get("engine") or ("edge" if options.get("tts") == "edge" else None)
    if not engine:
        return None
    settings = Settings()
    voice = options.get("voice", settings.voice)
    ref = wd.path / "clone_ref.wav"
    return tts.cached_rate(wd.path.parent, engine, ref, voice, settings.rate)


def translation(wd: WorkDir, manager: JobManager) -> dict[str, Any] | None:
    if not (wd.translation.exists() and wd.segments.exists()):
        return None
    originals = load_segments(wd.segments)
    texts = {s.id: s.text for s in load_segments(wd.translation)}
    edited = set((_read_json(wd.translation_edits) or {}))
    pace = _speaking_rate(wd, manager)
    segments = []
    for i, seg in enumerate(originals):
        slot = translate._slot(originals, i)  # the same slot the translation was capped with
        segments.append({
            "id": seg.id, "start": seg.start, "end": seg.end, "original": seg.text,
            "text": texts.get(seg.id, ""), "slot": round(slot, 2),
            "max_chars": pace.max_chars(slot) if pace else None,
            "edited": str(seg.id) in edited,
        })
    return {"segments": segments, "chars_per_second": pace.cps if pace else None,
            "needs_regeneration": not (wd.has("tts") and wd.has("mix"))}


def save_translation(wd: WorkDir, edits: list[dict[str, Any]]) -> None:
    """Apply {id, text} edits to translation.json and invalidate TTS and mix.

    The next job for this video then redoes only those phases: the translation
    phase is still cached (its inputs didn't change), and TTS sees new texts.
    """
    segments = load_segments(wd.translation)
    by_id = {s.id: s for s in segments}
    for edit in edits:
        if edit["id"] not in by_id:
            raise KeyError(edit["id"])
    source = {s.id: s.text for s in load_segments(wd.segments)}
    kept = _read_json(wd.translation_edits) or {}
    for edit in edits:
        by_id[edit["id"]].text = edit["text"].strip()
        # remembered so a translation made again (e.g. for another engine) keeps them (translate.keep_edits)
        kept[str(edit["id"])] = {"source": source.get(edit["id"]), "text": edit["text"].strip()}
    save_segments(wd.translation, segments)
    wd.translation_edits.write_text(json.dumps(kept, ensure_ascii=False, indent=1), encoding="utf-8")
    wd.invalidate_from("tts")


# --- clips with problems --------------------------------------------------------
def issues(wd: WorkDir) -> list[dict[str, Any]]:
    """Clips listed in overflow.log, plus those the quality check had to redo, with their wav."""
    index = _tts_index(wd) or {}
    clips = {c["id"]: c for c in index.get("clips") or []}
    engine = index.get("engine")
    out: list[dict[str, Any]] = []
    seen = set()

    def add(kind: str, clip_id: int, message: str, start: float | None = None, text: str | None = None) -> None:
        if (kind, clip_id) in seen:
            return
        seen.add((kind, clip_id))
        clip = clips.get(clip_id, {})
        wav = Path(clip["file"]).name if clip.get("file") else None
        out.append({
            "id": clip_id, "kind": kind, "message": message,
            "start": start if start is not None else clip.get("start"),
            "text": text or clip.get("text"),
            "wav": f"/videos/{wd.path.name}/tts/{wav}" if wav and (wd.tts_dir / wav).exists() else None,
        })

    if wd.overflow_log.exists():
        for line in wd.overflow_log.read_text(encoding="utf-8").splitlines():
            for kind, pattern in _ISSUE_LINES:
                if m := pattern.match(line):
                    add(kind, int(m[1]), m[3], float(m[2]), m[4])
                    break
            else:
                if m := _DELAYED.match(line):
                    add("delayed", int(m[1]), m[2])
    for clip in clips.values():
        label = clip.get("voice") or ""
        if engine and engine != "edge" and label not in (engine, "edge"):
            add("repaired", clip["id"], f"redone by the quality check: {label}")
    order = {"fallback": 0, "floor": 1, "overflow": 2, "abnormal": 3, "repaired": 4, "delayed": 5}
    return sorted(out, key=lambda i: (order[i["kind"]], i["start"] or 0))
