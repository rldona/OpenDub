"""Diarization: who speaks when (`--multi-speaker`), with NVIDIA Nemotron 3 Diarization.

Chosen in docs/bench/diarize (docs/v2-plan.md, "Several voices"): as accurate as
pyannote on easy cases, better on two men of the same pitch and on overlaps,
five times faster, and it splits a single voice less. It runs once per video
on the separated vocals, as a separate process in its own venv
(engines/nemotron, NeMo from a pinned commit), installed with
`setup-engine nemotron`.

Its raw turns go through two rules before anyone is dubbed with them:
- a speaker needs MIN_SPEECH_S of speech to count: false second voices in a
  single-voice video were crumbs of mumbled speech adding up to 14–19 s, while
  real speakers talk for minutes; their turns are dropped and their sentences
  go to whoever speaks around them;
- the speakers left are named A, B, C… from the one who speaks most.

Writes diarization.json: the turns, and per speaker its speech time and pitch
(mean F0 of its longest turns), which picks a stock voice of its gender.

License: OpenMDW 1.1 (commercial use allowed), up to 8 speakers.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from collections import Counter
from pathlib import Path

from . import media
from .config import Settings
from .log import log
from .media import ffmpeg
from .workdir import WorkDir, write_text_atomic

MODEL = "nemotron-3-diarization"
HF_REPO = "nvidia/Nemotron-3-Diarization"
HF_FILE = "Nemotron-3-Diarization.nemo"
NEMO_REV = "68a12fc5e469614abd23b25ff9cfcb822aa0be93"  # engines/nemotron/pyproject.toml
MIN_SPEECH_S = 30.0
PITCH_SECONDS = 20.0  # of a speaker's longest turns, to measure their pitch
ENV_PROJECT = Path(__file__).resolve().parents[2] / "engines" / "nemotron"
SETUP_HINT = "Install it with: uv run opendub setup-engine nemotron"
WORKER = Path(__file__).parent / "workers" / "diarize_worker.py"


def paths(home: Path) -> tuple[Path, Path]:
    """(venv python, model file) of a Nemotron install."""
    home = home.expanduser().resolve()
    return home / ".venv" / "bin" / "python", home / "models" / HF_FILE


def installed(home: Path) -> bool:
    python, model = paths(home)
    return python.exists() and model.exists()


def setup(home: Path) -> None:
    """Create the Nemotron venv (PyTorch 2.8 with CUDA 12.8, NeMo) and download the model."""
    python, model = paths(home)
    home.mkdir(parents=True, exist_ok=True)
    log.info("Creating its venv (Python 3.12, PyTorch 2.8 with CUDA 12.8, NeMo)…")
    env = {**os.environ, "UV_PROJECT_ENVIRONMENT": str(python.parent.parent)}
    subprocess.run(["uv", "sync", "--frozen", "--python", "3.12", "--project", str(ENV_PROJECT)], env=env, check=True)
    log.info(f"Downloading {HF_REPO}…")
    subprocess.run(
        [str(python), "-c", "import sys; from huggingface_hub import hf_hub_download; "
         "hf_hub_download(sys.argv[1], sys.argv[2], local_dir=sys.argv[3])", HF_REPO, HF_FILE, str(model.parent)],
        check=True,
    )
    log.info(f"Nemotron 3 Diarization ready in {home}")


def speech(turns: list) -> Counter:
    talk: Counter = Counter()
    for a, b, s in turns:
        talk[s] += b - a
    return talk


def keep_speakers(turns: list, min_speech: float = MIN_SPEECH_S) -> tuple[list, dict[str, float], dict[str, float]]:
    """(turns, kept, dropped): the turns of speakers with enough speech, renamed A, B, C… by speech
    time; kept and dropped map each speaker to its seconds of speech."""
    talk = speech(turns)
    ranked = [s for s, t in talk.most_common() if t >= min_speech]
    if not ranked and talk:  # nobody reaches it (a short video): the main voice is still a speaker
        ranked = [talk.most_common(1)[0][0]]
    names = {s: "ABCDEFGH"[i] for i, s in enumerate(ranked)}
    kept_turns = [[a, b, names[s]] for a, b, s in turns if s in names]
    kept = {names[s]: round(talk[s], 1) for s in ranked}
    dropped = {s: round(t, 1) for s, t in talk.items() if s not in names}
    return kept_turns, kept, dropped


def speaker_at(turns: list, start: float, end: float) -> str | None:
    """The speaker with the most time between start and end, or None if nobody speaks there."""
    inside: Counter = Counter()
    for a, b, s in turns:
        overlap = min(b, end) - max(a, start)
        if overlap > 0:
            inside[s] += overlap
    return inside.most_common(1)[0][0] if inside else None


def _pitch(vocals: Path, turns: list, speaker: str) -> float | None:
    """Mean F0 of the speaker's longest turns, up to PITCH_SECONDS of them."""
    from .reference import mean_f0

    longest = sorted((t for t in turns if t[2] == speaker), key=lambda t: t[0] - t[1])
    chosen, total = [], 0.0
    for a, b, _ in longest:
        chosen.append((a, b))
        total += b - a
        if total >= PITCH_SECONDS:
            break
    with tempfile.TemporaryDirectory() as tmp:
        parts = []
        for i, (a, b) in enumerate(sorted(chosen)):
            part = Path(tmp) / f"{i}.wav"
            ffmpeg("-ss", f"{a:.3f}", "-to", f"{b:.3f}", "-i", str(vocals), "-ac", "1", "-ar", "16000", str(part))
            parts.append(part)
        listing = Path(tmp) / "parts.txt"
        listing.write_text("".join(f"file '{p}'\n" for p in parts))
        joined = Path(tmp) / "speaker.wav"
        ffmpeg("-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(joined))
        return mean_f0(joined)


def load(wd: WorkDir) -> dict:
    return json.loads(wd.diarization.read_text(encoding="utf-8"))


def run(wd: WorkDir, settings: Settings, force: bool = False) -> dict:
    if not wd.vocals.exists():
        raise SystemExit("Diarization needs the separated vocals: run `separate` first (or use `dub`)")
    params = {"model": MODEL, "rev": NEMO_REV, "min_speech": MIN_SPEECH_S}
    if not force and wd.is_done("diarize", params) and wd.diarization.exists():
        log.info("Diarization cached, skipping")
        return load(wd)
    python, model = paths(settings.nemotron_dir)
    if not installed(settings.nemotron_dir):
        raise SystemExit(f"Several voices need Nemotron 3 Diarization, not installed in "
                         f"{settings.nemotron_dir}. {SETUP_HINT}")
    log.info("Diarizing with Nemotron 3 Diarization in its own process…")
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "turns.json"
        result = media.run([str(python), str(WORKER), str(model), str(wd.vocals), str(out)],
                           capture_output=True, text=True)
        if result.returncode != 0 or not out.exists():
            raise SystemExit(f"Diarization failed: {(result.stderr or '').strip()[-800:]}")
        raw = json.loads(out.read_text())
    turns, kept, dropped = keep_speakers(raw["turns"])
    speakers = {s: {"seconds": t, "f0_hz": _pitch(wd.vocals, turns, s)} for s, t in kept.items()}
    data = {"model": MODEL, "turns": turns, "speakers": speakers, "dropped": dropped,
            "seconds": raw.get("seconds"), "device": raw.get("device")}
    write_text_atomic(wd.diarization, json.dumps(data, indent=1))
    described = ", ".join(f"{s} {v['seconds'] / 60:.1f} min ({v['f0_hz'] or '?'} Hz)" for s, v in speakers.items())
    log.info(f"{len(speakers)} speaker(s): {described} · {raw.get('seconds')}s on {raw.get('device')}")
    if dropped:
        log.info(f"Ignored {len(dropped)} voice(s) under {MIN_SPEECH_S:.0f} s of speech "
                 f"({', '.join(f'{t:.0f} s' for t in dropped.values())})")
    wd.mark_done("diarize", params)
    return data
