"""Voice cloning with Chatterbox Multilingual V3 (`--tts clone --engine chatterbox`), and
the whisper quality check shared by every cloning engine.

The reference (reference.py) is cut from the separated vocals, so cloning needs
the `separate` phase. Chatterbox clones from
the audio alone (no transcript needed) and has no speaking-rate control, so
slot fitting relies on atempo and sentence shortening as with edge-tts.
Every clip carries Resemble AI's inaudible Perth watermark.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
import wave
from pathlib import Path
from typing import Any

import numpy as np

from . import media
from .errors import PhaseError
from .log import log

MODEL = "chatterbox-multilingual-v3"
HF_REPO = "ResembleAI/chatterbox"
HF_REV = "5bb1f6ee58e50c3b8d408bc82a6d3740c2db6e18"  # the weights benchmarked (docs/v2-plan.md)
T3_MODEL = "v3"
# The es-ES finetune (--engine chatterbox-es): an evaluation variant for the blind listening. It lost
# to V3 by ear in the first benchmark (docs/v2-plan.md, Phase C) and is compared again on whole dubs
MODEL_ES = "chatterbox-multilingual-es-es"
HF_REPO_ES = "ResembleAI/Chatterbox-Multilingual-es-es"
HF_REV_ES = "7262b364e3222ba9446c9289e7485eadc47ed902"
VARIANTS = {"v3": MODEL, "es-es": MODEL_ES}
SAMPLE_RATE = 24000
QC_MAX_CER = 0.3  # whisper character error rate above which a clip is redone
# On very short texts one misheard word swings the rate: "Ups, llénalo" failed on a fine clip
QC_SHORT_CHARS, QC_SHORT_MAX_CER = 20, 0.6
INSTALL_HINT = "Install the optional dependencies with: uv sync --extra clone"

_models: dict[str, object] = {}  # one per variant (v3, es-es)
_whisper: dict[str, Any] = {}  # quality-check model, loaded once per run (several check rounds)


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def _device() -> str:
    import torch

    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def _load(variant: str = "v3"):
    if variant not in _models:
        try:
            from chatterbox.mtl_tts import ChatterboxMultilingualTTS
        except ImportError:
            raise PhaseError("engine_missing", f"chatterbox-tts is not installed. {INSTALL_HINT}",
                             engine="Chatterbox", cmd="uv sync --extra clone")
        device = _device()
        log.info(f"Loading {VARIANTS[variant]} ({device})…")
        if variant == "es-es":
            _models[variant] = ChatterboxMultilingualTTS.from_local(_checkpoints_es(), device,
                                                                    t3_model="t3_es_es.safetensors")
        else:  # what from_pretrained does, at a fixed revision instead of its "main"
            _models[variant] = ChatterboxMultilingualTTS.from_local(_checkpoints(), device, t3_model=T3_MODEL)
    return _models[variant]


def _checkpoints() -> Path:
    """The Chatterbox files at HF_REV, downloaded once into the Hugging Face cache."""
    import os

    from chatterbox.mtl_tts import _resolve_multilingual_t3_model
    from huggingface_hub import snapshot_download

    files = ["ve.pt", _resolve_multilingual_t3_model(T3_MODEL), "s3gen.pt", "grapheme_mtl_merged_expanded_v1.json",
             "conds.pt", "Cangjie5_TC.json"]
    return Path(snapshot_download(HF_REPO, revision=HF_REV, allow_patterns=files, token=os.getenv("HF_TOKEN")))


def _checkpoints_es() -> Path:
    """The es-ES finetune assembled as the benchmark did: V3's voice encoder and conditionals,
    the finetune's T3 and tokenizer, and its s3gen_v3 with the two buffers it omits rebuilt."""
    import os

    import torch
    from huggingface_hub import hf_hub_download

    d = Path.home() / ".cache" / "opendub" / f"chatterbox-es-es-{HF_REV_ES[:12]}"
    d.mkdir(parents=True, exist_ok=True)
    token = os.getenv("HF_TOKEN")
    files = {"ve.pt": (HF_REPO, HF_REV), "conds.pt": (HF_REPO, HF_REV), "Cangjie5_TC.json": (HF_REPO, HF_REV),
             "t3_es_es.safetensors": (HF_REPO_ES, HF_REV_ES),
             "grapheme_mtl_merged_expanded_v1.json": (HF_REPO_ES, HF_REV_ES)}
    for name, (repo, rev) in files.items():
        if not (d / name).exists():
            (d / name).symlink_to(hf_hub_download(repo, name, revision=rev, token=token))
    if not (d / "s3gen.pt").exists():
        from chatterbox.models.s3gen import S3Gen

        state = torch.load(hf_hub_download(HF_REPO_ES, "s3gen_v3.pt", revision=HF_REV_ES, token=token),
                           map_location="cpu", weights_only=True)
        fresh = S3Gen().state_dict()
        missing, unexpected = set(fresh) - set(state), set(state) - set(fresh)
        if unexpected or not missing <= {"tokenizer._mel_filters", "tokenizer.window"}:
            raise RuntimeError(f"Unexpected es-ES s3gen: missing {sorted(missing)}, unexpected {sorted(unexpected)}")
        torch.save(state | {k: fresh[k] for k in missing}, d / "s3gen.pt")
    return d


def unload() -> None:
    """Drop the Chatterbox and quality-check whisper models (the next use loads them again)."""
    _models.clear()
    _whisper.clear()


