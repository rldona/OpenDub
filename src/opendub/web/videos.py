"""What the web frontend shows about each video, read from its work folder.

Nothing here runs a phase: it reads the files the pipeline already writes
(meta.json, segments.json, translation.json, tts.json, overflow.log,
manifest.json) and, for translation edits, writes translation.json and
invalidates the phases that depend on it.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from .. import retouch, style, translate, tts
from .. import voices as voices_mod
from ..config import Settings
from ..models import load_segments, save_segments
from ..workdir import WorkDir, write_text_atomic
from .jobs import ACTIVE, VIDEO_ID, JobManager

# overflow.log lines (see tts.run and mix.run)
_ISSUE_LINES = [
    ("overflow", re.compile(r"^#(\d+) @([\d.]+)s: (lasts .*?\(\+[\d.]+s\)) · (.*)$")),
    ("abnormal", re.compile(r"^#(\d+) @([\d.]+)s: (abnormal duration after regenerating .*?) · (.*)$")),
    ("fallback", re.compile(r"^#(\d+) @([\d.]+)s: (cloned voice failed the quality check, used edge-tts) · (.*)$")),
    ("floor", re.compile(r"^#(\d+) @([\d.]+)s: (did not fit even shortened, duration[_ ]factor .*?) · (.*)$")),
]
ENGINE_NAMES = {"chatterbox": "Chatterbox V3", "indextts": "IndexTTS-2.5", "cosyvoice": "CosyVoice 3",
                "chatterbox-es": "Chatterbox es-ES"}
WEB_ENGINES = ("chatterbox", "indextts", "cosyvoice")  # chatterbox-es is a CLI-only evaluation variant


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
    for e in WEB_ENGINES:
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
    newer = finished and wd.job.exists() and wd.output.stat().st_mtime > wd.job.stat().st_mtime
    if state == "error" and not newer:
        return "error", error
    if state == "cancelled" and not newer:
        return "cancelled", None
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
        "several_voices": index.get("speakers") is not None,  # the latest dub, from the web or the CLI
        "clips": len(clips),
        "sped_up": sum(1 for c in clips if c.get("tempo", 1.0) > 1.0),
        "shortened": sum(1 for c in clips if c["id"] in translation and c.get("text") != translation[c["id"]]),
        "issues": len(issues(wd)) if state == "done" else 0,
        "options": (manager.saved(wd.path.name) or {}).get("options"),
        "outputs": outputs(wd),
    }


def outputs(wd: WorkDir) -> list[dict[str, Any]]:
    """Every dub kept (mix.archive), newest first: version id, engine, date, and which one output.mp4 is.

    Each also counts its issues (from its own overflow.log and tts.json).
    """
    from ..mix import VERSION

    if not wd.outputs_dir.exists():
        return []
    found = []
    for video in wd.outputs_dir.glob("*.mp4"):
        if not (m := VERSION.fullmatch(video.stem)):
            continue
        made = datetime.strptime(m[1], "%Y%m%d-%H%M%S") if m[1] else datetime.fromtimestamp(video.stat().st_mtime)
        found.append({
            "version": video.stem,
            "engine": m[2],
            "date": made.isoformat(timespec="seconds"),
            "current": wd.output.exists() and video.samefile(wd.output),
            "_mtime": video.stat().st_mtime_ns,
        })
    # versions are named to the second: two in the same second (or legacy ones with no date)
    # go latest first, then by when their file was written
    found.sort(key=lambda o: (o["date"], o["current"], o["_mtime"]), reverse=True)
    for o in found:
        del o["_mtime"]
    for o in found:
        o["issues"], o["retouched"] = _counts(wd, None if o["current"] else o["version"])
    return found


# (video folder, version) → (the stamps of the files its numbers come from, (issues, retouched)): the library
# lists every version of every video on each load, and a kept version's files don't change
_COUNTS: dict[tuple[Path, str | None], tuple[tuple, tuple[int, int]]] = {}


def _counts(wd: WorkDir, version: str | None) -> tuple[int, int]:
    """A version's issues and retouched sentences, read again only when a file they depend on changed."""
    if version is None:
        own = [wd.tts_index, wd.overflow_log]
    else:
        own = [wd.outputs_dir / f"{version}.tts.json", wd.outputs_dir / f"{version}.overflow.log"]
    # issues() also reads the transcription, the hand edits and both styles (glossary misses)
    inputs = [*own, wd.segments, wd.translation_edits, wd.path / style.FILE, wd.path.parent / style.FILE]
    stamp = tuple((st.st_mtime_ns, st.st_size) if (st := _stat(p)) else None for p in inputs)
    key = (wd.path, version)
    if (cached := _COUNTS.get(key)) and cached[0] == stamp:
        return cached[1]
    # a retouch: how many sentences it spoke again over the dub before it
    retouched = len((_version_sources(wd, version)[0].get("stats") or {}).get("retouched") or [])
    _COUNTS[key] = (stamp, counts := (len(issues(wd, version)), retouched))
    return counts


