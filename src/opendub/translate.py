"""Phase 3: translation into Spanish with Claude, in blocks of segments.

Two backends with the same prompt and the same output schema:
- cli: `claude -p` (Claude Code), uses the user's subscription.
- api: Anthropic SDK with ANTHROPIC_API_KEY.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from rich.progress import BarColumn, MofNCompleteColumn, TimeElapsedColumn

from . import media
from . import speakers as speakers_mod
from . import style as style_mod
from .config import Settings
from .log import Progress, check_cancelled, console, log
from .models import Segment, load_segments, save_segments
from .workdir import WorkDir, params_hash, write_text_atomic

if TYPE_CHECKING:
    from .tts import Pace  # tts imports translate: only for the annotations

CONTEXT_SEGMENTS = 5
MAX_ATTEMPTS = 3

LANG_NAMES = {"en": "English", "fr": "French", "de": "German", "it": "Italian", "pt": "Portuguese", "ja": "Japanese"}

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "segments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"id": {"type": "integer"}, "text": {"type": "string"}},
                "required": ["id", "text"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["segments"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """\
You are a professional dubbing translator. You translate a video's transcript from \
{source} into {target} so it can be voiced with a synthetic voice kept in sync with \
the picture.

You will receive JSON with `segments` (id, duration_s, max_chars, text) and sometimes \
`previous_context` with the last segments already translated, for reference only.

Rules:
- Write every translation in {target}.
- Return exactly one item per segment, with the same id and in the same order. Do not \
merge, split or drop segments.
- The translation will be read in the same time as the original: do not exceed \
max_chars (the characters that fit in the slot). If the original does not fit, condense \
it without losing meaning. If it fits, translate it fully without summarizing: max_chars \
is a cap, not a target to cut down to. Prefer natural, spoken phrasing over literal \
translation.
- A segment may start or end mid-sentence: translate it so it joins up with its \
neighbours.
{register}
- Leave proper nouns, and technical terms that are used as-is in Spanish, in the \
original language.
- Output only text to be read aloud: no markdown, emojis, stage directions or \
translator's notes.
"""


REGISTER_RULES = {
    "auto": "- Keep the original's register (tú or usted, formal or casual tone).",
    "tu": "- Address the viewer as tú (informal), whatever the original's register.",
    "usted": "- Address the viewer as usted (formal), whatever the original's register.",
}

GLOSSARY_RULE = """\
- `glossary` lists terms these segments say and how they must be rendered: use that \
rendering every time, inflected only if the grammar needs it. An empty translation \
means leave the term exactly as in the original.
"""

SPEAKER_RULE = """\
- `speaker_gender` says whether a man or a woman says the sentence: when they \
speak of themselves, use that grammatical gender (cansado/cansada).
"""

SPEAKERS_RULE = """\
- Several people speak: each segment says who (`speaker`, a letter) and, when \
known, their `gender`. When a speaker speaks of themselves, use their \
grammatical gender (cansado/cansada), and keep each one's way of speaking \
consistent.
"""

NOTES = """
Notes about this video from the person dubbing it (follow them):
{notes}
"""


SHORTEN_PROMPT = """\
You are a dubbing adapter. You will receive sentences already translated into \
{target} that, once voiced, do not fit their slot in the video.

For each item (id, original, translation, max_chars), rewrite the translation shorter, \
still in {target}, without exceeding max_chars, keeping its meaning and a natural \
spoken style. The original is for reference only. Return one item per id, with the \
same id. Only text to be read aloud: no markdown, emojis or notes.
"""


def _system(template: str, style: style_mod.Style, terms: list[style_mod.Term], **names: str) -> str:
    """A prompt with the style's register, the glossary rule when there are terms, and its notes."""
    system = template.format(register=REGISTER_RULES[style.register], **names)
    if template is SHORTEN_PROMPT and style.register != "auto":
        system += REGISTER_RULES[style.register] + "\n"
    if terms:
        system += GLOSSARY_RULE
    if style.notes:
        system += NOTES.format(notes=style.notes)
    return system


