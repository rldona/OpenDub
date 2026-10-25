"""Conversations with a known answer, built from single-voice videos, to score the diarizers.

    uv run python docs/bench/diarize/synth.py

Hand labels need someone listening; these don't. Each conversation alternates
turns of real speech (1–3 consecutive sentences from a speaker's separated vocals)
of distinct people, with pauses and, in the panel, some overlap, so who says each
sentence is known exactly. To keep the speakers from being told apart by their
recordings alone, every turn is brought to the same loudness and one quiet music
bed runs under the whole conversation.

Writes work/_bench/diarize/synth/<name>/{audio.wav, segments.json} and the answer
to work/_bench/diarize/labels/<name>.json, in the shape score.py reads.

Limits: speakers still come from different rooms and microphones, which makes this
easier than a real conversation; the real interview's checks (real_checks.py) are
the other half of the evidence.
"""

from __future__ import annotations

import json
import random
import subprocess
import wave
from pathlib import Path

import numpy as np

WORK = Path("work")
OUT = WORK / "_bench" / "diarize"
SR = 16000
# distinct people (uploader, mean F0 of their reference): two men of nearly the same pitch, one woman
SPEAKERS = {
    "m1": "17kBVfGjI8c",  # explainity, male, 120 Hz
    "f1": "rwF-X5STYks",  # KI-Campus, female, 214 Hz
    "m2": "KS837a-TFRc",  # Penusbmic, male, 123 Hz
}
CONVERSATIONS = {
    "synth_mf": {"speakers": ["m1", "f1"], "overlap": 0.0, "seconds": 240},
    "synth_mm": {"speakers": ["m1", "m2"], "overlap": 0.0, "seconds": 270},
    "synth_panel": {"speakers": ["m1", "f1", "m2"], "overlap": 0.3, "seconds": 300},
}
BED = WORK / "KS837a-TFRc" / "stems" / "background.wav"  # one music bed under every conversation
TURN_RMS = 0.08
BED_DB = -26.0


def load(path: Path) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.float32).copy()


def speaker_turns(key: str) -> list[list[dict]]:
    """The speaker's sentences grouped in turns of 1–3 consecutive ones, each with its audio."""
    vid = SPEAKERS[key]
    vocals = load(WORK / vid / "stems" / "vocals.wav")
    segments = json.loads((WORK / vid / "segments.json").read_text(encoding="utf-8"))
    rng = random.Random(f"turns-{key}")
    turns, i = [], 0
    while i < len(segments):
        n = rng.choice((1, 1, 2, 3))
        group = []
        for s in segments[i : i + n]:
            audio = vocals[int(s["start"] * SR) : int(s["end"] * SR)]
            if len(audio) > 0.4 * SR:
                group.append({"text": s["text"], "audio": audio})
        if group:
            turns.append(group)
        i += n
    return turns


def build(name: str, spec: dict, pools: dict[str, list[list[dict]]]) -> None:
    rng = random.Random(name)
    queues = {k: list(pools[k]) for k in spec["speakers"]}
    for q in queues.values():
        rng.shuffle(q)
    track = np.zeros(int((spec["seconds"] + 30) * SR), dtype=np.float32)
    segments, labels, cursor, last = [], {}, 0.5, None
    letters = {k: "ABCD"[i] for i, k in enumerate(spec["speakers"])}
    while cursor < spec["seconds"]:
        choices = [k for k in spec["speakers"] if k != last and queues[k]]
        if not choices:
            break
        key = rng.choice(choices)
        turn = queues[key].pop()
        start = cursor
        for sentence in turn:
            audio = sentence["audio"]
            audio = audio * (TURN_RMS / max(float(np.sqrt(np.mean(audio**2))), 1e-4))
            a = int(start * SR)
            track[a : a + len(audio)] += audio[: len(track) - a]
            end = start + len(audio) / SR
            sid = len(segments) + 1
            segments.append({"id": sid, "start": round(start, 3), "end": round(end, 3), "text": sentence["text"]})
            labels[str(sid)] = letters[key]
            start = end + rng.uniform(0.05, 0.25)  # the speaker's own pause between sentences
        # the next turn starts after a pause, or over the end of this one in a panel
        overlap = rng.random() < spec["overlap"]
        cursor = end - rng.uniform(0.3, 1.0) if overlap else end + rng.uniform(0.2, 0.8)
        last = key
    length = int((segments[-1]["end"] + 0.5) * SR)
    track = track[:length]
    bed = load(BED)
    bed = np.resize(bed, length) * (10 ** (BED_DB / 20) / max(float(np.sqrt(np.mean(bed**2))), 1e-4) * TURN_RMS)
    mix = np.clip(track + bed, -1, 1)
    folder = OUT / "synth" / name
    folder.mkdir(parents=True, exist_ok=True)
    with wave.open(str(folder / "audio.wav"), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((mix * 32767).astype(np.int16).tobytes())
    (folder / "segments.json").write_text(json.dumps(segments, indent=1, ensure_ascii=False), encoding="utf-8")
    (OUT / "labels").mkdir(parents=True, exist_ok=True)
    (OUT / "labels" / f"{name}.json").write_text(json.dumps(labels, indent=1))
    talk = {letters[k]: round(sum(s["end"] - s["start"] for s in segments if labels[str(s["id"])] == letters[k]))
            for k in spec["speakers"]}
    print(f"{name}: {len(segments)} sentences, {length / SR:.0f} s, speech per speaker {talk}")


def main() -> None:
    pools = {k: speaker_turns(k) for k in SPEAKERS}
    for name, spec in CONVERSATIONS.items():
        build(name, spec, pools)


if __name__ == "__main__":
    main()