def _stat(path: Path) -> os.stat_result | None:
    try:
        return path.stat()
    except OSError:
        return None


def version_detail(wd: WorkDir, version: str) -> dict[str, Any]:
    """One kept dub: its numbers, its issues and its clips (for the version panel and Compare)."""
    index, _, current = _version_sources(wd, version)
    kept = next((o for o in outputs(wd) if o["current"] == current and (current or o["version"] == version)), None)
    clips = index.get("clips") or []
    engine = index.get("engine")
    found = issues(wd, None if current else version)
    stats = index.get("stats") or {}
    shortened = stats.get("shortened")
    if shortened is None and current and wd.translation.exists():  # dubs made before tts.json kept it
        texts = {s.id: s.text for s in load_segments(wd.translation)}
        shortened = sum(1 for c in clips if c["id"] in texts and c.get("text") != texts[c["id"]])
    return {
        "version": kept["version"] if kept else version,
        "engine": engine,
        "date": kept["date"] if kept else None,
        "current": current,
        "stats": {
            "clips": len(clips),
            "voice_seconds": stats.get("seconds"),
            "sped_up": sum(1 for c in clips if c.get("tempo", 1.0) > 1.0),
            "shortened": shortened,
            "below_floor": sum(1 for i in found if i["kind"] == "floor"),
            "redone": sum(1 for i in found if i["kind"] == "repaired"),
            "edge": sum(1 for c in clips if c.get("voice") == "edge") if engine != "edge" else 0,
            "retouched": stats.get("retouched") or [],
        },
        "issues": found,
        "clips": [{k: c.get(k) for k in ("id", "start", "slot", "raw_duration", "tempo", "factor", "voice", "text")}
                  for c in clips],
    }


def delete_output(wd: WorkDir, version: str) -> None:
    """Delete a kept dub (its video, tts.json, overflow.log and exports). Not the latest one:
    output.mp4, tts.json and the issues on the video's page belong to it."""
    from ..export import FORMATS
    from ..mix import VERSION

    video = wd.outputs_dir / f"{version}.mp4"
    if not VERSION.fullmatch(version) or not video.exists():
        raise LookupError(version)
    if wd.output.exists() and video.samefile(wd.output):
        raise ValueError("the latest dub can't be deleted")
    for suffix in (".mp4", ".tts.json", ".overflow.log", *FORMATS.values()):
        (wd.outputs_dir / f"{version}{suffix}").unlink(missing_ok=True)


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
    translated = load_segments(wd.translation)
    texts = {s.id: s.text for s in translated}
    speaker_of = {s.id: s.speaker for s in translated}
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
            "speaker": speaker_of.get(seg.id),
        })
    return {"segments": segments, "chars_per_second": pace.cps if pace else None,
            "needs_regeneration": not (wd.has("tts") and wd.has("mix")),
            # edited since the latest dub: what a retouch speaks again
            "pending": sorted(retouch.pending_edits(wd)) if wd.output.exists() else [],
            # the voice clips a retouch needs may have been deleted to save space (storage.py)
            "clips_available": tts.clips_exist(wd)}


