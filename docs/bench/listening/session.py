"""Blind listening sessions: two dubs of the same videos, heard without knowing which is which.

    uv run python docs/bench/listening/session.py make <name> --a chatterbox --b chatterbox-es \\
        --videos 17kBVfGjI8c rwF-X5STYks VD6xJq8NguY 7mCTaTJ0kDo [--clips 12] [--seed 1]
    uv run python docs/bench/listening/session.py serve <name>        # http://127.0.0.1:8766/

`make` takes, per video, the latest version of each engine (outputs/<date>-<engine>.mp4),
or the version named instead of an engine (--a 20261025-213000-chatterbox), and picks 10–15 s fragments spread over the videos. For each one it cuts the original
(audio only, to judge the meaning) and both dubs (with the picture, to judge the sync),
brings each fragment to the same loudness, and shuffles which dub is "1" and which "2"
with the seed, so a session is made again identically. The media and the hidden mapping
stay in work/_bench/listening/<name>/ (third-party audio, not committed).

`serve` shows one fragment at a time: notes 1–5 for naturalness, meaning and sync of
each dub, and which one you prefer. Every answer is saved at once to
docs/bench/listening/results/<name>.json; which dub was which is only shown, and
written there, when every fragment has an answer. summary.py adds the sessions up.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

WORK = Path("work")
OUT = WORK / "_bench" / "listening"
RESULTS = Path(__file__).parent / "results"
VERSION = re.compile(r"(\d{8}-\d{6})-([a-z][a-z-]*)")
CRITERIA = ("naturalness", "meaning", "sync")
MIN_S, MAX_S = 10.0, 15.0
LOUDNESS = -20  # LUFS of every fragment, so neither dub wins by being louder


def latest(vid: str, engine: str) -> str:
    """The newest kept version of an engine for a video, or the version itself if one is named (to set two
    dubs of the same engine against each other: one voice and several voices)."""
    if VERSION.fullmatch(engine) and (WORK / vid / "outputs" / f"{engine}.mp4").exists():
        return engine
    found = sorted(m[0] for p in (WORK / vid / "outputs").glob("*.mp4") if (m := VERSION.fullmatch(p.stem))
                   and m[2] == engine)
    if not found:
        raise SystemExit(f"{vid} has no {engine} version: dub it first")
    return found[-1]


def windows(vid: str) -> list[tuple[float, float]]:
    """Every run of consecutive sentences lasting MIN_S–MAX_S, with how much of it is speech."""
    segments = json.loads((WORK / vid / "segments.json").read_text(encoding="utf-8"))
    out = []
    for i, first in enumerate(segments):
        for last in segments[i:]:
            span = last["end"] - first["start"]
            if span > MAX_S:
                break
            if span >= MIN_S:
                out.append((first["start"], last["end"]))
                break
    return out


def pick(vid: str, n: int, rng: random.Random) -> list[tuple[float, float]]:
    """n windows spread over the video: one in each of n equal parts, chosen at random within it."""
    found = windows(vid)
    if not found:
        raise SystemExit(f"{vid} has no {MIN_S:.0f}–{MAX_S:.0f} s run of sentences")
    end = found[-1][1]
    chosen = []
    for k in range(n):
        after = chosen[-1][1] if chosen else 0.0  # a window may run into the next part: never hear a stretch twice
        part = [w for w in found if k * end / n <= w[0] < (k + 1) * end / n and w[0] >= after]
        if part:
            chosen.append(rng.choice(part))
    return chosen


def _cut(src: Path, start: float, end: float, dst: Path, video: bool) -> None:
    pad = 0.3
    args = ["ffmpeg", "-v", "error", "-y", "-ss", f"{max(start - pad, 0):.3f}", "-to", f"{end + pad:.3f}",
            "-i", str(src), "-af", f"loudnorm=I={LOUDNESS}:TP=-2:LRA=11,aresample=48000"]
    if video:
        args += ["-vf", "scale=-2:480", "-c:v", "libx264", "-preset", "veryfast", "-crf", "28", "-c:a", "aac",
                 "-b:a", "160k", "-movflags", "+faststart"]
    else:
        args += ["-vn", "-c:a", "aac", "-b:a", "160k"]
    subprocess.run([*args, str(dst)], check=True)


def make(name: str, a: str, b: str, videos: list[str], clips: int, seed: int) -> None:
    rng = random.Random(seed)
    folder = OUT / name
    (folder / "media").mkdir(parents=True, exist_ok=True)
    per = [clips // len(videos) + (1 if i < clips % len(videos) else 0) for i in range(len(videos))]
    fragments = []
    for vid, n in zip(videos, per):
        versions = {"a": latest(vid, a), "b": latest(vid, b)}
        for start, end in pick(vid, n, rng):
            fid = f"f{len(fragments) + 1:02d}"
            first = rng.choice(("a", "b"))  # which dub is "1"
            order = {"1": first, "2": "b" if first == "a" else "a"}
            src_orig = WORK / vid / ("video.mp4" if (WORK / vid / "video.mp4").exists() else "audio.wav")
            _cut(src_orig, start, end, folder / "media" / f"{fid}_orig.m4a", video=False)
            for side, which in order.items():
                _cut(WORK / vid / "outputs" / f"{versions[which]}.mp4", start, end,
                     folder / "media" / f"{fid}_{side}.mp4", video=True)
            fragments.append({"id": fid, "video": vid, "start": round(start, 2), "end": round(end, 2),
                              "versions": versions, "order": order})
            print(f"{fid} {vid} {start:7.1f}–{end:7.1f} s")
    session = {"name": name, "a": a, "b": b, "seed": seed, "videos": videos, "fragments": fragments}
    (folder / "session.json").write_text(json.dumps(session, indent=1))
    print(f"{len(fragments)} fragments in {folder}")


def results(session: dict) -> dict:
    path = RESULTS / f"{session['name']}.json"
    if path.exists():
        return json.loads(path.read_text())
    return {"name": session["name"], "a": session["a"], "b": session["b"], "seed": session["seed"],
            "videos": session["videos"], "answers": {}}


def reveal(session: dict, data: dict) -> dict:
    """The answers per engine (a or b), once every fragment is answered."""
    out = {}
    for f in session["fragments"]:
        answer = data["answers"].get(f["id"])
        if not answer:
            continue
        engine = {side: session[f["order"][side]] for side in ("1", "2")}
        out[f["id"]] = {"video": f["video"], "start": f["start"], "end": f["end"],
                        "versions": {session[k]: v for k, v in f["versions"].items()},
                        "ratings": {engine[side]: answer["ratings"][side] for side in ("1", "2")},
                        "prefer": engine.get(answer["prefer"], "same")}
    return out


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Blind listening</title>
<style>
:root { color-scheme: light dark; --bg: #f6f6f9; --card: #fff; --text: #1c1c24; --muted: #6b6b7b; --accent: #7c6cf0;
  --border: #e2e2ea; }
@media (prefers-color-scheme: dark) { :root { --bg: #121218; --card: #1c1c25; --text: #ececf2; --muted: #9a9aab;
  --border: #2c2c38; } }
body { margin: 0; font: 15px/1.45 system-ui, sans-serif; background: var(--bg); color: var(--text); }
main { max-width: 1100px; margin: 0 auto; padding: 16px; }
.card { background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 14px; }
.sides { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 14px; margin-top: 14px; }
video { width: 100%; border-radius: 8px; background: #000; }
.muted { color: var(--muted); font-size: 13px; }
.row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin: 6px 0; }
.row span.label { width: 110px; }
button { font: inherit; border: 1px solid var(--border); background: var(--card); color: var(--text); border-radius: 8px;
  padding: 4px 10px; cursor: pointer; }
button[aria-pressed=true] { background: var(--accent); color: #fff; border-color: var(--accent); }
.nav { display: flex; justify-content: space-between; margin-top: 14px; }
table { border-collapse: collapse; } td, th { padding: 4px 8px; border-bottom: 1px solid var(--border); }
</style></head><body><main id="app"></main>
<script>
const CRITERIA = {naturalness: "Naturalness", meaning: "Meaning kept", sync: "Sync with the picture"};
let s = null, answers = {}, k = 0;
async function load() {
  s = await (await fetch("/data")).json();
  answers = s.answers;
  k = Math.max(0, s.fragments.findIndex((f) => !answers[f.id] || !complete(answers[f.id])));
  if (k < 0) k = 0;
  render();
}
function complete(a) { return a && a.prefer && ["1", "2"].every((side) => Object.keys(CRITERIA).every((c) => a.ratings[side][c])); }
function blank() { return {ratings: {"1": {}, "2": {}}, prefer: null}; }
async function save(f) {
  const r = await (await fetch("/save", {method: "POST", headers: {"Content-Type": "application/json"},
                                        body: JSON.stringify({id: f.id, answer: answers[f.id]})})).json();
  if (r.revealed) { s.revealed = r.revealed; }
}
function render() {
  const app = document.getElementById("app");
  if (s.revealed) return renderReveal(app);
  const f = s.fragments[k], a = answers[f.id] || (answers[f.id] = blank());
  const done = s.fragments.filter((x) => complete(answers[x.id])).length;
  app.innerHTML = `<div class="card"><b>Fragment ${k + 1} of ${s.fragments.length}</b>
    <span class="muted"> · ${done} answered · listen to the original first, then both dubs</span>
    <div class="row" style="margin-top:10px"><span class="label">Original</span><audio controls src="/media/${f.id}_orig.m4a"></audio></div></div>
    <div class="sides">${["1", "2"].map((side) => `<div class="card"><b>Dub ${side}</b>
      <video controls preload="metadata" src="/media/${f.id}_${side}.mp4"></video>
      ${Object.entries(CRITERIA).map(([c, label]) => `<div class="row"><span class="label">${label}</span>
        ${[1, 2, 3, 4, 5].map((n) => `<button data-side="${side}" data-c="${c}" data-n="${n}" aria-pressed="${a.ratings[side][c] === n}">${n}</button>`).join("")}</div>`).join("")}
    </div>`).join("")}</div>
    <div class="card" style="margin-top:14px"><div class="row"><span class="label">I prefer</span>
      ${[["1", "Dub 1"], ["same", "Same"], ["2", "Dub 2"]].map(([v, l]) => `<button data-prefer="${v}" aria-pressed="${a.prefer === v}">${l}</button>`).join("")}</div>
      <div class="muted">1 = bad · 3 = acceptable · 5 = as good as a human dub</div></div>
    <div class="nav"><button id="prev" ${k === 0 ? "disabled" : ""}>← Previous</button>
      <button id="next">${k === s.fragments.length - 1 ? "Finish" : "Next →"}</button></div>`;
  app.querySelectorAll("button[data-side]").forEach((b) => b.onclick = async () => {
    a.ratings[b.dataset.side][b.dataset.c] = Number(b.dataset.n); await save(f); render(); });
  app.querySelectorAll("button[data-prefer]").forEach((b) => b.onclick = async () => {
    a.prefer = b.dataset.prefer; await save(f); render(); });
  app.querySelector("#prev").onclick = () => { k--; render(); };
  app.querySelector("#next").onclick = () => {
    if (!complete(a)) { alert("Rate both dubs on every line and choose a preference first."); return; }
    if (k < s.fragments.length - 1) { k++; render(); } else if (!s.revealed) { alert("Some fragments still have no answer."); k = s.fragments.findIndex((x) => !complete(answers[x.id])); render(); }
  };
}
function renderReveal(app) {
  const rows = Object.entries(s.revealed).map(([id, r]) => `<tr><td>${id}</td><td>${r.video}</td>
    ${Object.entries(r.ratings).map(([e, v]) => `<td>${e}: ${v.naturalness}/${v.meaning}/${v.sync}</td>`).join("")}
    <td>${r.prefer}</td></tr>`).join("");
  app.innerHTML = `<div class="card"><b>Done: thank you.</b> <span class="muted">Saved in docs/bench/listening/results/${s.name}.json</span>
    <table style="margin-top:10px"><tr><th>Fragment</th><th>Video</th><th colspan="2">Naturalness / meaning / sync</th><th>Preferred</th></tr>${rows}</table></div>`;
}
load();
</script></body></html>
"""


