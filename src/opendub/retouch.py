"""Retouching a dub: speak again only the sentences that changed, and new takes.

A sentence is pending when its translation changed since the latest dub (a hand
edit, or a speaker corrected on the page) or when another take was asked for (the
same text with the next seed). A retouch speaks just those with the dub's own
voices, fits and checks them like a full run, judged against the whole video, and
patches tts.json and overflow.log: the mix then makes a new version in seconds.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import asdict, replace

from . import repair, tts
from . import voices as voices_mod
from .config import Settings
from .log import log
from .models import load_segments
from .workdir import WorkDir, write_text_atomic


def takes(wd: WorkDir) -> dict[int, int]:
    """The seed each sentence asked for another take was last spoken with (takes.json)."""
    path = wd.path / "takes.json"
    return {int(k): v for k, v in json.loads(path.read_text(encoding="utf-8")).items()} if path.exists() else {}


def hand_edited(wd: WorkDir) -> set[int]:
    """Sentences edited from the web: their text is never rewritten shorter."""
    if not wd.translation_edits.exists():
        return set()
    return {int(k) for k in json.loads(wd.translation_edits.read_text(encoding="utf-8"))}


def pending_edits(wd: WorkDir) -> set[int]:
    """Sentences whose translation changed since the latest dub: what a retouch speaks again.

    tts.json keeps the translation each clip was made from ("sources"); dubs made
    before it did compare the hand edits with what their clips say.
    """
    if not (wd.tts_index.exists() and wd.translation.exists()):
        return set()
    index = tts._index(wd)
    texts = {s.id: s.text for s in load_segments(wd.translation)}
    sources = index.get("sources")
    if sources is not None:
        changed = {i for i, text in texts.items() if sources.get(str(i)) != text}
        said_by = index.get("speakers")  # several voices: who each clip was spoken as
        if said_by is not None:
            speakers = {s.id: s.speaker for s in load_segments(wd.translation)}
            changed |= {i for i in texts if said_by.get(str(i)) != speakers.get(i)}
        return changed
    said = {c["id"]: c.get("text") for c in index.get("clips") or []}
    return {i for i in hand_edited(wd) if i in texts and texts[i] != said.get(i)}


def retouch(wd: WorkDir, settings: Settings, new_takes: list[int] | tuple[int, ...] = ()) -> list[int]:
    """Speak again only some sentences of the latest dub; returns their ids.

    The sentences whose translation changed since the dub (pending_edits), and
    `new_takes`: the same text with the next seed (another take of a cloned voice).
    Each goes through the same fitting and quality check as a full run, judged
    against the whole video, then tts.json and overflow.log are patched and the
    TTS phase is marked done for the current translation: a later full run finds
    it cached. The engine is the dub's own, whatever `settings` says.
    """
    if not (wd.tts_index.exists() and wd.translation.exists()):
        raise SystemExit("Nothing to retouch: this video has no dub yet")
    if not tts.clips_exist(wd):
        raise SystemExit("The voice clips were deleted to save space: dub the video again (its translation is "
                         "kept; only the voice and the mix are redone) before retouching it")
    index = tts._index(wd)
    engine = index.get("engine") or "edge"
    cloned = engine != "edge"
    settings = replace(settings, tts="clone" if cloned else "edge", engine=engine if cloned else settings.engine,
                       multi_speaker=index.get("speakers") is not None)  # with the dub's own voices
    segments = load_segments(wd.translation)
    clips = {c.id: c for c in tts.load_clips(wd)}
    unknown = sorted(set(new_takes) - set(clips))
    if unknown:
        raise SystemExit(f"No segment {unknown[0]} in this dub")
    if not cloned and new_takes:
        raise SystemExit("Another take needs a cloned voice: edge-tts always says a text the same way")

    edits = pending_edits(wd)
    seeds = takes(wd)
    for i in new_takes:
        seeds[i] = seeds.get(i, tts.SEED) + 1
    ids = sorted(edits | set(new_takes))
    if not ids:
        log.info("Nothing to retouch: no edited sentence and no take asked for")
        return []
    log.info(f"Retouch with {engine}: {len(ids)} segment(s) · edited {len(edits)} · new takes {len(new_takes)}")

    started = time.monotonic()
    every, _, ref, by_speaker = voices_mod.segment_voices(wd, settings, segments, seeds)
    asyncio.run(tts._check_voice(settings.voice))
    (wd.tts_dir / "raw").mkdir(parents=True, exist_ok=True)
    meta = json.loads(wd.meta.read_text(encoding="utf-8"))
    slots = {s.id: slot for s, slot in zip(segments, tts._slots(segments, meta.get("duration")))}
    translated = {s.id: s for s in segments}
    # an edit speaks the new translation; a take, what the clip said (maybe a shortened version that fit)
    by_id = {i: replace(translated[i], text=translated[i].text if i in edits else clips[i].text) for i in ids}
    voices = {i: every[i] for i in clips}
    f = repair.Fitting(wd, clips, voices, slots, by_id, settings, only=set(ids))
    f.speak([(by_id[i], voices[i]) for i in ids])
    fell_back, still_bad, n_short, below_floor = repair.fit(f, engine)
    tts.fill_gaps(wd, clips, segments, settings.min_tempo, only=set(ids))

    index["clips"] = [asdict(clips[s.id]) for s in segments]
    index["sources"] = {str(s.id): s.text for s in segments}  # every pending edit is spoken now
    if by_speaker:
        index["speakers"] = {str(s.id): s.speaker for s in segments}
        index["speaker_voices"] = voices_mod.describe(by_speaker)
    index["stats"] = {"seconds": round(time.monotonic() - started, 1), "shortened": n_short, "retouched": ids}
    write_text_atomic(wd.tts_index, json.dumps(index, ensure_ascii=False, indent=1))
    # the other clips keep their lines; the mix writes its "delayed" lines again
    kept = []
    if wd.overflow_log.exists():
        for line in wd.overflow_log.read_text(encoding="utf-8").splitlines(keepends=True):
            m = re.match(r"#(\d+) (@|delayed)", line)
            if m and (int(m[1]) in ids or m[2] == "delayed"):
                continue
            kept.append(line)
    with wd.overflow_log.open("w", encoding="utf-8") as f:
        f.writelines(kept)
        for i in ids:
            f.writelines(tts._issue_lines(clips[i], still_bad, fell_back, below_floor, settings.min_factor))
    write_text_atomic((wd.path / "takes.json"), json.dumps({str(k): v for k, v in sorted(seeds.items())}))

    fits = sum(1 for i in ids if clips[i].overflow == 0)
    log.info(f"Retouched {len(ids)} segment(s) in {time.monotonic() - started:.1f}s · fit: {fits} · "
             f"shortened: {n_short} · fell back to edge-tts: {len(fell_back)}")
    wd.mark_done("tts", tts._params(settings, segments, engine, ref, seeds if cloned else {}, by_speaker))
    return ids
