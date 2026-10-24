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
    clone_ref: Path | None = None  # fixed reference for cloned clips that fail the quality check
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