def dub_engine(wd: WorkDir) -> str:
    return (_tts_index(wd) or {}).get("engine") or "edge"


def retouchable(wd: WorkDir, takes: list[int]) -> list[int]:
    """What a retouch with these takes would speak again. LookupError: no dub, or no such segment."""
    if not (wd.output.exists() and wd.tts_index.exists()):
        raise LookupError()
    ids = {c["id"] for c in (_tts_index(wd) or {}).get("clips") or []}
    unknown = sorted(set(takes) - ids)
    if unknown:
        raise LookupError(f"No segment {unknown[0]} in this dub")
    if takes and dub_engine(wd) == "edge":
        raise LookupError("Another take needs a cloned voice: edge-tts always says a text the same way")
    return sorted(retouch.pending_edits(wd) | set(takes))


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
    write_text_atomic(wd.translation_edits, json.dumps(kept, ensure_ascii=False, indent=1))
    wd.invalidate_from("tts")


# --- translation style ------------------------------------------------------------
def video_style(wd: WorkDir) -> dict[str, Any]:
    """The video's own style, the global one, what applies, and whether the translation predates it.

    `used` are the glossary terms the video says; `stale` is true when the style that
    applies differs from the one the current translation was made with (or never had one).
    """
    own = style.read(wd.path / style.FILE)
    shared = style.read(wd.path.parent / style.FILE)
    applied = style.merge(shared, own)
    sources = [s.text for s in load_segments(wd.segments)] if wd.segments.exists() else []
    made_with = _read_json(wd.translation_style)
    current = style.snapshot(applied, sources)
    if made_with is None:  # translated before styles existed: as if with an empty one
        made_with = style.snapshot(style.Style(), sources)
    return {
        "video": own.to_json(), "global": shared.to_json(), "applied": applied.to_json(),
        "used": [t.source for t in style.matching(applied.terms, sources)],
        "stale": wd.translation.exists() and made_with != current,
    }


def save_style(path: Path, data: dict[str, Any]) -> None:
    """Write a style.json (an empty style removes it). ValueError if a value is not valid."""
    style.write(path, style.parse(data))


# --- clips with problems --------------------------------------------------------
def _version_sources(wd: WorkDir, version: str | None) -> tuple[dict[str, Any], str, bool]:
    """(tts.json, overflow.log text, whether it is the latest dub) of a kept version; None: the latest."""
    from ..mix import VERSION

    video = wd.outputs_dir / f"{version}.mp4"
    if version in (None, "latest") or (VERSION.fullmatch(version) and video.exists() and wd.output.exists()
                                       and video.samefile(wd.output)):
        log = wd.overflow_log.read_text(encoding="utf-8") if wd.overflow_log.exists() else ""
        return _tts_index(wd) or {}, log, True
    if not VERSION.fullmatch(version) or not video.exists():
        raise LookupError(version)
    index = _read_json(wd.outputs_dir / f"{version}.tts.json") or {}
    if isinstance(index, list):
        index = {"engine": None, "clips": index}
    log_path = wd.outputs_dir / f"{version}.overflow.log"
    return index, log_path.read_text(encoding="utf-8") if log_path.exists() else "", False


