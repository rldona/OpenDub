"""The full dub pipeline, shared by `opentranslator dub` and the web frontend."""

from __future__ import annotations

import gc
import sys
from pathlib import Path

from . import download as download_mod
from . import mix as mix_mod
from . import separate as separate_mod
from . import transcribe as transcribe_mod
from . import translate as translate_mod
from . import tts as tts_mod
from .config import Settings
from .log import log, phase
from .media import require_ffmpeg
from .workdir import WorkDir

# Phase names, in order, as `phase()` reports them
PHASES = ["Download", "Transcription", "Separation", "Translation", "TTS", "Mix"]


def workdir(url: str, settings: Settings) -> WorkDir:
    require_ffmpeg()
    wd = WorkDir(settings.work_root, download_mod.video_id(url))
    log.info(f"Working folder: {wd.path}")
    return wd


def dub(url: str, settings: Settings, output: Path | None = None, force: bool = False) -> Path:
    """download → transcription → (separation) → translation → TTS → mix; each phase is cached.

    Separation runs before translation with a cloned voice, since its speaking
    rate (measured from the separated vocals) caps the translation length.
    """
    wd = workdir(url, settings)
    if force:
        wd.invalidate_from("download")
    with phase("Download"):
        download_mod.run(url, wd, settings)
    with phase("Transcription"):
        transcribe_mod.run(wd, settings)
    if settings.separate or settings.tts != "edge":
        with phase("Separation"):
            separate_mod.run(wd, settings)
    with phase("Translation"):
        translate_mod.run(wd, settings)
    with phase("TTS"):
        tts_mod.run(wd, settings)
    with phase("Mix"):
        return mix_mod.run(wd, settings, output=output)


def release_models() -> None:
    """Free the GPU memory the phases keep between clips: the engine workers (IndexTTS,
    CosyVoice), Chatterbox and PyTorch's cached blocks. A CLI run frees it on exit; a
    long-lived server must do it after each job, or the next one may run out of memory."""
    from . import clone, engines

    engines.shutdown()
    clone.unload()
    gc.collect()
    if "torch" in sys.modules:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
