"""Metrics of a whole dub, version by version: what the final MP4 sounds like, not single sentences.

    uv run python docs/bench/dub_metrics.py 17kBVfGjI8c rwF-X5STYks KS837a-TFRc [--versions all|latest]
    uv run python docs/bench/dub_metrics.py KS837a-TFRc/20261025-141750-chatterbox   (one version)

For each kept version (work/<id>/outputs/<version>.mp4 with its tts.json), into
docs/bench/results/dubs/<id>__<version>.json:

- fit: clips, sped up (and the highest tempo), not fitting, shortened, on edge-tts;
- delays and drift, from the same placement the mix makes (mix.place): the largest and
  mean delay, and the seconds of voice heard more than 0.5 s late;
- loudness: integrated loudness and true peak of the final track (EBU R128);
- intelligibility on the final track: whisper transcribes, in Spanish, the stretch where
  each clip is heard (over the music, as it is heard) and it is compared with the text
  (CER, as the quality check computes it); and whisper's probability that it is Spanish
  when the language is not forced. Needs a GPU for long videos (--no-asr skips it).

These measure the dub as heard, to set against the blind listening (listening/), not
to replace it.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parents[2] / "src"))
from opendub.clone import cer  # noqa: E402
from opendub.mix import VERSION, place  # noqa: E402
from opendub.tts import Clip  # noqa: E402

WORK = Path("work")
RESULTS = Path(__file__).parent / "results" / "dubs"
SR = 16000
LATE_S = 0.5


def versions(vid: str, which: str) -> list[str]:
    found = sorted(p.stem for p in (WORK / vid / "outputs").glob("*.mp4") if VERSION.fullmatch(p.stem)
                   and (WORK / vid / "outputs" / f"{p.stem}.tts.json").exists())
    dated = [v for v in found if re.match(r"\d{8}-\d{6}-", v)]
    return found if which == "all" else (dated or found)[-1:]


def loudness(path: Path) -> dict:
    err = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-map", "0:a",
                          "-af", "ebur128=peak=true", "-f", "null", "-"], capture_output=True, text=True).stderr
    summary = err[err.rfind("Summary:"):]
    return {"lufs": float(re.search(r"I:\s+(-?[\d.]+) LUFS", summary)[1]),
            "true_peak_db": float(re.search(r"Peak:\s+(-?[\d.]+) dBFS", summary)[1])}


def fit_and_drift(clips: list[Clip]) -> dict:
    placements = {p.id: p for p in place(clips)}
    delays = [placements[c.id].delay for c in clips]
    late = sum(c.duration for c in clips if placements[c.id].delay > LATE_S)
    sped = [c.tempo for c in clips if c.tempo > 1.0]
    return {"clips": len(clips), "sped_up": len(sped), "max_tempo": max(sped, default=1.0),
            "not_fitting": sum(1 for c in clips if c.overflow > 0),
            "edge": sum(1 for c in clips if c.voice == "edge"),
            "max_delay_s": round(max(delays, default=0.0), 2),
            "mean_delay_s": round(sum(delays) / len(delays), 3) if delays else 0.0,
            "late_voice_s": round(late, 1)}


def asr(path: Path, clips: list[Clip], model_name: str) -> dict:
    import torch  # noqa: F401  (loads the CUDA libraries faster-whisper needs)
    from faster_whisper import WhisperModel

    from opendub.transcribe import whisper_device

    device, compute = whisper_device()
    model = WhisperModel(model_name, device=device, compute_type=compute)
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    audio = np.frombuffer(raw, dtype=np.float32)
    placements = {p.id: p for p in place(clips)}
    cers, p_es = [], []
    for c in clips:
        p = placements[c.id]
        piece = audio[int(p.start * SR): int((p.start + c.duration) * SR) + SR // 5]
        if len(piece) < SR // 4 or not c.text.strip():
            continue
        segments, _ = model.transcribe(piece, language="es", beam_size=1, without_timestamps=True,
                                       condition_on_previous_text=False)
        cers.append(min(cer(c.text, " ".join(s.text for s in segments)), 1.0))
        _, info = model.transcribe(piece, beam_size=1, without_timestamps=True)
        p_es.append(dict(info.all_language_probs or []).get("es", 0.0))
    cers.sort()
    return {"asr_clips": len(cers), "cer_mean": round(float(np.mean(cers)), 3) if cers else None,
            "cer_p90": round(cers[int(0.9 * (len(cers) - 1))], 3) if cers else None,
            "cer_over_0_3": sum(1 for x in cers if x > 0.3),
            "p_es_mean": round(float(np.mean(p_es)), 3) if p_es else None, "whisper": model_name}


def measure(vid: str, version: str, model_name: str | None) -> dict:
    out = WORK / vid / "outputs"
    index = json.loads((out / f"{version}.tts.json").read_text(encoding="utf-8"))
    clips = [Clip(**c) for c in (index["clips"] if isinstance(index, dict) else index)]
    row = {"video": vid, "version": version, "engine": index.get("engine") if isinstance(index, dict) else None,
           "shortened": (index.get("stats") or {}).get("shortened") if isinstance(index, dict) else None}
    row |= fit_and_drift(clips) | loudness(out / f"{version}.mp4")
    if model_name:
        row |= asr(out / f"{version}.mp4", clips, model_name)
    return row


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("videos", nargs="+", help="<id> (its latest or all versions) or <id>/<version>")
    parser.add_argument("--versions", choices=("latest", "all"), default="latest")
    parser.add_argument("--whisper", default="small")
    parser.add_argument("--no-asr", action="store_true")
    args = parser.parse_args()
    RESULTS.mkdir(parents=True, exist_ok=True)
    for arg in args.videos:
        vid, _, one = arg.partition("/")
        for version in [one] if one else versions(vid, args.versions):
            row = measure(vid, version, None if args.no_asr else args.whisper)
            (RESULTS / f"{vid}__{version}.json").write_text(json.dumps(row, indent=1))
            print(json.dumps(row))


if __name__ == "__main__":
    main()
