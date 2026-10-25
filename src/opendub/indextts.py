"""IndexTTS-2.5 engine (`--tts indextts`), run as a separate process in its own venv.

IndexTTS pins Python 3.11, torch 2.8 and transformers 4.52, which can't share a
venv with the rest of OpenDub. `setup-indextts` installs it (a pinned
commit of its repo, its own uv venv and the checkpoints) under
Settings.indextts_dir, and synthesis goes through workers/indextts_worker.py,
which talks JSON lines over stdin/stdout (engines.py).

Unlike Chatterbox it controls the length of what it says: duration_factor
(0.5–2.0) scales the clip duration almost exactly, so clips are fitted to their
slot natively and atempo only covers what is left.

License: bilibili Model Use License Agreement (see docs/v2-plan.md).
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from . import engines
from .log import log

MODEL = "indextts-2.5"
REPO_URL = "https://github.com/index-tts/index-tts.git"
REPO_REV = "d9e41aac89fd00b3d71497fddb287b7f24613712"
HF_REPO = "IndexTeam/IndexTTS-2.5"
MIN_FACTOR = 0.5  # documented lower bound of duration_factor
FLOOR = 0.7  # default --min-factor: below it, shorten the sentence before compressing further
# Speaking rate calibrated at this factor: its natural pace is slow (~12 chars/s),
# and 0.85 sounds as natural, so translations are not cut more than needed
CALIBRATION_FACTOR = 0.85
SETUP_HINT = "Install it with: uv run opendub setup-engine indextts"
WORKER = engines.WORKERS_DIR / "indextts_worker.py"


def paths(home: Path) -> tuple[Path, Path, Path]:
    """(repo, venv python, checkpoints) of an IndexTTS install."""
    repo = home.expanduser().resolve() / "repo"  # absolute: the worker runs with cwd=repo
    return repo, repo / ".venv" / "bin" / "python", repo / "checkpoints"


def setup(home: Path) -> None:
    """Clone the pinned IndexTTS commit, create its venv and download the checkpoints."""
    repo, python, checkpoints = paths(home)
    home.mkdir(parents=True, exist_ok=True)
    if not repo.exists():
        log.info(f"Cloning IndexTTS into {repo}…")
        subprocess.run(["git", "clone", "-q", REPO_URL, str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "checkout", "-q", REPO_REV], check=True)
    log.info("Creating its venv (Python 3.11, PyTorch with CUDA)…")
    # The `accel` extra brings flash-attn for its 1.3x faster engine. Its prebuilt wheel
    # runs on RTX 50-series too, but its build script wants nvcc unless told to only
    # download it; without a wheel for this setup, carry on without acceleration.
    env = {**os.environ, "FLASH_ATTENTION_SKIP_CUDA_BUILD": "TRUE"}
    if subprocess.run(["uv", "sync", "--extra", "accel"], cwd=repo, env=env).returncode != 0:
        log.warning("flash-attn could not be installed: IndexTTS will run without its acceleration")
        subprocess.run(["uv", "sync"], cwd=repo, check=True)
    log.info(f"Downloading {HF_REPO} checkpoints…")
    subprocess.run(
        [str(python), "-c", "import sys; from huggingface_hub import snapshot_download; "
         "snapshot_download(sys.argv[1], local_dir=sys.argv[2])", HF_REPO, str(checkpoints)],
        check=True,
    )
    log.info(f"IndexTTS ready in {home}")


def synthesize(home: Path, log_path: Path, text: str, ref: Path, out: Path, factor: float, seed: int) -> None:
    """Speak `text` with the voice of `ref`, its duration scaled by `factor`."""
    engines.speak(MODEL, lambda: _start(home, log_path), text, ref, out, factor, seed, lang="ES")


def _start(home: Path, log_path: Path) -> engines.Worker:
    repo, python, checkpoints = paths(home)
    if not python.exists() or not (checkpoints / "config.yaml").exists():
        raise SystemExit(f"IndexTTS is not installed in {home}. {SETUP_HINT}")
    # cwd = repo: IndexTTS resolves its auxiliary model cache relative to it
    return engines.Worker(MODEL, python, WORKER, [str(checkpoints)], repo, log_path)


def shutdown() -> None:
    """Stop the worker and free its GPU memory (the next clip starts a new one)."""
    engines.shutdown(MODEL)


fit_factor = engines.fit_factor
