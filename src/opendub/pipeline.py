"""The full dub pipeline, shared by `opendub dub` and the web frontend."""

from __future__ import annotations

import gc
import sys
from pathlib import Path

from . import diarize as diarize_mod
from . import download as download_mod
from . import gpu
from . import mix as mix_mod
from . import retouch as retouch_mod
from . import separate as separate_mod
from . import style as style_mod
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
    rate (measured from the separated vocals) caps the translation length. With
    several voices it runs first, with the diarization (inside the same phase),
    since the transcription splits sentences where the speaker changes.
    """
    if settings.retouch is not None:
        return retouch(url, settings, output)
    wd = workdir(url, settings)
    with wd.lock("dub"):
        return _dub(url, wd, settings, output, force)


def _dub(url: str, wd: WorkDir, settings: Settings, output: Path | None, force: bool) -> Path:
    settings = style_mod.with_variant_voice(settings, style_mod.load(settings.work_root, wd.path, settings.style_file))
    if force:
        wd.invalidate_from("download")
    with phase("Download"):
        download_mod.run(url, wd, settings)
    # the GPU from the first phase that may use it to the voice (the translation calibrates a cloned
    # voice's pace); its memory is freed before the mix, which doesn't need it
    with gpu.hold(f"dub {wd.path.name}", on_release=release_models):
        if settings.multi_speaker:
            with phase("Separation"):
                separate_mod.run(wd, settings)
                diarize_mod.run(wd, settings)
        with phase("Transcription"):
            transcribe_mod.run(wd, settings)
        if (settings.separate or settings.tts != "edge") and not settings.multi_speaker:
            with phase("Separation"):
                separate_mod.run(wd, settings)
        with phase("Translation"):
            translate_mod.run(wd, settings)
        with phase("TTS"):
            tts_mod.run(wd, settings)
    with phase("Mix"):
        return mix_mod.run(wd, settings, output=output)


def retouch(url: str, settings: Settings, output: Path | None = None) -> Path:
    """Speak again only the edited sentences and the new takes of the latest dub, then mix:
    a new version, in seconds instead of a whole TTS phase."""
    wd = workdir(url, settings)
    with wd.lock("retouch"):
        settings = style_mod.with_variant_voice(settings, style_mod.load(settings.work_root, wd.path,
                                                                         settings.style_file))
        # what may have been deleted to save space (storage.py): the video for the mix, the stems for
        # a cloned voice's reference and for the background
        with phase("Download"):
            download_mod.run(url, wd, settings)
        cloned = wd.tts_index.exists() and (tts_mod._index(wd).get("engine") or "edge") != "edge"
        with gpu.hold(f"retouch {wd.path.name}", on_release=release_models):
            if cloned or settings.separate:
                with phase("Separation"):
                    separate_mod.run(wd, settings)
            with phase("TTS"):
                retouch_mod.retouch(wd, settings, settings.retouch or ())
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