def _glossary(terms: list[style_mod.Term]) -> list[dict[str, str]]:
    return [{"term": t.source, "translation": t.target} for t in terms]


def _slot(segments: list[Segment], i: int) -> float:
    """Available time: up to the next segment, borrowing at most 1 s of silence."""
    seg = segments[i]
    if i + 1 < len(segments):
        return min(segments[i + 1].start - seg.start, seg.duration + 1.0)
    return seg.duration + 1.0


def _block_segments(
    block: list[tuple[Segment, float]], pace: Pace, paces: dict[str, Pace] | None = None,
    genders: dict[str, str | None] | None = None,
) -> list[dict[str, Any]]:
    """Each segment with its slot and its character cap; with several voices (`paces` per
    speaker) the cap of its speaker's voice, and who says it."""
    out = []
    for s, slot in block:
        item: dict[str, Any] = {"id": s.id, "duration_s": round(slot, 1),
                                "max_chars": (paces or {}).get(s.speaker, pace).max_chars(slot), "text": s.text}
        if paces:
            item["speaker"] = s.speaker
            if (genders or {}).get(s.speaker):
                item["gender"] = genders[s.speaker]
        out.append(item)
    return out


def _user_prompt(
    block: list[tuple[Segment, float]], context: list[tuple[str, str]], pace: Pace,
    terms: list[style_mod.Term] | None = None, paces: dict[str, Pace] | None = None,
    genders: dict[str, str | None] | None = None,
) -> str:
    payload: dict[str, Any] = {}
    if context:
        payload["previous_context"] = [{"original": o, "translation": t} for o, t in context]
    if terms:
        payload["glossary"] = _glossary(terms)
    payload["segments"] = _block_segments(block, pace, paces, genders)
    return json.dumps(payload, ensure_ascii=False, indent=1)


def _call_cli(system: str, prompt: str, model: str) -> tuple[dict[str, Any], float]:
    claude = shutil.which("claude") or str(Path.home() / ".local/bin/claude")
    if not Path(claude).exists():
        raise SystemExit(
            "Claude Code CLI not found. Install it with "
            "`curl -fsSL https://claude.ai/install.sh | bash` or use --backend api"
        )
    cmd = [
        claude, "-p",
        "--output-format", "json",
        "--model", model,
        "--system-prompt", system,
        "--json-schema", json.dumps(SCHEMA),
        "--tools", "",
        "--effort", "medium",
        "--no-session-persistence",
        "--setting-sources", "",
        "--strict-mcp-config",
    ]
    result = media.run(cmd, input=prompt, capture_output=True, text=True, encoding="utf-8", timeout=600)
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        raise RuntimeError(f"Unexpected output from claude (exit code {result.returncode}): "
                           f"{(result.stderr or result.stdout)[:500]}")
    if data.get("is_error") or not data.get("structured_output"):
        raise RuntimeError(f"claude returned an error: {data.get('result') or data.get('subtype')}")
    return data["structured_output"], float(data.get("total_cost_usd") or 0)


def _create(client, model: str, system: str, prompt: str):
    return client.beta.messages.create(
        model=model,
        max_tokens=16000,
        system=system,
        messages=[{"role": "user", "content": prompt}],
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}},
        # If the model refuses the request, the API retries with another suitable model
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )


def _call_api(system: str, prompt: str, model: str, api_key: str | None) -> tuple[dict[str, Any], float]:
    import anthropic

    if not api_key:
        raise SystemExit("--backend api needs ANTHROPIC_API_KEY in .env")
    client = anthropic.Anthropic(api_key=api_key)
    try:
        response = _create(client, model, system, prompt)
    except (anthropic.APIConnectionError, anthropic.APITimeoutError) as e:
        raise RuntimeError(f"can't reach the Claude API ({type(e).__name__}). Is there an internet connection?")
    if response.stop_reason == "refusal":
        raise RuntimeError(f"Claude refused the block: {response.stop_details}")
    if response.stop_reason == "max_tokens":
        raise RuntimeError("Response truncated by max_tokens")
    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text), 0.0


