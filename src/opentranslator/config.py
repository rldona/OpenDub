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
    # Velocidad de locución con la que se calcula max_chars; edge-tts en español ronda 18-19
    chars_per_second: float = 17.0
    voice: str = "es-ES-AlvaroNeural"
    rate: str = "+0%"  # velocidad nativa de edge-tts ("-10%" = más despacio)
    min_tempo: float = 1.0  # < 1 permite ralentizar clips cortos para llenar su hueco
    max_tempo: float = 1.25
    bg_volume_db: float = -15.0
    mute_original: bool = False
    max_height: int = 1080
    anthropic_api_key: str | None = field(
        default_factory=lambda: os.environ.get("ANTHROPIC_API_KEY") or None
    )
