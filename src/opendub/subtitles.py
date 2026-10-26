"""The translation as subtitles with who says each sentence, to correct it in a subtitle editor (T-34).

One cue per sentence, at the original's timestamps, with the speaker's name (the one
given on the web page, else its letter):

- ASS: the name in each Dialogue's Actor field (Name);
- WebVTT: a `<v Name>` voice span, and the sentence's id as the cue identifier;
- SRT: no speaker (the format has none), for editors that only take SRT.

Importing reads one back into the translation: each cue goes to its sentence (by the
WebVTT id, else by its start time), a changed text is saved as a hand edit (as the web
editor does) and a changed name gives the sentence to that speaker. Timestamps belong
to the original and are not imported; a cue that matches no sentence, or a name that
is no speaker, stops the import before anything is saved.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from . import speakers
from .models import load_segments
from .workdir import WorkDir

FORMATS = {"ass": ".es.ass", "vtt": ".es.vtt", "srt": ".es.srt"}
MATCH_S = 0.25  # a cue starting this close to a sentence is that sentence


@dataclass(frozen=True)
class Cue:
    start: float
    end: float
    text: str
    speaker: str | None = None  # the speaker's name, or None
    id: int | None = None  # the sentence's id, when the format carries it (WebVTT)


# --- writing ------------------------------------------------------------------
def translation_cues(wd: WorkDir) -> list[Cue]:
    """The current translation, one cue per sentence, with its speaker's name."""
    names = speakers.load(wd)["names"]
    segments = speakers.apply(wd, load_segments(wd.translation))
    return [Cue(s.start, s.end, s.text, names.get(s.speaker, s.speaker) if s.speaker else None, s.id)
            for s in segments if s.text.strip()]


def _clock(t: float, sep: str, digits: int) -> str:
    """h:mm:ss with milliseconds (digits 3: SRT, WebVTT) or centiseconds (2: ASS), rounded."""
    units = max(0, int(round(t * 10**digits)))
    per_s = 10**digits
    h, m, s, frac = units // (3600 * per_s), units // (60 * per_s) % 60, units // per_s % 60, units % per_s
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{frac:03d}" if digits == 3 else f"{h}:{m:02d}:{s:02d}{sep}{frac:02d}"


def to_vtt(cues: list[Cue]) -> str:
    blocks = ["WEBVTT"]
    for c in cues:
        voice = f"<v {c.speaker}>" if c.speaker else ""
        ident = f"{c.id}\n" if c.id is not None else ""
        blocks.append(f"{ident}{_clock(c.start, '.', 3)} --> {_clock(c.end, '.', 3)}\n{voice}{c.text}")
    return "\n\n".join(blocks) + "\n"


ASS_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, \
Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, \
MarginV, Encoding
Style: Default,Arial,56,&H00FFFFFF,&H000000FF,&H00000000,&H64000000,0,0,0,0,100,100,0,0,1,3,1,2,60,60,50,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def to_ass(cues: list[Cue]) -> str:
    """ASS with the speaker as each line's Actor; centiseconds, the format's precision."""
    lines = [f"Dialogue: 0,{_clock(c.start, '.', 2)},{_clock(c.end, '.', 2)},Default,{c.speaker or ''},0,0,0,,"
             + c.text.replace("\n", "\\N") for c in cues]
    return ASS_HEADER + "\n".join(lines) + "\n"


def to_srt(cues: list[Cue]) -> str:
    return "\n".join(f"{i}\n{_clock(c.start, ',', 3)} --> {_clock(c.end, ',', 3)}\n{c.text}\n"
                     for i, c in enumerate(cues, start=1))


def export(wd: WorkDir, fmt: str) -> Path:
    """The translation in that format, written to translation<suffix> in the video's folder."""
    if fmt not in FORMATS:
        raise ValueError(f"format must be one of {', '.join(FORMATS)} (not {fmt!r})")
    cues = translation_cues(wd)
    text = {"ass": to_ass, "vtt": to_vtt, "srt": to_srt}[fmt](cues)
    path = wd.path / f"translation{FORMATS[fmt]}"
    path.write_text(text, encoding="utf-8")
    return path


# --- reading ------------------------------------------------------------------
_TIME = re.compile(r"(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{1,3})")


def _seconds(text: str) -> float:
    m = _TIME.fullmatch(text.strip())
    if not m:
        raise ValueError(f"Not a timestamp: {text!r}")
    h, mi, s, frac = m.groups()
    return int(h or 0) * 3600 + int(mi) * 60 + int(s) + int(frac.ljust(3, "0")) / 1000


