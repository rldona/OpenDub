"""Alternative references of one speaker: 8–12 s of continuous speech with the least music.

Scores every window of consecutive segments by speech coverage (fewest pauses)
and by how loud the separated background is under it (music that can leak into
vocals.wav), skips the window the pipeline already uses, and cuts the best
non-overlapping ones. Usage: alt_refs.py <work/VIDEO_ID> <out_dir> [count]
"""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

from opentranslator import reference
from opentranslator.models import load_segments

wd, out = Path(sys.argv[1]), Path(sys.argv[2])
count = int(sys.argv[3]) if len(sys.argv) > 3 else 3
out.mkdir(parents=True, exist_ok=True)


def load(path, ss, to):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(ss), "-to", str(to), "-i", str(path),
                          "-ac", "1", "-ar", "16000", "-f", "f32le", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.float32)


def db(x):
    return float(20 * np.log10(np.sqrt(np.mean(x**2)) + 1e-9))


segs = load_segments(wd / "segments.json")
current = reference.pick_reference(segs)
cands = []
for i, first in enumerate(segs):
    for j in range(i, len(segs)):
        start, end = first.start, segs[j].end
        span = end - start
        if span > 12:
            break
        if span < 8:
            continue
        coverage = sum(s.duration for s in segs[i : j + 1]) / span
        music = db(load(wd / "stems" / "background.wav", start, end))
        voice = db(load(wd / "stems" / "vocals.wav", start, end))
        cands.append({"start": start, "end": end, "coverage": round(coverage, 3),
                      "music_db": round(music, 1), "voice_to_music_db": round(voice - music, 1)})

overlaps = lambda a, b: a[0] < b[1] and b[0] < a[1]
picked = []
# continuous speech first (coverage ≥ 0.9), then the cleanest voice-to-music ratio
for c in sorted(cands, key=lambda c: (c["coverage"] < 0.9, -c["voice_to_music_db"])):
    span = (c["start"], c["end"])
    if overlaps(span, current) or any(overlaps(span, (p["start"], p["end"])) for p in picked):
        continue
    picked.append(c)
    if len(picked) == count:
        break

cur = {"start": current[0], "end": current[1], "coverage": None,
       "music_db": round(db(load(wd / "stems" / "background.wav", *current)), 1)}
cur["voice_to_music_db"] = round(db(load(wd / "stems" / "vocals.wav", *current)) - cur["music_db"], 1)
print("current", cur)
for n, c in enumerate(picked, 1):
    path = out / f"alt{n}.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{c['start']:.3f}", "-to", f"{c['end']:.3f}",
                    "-i", str(wd / "stems" / "vocals.wav"), "-ac", "1", "-ar", "24000", str(path)], check=True)
    c["file"] = path.name
    print(f"alt{n}", c)
(out / "alt_refs.json").write_text(json.dumps({"current": cur, "alternatives": picked}, indent=1))
