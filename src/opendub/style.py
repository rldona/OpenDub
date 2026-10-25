"""Translation style: register, Spanish variant, a glossary and free notes.

Two style.json files, both optional, with the same shape:

    {"register": "auto | tu | usted", "variant": "auto | es-ES | latam",
     "terms": [{"source": "itch store", "target": ""}, {"source": "slash", "target": "tajo"}],
     "notes": "Pixel art channel; 'frame' stays as 'frame'."}

- work/style.json applies to every video; work/<id>/style.json to one video and
  wins over it (register and variant when not auto, terms by source, notes added).
- An empty target keeps the term in the original language.
- Each translation block only gets the terms its text contains, so a term the
  video never says changes nothing, and adding one re-translates only the blocks
  that say it (translate.run caches each block by its own inputs).
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

from .log import log

FILE = "style.json"
REGISTERS = ("auto", "tu", "usted")
VARIANTS = ("auto", "es-ES", "latam")
# the edge-tts voice a variant switches to when the chosen one is from the other variant
VARIANT_VOICES = {"es-ES": "es-ES-AlvaroNeural", "latam": "es-MX-JorgeNeural"}


@dataclass
class Term:
    source: str
    target: str = ""  # empty: keep it in the original language

    @property
    def expected(self) -> str:
        return self.target or self.source


@dataclass
class Style:
    register: str = "auto"
    variant: str = "auto"
    terms: list[Term] = field(default_factory=list)
    notes: str = ""

    @property
    def empty(self) -> bool:
        return self == Style()

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


def parse(data: dict[str, Any] | None) -> Style:
    """A Style from style.json's content; unknown values are an error, not silently ignored."""
    data = data or {}
    register = data.get("register") or "auto"
    variant = data.get("variant") or "auto"
    if register not in REGISTERS:
        raise ValueError(f"register must be one of {', '.join(REGISTERS)} (not {register!r})")
    if variant not in VARIANTS:
        raise ValueError(f"variant must be one of {', '.join(VARIANTS)} (not {variant!r})")
    if not isinstance(data.get("terms") or [], list) or not all(isinstance(t, dict) for t in data.get("terms") or []):
        raise ValueError("terms must be a list of {source, target}")
    terms, seen = [], set()
    for t in data.get("terms") or []:
        source = str(t.get("source") or "").strip()
        if not source or source.lower() in seen:
            continue
        seen.add(source.lower())
        terms.append(Term(source, str(t.get("target") or "").strip()))
    return Style(register, variant, terms, str(data.get("notes") or "").strip())


def read(path: Path) -> Style:
    if not path.exists():
        return Style()
    try:
        return parse(json.loads(path.read_text(encoding="utf-8")))
    except (ValueError, AttributeError) as e:
        raise SystemExit(f"{path}: {e}")


def write(path: Path, style: Style) -> None:
    if style.empty:
        path.unlink(missing_ok=True)
    else:
        path.write_text(json.dumps(style.to_json(), ensure_ascii=False, indent=1), encoding="utf-8")


def merge(base: Style, over: Style) -> Style:
    terms = {t.source.lower(): t for t in base.terms}
    terms.update({t.source.lower(): t for t in over.terms})
    return Style(
        register=over.register if over.register != "auto" else base.register,
        variant=over.variant if over.variant != "auto" else base.variant,
        terms=list(terms.values()),
        notes="\n".join(n for n in (base.notes, over.notes) if n),
    )


def load(work_root: Path, video_dir: Path | None = None, extra: Path | None = None) -> Style:
    """The style a video is translated with: global, then the video's, then --style."""
    style = read(work_root / FILE)
    for path in (video_dir / FILE if video_dir else None, extra):
        if path:
            style = merge(style, read(path))
    return style


def _pattern(term: str) -> re.Pattern[str]:
    return re.compile(rf"(?<!\w){re.escape(term)}(?!\w)", re.IGNORECASE)


def matching(terms: list[Term], texts: list[str]) -> list[Term]:
    """The terms any of the texts says (whole words, any case)."""
    return [t for t in terms if any(_pattern(t.source).search(text) for text in texts)]


def misses(terms: list[Term], source: str, translation: str) -> list[Term]:
    """Terms the original says that its translation doesn't use as the glossary asks.

    A plain substring check, so inflections that only add letters ("tajo" → "tajos") pass.
    """
    return [t for t in matching(terms, [source]) if t.expected.lower() not in translation.lower()]


def snapshot(style: Style, sources: list[str]) -> dict[str, Any]:
    """What of a style shaped a video's translation: a term the video never says doesn't count."""
    return {"register": style.register, "variant": style.variant, "notes": style.notes,
            "terms": [[t.source, t.target] for t in matching(style.terms, sources)]}


def target_name(voice: str, variant: str = "auto") -> str:
    """The Spanish the translation is written in: the variant's, or the edge-tts voice's."""
    spain = variant == "es-ES" if variant != "auto" else voice.startswith("es-ES")
    return "Castilian Spanish (Spain)" if spain else "neutral Latin American Spanish"


def with_variant_voice(settings, style: Style):
    """Settings whose edge-tts voice (also the cloned voice's last resort) speaks the style's variant."""
    if style.variant == "auto":
        return settings
    spain = settings.voice.startswith("es-ES")
    if spain == (style.variant == "es-ES"):
        return settings
    voice = VARIANT_VOICES[style.variant]
    log.info(f"Style variant {style.variant}: edge-tts voice {settings.voice} → {voice}")
    return replace(settings, voice=voice)
