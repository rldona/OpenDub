"""Translate an SRT into Spanish as a subtitle editor does, for a dub made with another tool.

    uv run python docs/bench/listening/translate_srt.py work/_bench/external/input/17kBVfGjI8c.en.srt

Writes <name>.es.srt next to it: every line translated with its neighbours as context by
the same Claude model OpenDub uses (claude CLI, the subscription), keeping each line's
timing, but with **no length budget**. That is how Subtitle Edit's LLM translation
works (batches with context, then the voice is sped up to fit), so a blind comparison
with OpenDub measures what tells them apart (translating to fit the slot, shortening,
the quality check) and not two different translators.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

MODEL = "claude-sonnet-5-5"
BLOCK = re.compile(r"(\d+)\s*\n(\d\d:\d\d:\d\d,\d{3} --> \d\d:\d\d:\d\d,\d{3})\s*\n(.*?)(?:\n\s*\n|\Z)", re.S)

SYSTEM = """\
You translate video subtitles from English into natural Spanish from Spain (tú unless the \
speaker addresses an audience formally). Translate every line faithfully and idiomatically, \
using the neighbouring lines as context. Keep technical terms correct. Do not shorten, merge \
or split lines: one translation per id.
"""

SCHEMA = {
    "type": "object",
    "properties": {"lines": {"type": "array", "items": {
        "type": "object", "properties": {"id": {"type": "string"}, "text": {"type": "string"}},
        "required": ["id", "text"], "additionalProperties": False}}},
    "required": ["lines"], "additionalProperties": False,
}


def _ask(payload: list[dict]) -> dict[str, str]:
    claude = shutil.which("claude") or str(Path.home() / ".local/bin/claude")
    out = subprocess.run(
        [claude, "-p", "--output-format", "json", "--model", MODEL, "--system-prompt", SYSTEM,
         "--json-schema", json.dumps(SCHEMA), "--tools", "", "--no-session-persistence", "--setting-sources", ""],
        input=json.dumps(payload, ensure_ascii=False), capture_output=True, text=True, timeout=900,
    )
    data = json.loads(out.stdout)
    if data.get("is_error") or not data.get("structured_output"):
        sys.exit(f"claude failed: {data.get('result')}")
    return {line["id"]: line["text"] for line in data["structured_output"]["lines"] if line["text"].strip()}


def translate(path: Path) -> Path:
    blocks = BLOCK.findall(path.read_text(encoding="utf-8"))
    if not blocks:
        sys.exit(f"{path}: no subtitles found")
    lines = [{"id": n, "text": " ".join(t.split())} for n, _, t in blocks]
    spanish = _ask(lines)
    for _ in range(2):  # a one-word line may come back merged into its neighbour: ask for it alone
        missing = [i for i, line in enumerate(lines) if not spanish.get(line["id"])]
        if not missing:
            break
        spanish |= _ask([{"id": lines[i]["id"], "text": lines[i]["text"],
                          "previous_line": lines[i - 1]["text"] if i else "",
                          "next_line": lines[i + 1]["text"] if i + 1 < len(lines) else ""} for i in missing])
    missing = [line["id"] for line in lines if not spanish.get(line["id"])]
    if missing:
        sys.exit(f"{path}: no translation for line(s) {', '.join(missing)}")
    dst = path.with_name(path.name.removesuffix(".en.srt").removesuffix(".srt") + ".es.srt")
    dst.write_text("".join(f"{n}\n{t}\n{spanish[n]}\n\n" for n, t, _ in blocks), encoding="utf-8")
    print(f"{dst}: {len(blocks)} lines")
    return dst


if __name__ == "__main__":
    for arg in sys.argv[1:]:
        translate(Path(arg))
