"""Score the diarizers against the hand labels (label.py) and the single-voice controls.

    uv run python docs/bench/diarize/score.py

For each video and model (work/_bench/diarize/out/<id>.<model>.json):
- speakers: those with at least MIN_SPEECH_S of speech (shorter ones are noise a
  dub would never clone), against the speakers in the labels (1 for controls);
- accuracy: share of the labeled single-voice sentences given the right speaker.
  Each sentence takes the speaker with the most time inside it, and the model's
  speakers are matched to the labels' letters the way that gets the most right;
- mixed: labeled sentences where several people speak (a dub must split them);
- time and VRAM of the run.
"""

from __future__ import annotations

import itertools
import json
from collections import Counter, defaultdict
from pathlib import Path

WORK = Path("work")
OUT = WORK / "_bench" / "diarize"
MIN_SPEECH_S = 6.0
CONTROLS = ("17kBVfGjI8c", "rwF-X5STYks", "KS837a-TFRc", "r5VIb2wLww4", "qODPK9kf-h4")


def speech(turns: list) -> Counter:
    talk: Counter = Counter()
    for a, b, s in turns:
        talk[s] += b - a
    return talk


def speaker_of(seg: dict, turns: list) -> str | None:
    """The speaker with the most time inside a sentence, or None if nobody speaks in it."""
    inside: Counter = Counter()
    for a, b, s in turns:
        overlap = min(b, seg["end"]) - max(a, seg["start"])
        if overlap > 0:
            inside[s] += overlap
    return inside.most_common(1)[0][0] if inside else None


def best_match(pairs: list[tuple[str | None, str]]) -> tuple[int, dict]:
    """(right, mapping): the model→label speaker mapping with the most sentences right."""
    predicted = sorted({p for p, _ in pairs if p is not None})
    truth = sorted({t for _, t in pairs})
    best, best_map = -1, {}
    targets = truth + [None] * max(0, len(predicted) - len(truth))
    for perm in itertools.permutations(targets, len(predicted)):
        mapping = dict(zip(predicted, perm))
        right = sum(1 for p, t in pairs if p is not None and mapping[p] == t)
        if right > best:
            best, best_map = right, mapping
    return max(best, 0), best_map


def score(vid: str, model: str) -> dict | None:
    path = OUT / "out" / f"{vid}.{model}.json"
    if not path.exists():
        return None
    run = json.loads(path.read_text())
    turns = run["turns"]
    talk = speech(turns)
    speakers = [s for s, t in talk.items() if t >= MIN_SPEECH_S]
    row = {"video": vid, "model": model, "speakers": len(speakers), "seconds": run["seconds"],
           "vram_gb": run["vram_gb"]}
    labels_path = OUT / "labels" / f"{vid}.json"
    if vid in CONTROLS:
        row["true_speakers"] = 1
        return row
    if not labels_path.exists():
        return row
    labels = json.loads(labels_path.read_text())
    synth = OUT / "synth" / vid / "segments.json"  # synth.py's conversations, else a real video
    seg_path = synth if synth.exists() else WORK / vid / "segments.json"
    segments = {s["id"]: s for s in json.loads(seg_path.read_text(encoding="utf-8"))}
    single = [(int(i), label) for i, label in labels.items() if label in ("A", "B", "C", "D")]
    pairs = [(speaker_of(segments[i], turns), label) for i, label in single]
    right, mapping = best_match(pairs)
    row |= {"true_speakers": len({label for _, label in single}), "labeled": len(single),
            "accuracy": round(right / len(single), 3) if single else None,
            "mixed": sum(1 for label in labels.values() if label == "mixed"),
            "unsure": sum(1 for label in labels.values() if label == "unsure"),
            "mapping": {k: v for k, v in mapping.items()}}
    # per true speaker: how many of their sentences went to the right one (who gets confused with whom)
    per = defaultdict(lambda: [0, 0])
    for p, t in pairs:
        per[t][1] += 1
        per[t][0] += p is not None and mapping.get(p) == t
    row["per_speaker"] = {t: f"{r}/{n}" for t, (r, n) in sorted(per.items())}
    return row


def main() -> None:
    videos = sorted({p.name.split(".")[0] for p in (OUT / "out").glob("*.json")})
    rows = [r for v in videos for m in ("pyannote", "nemotron") if (r := score(v, m))]
    print(f"{'video':13} {'model':9} {'spk':>7} {'acc':>6} {'mixed':>5} {'time':>6} {'vram':>5}  per speaker")
    for r in rows:
        spk = f"{r['speakers']}/{r.get('true_speakers', '?')}"
        acc = f"{r['accuracy']:.0%}" if r.get("accuracy") is not None else "—"
        print(f"{r['video']:13} {r['model']:9} {spk:>7} {acc:>6} {r.get('mixed', '—')!s:>5} "
              f"{r['seconds']:>5}s {r['vram_gb']!s:>5}  {r.get('per_speaker', '')}")
    (OUT / "scores.json").write_text(json.dumps(rows, indent=1))


if __name__ == "__main__":
    main()
