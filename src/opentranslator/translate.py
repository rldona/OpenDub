"""Fase 3: traducción al español con Claude, por bloques de segmentos.

Dos backends con el mismo prompt y el mismo esquema de salida:
- cli: `claude -p` (Claude Code), consume la suscripción del usuario.
- api: SDK de Anthropic con ANTHROPIC_API_KEY.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import Any

from rich.progress import BarColumn, MofNCompleteColumn, Progress, TimeElapsedColumn

from .config import Settings
from .log import console, log
from .models import Segment, load_segments, save_segments
from .workdir import WorkDir, params_hash

CONTEXT_SEGMENTS = 5
MAX_ATTEMPTS = 3

LANG_NAMES = {"en": "inglés", "fr": "francés", "de": "alemán", "it": "italiano", "pt": "portugués", "ja": "japonés"}

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
Eres un traductor profesional de doblaje. Traduces la transcripción de un vídeo \
del {source} al {target} para locutarla con voz sintética sincronizada con la imagen.

Recibirás un JSON con `segmentos` (id, duracion_s, max_chars, texto) y, a veces, \
`contexto_previo` con los últimos segmentos ya traducidos, solo como referencia.

Reglas:
- Devuelve exactamente un elemento por segmento, con el mismo id y en el mismo orden. \
No unas, partas ni omitas segmentos.
- La traducción se leerá en el mismo tiempo que el original: no superes max_chars \
(caracteres que caben en el hueco). Si el original no cabe, condensa sin perder el \
sentido. Si cabe, traduce completo sin resumir: max_chars es un límite, no un objetivo \
de recorte. Prefiere frases naturales y habladas a traducciones literales.
- Un segmento puede empezar o terminar a mitad de frase: tradúcelo para que encaje \
con sus vecinos.
- Mantén el registro del original (tuteo o trato de usted, tono formal o coloquial).
- Deja en el idioma original los nombres propios y los términos técnicos que se usen \
así en español.
- Solo texto para leer en voz alta: sin markdown, emojis, acotaciones ni notas del traductor.
"""


def _target_name(voice: str) -> str:
    return "español de España" if voice.startswith("es-ES") else "español latinoamericano neutro"


def _slot(segments: list[Segment], i: int) -> float:
    """Tiempo disponible: hasta el siguiente segmento, con como mucho 1 s de silencio prestado."""
    seg = segments[i]
    if i + 1 < len(segments):
        return min(segments[i + 1].start - seg.start, seg.duration + 1.0)
    return seg.duration + 1.0


def _user_prompt(
    block: list[tuple[Segment, float]], context: list[tuple[str, str]], chars_per_second: float
) -> str:
    payload: dict[str, Any] = {}
    if context:
        payload["contexto_previo"] = [{"original": o, "traduccion": t} for o, t in context]
    payload["segmentos"] = [
        {
            "id": s.id,
            "duracion_s": round(slot, 1),
            "max_chars": round(slot * chars_per_second),
            "texto": s.text,
        }
        for s, slot in block
    ]
    return json.dumps(payload, ensure_ascii=False, indent=1)


def _call_cli(system: str, prompt: str, model: str) -> tuple[dict[str, Any], float]:
    claude = shutil.which("claude") or str(Path.home() / ".local/bin/claude")
    if not Path(claude).exists():
        raise SystemExit(
            "No encuentro el CLI de Claude Code. Instálalo con "
            "`curl -fsSL https://claude.ai/install.sh | bash` o usa --backend api"
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
    result = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=600)
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        raise RuntimeError(f"Salida inesperada de claude (código {result.returncode}): "
                           f"{(result.stderr or result.stdout)[:500]}")
    if data.get("is_error") or not data.get("structured_output"):
        raise RuntimeError(f"claude devolvió un error: {data.get('result') or data.get('subtype')}")
    return data["structured_output"], float(data.get("total_cost_usd") or 0)


