"""Checks on a real multi-speaker video that need no hand labels.

    uv run python docs/bench/diarize/real_checks.py h7PA4mXE_GA

- gender: each sentence's own pitch (from the separated vocals) says whether a
  woman (> 165 Hz) or a man (< 150 Hz) speaks it, when it is clear; each model's
  speaker gets the gender most of its sentences have, and a sentence counts as
  right if its speaker's gender is its own. It catches man↔woman mix-ups only,
  not one man taken for another.
- agreement: share of sentences the two models give the same speaker (after
  matching their speakers the way that agrees most). Agreement is not accuracy,
  but where they disagree at least one of them is wrong.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from score import OUT, WORK, best_match, speaker_of  # noqa: E402
from synth import SR, load  # noqa: E402

FEMALE_HZ, MALE_HZ = 165.0, 150.0


def pitch(audio: np.ndarray) -> float | None:
    """Median F0 of the voiced 40 ms frames (the autocorrelation tracker of opendub.reference)."""
    size, hop = int(0.04 * SR), int(0.01 * SR)
    lo, hi = SR // 400, SR // 60
    frames = [audio[i : i + size] for i in range(0, len(audio) - size, hop)]
    if not frames:
        return None
    loudest = max(float(np.sqrt(np.mean(f**2))) for f in frames)
    found = []
    for f in frames:
        if np.sqrt(np.mean(f**2)) < 0.1 * loudest:
            continue
        f = f - f.mean()
        ac = np.correlate(f, f, mode="full")[size - 1 :]
        if ac[0] <= 0:
            continue
        lag = lo + int(np.argmax(ac[lo:hi]))
        if ac[lag] / ac[0] > 0.5:
            found.append(SR / lag)
    return float(np.median(found)) if len(found) >= 10 else None


def main() -> None:
    vid = sys.argv[1]
    segments = json.loads((WORK / vid / "segments.json").read_text(encoding="utf-8"))
    vocals = load(WORK / vid / "stems" / "vocals.wav")
    gender = {}
    for s in segments:
        f0 = pitch(vocals[int(s["start"] * SR) : int(s["end"] * SR)])
        if f0 is not None and (f0 > FEMALE_HZ or f0 < MALE_HZ):
            gender[s["id"]] = "F" if f0 > FEMALE_HZ else "M"
    print(f"{vid}: {len(segments)} sentences, clear pitch in {len(gender)} "
          f"({sum(g == 'F' for g in gender.values())} female, {sum(g == 'M' for g in gender.values())} male)")

    assigned = {}
    for model in ("pyannote", "nemotron"):
        turns = json.loads((OUT / "out" / f"{vid}.{model}.json").read_text())["turns"]
        assigned[model] = {s["id"]: speaker_of(s, turns) for s in segments}
        votes: dict[str, Counter] = {}
        for sid, g in gender.items():
            spk = assigned[model][sid]
            votes.setdefault(spk, Counter())[g] += 1
        spk_gender = {spk: c.most_common(1)[0][0] for spk, c in votes.items()}
        right = sum(1 for sid, g in gender.items() if spk_gender.get(assigned[model][sid]) == g)
        detail = {spk: dict(c) for spk, c in votes.items()}
        print(f"  {model:9} gender right {right}/{len(gender)} ({right / len(gender):.1%}) · per speaker {detail}")

    pairs = [(assigned["pyannote"][s["id"]], assigned["nemotron"][s["id"]] or "none") for s in segments]
    agree, mapping = best_match(pairs)
    print(f"  agreement pyannote↔nemotron: {agree}/{len(segments)} ({agree / len(segments):.1%}) · {mapping}")


if __name__ == "__main__":
    main()
