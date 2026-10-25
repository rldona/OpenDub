"""Hand-label who says each sentence, to score the diarizers against (score.py).

    uv run python docs/bench/diarize/label.py h7PA4mXE_GA g8r8hwBHKYM 9tXzgxT5_ac --minutes 10

Serves a page on http://127.0.0.1:8765/ with the sentences of each video's first
minutes (work/<id>/segments.json), each with its clip of the original audio.
Speakers are letters you choose by ear (A = the first voice you hear, and so on);
"mixed" marks a sentence where more than one person speaks, "unsure" one you
can't tell. Every label is saved at once to work/_bench/diarize/labels/<id>.json.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

WORK = Path("work")
OUT = WORK / "_bench" / "diarize"
LABELS = ("A", "B", "C", "D", "mixed", "unsure")


def prepare(vid: str, minutes: float) -> list[dict]:
    """The sentences to label, each with its clip cut from the original audio (cached)."""
    segments = json.loads((WORK / vid / "segments.json").read_text(encoding="utf-8"))
    # empty sentences (start == end, left by the subtitles) have no audio to judge by ear
    chosen = [s for s in segments if s["start"] < minutes * 60 and s["end"] > s["start"]]
    clips = OUT / "label" / vid
    clips.mkdir(parents=True, exist_ok=True)
    for s in chosen:
        clip = clips / f"{s['id']}.mp3"
        if not clip.exists():
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{s['start']:.3f}", "-to", f"{s['end']:.3f}",
                            "-i", str(WORK / vid / "audio.wav"), "-ac", "1", "-b:a", "96k", str(clip)], check=True)
    return [{"id": s["id"], "start": s["start"], "end": s["end"], "text": s["text"]} for s in chosen]


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Who speaks</title>
<style>
:root { color-scheme: light dark; --bg: #f6f6f9; --card: #fff; --text: #1c1c24; --muted: #6b6b7b; --accent: #7c6cf0;
  --border: #e2e2ea; }
@media (prefers-color-scheme: dark) { :root { --bg: #121218; --card: #1c1c25; --text: #ececf2; --muted: #9a9aab;
  --border: #2c2c38; } }
body { margin: 0; font: 15px/1.45 system-ui, sans-serif; background: var(--bg); color: var(--text); }
header { position: sticky; top: 0; background: var(--bg); padding: 12px 16px; border-bottom: 1px solid var(--border); z-index: 2; }
header h1 { font-size: 18px; margin: 0 0 6px; }
.tabs button, .labels button { font: inherit; border: 1px solid var(--border); background: var(--card); color: var(--text);
  border-radius: 8px; padding: 4px 10px; cursor: pointer; }
.tabs button[aria-pressed=true], .labels button[aria-pressed=true] { background: var(--accent); color: #fff; border-color: var(--accent); }
.hint { color: var(--muted); font-size: 13px; margin-top: 6px; }
main { padding: 12px 16px 80px; max-width: 980px; margin: 0 auto; }
.row { display: grid; grid-template-columns: 70px 40px 1fr; gap: 10px; align-items: start; padding: 10px; border-radius: 10px;
  background: var(--card); border: 1px solid var(--border); margin-bottom: 8px; }
.row.current { outline: 2px solid var(--accent); }
.row .meta { color: var(--muted); font-size: 12px; }
.play { width: 34px; height: 34px; border-radius: 50%; border: 0; background: var(--accent); color: #fff; cursor: pointer; }
.labels { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 8px; }
</style></head><body>
<header>
  <h1>Who speaks each sentence</h1>
  <div class="tabs" id="tabs"></div>
  <div class="hint" id="progress"></div>
  <div class="hint">Space: play · 1–4: speaker A–D · 5: mixed (several voices) · 0: unsure · ↑/↓: move.
  A is the first voice you hear, B the second… keep the same letter for the same person.</div>
</header>
<main id="rows"></main>
<script>
const LABELS = ["A", "B", "C", "D", "mixed", "unsure"];
const KEYS = {"1": "A", "2": "B", "3": "C", "4": "D", "5": "mixed", "0": "unsure"};
let data = {}, video = null, current = 0, audio = new Audio();

async function load() {
  data = await (await fetch("/data")).json();
  const tabs = document.getElementById("tabs");
  Object.keys(data).forEach((vid) => {
    const b = document.createElement("button");
    b.textContent = vid; b.onclick = () => show(vid); tabs.appendChild(b);
  });
  show(Object.keys(data)[0]);
}

function show(vid) {
  video = vid; current = firstUnlabeled();
  document.querySelectorAll("#tabs button").forEach((b) => b.setAttribute("aria-pressed", b.textContent === vid));
  render();
}

function firstUnlabeled() {
  const d = data[video], i = d.sentences.findIndex((s) => !d.labels[s.id]);
  return i < 0 ? 0 : i;
}

function render() {
  const d = data[video], main = document.getElementById("rows");
  main.innerHTML = "";
  d.sentences.forEach((s, i) => {
    const row = document.createElement("div");
    row.className = "row" + (i === current ? " current" : ""); row.id = "r" + i;
    const t = new Date(s.start * 1000).toISOString().slice(14, 19);
    row.innerHTML = `<div class="meta">#${s.id}<br>${t}</div><button class="play" aria-label="Play">▶</button>
      <div><div></div><div class="labels"></div></div>`;
    row.querySelector(".play").onclick = () => { current = i; mark(); play(); };
    row.querySelector("div > div").textContent = s.text;
    const labels = row.querySelector(".labels");
    LABELS.forEach((l) => {
      const b = document.createElement("button");
      b.textContent = l; b.setAttribute("aria-pressed", d.labels[s.id] === l);
      b.onclick = () => { current = i; set(l); };
      labels.appendChild(b);
    });
    main.appendChild(row);
  });
  progress();
  document.getElementById("r" + current)?.scrollIntoView({block: "center"});
}

function mark() {
  document.querySelectorAll(".row").forEach((r, i) => r.classList.toggle("current", i === current));
  document.getElementById("r" + current)?.scrollIntoView({block: "center", behavior: "smooth"});
}

function progress() {
  const d = data[video], n = d.sentences.filter((s) => d.labels[s.id]).length;
  document.getElementById("progress").textContent = `${video}: ${n} of ${d.sentences.length} labeled`;
}

function play() {
  const s = data[video].sentences[current];
  audio.pause(); audio = new Audio(`/clip/${video}/${s.id}.mp3`); audio.play();
}

async function set(label) {
  const d = data[video], s = d.sentences[current];
  d.labels[s.id] = label;
  await fetch(`/save/${video}`, {method: "POST", headers: {"Content-Type": "application/json"},
                                 body: JSON.stringify({id: s.id, label})});
  const row = document.getElementById("r" + current);
  row.querySelectorAll(".labels button").forEach((b) => b.setAttribute("aria-pressed", b.textContent === label));
  progress();
  if (current < d.sentences.length - 1) { current++; mark(); play(); }
}

document.addEventListener("keydown", (e) => {
  if (e.key === " ") { e.preventDefault(); play(); }
  else if (KEYS[e.key]) set(KEYS[e.key]);
  else if (e.key === "ArrowDown") { e.preventDefault(); current = Math.min(current + 1, data[video].sentences.length - 1); mark(); }
  else if (e.key === "ArrowUp") { e.preventDefault(); current = Math.max(current - 1, 0); mark(); }
});
load();
</script></body></html>
"""


