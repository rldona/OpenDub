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
from typing import Any

from rich.progress import BarColumn, MofNCompleteColumn, TimeElapsedColumn

from .config import Settings
from .log import Progress, console, log
from .models import Segment, load_segments, save_segments
from .workdir import WorkDir, params_hash

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
- Keep the original's register (tú or usted, formal or casual tone).
- Leave proper nouns, and technical terms that are used as-is in Spanish, in the \
original language.
- Output only text to be read aloud: no markdown, emojis, stage directions or \
translator's notes.
"""


SHORTEN_PROMPT = """\
You are a dubbing adapter. You will receive sentences already translated into \
{target} that, once voiced, do not fit their slot in the video.

For each item (id, original, translation, max_chars), rewrite the translation shorter, \
still in {target}, without exceeding max_chars, keeping its meaning and a natural \
spoken style. The original is for reference only. Return one item per id, with the \
same id. Only text to be read aloud: no markdown, emojis or notes.
"""


def _target_name(voice: str) -> str:
    return "Castilian Spanish (Spain)" if voice.startswith("es-ES") else "neutral Latin American Spanish"


def _slot(segments: list[Segment], i: int) -> float:
    """Available time: up to the next segment, borrowing at most 1 s of silence."""
    seg = segments[i]
    if i + 1 < len(segments):
        return min(segments[i + 1].start - seg.start, seg.duration + 1.0)
    return seg.duration + 1.0


def _user_prompt(
    block: list[tuple[Segment, float]], context: list[tuple[str, str]], pace: Pace
) -> str:
    payload: dict[str, Any] = {}
    if context:
        payload["previous_context"] = [{"original": o, "translation": t} for o, t in context]
    payload["segments"] = [
        {
            "id": s.id,
            "duration_s": round(slot, 1),
            "max_chars": pace.max_chars(slot),
            "text": s.text,
        }
        for s, slot in block
    ]
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
    result = subprocess.run(cmd, input=prompt, capture_output=True, text=True, encoding="utf-8", timeout=600)
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        raise RuntimeError(f"Unexpected output from claude (exit code {result.returncode}): "
                           f"{(result.stderr or result.stdout)[:500]}")
    if data.get("is_error") or not data.get("structured_output"):
        raise RuntimeError(f"claude returned an error: {data.get('result') or data.get('subtype')}")
    return data["structured_output"], float(data.get("total_cost_usd") or 0)


def _call_api(system: str, prompt: str, model: str, api_key: str | None) -> tuple[dict[str, Any], float]:
    import anthropic

    if not api_key:
        raise SystemExit("--backend api needs ANTHROPIC_API_KEY in .env")
    client = anthropic.Anthropic(api_key=api_key)
    response = client.beta.messages.create(
        model=model,
        max_tokens=16000,
        system=system,
        messages=[{"role": "user", "content": prompt}],
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}},
        # If the model refuses the request, the API retries with another suitable model
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )
    if response.stop_reason == "refusal":
        raise RuntimeError(f"Claude refused the block: {response.stop_details}")
    if response.stop_reason == "max_tokens":
        raise RuntimeError("Response truncated by max_tokens")
    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text), 0.0


def _ask(system: str, prompt: str, expected: list[int], settings: Settings) -> tuple[dict[int, str], float]:
    """Call the backend and check that exactly the requested ids come back, with retries."""
    cost = 0.0
    for attempt in range(1, MAX_ATTEMPTS + 1):
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
            log.warning(f"Attempt {attempt} failed: {e}")
    raise SystemExit(f"Claude did not return a valid response for ids {expected[0]}–{expected[-1]}")


def shorten(items: list[tuple[int, str, str, int]], voice: str, settings: Settings) -> dict[int, str]:
    """Ask for shorter versions of sentences that do not fit: (id, original, translation, max_chars)."""
    system = SHORTEN_PROMPT.format(target=_target_name(voice))
    prompt = json.dumps(
        [{"id": i, "original": o, "translation": t, "max_chars": m} for i, o, t, m in items],
        ensure_ascii=False, indent=1,
    )
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
    wd.translation_edits.write_text(json.dumps(kept, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def run(wd: WorkDir, settings: Settings, force: bool = False) -> list[Segment]:
    if settings.backend not in ("cli", "api"):
        raise SystemExit(f"--backend must be cli or api (not {settings.backend!r})")
    segments = load_segments(wd.segments)
    meta = json.loads(wd.meta.read_text(encoding="utf-8"))
    source_code = (meta.get("language") or "en").split("-")[0]
    target = _target_name(settings.voice)
    from .tts import Pace, voice_rate  # lazy import: tts also imports this module

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
    if not force and wd.is_done("translate", params) and wd.translation.exists():
        log.info("Translation cached, skipping")
        return load_segments(wd.translation)

    # Each translated block is saved separately so a run can resume if something fails midway
    block_dir = wd.path / "translate_blocks" / params_hash(params)
    if force and block_dir.exists():
        shutil.rmtree(block_dir)
    block_dir.mkdir(parents=True, exist_ok=True)

    system = SYSTEM_PROMPT.format(source=LANG_NAMES.get(source_code, source_code), target=target)
    slots = [_slot(segments, i) for i in range(len(segments))]
    pairs = list(zip(segments, slots))
    blocks = [pairs[i : i + settings.batch_size] for i in range(0, len(pairs), settings.batch_size)]
    log.info(f"{len(segments)} segments in {len(blocks)} blocks · backend {settings.backend} · {settings.claude_model}")
    log.info(f"Speaking rate for max_chars: {cps:.1f} chars/s"
             + (f" after {pace.overhead:.2f} s per clip" if pace.overhead else ""))

    translated: dict[int, str] = {}
    total_cost = 0.0
    with Progress(
        "[progress.description]{task.description}", BarColumn(), MofNCompleteColumn(),
        TimeElapsedColumn(), console=console, transient=True,
    ) as progress:
        task = progress.add_task("Translating blocks", total=len(blocks))
        for n, block in enumerate(blocks):
            path = block_dir / f"block_{n:03d}.json"
            if path.exists():
                got = {int(k): v for k, v in json.loads(path.read_text(encoding="utf-8")).items()}
            else:
                prev = [s for s, _ in pairs[: n * settings.batch_size]][-CONTEXT_SEGMENTS:]
                context = [(s.text, translated[s.id]) for s in prev]
                prompt = _user_prompt(block, context, pace)
                got, cost = _ask(system, prompt, [s.id for s, _ in block], settings)
                total_cost += cost
                path.write_text(json.dumps(got, ensure_ascii=False, indent=1), encoding="utf-8")
            translated.update(got)
            progress.advance(task)

    result = keep_edits(wd, segments, [replace(s, text=translated[s.id]) for s in segments], pace)
    save_segments(wd.translation, result)

    over = [
        (s, slot) for s, slot in zip(result, slots) if len(s.text) > pace.max_chars(slot) * 1.25
    ]
    ratio = sum(len(s.text) for s in result) / sum(len(s.text) for s in segments)
    log.info(f"ES/original length: {ratio:.0%} · probably too long: {len(over)}")
    if settings.backend == "cli" and total_cost:
        log.info(f"Equivalent API cost: ${total_cost:.3f} (not billed separately with a subscription)")
    wd.mark_done("translate", params)
    return result
