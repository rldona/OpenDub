"""Fun-CosyVoice 3 engine (`--engine cosyvoice`), run as a separate process in its own venv.

CosyVoice is not a pip package and pins torch 2.3.1, so `setup-engine cosyvoice`
installs a pinned commit of its repo, a uv venv from engines/cosyvoice/pyproject.toml
(versions checked on an RTX 5080) and the weights under Settings.cosyvoice_dir;
synthesis goes through workers/cosyvoice_worker.py (JSON lines, engines.py).

It clones cross-lingually: the reference audio alone, without its transcript,
since the references come from the original (English) video. Its native
duration control is `speed`, which stretches the mel spectrogram before the
vocoder; the pipeline passes it as a duration factor (1/speed) and fits clips
like IndexTTS's, with the same --min-factor floor before shortening. It speaks
fast (~16 chars/s), so few clips need it.

License: Apache 2.0 (code and weights).
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from . import engines
from .log import log

MODEL = "cosyvoice3-0.5b"
REPO_URL = "https://github.com/FunAudioLLM/CosyVoice.git"
REPO_REV = "074ca6dc9e80a2f424f1f74b48bdd7d3fea531cc"  # 2026-05-25, the commit benchmarked
HF_REPO = "FunAudioLLM/Fun-CosyVoice3-0.5B-2512"
MIN_FACTOR = 0.5  # speed 2.0: the fastest the pipeline asks for
CALIBRATION_FACTOR = 1.0  # its natural pace is already fast
ENV_PROJECT = Path(__file__).resolve().parents[2] / "engines" / "cosyvoice"
SETUP_HINT = "Install it with: uv run opentranslator setup-engine cosyvoice"
WORKER = engines.WORKERS_DIR / "cosyvoice_worker.py"


def paths(home: Path) -> tuple[Path, Path, Path]:
    """(repo, venv python, model dir) of a CosyVoice install."""
    home = home.expanduser().resolve()  # absolute: the worker runs with cwd=repo
    return home / "repo", home / ".venv" / "bin" / "python", home / "models" / "Fun-CosyVoice3-0.5B"


def installed(home: Path) -> bool:
    _, python, model_dir = paths(home)
    return python.exists() and (model_dir / "cosyvoice3.yaml").exists()


def setup(home: Path) -> None:
    """Clone the pinned CosyVoice commit, create its venv and download the weights (~9 GB)."""
    repo, python, model_dir = paths(home)
    home.mkdir(parents=True, exist_ok=True)
    if not repo.exists():
        log.info(f"Cloning CosyVoice into {repo}…")
        subprocess.run(["git", "clone", "-q", REPO_URL, str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "checkout", "-q", REPO_REV], check=True)
    subprocess.run(["git", "-C", str(repo), "submodule", "update", "-q", "--init", "--recursive"], check=True)
    log.info("Creating its venv (Python 3.11, PyTorch 2.8 with CUDA 12.8)…")
    env = {**os.environ, "UV_PROJECT_ENVIRONMENT": str(python.parent.parent)}
    subprocess.run(["uv", "sync", "--frozen", "--python", "3.11", "--project", str(ENV_PROJECT)], env=env, check=True)
    log.info(f"Downloading {HF_REPO} weights…")
    subprocess.run(
        [str(python), "-c", "import sys; from huggingface_hub import snapshot_download; "
         "snapshot_download(sys.argv[1], local_dir=sys.argv[2])", HF_REPO, str(model_dir)],
        check=True,
    )
    log.info(f"CosyVoice ready in {home}")


def synthesize(home: Path, log_path: Path, text: str, ref: Path, out: Path, factor: float, seed: int) -> None:
    """Speak `text` with the voice of `ref`, its duration scaled by `factor` (speed = 1/factor)."""
    engines.worker(MODEL, lambda: _start(home, log_path)).request(text, ref, out, factor, seed)


def _start(home: Path, log_path: Path) -> engines.Worker:
    repo, python, model_dir = paths(home)
    if not installed(home):
        raise SystemExit(f"CosyVoice is not installed in {home}. {SETUP_HINT}")
    # cwd = repo: the worker imports cosyvoice (and its Matcha-TTS submodule) from there
    return engines.Worker(MODEL, python, WORKER, [str(model_dir)], repo, log_path)


def shutdown() -> None:
    """Stop the worker and free its GPU memory (the next clip starts a new one)."""
    engines.shutdown(MODEL)