def synthesize(text: str, ref: Path, seed: int, out: Path, variant: str = "v3") -> None:
    """Speak `text` with the voice of `ref` and write it as a 24 kHz mono wav."""
    import torch

    model = _load(variant)
    torch.manual_seed(seed)
    wav = model.generate(text, language_id="es", audio_prompt_path=str(ref))
    pcm = (np.clip(wav.squeeze(0).cpu().numpy(), -1.0, 1.0) * 32767).astype(np.int16)
    tmp = out.with_suffix(".part")
    with wave.open(str(tmp), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(model.sr)
        w.writeframes(pcm.tobytes())
    tmp.rename(out)


# Chatterbox doesn't use the whole GPU for one clip: two processes speaking side by side
# went from 3.64x to 5.00x real time (docs/v2-plan.md). Each takes 3.6 GB, so the pool
# needs room for both plus the quality check's whisper
POOL_MIN_VRAM_GB = 12
WORKER = Path(__file__).parent / "workers" / "chatterbox_worker.py"


def pool_size() -> int:
    """Chatterbox processes to speak with: 2 on a GPU with room for them, else 1 (in this process).

    OPENDUB_CHATTERBOX_WORKERS overrides it.
    """
    import os

    if os.environ.get("OPENDUB_CHATTERBOX_WORKERS"):
        return max(1, int(os.environ["OPENDUB_CHATTERBOX_WORKERS"]))
    try:
        import torch

        if torch.cuda.is_available() and torch.cuda.get_device_properties(0).total_memory / 2**30 >= POOL_MIN_VRAM_GB:
            return 2
    except ImportError:
        pass
    return 1


def synthesize_batch(jobs: list[tuple[str, Path, int, Path]], log_path: Path, done=lambda: None,
                     variant: str = "v3") -> None:
    """Speak (text, ref, seed, out) jobs, on pool_size() processes when there is more than one.

    Each process takes the next job as soon as it is free; `done` is called after
    each clip (from the pool's threads). With one process, this one speaks them.
    A single job also goes to the pool when there is one: its processes are likely
    loaded already (a quality-check retry, a retouch), and loading Chatterbox here
    too would cost ~10 s and another 3.6 GB of VRAM.
    """
    if not jobs:
        return
    size = min(pool_size(), len(jobs))
    if pool_size() <= 1:
        for text, ref, seed, out in jobs:
            synthesize(text, ref, seed, out, variant)
            done()
        return
    import sys
    from concurrent.futures import ThreadPoolExecutor
    from queue import Empty, Queue

    from . import engines

    _models.pop(variant, None)  # the workers speak: this process doesn't need Chatterbox on the GPU
    model = VARIANTS[variant]
    pending: Queue = Queue()
    for job in jobs:
        pending.put(job)

    def serve(k: int) -> None:
        def start() -> engines.Worker:
            return engines.Worker(f"{model} #{k + 1}", Path(sys.executable), WORKER, [variant], Path.cwd(), log_path)

        while True:
            try:
                text, ref, seed, out = pending.get_nowait()
            except Empty:
                return
            engines.speak(f"{model}#{k}", start, text, ref, out, 1.0, seed)
            done()

    with ThreadPoolExecutor(max_workers=size) as pool:
        for future in [pool.submit(serve, k) for k in range(size)]:
            future.result()  # re-raise a worker's failure


def normalize(text: str) -> str:
    """Lowercase, no punctuation, figures written out: "Llegó 4x4" ≈ "llego cuatro por cuatro"."""
    from .spoken import spell_numbers

    text = unicodedata.normalize("NFC", spell_numbers(text).lower())
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", text)).strip()


def cer(reference_text: str, hypothesis: str) -> float:
    """Character error rate between two texts, ignoring case and punctuation."""
    r, h = normalize(reference_text), normalize(hypothesis)
    row = list(range(len(h) + 1))
    for i, rc in enumerate(r, 1):
        prev, row[0] = row[0], i
        for j, hc in enumerate(h, 1):
            prev, row[j] = row[j], min(row[j] + 1, row[j - 1] + 1, prev + (rc != hc))
    return row[len(h)] / max(len(r), 1)


def unintelligible(clips: list[tuple[int, Path, str]], whisper_model: str) -> set[int]:
    """Ids of the clips whose whisper transcription strays too far from their text."""
    model = _whisper.get(whisper_model)
    if model is None:
        from faster_whisper import WhisperModel  # lazy import: slow to load

        from .transcribe import whisper_device

        device, compute_type = whisper_device()
        model = _whisper[whisper_model] = WhisperModel(whisper_model, device=device, compute_type=compute_type)
    bad = set()
    for clip_id, path, text in clips:
        # decoded with ffmpeg to avoid faster-whisper's PyAV decoder, as in transcribe
        raw = media.run(
            ["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", "16000", "-f", "f32le", "-"],
            capture_output=True, check=True,
        ).stdout
        # greedy: half the time of beam search, same verdict on 352 of 353 real clips
        segments, _ = model.transcribe(np.frombuffer(raw, dtype=np.float32), language="es", beam_size=1,
                                       without_timestamps=True, condition_on_previous_text=False)
        limit = QC_SHORT_MAX_CER if len(normalize(text)) < QC_SHORT_CHARS else QC_MAX_CER
        if cer(text, " ".join(s.text for s in segments)) > limit:
            bad.add(clip_id)
    return bad