def serve(name: str, port: int) -> None:
    folder = OUT / name
    session = json.loads((folder / "session.json").read_text())
    RESULTS.mkdir(parents=True, exist_ok=True)

    def complete(answer: dict) -> bool:
        return bool(answer.get("prefer")) and all(answer["ratings"][side].get(c) for side in ("1", "2")
                                                  for c in CRITERIA)

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
                data = results(session)
                done = all(complete(data["answers"].get(f["id"], {"ratings": {"1": {}, "2": {}}}))
                           for f in session["fragments"])
                public = [{"id": f["id"]} for f in session["fragments"]]  # no video, no mapping
                body = {"name": name, "fragments": public, "answers": data["answers"],
                        "revealed": reveal(session, data) if done else None}
                return self._send(json.dumps(body).encode(), "application/json")
            m = re.fullmatch(r"/media/(f\d{2}_(?:orig|1|2)\.(?:m4a|mp4))", self.path)
            if m and (path := folder / "media" / m[1]).exists():
                return self._send(path.read_bytes(), "video/mp4" if path.suffix == ".mp4" else "audio/mp4")
            self._send(b"not found", "text/plain", 404)

        def do_POST(self) -> None:
            if self.path != "/save":
                return self._send(b"not found", "text/plain", 404)
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
            ids = {f["id"] for f in session["fragments"]}
            if body.get("id") not in ids:
                return self._send(b"bad fragment", "text/plain", 422)
            data = results(session)
            data["answers"][body["id"]] = body["answer"]
            done = all(complete(data["answers"].get(i, {"ratings": {"1": {}, "2": {}}})) for i in ids)
            if done:
                data["revealed"] = reveal(session, data)
            (RESULTS / f"{name}.json").write_text(json.dumps(data, indent=1))
            self._send(json.dumps({"revealed": data.get("revealed")}).encode(), "application/json")

        def log_message(self, *args) -> None:
            pass

    print(f"Listening session {name} on http://127.0.0.1:{port}/ (Ctrl+C to stop)")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("make")
    m.add_argument("name")
    m.add_argument("--a", required=True)
    m.add_argument("--b", required=True)
    m.add_argument("--videos", nargs="+", required=True)
    m.add_argument("--clips", type=int, default=12)
    m.add_argument("--seed", type=int, default=1)
    s = sub.add_parser("serve")
    s.add_argument("name")
    s.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    if args.cmd == "make":
        make(args.name, args.a, args.b, args.videos, args.clips, args.seed)
    else:
        serve(args.name, args.port)


if __name__ == "__main__":
    main()