def _call_api(system: str, prompt: str, model: str, api_key: str | None) -> tuple[dict[str, Any], float]:
    import anthropic

    if not api_key:
        raise SystemExit("--backend api necesita ANTHROPIC_API_KEY en .env")
    client = anthropic.Anthropic(api_key=api_key)
    response = client.beta.messages.create(
        model=model,
        max_tokens=16000,
        system=system,
        messages=[{"role": "user", "content": prompt}],
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}},
        # Si el modelo rechaza la petición, la API reintenta con otro modelo adecuado
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )
    if response.stop_reason == "refusal":
        raise RuntimeError(f"Claude rechazó el bloque: {response.stop_details}")
    if response.stop_reason == "max_tokens":
        raise RuntimeError("Respuesta truncada por max_tokens")
    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text), 0.0


def _translate_block(
    block: list[tuple[Segment, float]], context: list[tuple[str, str]], system: str, settings: Settings
) -> tuple[dict[int, str], float]:
    prompt = _user_prompt(block, context, settings.chars_per_second)
    expected = [s.id for s, _ in block]
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
            log.warning(f"Ids no coinciden (esperados {expected[0]}–{expected[-1]}), reintento {attempt}")
        except (RuntimeError, subprocess.TimeoutExpired) as e:
            log.warning(f"Fallo en el intento {attempt}: {e}")
    raise SystemExit(f"No se pudo traducir el bloque {expected[0]}–{expected[-1]}")


def run(wd: WorkDir, settings: Settings, force: bool = False) -> list[Segment]:
    if settings.backend not in ("cli", "api"):
        raise SystemExit(f"--backend debe ser cli o api (no {settings.backend!r})")
    segments = load_segments(wd.segments)
    meta = json.loads(wd.meta.read_text(encoding="utf-8"))
    source_code = (meta.get("language") or "en").split("-")[0]
    target = _target_name(settings.voice)
    params = {
        "model": settings.claude_model,
        "batch": settings.batch_size,
        "chars_per_second": settings.chars_per_second,
        "target": target,
        "source": [(s.id, s.text) for s in segments],
    }
    if not force and wd.is_done("translate", params) and wd.translation.exists():
        log.info("Traducción en caché, la salto")
        return load_segments(wd.translation)

    # Cada bloque traducido se guarda aparte para poder reanudar si algo falla a mitad
    block_dir = wd.path / "translate_blocks" / params_hash(params)
    if force and block_dir.exists():
        shutil.rmtree(block_dir)
    block_dir.mkdir(parents=True, exist_ok=True)

    system = SYSTEM_PROMPT.format(source=LANG_NAMES.get(source_code, source_code), target=target)
    slots = [_slot(segments, i) for i in range(len(segments))]
    pairs = list(zip(segments, slots))
    blocks = [pairs[i : i + settings.batch_size] for i in range(0, len(pairs), settings.batch_size)]
    log.info(f"{len(segments)} segmentos en {len(blocks)} bloques · backend {settings.backend} · {settings.claude_model}")

    translated: dict[int, str] = {}
    total_cost = 0.0
    with Progress(
        "[progress.description]{task.description}", BarColumn(), MofNCompleteColumn(),
        TimeElapsedColumn(), console=console, transient=True,
    ) as progress:
        task = progress.add_task("Traduciendo bloques", total=len(blocks))
        for n, block in enumerate(blocks):
            path = block_dir / f"block_{n:03d}.json"
            if path.exists():
                got = {int(k): v for k, v in json.loads(path.read_text(encoding="utf-8")).items()}
            else:
                prev = [s for s, _ in pairs[: n * settings.batch_size]][-CONTEXT_SEGMENTS:]
                context = [(s.text, translated[s.id]) for s in prev]
                got, cost = _translate_block(block, context, system, settings)
                total_cost += cost
                path.write_text(json.dumps(got, ensure_ascii=False, indent=1), encoding="utf-8")
            translated.update(got)
            progress.advance(task)

    result = [replace(s, text=translated[s.id]) for s in segments]
    save_segments(wd.translation, result)

    over = [
        (s, slot) for s, slot in zip(result, slots) if len(s.text) > slot * settings.chars_per_second * 1.25
    ]
    ratio = sum(len(s.text) for s in result) / sum(len(s.text) for s in segments)
    log.info(f"Longitud ES/original: {ratio:.0%} · segmentos probablemente largos: {len(over)}")
    if settings.backend == "cli" and total_cost:
        log.info(f"Coste equivalente en API: ${total_cost:.3f} (con suscripción no se cobra aparte)")
    wd.mark_done("translate", params)
    return result