CLAUDE_HOST = ("api.anthropic.com", 443)
_reachable: bool | None = None  # checked once per process


def check_claude_reachable() -> None:
    """Fail at once, clearly, when Claude can't be reached: without a connection the claude CLI
    doesn't fail, it waits (measured: no answer in 90 s), so each attempt would take its whole
    timeout. Skipped behind a proxy, where a direct connection says nothing."""
    import os
    import socket

    global _reachable
    if _reachable or any(os.environ.get(v) for v in ("HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy")):
        return
    try:
        socket.create_connection(CLAUDE_HOST, timeout=5).close()
    except OSError as e:
        raise SystemExit(f"Can't reach Claude ({CLAUDE_HOST[0]}) to translate: {e}. "
                         "Is there an internet connection?") from None
    _reachable = True


def _ask(system: str, prompt: str, expected: list[int], settings: Settings) -> tuple[dict[int, str], float]:
    """Call the backend and check that exactly the requested ids come back, with retries."""
    check_claude_reachable()
    cost = 0.0
    last: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        check_cancelled()  # a cancelled job's claude call is killed: don't start another one
        try:
            if settings.backend == "cli":
                out, c = _call_cli(system, prompt, settings.claude_model)
            else:
                out, c = _call_api(system, prompt, settings.claude_model, settings.anthropic_api_key)
            cost += c
            got = {item["id"]: item["text"].strip() for item in out["segments"]}
            if sorted(got) == sorted(expected) and all(got.values()):
                return got, cost
            log.warning(f"Ids do not match (expected {expected[0]}–{expected[-1]}), retry {attempt}")
        except (RuntimeError, subprocess.TimeoutExpired) as e:
            last = e
            log.warning(f"Attempt {attempt} failed: {e}")
    why = f": {last}" if last else " (the ids it returned never matched)"
    raise SystemExit(f"Claude did not return a valid response for ids {expected[0]}–{expected[-1]} "
                     f"after {MAX_ATTEMPTS} attempts{why}")


def shorten(
    items: list[tuple[int, str, str, int]], voice: str, settings: Settings, style: style_mod.Style | None = None,
    genders: dict[int, str | None] | None = None,
) -> dict[int, str]:
    """Ask for shorter versions of sentences that do not fit: (id, original, translation, max_chars).

    With a style, the shorter versions keep its register and glossary too; with
    `genders` (several voices), the gender agreement of whoever says each one.
    """
    style = style or style_mod.Style()
    terms = style_mod.matching(style.terms, [o for _, o, _, _ in items])
    system = _system(SHORTEN_PROMPT, style, terms, target=style_mod.target_name(voice, style.variant))
    listed = [{"id": i, "original": o, "translation": t, "max_chars": m} for i, o, t, m in items]
    genders = {i: g for i, g in (genders or {}).items() if g}
    if genders:
        for item in listed:
            if item["id"] in genders:
                item["speaker_gender"] = genders[item["id"]]
        system += SPEAKER_RULE
    payload: Any = {"glossary": _glossary(terms), "items": listed} if terms else listed
    prompt = json.dumps(payload, ensure_ascii=False, indent=1)
    got, _ = _ask(system, prompt, [i for i, *_ in items], settings)
    # a shorter version that came back empty or garbled (U+FFFD) is worse than none
    bad = [i for i, text in got.items() if not text.strip() or "\ufffd" in text]
    if bad:
        log.warning(f"Ignoring {len(bad)} unusable shortened sentence(s): {bad}")
    return {i: text for i, text in got.items() if i not in bad}


