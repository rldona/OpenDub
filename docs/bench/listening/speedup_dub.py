"""A dub made the way Subtitle Edit and pyVideoTrans make theirs, to set against OpenDub.

    uv run python docs/bench/listening/speedup_dub.py 17kBVfGjI8c rwF-X5STYks
    uv run python docs/bench/listening/speedup_dub.py R4zlpwwEpnY@484-634   # only that stretch (seconds)

Both tools (docs/audit/03-competencia.md) translate the subtitles without a length budget
and then speed each line's voice up until it fits its subtitle. This rebuilds that
approach from OpenDub's own parts, so that a blind session compares the approaches and
not the voice models:

- the text: work/_bench/external/input/<id>.es.srt, the plain translation that
  translate_srt.py makes (same Claude model, no slot budget);
- the voice: Chatterbox Multilingual V3 cloned from the same reference OpenDub uses
  (Subtitle Edit and pyVideoTrans both offer it), seed 0, the text as written; in a
  video with several voices, each line with its speaker's own reference, as Subtitle
  Edit's "Find voices in video and clone" does (the speaker of the sentence the line
  falls in, from OpenDub's diarization);
- the fit: silence trimmed, then sped up (atempo, no ceiling) to the subtitle's own
  duration when it is longer, as Subtitle Edit's text-to-speech documents; never
  slowed down; no shortening, no quality check, no fallback;
- the mix: each line at its subtitle's start over the separated background, brought to
  −16 LUFS like OpenDub's mix, so neither wins by loudness.

It is a reproduction of their approach, not their programs (their own pipelines may
differ in details: trimming, the speed ceiling, the mix). Writes
work/_bench/external/speedup/<id>.mp4, not committed. With a stretch (<id>@start-end)
only its lines are spoken; the rest of the video keeps the background alone.
"""

from __future__ import annotations

import json
import re
import sys
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parents[3] / "src"))
from opendub import clone, mix, reference  # noqa: E402
from opendub.media import duration, ffmpeg  # noqa: E402
from opendub.tts import SAMPLE_RATE, SEED, TRIM  # noqa: E402
from opendub.workdir import WorkDir  # noqa: E402

WORK = Path("work")
INPUT = WORK / "_bench" / "external" / "input"
OUT = WORK / "_bench" / "external" / "speedup"
SRT = re.compile(r"(\d+)\s*\n(\d\d):(\d\d):(\d\d),(\d{3}) --> (\d\d):(\d\d):(\d\d),(\d{3})\s*\n(.*?)(?:\n\s*\n|\Z)", re.S)


def lines(path: Path) -> list[tuple[int, float, float, str]]:
    """(id, start, end, text) of each subtitle."""
    out = []
    for m in SRT.finditer(path.read_text(encoding="utf-8")):
        h1, m1, s1, ms1, h2, m2, s2, ms2 = (int(x) for x in m.groups()[1:9])
        start = h1 * 3600 + m1 * 60 + s1 + ms1 / 1000
        end = h2 * 3600 + m2 * 60 + s2 + ms2 / 1000
        out.append((int(m[1]), start, end, " ".join(m[10].split())))
    return out


def _read(path: Path) -> np.ndarray:
    with wave.open(str(path)) as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768


def references(wd: WorkDir, subs: list[tuple[int, float, float, str]]) -> dict[int, Path]:
    """Each line's reference: its speaker's with several voices, else the video's."""
    main = reference.reference(wd)
    segments = json.loads(wd.segments.read_text(encoding="utf-8"))
    if not any(s.get("speaker") for s in segments):
        return {i: main for i, *_ in subs}
    own = {spk: reference.speaker_reference(wd, spk) or main for spk in {s["speaker"] for s in segments if s.get("speaker")}}

    def speaker_at(t: float) -> str | None:
        return next((s.get("speaker") for s in segments if s["start"] <= t <= s["end"]),
                    min(segments, key=lambda s: min(abs(s["start"] - t), abs(s["end"] - t))).get("speaker"))

    return {i: own.get(speaker_at((start + end) / 2), main) for i, start, end, _ in subs}


def dub(vid: str, span: tuple[float, float] | None = None) -> Path:
    wd = WorkDir(WORK, vid)
    subs = [line for line in lines(INPUT / f"{vid}.es.srt") if not span or span[0] <= line[1] and line[2] <= span[1]]
    refs = references(wd, subs)
    tmp = OUT / f"{vid}.clips"
    tmp.mkdir(parents=True, exist_ok=True)
    jobs = [(text, refs[i], SEED, tmp / f"{i:04d}.raw.wav")
            for i, _, _, text in subs if not (tmp / f"{i:04d}.raw.wav").exists()]
    if jobs:
        print(f"{vid}: speaking {len(jobs)} lines with Chatterbox V3…", flush=True)
        clone.synthesize_batch(jobs, tmp / "chatterbox.log", variant="v3")
    total = duration(wd.video)
    track = np.zeros(int(total * SAMPLE_RATE) + SAMPLE_RATE, dtype=np.float32)
    sped = 0
    for i, start, end, _ in subs:
        trimmed, fitted = tmp / f"{i:04d}.trim.wav", tmp / f"{i:04d}.wav"
        ffmpeg("-i", str(tmp / f"{i:04d}.raw.wav"), "-af", TRIM, "-ac", "1", "-ar", str(SAMPLE_RATE), str(trimmed))
        length = len(_read(trimmed)) / SAMPLE_RATE
        slot = end - start
        if length > slot:  # sped up to the subtitle's duration, however much it takes
            tempo, chain = length / slot, []
            while tempo > 2.0:  # atempo takes 0.5–2.0 per stage
                chain.append("atempo=2.0")
                tempo /= 2.0
            chain.append(f"atempo={tempo:.4f}")
            ffmpeg("-i", str(trimmed), "-af", ",".join(chain), str(fitted))
            sped += 1
        else:
            trimmed.replace(fitted)
        audio = _read(fitted)
        at = int(start * SAMPLE_RATE)
        n = min(len(audio), len(track) - at)
        track[at: at + n] += audio[:n]
    voice = tmp / "voice.wav"
    with wave.open(str(voice), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes((np.clip(track[: int(total * SAMPLE_RATE)], -1, 1) * 32767).astype(np.int16).tobytes())
    inputs = ["-i", str(wd.video), "-i", str(voice), "-i", str(wd.background)]
    graph = ("[2:a]aresample=48000[bg];[1:a]aresample=48000,pan=stereo|c0=c0|c1=c0[dub];"
             "[bg][dub]amix=inputs=2:duration=first:normalize=0[a]")
    measured = mix._measure(inputs, graph, -16.0)
    out = OUT / f"{vid}.mp4"
    ffmpeg(*inputs, "-filter_complex", f"{graph};[a]{mix.loudnorm_filter(measured, -16.0)}[n]",
           "-map", "0:v:0", "-map", "[n]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
           "-t", f"{total:.3f}", str(out))
    print(f"{vid}: {len(subs)} lines, {sped} sped up → {out}", flush=True)
    return out


if __name__ == "__main__":
    for arg in sys.argv[1:]:
        vid, _, stretch = arg.partition("@")
        dub(vid, tuple(float(x) for x in stretch.split("-")) if stretch else None)
