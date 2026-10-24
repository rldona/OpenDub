"""Parseo de subtítulos (json3/vtt) y reagrupado en frases.

Todas las fuentes (subtítulos manuales, automáticos o whisper) se reducen a
una lista de `Piece` (cue o palabra con tiempos) y se reagrupan con las mismas
reglas, para que la traducción y el TTS trabajen con frases completas.
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass
from pathlib import Path

from .models import Segment


@dataclass
class Piece:
    start: float
    end: float
    text: str


_NOISE = re.compile(r"\[[^\]]*\]|\([^)]*\)|♪+|>>")
_TAG = re.compile(r"<[^>]+>")
_SENTENCE_END = re.compile(r"[.!?…][\"'”’)]*$")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?…])\s+")
_VTT_TIME = re.compile(r"(\d+:)?(\d{2}):(\d{2})[.,](\d{3})")
_VTT_INLINE = re.compile(r"<((?:\d+:)?\d{2}:\d{2}[.,]\d{3})>")


def clean_text(text: str) -> str:
    text = html.unescape(_TAG.sub("", text))
    text = _NOISE.sub(" ", text)
    text = re.sub(r"(^|\s)-\s+", r"\1", text)  # guiones de diálogo
    return re.sub(r"\s+", " ", text).strip()


def _vtt_seconds(stamp: str) -> float:
    m = _VTT_TIME.fullmatch(stamp.strip())
    if not m:
        raise ValueError(f"Marca de tiempo VTT inválida: {stamp!r}")
    h = int(m.group(1)[:-1]) if m.group(1) else 0
    return h * 3600 + int(m.group(2)) * 60 + int(m.group(3)) + int(m.group(4)) / 1000


def parse_json3(path: Path) -> list[Piece]:
    events = json.loads(path.read_text(encoding="utf-8")).get("events", [])
    pieces: list[Piece] = []
    for ev in events:
        segs = [s for s in ev.get("segs") or [] if s.get("utf8", "").strip()]
        if not segs:
            continue
        start = ev["tStartMs"] / 1000
        end = start + ev.get("dDurationMs", 0) / 1000
        if len(segs) == 1 and "tOffsetMs" not in segs[0]:
            pieces.append(Piece(start, end, segs[0]["utf8"]))
            continue
        # ASR con tiempos por palabra
        starts = [start + s.get("tOffsetMs", 0) / 1000 for s in segs]
        for i, s in enumerate(segs):
            word_end = starts[i + 1] if i + 1 < len(segs) else end
            pieces.append(Piece(starts[i], word_end, s["utf8"]))
    return pieces


def parse_vtt(path: Path) -> list[Piece]:
    pieces: list[Piece] = []
    prev_lines: set[str] = set()
    blocks = re.split(r"\n\s*\n", path.read_text(encoding="utf-8").replace("\r", ""))
    for block in blocks:
        lines = block.strip().split("\n")
        idx = next((i for i, l in enumerate(lines) if "-->" in l), None)
        if idx is None:
            continue
        a, b = lines[idx].split("-->")
        start, end = _vtt_seconds(a), _vtt_seconds(b.split()[0])
        text_lines = [l for l in lines[idx + 1 :] if l.strip()]

        tagged = [l for l in text_lines if _VTT_INLINE.search(l)]
        if tagged:
            # ASR en rodillo: solo las líneas con marcas por palabra son nuevas
            for line in tagged:
                parts = _VTT_INLINE.split(line)
                times = [start] + [_vtt_seconds(t) for t in parts[1::2]]
                words = parts[0::2]
                for i, w in enumerate(words):
                    w_end = times[i + 1] if i + 1 < len(times) else end
                    pieces.append(Piece(times[i], w_end, _TAG.sub("", w)))
            prev_lines = {clean_text(l) for l in text_lines}
            continue

        cleaned = [clean_text(l) for l in text_lines]
        new = [l for l in cleaned if l and l not in prev_lines]
        prev_lines = set(cleaned)
        if new:
            pieces.append(Piece(start, end, " ".join(new)))
    return pieces


def parse_subtitles(path: Path) -> list[Piece]:
    if path.suffix == ".json3":
        return parse_json3(path)
    if path.suffix == ".vtt":
        return parse_vtt(path)
    raise ValueError(f"Formato de subtítulos no soportado: {path.name}")


def normalize(pieces: list[Piece]) -> list[Piece]:
    """Limpia texto, descarta piezas vacías y elimina solapes entre piezas."""
    out: list[Piece] = []
    for p in sorted(pieces, key=lambda p: p.start):
        text = clean_text(p.text)
        if not text:
            continue
        if out and out[-1].end > p.start:
            out[-1].end = max(out[-1].start, p.start)
        out.append(Piece(p.start, max(p.end, p.start), text))
    return out


def split_sentences(pieces: list[Piece]) -> list[Piece]:
    """Parte cues con varias frases, repartiendo el tiempo según los caracteres."""
    out: list[Piece] = []
    for p in pieces:
        parts = [s for s in _SENTENCE_SPLIT.split(p.text) if s]
        if len(parts) == 1:
            out.append(p)
            continue
        total = sum(len(s) for s in parts)
        t = p.start
        for s in parts:
            dur = (p.end - p.start) * len(s) / total
            out.append(Piece(t, t + dur, s))
            t += dur
    return out


def regroup(
    pieces: list[Piece], max_dur: float = 12.0, max_gap: float = 0.7, min_dur: float = 1.0
) -> list[Segment]:
    """Une piezas en frases: corta en fin de frase, en pausas largas o al superar max_dur."""
    groups: list[list[Piece]] = []
    cur: list[Piece] = []
    for p in split_sentences(normalize(pieces)):
        if cur and (p.start - cur[-1].end > max_gap or p.end - cur[0].start > max_dur):
            groups.append(cur)
            cur = []
        cur.append(p)
        if _SENTENCE_END.search(p.text) and cur[-1].end - cur[0].start >= min_dur:
            groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)

    return [
        Segment(
            id=i,
            start=round(g[0].start, 3),
            end=round(g[-1].end, 3),
            text=" ".join(p.text for p in g),
        )
        for i, g in enumerate(groups, start=1)
    ]