def keep_edits(wd: WorkDir, originals: list[Segment], result: list[Segment], pace) -> list[Segment]:
    """Put back the hand edits made from the web over a translation made again (e.g. for another engine).

    Each edit remembers the original sentence it was made for; if the transcription
    changed and it no longer matches, the edit is dropped rather than misplaced.
    Edits longer than the new voice's limit are kept, with a warning.
    """
    if not wd.translation_edits.exists():
        return result
    edits = json.loads(wd.translation_edits.read_text(encoding="utf-8"))
    source = {s.id: s.text for s in originals}
    slots = {s.id: _slot(originals, i) for i, s in enumerate(originals)}
    kept, dropped, long = {}, [], []
    out = []
    for seg in result:
        edit = edits.get(str(seg.id))
        if edit and edit.get("source") == source.get(seg.id):
            kept[str(seg.id)] = edit
            seg = replace(seg, text=edit["text"])
            if len(seg.text) > pace.max_chars(slots[seg.id]) * 1.25:
                long.append(seg.id)
        elif edit:
            dropped.append(seg.id)
        out.append(seg)
    if kept:
        log.info(f"Kept {len(kept)} hand-edited sentence(s) from the web")
    if long:
        log.warning(f"Hand-edited sentence(s) probably too long for this voice: {long}")
    if dropped:
        log.warning(f"Dropped hand edits of sentence(s) whose original changed: {dropped}")
    write_text_atomic(wd.translation_edits, json.dumps(kept, ensure_ascii=False, indent=1))
    return out


