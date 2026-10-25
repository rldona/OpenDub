"""Settings: defaults, .env and CLI arguments."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Settings:
    work_root: Path = Path("work")
    source_lang: str | None = None  # None = whatever YouTube reports
    subs: str = "manual"  # manual | auto | none: accepted subtitle sources
    whisper_model: str = "small"
    backend: str = "cli"  # cli (subscription via Claude Code) | api
    claude_model: str = "claude-sonnet-5-5"
    batch_size: int = 30  # segments per translation call
    # Speaking rate used to compute max_chars; None = calibrate it with the voice
    chars_per_second: float | None = None
    voice: str = "es-ES-AlvaroNeural"  # edge-tts voice (also the cloned voice's last resort)
    tts: str = "edge"  # edge | clone (the original speaker's voice, from the separated vocals)
    engine: str = "chatterbox"  # cloning engine for --tts clone: chatterbox | indextts | cosyvoice | auto
    min_factor: float = 0.7  # indextts, cosyvoice: lowest duration factor before shortening the sentence
    clone_ref: Path | None = None  # fixed reference for cloned clips that fail the quality check
    indextts_dir: Path = field(  # IndexTTS install (its own venv), see `setup-indextts`
        default_factory=lambda: Path(
            os.environ.get("OPENDUB_INDEXTTS_DIR") or Path.home() / ".local/share/opendub/indextts"
        )
    )
    cosyvoice_dir: Path = field(  # CosyVoice install (its own venv), see `setup-engine cosyvoice`
        default_factory=lambda: Path(
            os.environ.get("OPENDUB_COSYVOICE_DIR") or Path.home() / ".local/share/opendub/cosyvoice"
        )
    )
    nemotron_dir: Path = field(  # Nemotron 3 Diarization (its own venv), see `setup-engine nemotron`
        default_factory=lambda: Path(
            os.environ.get("OPENDUB_NEMOTRON_DIR") or Path.home() / ".local/share/opendub/nemotron"
        )
    )
    # Several voices: tell who speaks each sentence (diarization) and give each speaker their own voice
    multi_speaker: bool = False
    # Reuse the existing translation even if it was made for another voice's speaking rate
    # (e.g. to dub the same video with another engine); what no longer fits is fitted in TTS
    keep_translation: bool = False
    # Extra style.json (register, variant, glossary, notes) over work/style.json and the video's own
    style_file: Path | None = None
    # A retouch instead of a dub: speak again the edited sentences and these new takes, then mix
    retouch: tuple[int, ...] | None = None
    rate: str = "-10%"  # native edge-tts rate (more negative = slower)
    min_tempo: float = 1.0  # < 1 allows slowing down short clips to fill their slot
    max_tempo: float = 1.25
    shorten: bool = True  # re-translate shorter whatever does not fit even at max_tempo
    bg_volume_db: float = -15.0
    separate: bool = False  # mix over the separated background instead of the original audio
    separator: str = "auto"  # auto | mlx (Apple Silicon) | torch (CUDA or CPU)
    music_volume_db: float = 0.0  # volume of the separated background
    mute_original: bool = False
    max_height: int = 1080
    anthropic_api_key: str | None = field(
        default_factory=lambda: os.environ.get("ANTHROPIC_API_KEY") or None
    )
