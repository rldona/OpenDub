"""Configuración: valores por defecto, .env y argumentos de CLI."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Settings:
    work_root: Path = Path("work")
    source_lang: str | None = None  # None = el que declare YouTube
    subs: str = "manual"  # manual | auto | none: fuentes de subtítulos aceptadas
    whisper_model: str = "small"
    backend: str = "cli"  # cli (suscripción vía Claude Code) | api
    claude_model: str = "claude-sonnet-5-5"
    batch_size: int = 30  # segmentos por llamada de traducción
    # Velocidad de locución con la que se calcula max_chars; None = calibrarla con la voz
    chars_per_second: float | None = None
    voice: str = "es-ES-AlvaroNeural"
    rate: str = "-10%"  # velocidad nativa de edge-tts (más negativo = más despacio)
    min_tempo: float = 1.0  # < 1 permite ralentizar clips cortos para llenar su hueco
    max_tempo: float = 1.25
    shorten: bool = True  # retraducir más corto lo que no cabe ni a max_tempo
    bg_volume_db: float = -15.0
    mute_original: bool = False
    max_height: int = 1080
    anthropic_api_key: str | None = field(
        default_factory=lambda: os.environ.get("ANTHROPIC_API_KEY") or None
    )