def run(wd: WorkDir, settings: Settings, force: bool = False) -> list[Segment]:
    if settings.backend not in ("cli", "api"):
        raise SystemExit(f"--backend must be cli or api (not {settings.backend!r})")
    segments = speakers_mod.apply(wd, load_segments(wd.segments))  # with the speakers corrected by hand
    meta = json.loads(wd.meta.read_text(encoding="utf-8"))
    source_code = (meta.get("language") or "en").split("-")[0]
    style = style_mod.load(settings.work_root, wd.path, settings.style_file)
    target = style_mod.target_name(settings.voice, style.variant)
    from .tts import Pace, voice_rate  # lazy: tts imports this module
    from .voices import multi_speaker, speaker_genders, speaker_paces

    if settings.keep_translation and wd.has("translate") and wd.translation.exists():
        log.info("Keeping the existing translation (made for another voice's pace, fitted in TTS)")
        return load_segments(wd.translation)
    paces, genders = {}, {}
    if multi_speaker(settings, segments):  # several voices: each sentence capped at its speaker's pace
        genders = speaker_genders(wd)
        paces = ({spk: Pace(settings.chars_per_second) for spk in {s.speaker for s in segments}}
                 if settings.chars_per_second else speaker_paces(wd, settings, segments))
        pace = paces[min(paces)]  # A, who speaks most, for the logs
    else:
        pace = Pace(settings.chars_per_second) if settings.chars_per_second else voice_rate(wd, settings)
    cps = pace.cps
    params = {
        "model": settings.claude_model,
        "batch": settings.batch_size,
        "chars_per_second": cps,
        **({"overhead_s": pace.overhead} if pace.overhead else {}),  # cloned voices (see tts.Pace)
        "target": target,
        "source": [(s.id, s.text) for s in segments],
    }
    if paces:
        params["speakers"] = [(s.id, s.speaker) for s in segments]
        params["paces"] = {spk: [p.cps, p.overhead] for spk, p in sorted(paces.items())}
        params["genders"] = {spk: genders.get(spk) for spk in sorted(paces)}
    used = style_mod.matching(style.terms, [s.text for s in segments])
    if not style.empty:  # only then: a video without a style keeps its cached translation
        params["style"] = {"register": style.register, "notes": style.notes,
                           "terms": [(t.source, t.target) for t in used]}
    if not force and wd.is_done("translate", params) and wd.translation.exists():
        log.info("Translation cached, skipping")
        return load_segments(wd.translation)

    # Each translated block is saved under a hash of its own inputs (prompt, segments, glossary),
    # so a run can resume if something fails midway and a new glossary term only re-translates
    # the blocks that say it. The previous context is left out of it: it is for reference only.
    block_dir = wd.path / "translate_blocks" / "blocks"
    block_dir.mkdir(parents=True, exist_ok=True)

    source_name = LANG_NAMES.get(source_code, source_code)
    slots = [_slot(segments, i) for i in range(len(segments))]
    pairs = list(zip(segments, slots))
    blocks = [pairs[i : i + settings.batch_size] for i in range(0, len(pairs), settings.batch_size)]
    log.info(f"{len(segments)} segments in {len(blocks)} blocks · backend {settings.backend} · {settings.claude_model}")
    if paces:
        log.info("Speaking rate for max_chars per speaker: " + ", ".join(
            f"{spk} {p.cps:.1f} chars/s ({genders.get(spk) or '?'})" for spk, p in sorted(paces.items())))
    else:
        log.info(f"Speaking rate for max_chars: {cps:.1f} chars/s"
                 + (f" after {pace.overhead:.2f} s per clip" if pace.overhead else ""))
    if not style.empty:
        log.info(f"Style: register {style.register} · {target} · {len(used)} of {len(style.terms)} glossary "
                 f"term(s) in this video" + (" · with notes" if style.notes else ""))

    translated: dict[int, str] = {}
    total_cost = 0.0
    asked = 0
    with Progress(
        "[progress.description]{task.description}", BarColumn(), MofNCompleteColumn(),
        TimeElapsedColumn(), console=console, transient=True,
    ) as progress:
        task = progress.add_task("Translating blocks", total=len(blocks))
        for n, block in enumerate(blocks):
            terms = style_mod.matching(used, [s.text for s, _ in block])
            system = _system(SYSTEM_PROMPT, style, terms, source=source_name, target=target)
            if paces:
                system += SPEAKERS_RULE
            key = params_hash({"model": settings.claude_model, "system": system,
                               "segments": _block_segments(block, pace, paces, genders), "glossary": _glossary(terms)})
            path = block_dir / f"{key}.json"
            if path.exists() and not force:
                got = {int(k): v for k, v in json.loads(path.read_text(encoding="utf-8")).items()}
            else:
                prev = [s for s, _ in pairs[: n * settings.batch_size]][-CONTEXT_SEGMENTS:]
                context = [(s.text, translated[s.id]) for s in prev]
                prompt = _user_prompt(block, context, pace, terms, paces, genders)
                got, cost = _ask(system, prompt, [s.id for s, _ in block], settings)
                asked += 1
                total_cost += cost
                write_text_atomic(path, json.dumps(got, ensure_ascii=False, indent=1))
            translated.update(got)
            progress.advance(task)

    result = keep_edits(wd, segments, [replace(s, text=translated[s.id]) for s in segments], pace)
    save_segments(wd.translation, result)
    # so the web can tell when the style changed since (and the video needs translating again)
    write_text_atomic(wd.translation_style,
                      json.dumps(style_mod.snapshot(style, [s.text for s in segments]), ensure_ascii=False))

    over = [
        (s, slot) for s, slot in zip(result, slots) if len(s.text) > paces.get(s.speaker, pace).max_chars(slot) * 1.25
    ]
    ratio = sum(len(s.text) for s in result) / sum(len(s.text) for s in segments)
    log.info(f"ES/original length: {ratio:.0%} · probably too long: {len(over)}")
    if asked < len(blocks):
        log.info(f"Blocks translated: {asked} · reused: {len(blocks) - asked}")
    edited = set(json.loads(wd.translation_edits.read_text(encoding="utf-8"))) if wd.translation_edits.exists() else set()
    missed = [s.id for o, s in zip(segments, result)
              if str(s.id) not in edited and style_mod.misses(used, o.text, s.text)]
    if missed:
        log.warning(f"Glossary not followed in {len(missed)} segment(s): {missed}")
    if settings.backend == "cli" and total_cost:
        log.info(f"Equivalent API cost: ${total_cost:.3f} (not billed separately with a subscription)")
    wd.mark_done("translate", params)
    return result
