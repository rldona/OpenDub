"""Subtitle parsing (json3/vtt) and regrouping into sentences.

Every source (manual subtitles, auto-generated ones or whisper) is reduced to a
list of `Piece` (a timed cue or word) and regrouped with the same rules, so that
translation and TTS work with whole sentences.
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
    text = re.sub(r"(^|\s)-\s+", r"\1", text)  # dialogue dashes
    return re.sub(r"\s+", " ", text).strip()


def _vtt_seconds(stamp: str) -> float:
    m = _VTT_TIME.fullmatch(stamp.strip())
    if not m:
        raise ValueError(f"Invalid VTT timestamp: {stamp!r}")
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
        # ASR with per-word timings
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
            # Rolling ASR: only lines with per-word timestamps are new
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
    raise ValueError(f"Unsupported subtitle format: {path.name}")


def normalize(pieces: list[Piece]) -> list[Piece]:
    """Clean the text, drop empty pieces and remove overlaps between pieces."""
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
    """Split cues holding several sentences, sharing the time out by characters."""
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


# A pause splits a sentence in two: "I" | (2.5 s) | "want to redesign this character.", or
# "…and this will be the" | "slash itself.". Translated and spoken on its own, such a
# fragment comes out odd ("Yo" said alone) and is what the voices most often garble.
FRAGMENT_WORDS = 3  # a group this short that doesn't close a sentence is a fragment
MAX_JOIN_GAP = 4.0  # seconds of pause a fragment is joined across


def _words(group: list[Piece]) -> int:
    return sum(len(p.text.split()) for p in group)


def _closes(group: list[Piece]) -> bool:
    return bool(_SENTENCE_END.search(group[-1].text))


def join_fragments(groups: list[list[Piece]], max_dur: float = 12.0) -> list[list[Piece]]:
    """Join a short fragment to the sentence it belongs to, across a pause.

    A short group that leaves its sentence open goes with the next group; a short
    group after one that was left open goes with that one. Never across more
    than MAX_JOIN_GAP of pause, nor into a group longer than max_dur.
    """
    def fits(a: list[Piece], b: list[Piece]) -> bool:
        return b[0].start - a[-1].end <= MAX_JOIN_GAP and b[-1].end - a[0].start <= max_dur

    out: list[list[Piece]] = []
    i = 0
    while i < len(groups):
        g = groups[i]
        short = _words(g) <= FRAGMENT_WORDS
        if short and out and not _closes(out[-1]) and fits(out[-1], g):
            out[-1] = out[-1] + g  # "…and this will be the" + "slash itself."
        elif short and not _closes(g) and i + 1 < len(groups) and fits(g, groups[i + 1]):
            groups[i + 1] = g + groups[i + 1]  # "I" + "want to redesign this character."
        else:
            out.append(g)
        i += 1
    return out


def regroup(
    pieces: list[Piece], max_dur: float = 12.0, max_gap: float = 0.7, min_dur: float = 1.0
) -> list[Segment]:
    """Join pieces into sentences: break at sentence ends, long pauses or past max_dur."""
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
    groups = join_fragments(groups, max_dur)

    return [
        Segment(
            id=i,
            start=round(g[0].start, 3),
            end=round(g[-1].end, 3),
            text=" ".join(p.text for p in g),
        )
        for i, g in enumerate(groups, start=1)
    ]