def serve(videos: dict[str, list[dict]], port: int) -> None:
    labels_dir = OUT / "labels"
    labels_dir.mkdir(parents=True, exist_ok=True)

    def labels(vid: str) -> dict:
        path = labels_dir / f"{vid}.json"
        return json.loads(path.read_text()) if path.exists() else {}

    class Handler(BaseHTTPRequestHandler):
        def _send(self, body: bytes, kind: str, code: int = 200) -> None:
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            if self.path == "/":
                return self._send(PAGE.encode(), "text/html; charset=utf-8")
            if self.path == "/data":
                body = {v: {"sentences": s, "labels": labels(v)} for v, s in videos.items()}
                return self._send(json.dumps(body).encode(), "application/json")
            m = re.fullmatch(r"/clip/([\w-]{11})/(\d+)\.mp3", self.path)
            if m and m[1] in videos and (clip := OUT / "label" / m[1] / f"{m[2]}.mp3").exists():
                return self._send(clip.read_bytes(), "audio/mpeg")
            self._send(b"not found", "text/plain", 404)

        def do_POST(self) -> None:
            m = re.fullmatch(r"/save/([\w-]{11})", self.path)
            if not m or m[1] not in videos:
                return self._send(b"not found", "text/plain", 404)
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
            if body.get("label") not in LABELS or not isinstance(body.get("id"), int):
                return self._send(b"bad label", "text/plain", 422)
            current = labels(m[1])
            current[str(body["id"])] = body["label"]
            (labels_dir / f"{m[1]}.json").write_text(json.dumps(current, indent=1))
            self._send(b"{}", "application/json")

        def log_message(self, *args) -> None:  # quiet
            pass

    print(f"Labeling on http://127.0.0.1:{port}/ (Ctrl+C to stop)")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("videos", nargs="+")
    parser.add_argument("--minutes", type=float, default=10.0)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    videos = {v: prepare(v, args.minutes) for v in args.videos}
    for v, s in videos.items():
        print(f"{v}: {len(s)} sentences in the first {args.minutes:g} min")
    serve(videos, args.port)


if __name__ == "__main__":
    main()
