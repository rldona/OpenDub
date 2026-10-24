"""IndexTTS-2.5 engine (`--tts indextts`), run as a separate process in its own venv.

IndexTTS pins Python 3.11, torch 2.8 and transformers 4.52, which can't share a
venv with the rest of OpenTranslator. `setup-indextts` installs it (a pinned
commit of its repo, its own uv venv and the checkpoints) under
Settings.indextts_dir, and synthesis goes through workers/indextts_worker.py,
which talks JSON lines over stdin/stdout.

Unlike Chatterbox it controls the length of what it says: duration_factor
(0.5–2.0) scales the clip duration almost exactly, so clips are fitted to their
slot natively and atempo only covers what is left.

License: bilibili Model Use License Agreement (see docs/v2-plan.md).
"""

from __future__ import annotations

import atexit
import json
import os
import subprocess
from pathlib import Path

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
SETUP_HINT = "Install it with: uv run opentranslator setup-indextts"
WORKER = Path(__file__).parent / "workers" / "indextts_worker.py"

_worker: Worker | None = None


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


class Worker:
    """A long-lived IndexTTS process: loads the model once, then serves clips."""

    def __init__(self, home: Path, log_path: Path):
        repo, python, checkpoints = paths(home)
        if not python.exists() or not (checkpoints / "config.yaml").exists():
            raise SystemExit(f"IndexTTS is not installed in {home}. {SETUP_HINT}")
        log_path.parent.mkdir(parents=True, exist_ok=True)
        self.log_path = log_path
        self._stderr = log_path.open("a", encoding="utf-8")
        log.info(f"Starting {MODEL} (its own venv; log in {log_path})…")
        # cwd = repo: IndexTTS resolves its auxiliary model cache relative to it
        self.proc = subprocess.Popen(
            [str(python), "-I", str(WORKER), str(checkpoints)], cwd=repo,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self._stderr, text=True, bufsize=1,
        )
        hello = self._read()
        accel = ", accelerated" if hello.get("accel") else ""
        log.info(f"{MODEL} loaded in {hello['load_s']}s ({hello['device']}{accel})")
        self._next_id = 0

    def _read(self) -> dict:
        line = self.proc.stdout.readline()
        if not line:
            raise RuntimeError(f"The IndexTTS worker stopped (see {self.log_path})")
        return json.loads(line)

    def synthesize(self, text: str, ref: Path, out: Path, factor: float, seed: int) -> None:
        self._next_id += 1
        req = {"id": self._next_id, "text": text, "ref": str(ref.resolve()), "out": str(out.resolve()),
               "lang": "ES", "duration_factor": factor, "seed": seed}
        self.proc.stdin.write(json.dumps(req, ensure_ascii=False) + "\n")
        self.proc.stdin.flush()
        reply = self._read()
        if not reply.get("ok"):
            raise RuntimeError(f"IndexTTS failed on {text[:40]!r}: {reply.get('error')} (see {self.log_path})")

    def close(self) -> None:
        if self.proc.poll() is None:
            self.proc.stdin.close()
            try:
                self.proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self._stderr.close()


def synthesize(home: Path, log_path: Path, text: str, ref: Path, out: Path, factor: float, seed: int) -> None:
    """Speak `text` with the voice of `ref`, its duration scaled by `factor`."""
    global _worker
    if _worker is None:
        _worker = Worker(home, log_path)
        atexit.register(_worker.close)
    _worker.synthesize(text, ref, out, factor, seed)


def shutdown() -> None:
    """Stop the worker and free its GPU memory (the next clip starts a new one)."""
    global _worker
    if _worker is not None:
        _worker.close()
        _worker = None


def fit_factor(duration: float, slot: float, factor: float = 1.0, floor: float = MIN_FACTOR,
               ceiling: float | None = None) -> float:
    """duration_factor that makes a clip of `duration` (spoken at `factor`) fit `slot`, with a 3% margin.

    duration_factor scales the duration almost exactly. Never below `floor`; never
    above `ceiling`, which defaults to `factor` (only shorten) and can be 1.0 to
    also let a clip that has room relax towards its natural pace.
    """
    ceiling = factor if ceiling is None else ceiling
    return round(min(max(factor * slot * 0.97 / duration, floor), ceiling), 3)