def issues(wd: WorkDir, version: str | None = None) -> list[dict[str, Any]]:
    """Clips listed in a dub's overflow.log, plus those the quality check had to redo.

    The latest dub's clips also link their wav (tts/ holds only the latest's clips);
    an older version's are heard by seeking its video to the clip's start.
    """
    index, log_text, current = _version_sources(wd, version)
    clips = {c["id"]: c for c in index.get("clips") or []}
    engine = index.get("engine")
    out: list[dict[str, Any]] = []
    seen = set()

    def add(kind: str, clip_id: int, message: str, start: float | None = None, text: str | None = None) -> None:
        if (kind, clip_id) in seen:
            return
        seen.add((kind, clip_id))
        clip = clips.get(clip_id, {})
        wav = Path(clip["file"]).name if clip.get("file") and current else None
        out.append({
            "id": clip_id, "kind": kind, "message": message,
            "start": start if start is not None else clip.get("start"),
            "text": text or clip.get("text"),
            "wav": f"/videos/{wd.path.name}/tts/{wav}" if wav and (wd.tts_dir / wav).exists() else None,
        })

    for line in log_text.splitlines():
        for kind, pattern in _ISSUE_LINES:
            if m := pattern.match(line):
                add(kind, int(m[1]), m[3], float(m[2]), m[4])
                break
        else:
            if m := _DELAYED.match(line):
                add("delayed", int(m[1]), m[2])
    for clip_id, term in _glossary_misses(wd, clips):
        add("glossary", clip_id, f'glossary: "{term.source}" → "{term.expected}"')
    for clip in clips.values():
        label = clip.get("voice") or ""
        if engine and engine != "edge" and label not in (engine, "edge"):
            add("repaired", clip["id"], f"redone by the quality check: {label}")
    order = {"fallback": 0, "floor": 1, "overflow": 2, "abnormal": 3, "glossary": 4, "repaired": 5, "delayed": 6}
    return sorted(out, key=lambda i: (order[i["kind"]], i["start"] or 0))


def _glossary_misses(wd: WorkDir, clips: dict[int, dict[str, Any]]) -> list[tuple[int, style.Term]]:
    """Spoken sentences that don't use a glossary term their original says (not hand edits:
    what you wrote is what you meant). Against today's glossary, so a new term shows up
    on the dubs made before it."""
    terms = style.load(wd.path.parent, wd.path).terms
    if not terms or not wd.segments.exists():
        return []
    edited = set(_read_json(wd.translation_edits) or {})
    sources = {s.id: s.text for s in load_segments(wd.segments)}
    out = []
    for clip_id, clip in clips.items():
        if str(clip_id) in edited or clip_id not in sources:
            continue
        out += [(clip_id, t) for t in style.misses(terms, sources[clip_id], clip.get("text") or "")]
    return out


# --- speakers (several voices) ------------------------------------------------------
def diarizer(settings: Settings | None = None) -> dict[str, Any]:
    """Whether several voices can be dubbed: Nemotron 3 Diarization installed, or how to."""
    from .. import diarize

    ready = diarize.installed((settings or Settings()).nemotron_dir)
    return {"installed": ready, "setup": None if ready else "uv run opendub setup-engine nemotron"}


def speakers_info(wd: WorkDir) -> list[dict[str, Any]]:
    """Each speaker of a video dubbed with several voices: name, speech, gender, voice and sample."""
    from .. import speakers as speakers_mod

    diarization = _read_json(wd.diarization)
    if not diarization:
        return []
    names = speakers_mod.load(wd)["names"]
    source = wd.translation if wd.translation.exists() else wd.segments
    counts: dict[str | None, int] = {}
    if source.exists():
        for seg in load_segments(source):
            counts[seg.speaker] = counts.get(seg.speaker, 0) + 1
    voices = (_tts_index(wd) or {}).get("speaker_voices") or {}
    out = []
    for spk, info in diarization["speakers"].items():
        out.append({
            "id": spk, "name": names.get(spk), "seconds": info.get("seconds"), "f0_hz": info.get("f0_hz"),
            "gender": voices_mod.gender_of(info.get("f0_hz")), "sentences": counts.get(spk, 0),
            "voice": voices.get(spk),
            "sample": f"/videos/{wd.path.name}/speakers/{spk}.wav" if speaker_sample(wd, spk) else None,
        })
    return out


def speaker_sample(wd: WorkDir, speaker: str) -> Path | None:
    """The speaker's reference clip, made when the video was dubbed."""
    if not re.fullmatch(r"[A-H]", speaker):
        return None
    path = wd.path / f"clone_ref_{speaker}.wav"
    return path if path.exists() else None