ASS_FIELDS = ["Layer", "Start", "End", "Style", "Name", "MarginL", "MarginR", "MarginV", "Effect", "Text"]


def parse_ass(text: str) -> list[Cue]:
    fields = ASS_FIELDS
    cues = []
    for line in text.splitlines():
        if line.startswith("Format:") and "Text" in line:  # the [Events] one (the styles' has no Text)
            fields = [f.strip() for f in line[7:].split(",")]
        elif line.startswith("Dialogue:"):
            row = dict(zip(fields, line[9:].split(",", len(fields) - 1)))  # Text may hold commas
            body = re.sub(r"\{[^}]*\}", "", row.get("Text", "")).replace("\\N", " ").replace("\\n", " ").strip()
            cues.append(Cue(_seconds(row["Start"]), _seconds(row["End"]), body, row.get("Name", "").strip() or None))
    return cues


def parse_vtt(text: str) -> list[Cue]:
    cues = []
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n").strip()):
        lines = [line for line in block.split("\n") if line.strip()]
        timing = next((i for i, line in enumerate(lines) if "-->" in line), None)
        if timing is None:
            continue  # the WEBVTT header, a NOTE or a STYLE block
        ident = lines[timing - 1].strip() if timing else ""
        start, end = (part.split()[0] for part in lines[timing].split("-->"))
        body = " ".join(lines[timing + 1:])
        voice = re.match(r"<v(?:\.[^ >]*)?\s+([^>]+)>", body)
        speaker = voice[1].strip() if voice else None
        body = re.sub(r"</?[^>]+>", "", body).strip()
        cues.append(Cue(_seconds(start), _seconds(end), body, speaker, int(ident) if ident.isdigit() else None))
    return cues


def parse_srt(text: str) -> list[Cue]:
    cues = []
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n").strip()):
        lines = [line for line in block.split("\n") if line.strip()]
        timing = next((i for i, line in enumerate(lines) if "-->" in line), None)
        if timing is None:
            continue
        start, end = (part.strip() for part in lines[timing].split("-->"))
        cues.append(Cue(_seconds(start), _seconds(end), " ".join(lines[timing + 1:]).strip()))
    return cues


def parse(name: str, text: str) -> list[Cue]:
    """The cues of a subtitle file, by its extension (.ass/.ssa, .vtt or .srt)."""
    suffix = Path(name).suffix.lower()
    if suffix in (".ass", ".ssa"):
        return parse_ass(text)
    if suffix == ".vtt":
        return parse_vtt(text)
    if suffix == ".srt":
        return parse_srt(text)
    raise ValueError(f"Unknown subtitle format {suffix or name!r}: use .ass, .vtt or .srt")


def import_cues(wd: WorkDir, cues: list[Cue]) -> dict[str, list[int]]:
    """Put cues back into the translation: {"texts": ids edited, "speakers": ids given to another}.

    ValueError, and nothing saved, when a cue matches no sentence or names no speaker.
    """
    from .web import videos  # the web editor's save: the same hand edit, the same invalidation

    segments = speakers.apply(wd, load_segments(wd.translation))
    by_id = {s.id: s for s in segments}
    names = speakers.load(wd)["names"]
    letters = {name: letter for letter, name in names.items()} | {spk: spk for spk in speakers.known(wd)}
    texts: dict[int, str] = {}
    moved: dict[int, str] = {}
    for cue in cues:
        seg = by_id.get(cue.id) if cue.id is not None else None
        if seg is None:
            seg = min(segments, key=lambda s: abs(s.start - cue.start), default=None)
            if seg is None or abs(seg.start - cue.start) > MATCH_S:
                raise ValueError(f"No sentence starts at {cue.start:.2f} s (cue {cue.text[:40]!r})")
        if cue.text and cue.text != seg.text:
            texts[seg.id] = cue.text
        if cue.speaker is not None and seg.speaker is not None:
            letter = letters.get(cue.speaker)
            if letter is None:
                raise ValueError(f"No speaker called {cue.speaker!r} (known: {', '.join(sorted(letters))})")
            if letter != seg.speaker:
                moved[seg.id] = letter
    if texts:
        videos.save_translation(wd, [{"id": i, "text": t} for i, t in sorted(texts.items())])
    if moved:
        speakers.reassign(wd, moved)
    return {"texts": sorted(texts), "speakers": sorted(moved)}
