"""Blind listening sessions: two to four dubs of the same videos, heard without knowing which is which.

    uv run python docs/bench/listening/session.py make <name> --a chatterbox --b chatterbox-es \\
        --videos 17kBVfGjI8c rwF-X5STYks VD6xJq8NguY 7mCTaTJ0kDo [--clips 12] [--seed 1]
    uv run python docs/bench/listening/session.py make vs-others --videos 17kBVfGjI8c rwF-X5STYks \\
        --source opendub=chatterbox \\
        --source subtitle-edit=file:work/_bench/external/subtitle-edit/{video}.mp4 \\
        --source elevenlabs=file:work/_bench/external/elevenlabs/{video}.mp3
    uv run python docs/bench/listening/session.py serve <name>        # http://127.0.0.1:8766/

Each source is a label and where its dub of each video is:
- an OpenDub engine (its latest version, outputs/<date>-<engine>.mp4) or a version name
  (20261025-213000-chatterbox), to set two dubs of the same engine against each other;
- `file:` and a path with `{video}` for the video id: a dub made with another tool. It
  must cover the whole video on the original's timeline; audio alone gets the original's
  picture.
`--a`/`--b` are the two-source shorthand for engines or versions. A video given as
<id>@start-end (seconds) only gets fragments from that stretch, for sources that dubbed
only it (elevenlabs_dub.py <id>@start-end).

`make` picks 10–15 s fragments spread over the videos. For each one it cuts the original
(audio only, to judge the meaning) and every dub (with the picture, to judge the sync),
brings each to the same loudness, and shuffles which dub is "1", "2"… with the seed, so a
session is made again identically. The media and the hidden mapping stay in
work/_bench/listening/<name>/ (third-party audio, not committed).

`serve` shows one fragment at a time: a note 1–5 for each dub and which one you prefer.
New sessions ask for one overall note (both earlier sessions gave the same note to
naturalness, meaning and sync in every fragment); `--full-criteria` asks for the three.
Every answer is saved at once to docs/bench/listening/results/<name>.json; which dub was
which is only shown, and written there, when every fragment has an answer. summary.py
adds the sessions up.
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
CRITERIA = ("naturalness", "meaning", "sync")  # sessions made before "criteria" was recorded
OVERALL = ("overall",)
KEYS = "abcd"  # the hidden name of each source in a session
MAX_DRIFT_S = 1.5  # an external dub this much longer or shorter than the video is not on its timeline
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


def pick(vid: str, n: int, rng: random.Random,
         span: tuple[float, float] | None = None) -> list[tuple[float, float]]:
    """n windows spread over the video, or over `span` of it: one in each of n equal parts, at random within it."""
    found = windows(vid)
    if span:  # only a stretch was dubbed by some source: fragments from inside it
        found = [w for w in found if w[0] >= span[0] and w[1] <= span[1]]
    if not found:
        raise SystemExit(f"{vid} has no {MIN_S:.0f}–{MAX_S:.0f} s run of sentences" + (f" in {span}" if span else ""))
    begin, end = (span or (0.0, found[-1][1]))
    chosen = []
    for k in range(n):
        after = chosen[-1][1] if chosen else 0.0  # a window may run into the next part: never hear a stretch twice
        lo, hi = begin + k * (end - begin) / n, begin + (k + 1) * (end - begin) / n
        part = [w for w in found if lo <= w[0] < hi and w[0] >= after]
        if part:
            chosen.append(rng.choice(part))
    return chosen


def _cut(src: Path, start: float, end: float, dst: Path, video: bool, picture: Path | None = None) -> None:
    """A fragment of `src`, loudness-matched; `picture`: the video to show under an audio-only dub."""
    pad = 0.3
    span = ["-ss", f"{max(start - pad, 0):.3f}", "-to", f"{end + pad:.3f}"]
    args = ["ffmpeg", "-v", "error", "-y", *span, "-i", str(src)]
    if picture is not None:
        args += [*span, "-i", str(picture), "-map", "1:v:0", "-map", "0:a:0"]
    args += ["-af", f"loudnorm=I={LOUDNESS}:TP=-2:LRA=11,aresample=48000"]
    if video:
        args += ["-vf", "scale=-2:480", "-c:v", "libx264", "-preset", "veryfast", "-crf", "28", "-c:a", "aac",
                 "-b:a", "160k", "-movflags", "+faststart"]
    else:
        args += ["-vn", "-c:a", "aac", "-b:a", "160k"]
    subprocess.run([*args, str(dst)], check=True)


def source_of(spec: str, vid: str) -> tuple[str, Path]:
    """("version" or "file", what to cut) of one source for one video."""
    if spec.startswith("file:"):
        path = Path(spec.removeprefix("file:").replace("{video}", vid))
        if not path.exists():
            raise SystemExit(f"{path} does not exist: make that dub of {vid} first")
        return "file", path
    version = latest(vid, spec)
    return "version", WORK / vid / "outputs" / f"{version}.mp4"


def _probe(path: Path) -> tuple[float, bool]:
    """(duration, whether it has a picture)."""
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type",
                          "-of", "json", str(path)], capture_output=True, text=True, check=True).stdout
    data = json.loads(out)
    return float(data["format"]["duration"]), any(s["codec_type"] == "video" for s in data["streams"])


def make(name: str, sources: dict[str, str], videos: list[str], clips: int, seed: int,
         criteria: tuple[str, ...] = OVERALL) -> None:
    """`sources`: label → engine, version or file:path (two to four)."""
    if not 2 <= len(sources) <= len(KEYS):
        raise SystemExit(f"a session sets 2 to {len(KEYS)} dubs against each other")
    keys = dict(zip(KEYS, sources))  # a → label
    rng = random.Random(seed)
    folder = OUT / name
    (folder / "media").mkdir(parents=True, exist_ok=True)
    per = [clips // len(videos) + (1 if i < clips % len(videos) else 0) for i in range(len(videos))]
    fragments = []
    for arg, n in zip(videos, per):
        vid, _, stretch = arg.partition("@")  # <id>@start-end: fragments only from that stretch
        span = tuple(float(x) for x in stretch.split("-")) if stretch else None
        picture = WORK / vid / "video.mp4"
        length = _probe(picture)[0] if picture.exists() else None
        where = {}
        for key, label in keys.items():
            kind, path = source_of(sources[label], vid)
            if kind == "file":
                duration, has_picture = _probe(path)
                if length and abs(duration - length) > MAX_DRIFT_S:
                    raise SystemExit(f"{path} lasts {duration:.1f}s and the video {length:.1f}s: "
                                     "it is not a dub of the whole video on its timeline")
                if not has_picture and not picture.exists():
                    raise SystemExit(f"{path} is audio only and {vid} has no video.mp4 to give it a picture")
            where[key] = path
        for start, end in pick(vid, n, rng, span):
            fid = f"f{len(fragments) + 1:02d}"
            if len(keys) == 2:  # as two-dub sessions always drew it: the same seed makes them again
                first = rng.choice(("a", "b"))
                shuffled = [first, "b" if first == "a" else "a"]
            else:
                shuffled = list(keys)
                rng.shuffle(shuffled)
            order = {str(i + 1): key for i, key in enumerate(shuffled)}  # which dub is "1", "2"…
            src_orig = picture if picture.exists() else WORK / vid / "audio.wav"
            _cut(src_orig, start, end, folder / "media" / f"{fid}_orig.m4a", video=False)
            for side, key in order.items():
                dub = where[key]
                still = None if _probe(dub)[1] else picture  # audio only: the original's picture
                _cut(dub, start, end, folder / "media" / f"{fid}_{side}.mp4", video=True, picture=still)
            fragments.append({"id": fid, "video": vid, "start": round(start, 2), "end": round(end, 2),
                              "versions": {k: (p.stem if p.parent.name == "outputs" else str(p))
                                           for k, p in where.items()},
                              "order": order})
            print(f"{fid} {vid} {start:7.1f}–{end:7.1f} s")
    session = {"name": name, "sources": keys, "criteria": list(criteria), "seed": seed, "videos": videos,
               "fragments": fragments}
    (folder / "session.json").write_text(json.dumps(session, indent=1))
    print(f"{len(fragments)} fragments in {folder}")


def labels(session: dict) -> dict[str, str]:
    """a → label; sessions made before several sources had "a" and "b" at the top."""
    return session.get("sources") or {"a": session["a"], "b": session["b"]}


def criteria_of(session: dict) -> tuple[str, ...]:
    return tuple(session.get("criteria") or CRITERIA)


def results(session: dict) -> dict:
    path = RESULTS / f"{session['name']}.json"
    if path.exists():
        return json.loads(path.read_text())
    if "sources" not in session:
        head = {"a": session["a"], "b": session["b"]}
    else:
        head = {"sources": list(labels(session).values()), "criteria": list(criteria_of(session))}
    return {"name": session["name"], **head, "seed": session["seed"], "videos": session["videos"], "answers": {}}


def complete(session: dict, fragment: dict, answer: dict | None) -> bool:
    if not answer or not answer.get("prefer"):
        return False
    return all(answer["ratings"].get(side, {}).get(c) for side in fragment["order"] for c in criteria_of(session))


def reveal(session: dict, data: dict) -> dict:
    """The answers per source, once every fragment is answered."""
    names = labels(session)
    out = {}
    for f in session["fragments"]:
        answer = data["answers"].get(f["id"])
        if not answer:
            continue
        source = {side: names[key] for side, key in f["order"].items()}
        out[f["id"]] = {"video": f["video"], "start": f["start"], "end": f["end"],
                        "versions": {names[k]: v for k, v in f["versions"].items()},
                        "ratings": {source[side]: answer["ratings"][side] for side in f["order"]},
                        "prefer": source.get(answer["prefer"], "same")}
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
const LABELS = {overall: "Overall", naturalness: "Naturalness", meaning: "Meaning kept", sync: "Sync with the picture"};
let s = null, answers = {}, k = 0, CRITERIA = {};
async function load() {
  s = await (await fetch("/data")).json();
  answers = s.answers;
  CRITERIA = Object.fromEntries(s.criteria.map((c) => [c, LABELS[c] || c]));
  k = Math.max(0, s.fragments.findIndex((f) => !complete(f, answers[f.id])));
  if (k < 0) k = 0;
  render();
}
function complete(f, a) { return !!(a && a.prefer && f.sides.every((side) => Object.keys(CRITERIA).every((c) => (a.ratings[side] || {})[c]))); }
function blank(f) { return {ratings: Object.fromEntries(f.sides.map((side) => [side, {}])), prefer: null}; }
async function save(f) {
  const r = await (await fetch("/save", {method: "POST", headers: {"Content-Type": "application/json"},
                                        body: JSON.stringify({id: f.id, answer: answers[f.id]})})).json();
  if (r.revealed) { s.revealed = r.revealed; }
}
function render() {
  const app = document.getElementById("app");
  if (s.revealed) return renderReveal(app);
  const f = s.fragments[k], a = answers[f.id] || (answers[f.id] = blank(f));
  const done = s.fragments.filter((x) => complete(x, answers[x.id])).length;
  app.innerHTML = `<div class="card"><b>Fragment ${k + 1} of ${s.fragments.length}</b>
    <span class="muted"> · ${done} answered · listen to the original first, then every dub</span>
    <div class="row" style="margin-top:10px"><span class="label">Original</span><audio controls src="/media/${f.id}_orig.m4a"></audio></div></div>
    <div class="sides">${f.sides.map((side) => `<div class="card"><b>Dub ${side}</b>
      <video controls preload="metadata" src="/media/${f.id}_${side}.mp4"></video>
      ${Object.entries(CRITERIA).map(([c, label]) => `<div class="row"><span class="label">${label}</span>
        ${[1, 2, 3, 4, 5].map((n) => `<button data-side="${side}" data-c="${c}" data-n="${n}" aria-pressed="${a.ratings[side][c] === n}">${n}</button>`).join("")}</div>`).join("")}
    </div>`).join("")}</div>
    <div class="card" style="margin-top:14px"><div class="row"><span class="label">I prefer</span>
      ${[...f.sides.map((side) => [side, `Dub ${side}`]), ["same", "All the same"]].map(([v, l]) => `<button data-prefer="${v}" aria-pressed="${a.prefer === v}">${l}</button>`).join("")}</div>
      <div class="muted">1 = bad · 3 = acceptable · 5 = as good as a human dub</div></div>
    <div class="nav"><button id="prev" ${k === 0 ? "disabled" : ""}>← Previous</button>
      <button id="next">${k === s.fragments.length - 1 ? "Finish" : "Next →"}</button></div>`;
  app.querySelectorAll("button[data-side]").forEach((b) => b.onclick = async () => {
    a.ratings[b.dataset.side][b.dataset.c] = Number(b.dataset.n); await save(f); render(); });
  app.querySelectorAll("button[data-prefer]").forEach((b) => b.onclick = async () => {
    a.prefer = b.dataset.prefer; await save(f); render(); });
  app.querySelector("#prev").onclick = () => { k--; render(); };
  app.querySelector("#next").onclick = () => {
    if (!complete(f, a)) { alert("Rate every dub and choose a preference first."); return; }
    if (k < s.fragments.length - 1) { k++; render(); } else if (!s.revealed) { alert("Some fragments still have no answer."); k = s.fragments.findIndex((x) => !complete(x, answers[x.id])); render(); }
  };
}
function renderReveal(app) {
  const rows = Object.entries(s.revealed).map(([id, r]) => `<tr><td>${id}</td><td>${r.video}</td>
    ${Object.entries(r.ratings).map(([e, v]) => `<td>${e}: ${Object.keys(CRITERIA).map((c) => v[c]).join("/")}</td>`).join("")}
    <td>${r.prefer}</td></tr>`).join("");
  app.innerHTML = `<div class="card"><b>Done: thank you.</b> <span class="muted">Saved in docs/bench/listening/results/${s.name}.json</span>
    <table style="margin-top:10px"><tr><th>Fragment</th><th>Video</th><th colspan="${s.fragments[0].sides.length}">${Object.values(CRITERIA).join(" / ")}</th><th>Preferred</th></tr>${rows}</table></div>`;
}
load();
</script></body></html>
"""


def serve(name: str, port: int) -> None:
    folder = OUT / name
    session = json.loads((folder / "session.json").read_text())
    RESULTS.mkdir(parents=True, exist_ok=True)

    def done(answers: dict) -> bool:
        return all(complete(session, f, answers.get(f["id"])) for f in session["fragments"])

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
                # no video, no mapping: only how many dubs each fragment has
                public = [{"id": f["id"], "sides": sorted(f["order"])} for f in session["fragments"]]
                body = {"name": name, "fragments": public, "criteria": criteria_of(session),
                        "answers": data["answers"], "revealed": reveal(session, data) if done(data["answers"]) else None}
                return self._send(json.dumps(body).encode(), "application/json")
            m = re.fullmatch(r"/media/(f\d{2}_(?:orig|[1-4])\.(?:m4a|mp4))", self.path)
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
            if done(data["answers"]):
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
    m.add_argument("--a", help="two sources: the first engine or version")
    m.add_argument("--b", help="two sources: the second engine or version")
    m.add_argument("--source", action="append", default=[], metavar="LABEL=SPEC",
                   help="label=engine, label=version or label=file:path/with/{video}.mp4 (2 to 4 of them)")
    m.add_argument("--full-criteria", action="store_true", help="rate naturalness, meaning and sync, not one note")
    m.add_argument("--videos", nargs="+", required=True)
    m.add_argument("--clips", type=int, default=12)
    m.add_argument("--seed", type=int, default=1)
    s = sub.add_parser("serve")
    s.add_argument("name")
    s.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    if args.cmd == "make":
        if args.source and (args.a or args.b):
            parser.error("use --a/--b or --source, not both")
        if args.source:
            pairs = [s.split("=", 1) for s in args.source]
            if any(len(p) != 2 or not p[0] for p in pairs):
                parser.error("--source takes label=spec")
            sources = dict(pairs)
            if len(sources) != len(pairs):
                parser.error("each --source needs its own label")
        elif args.a and args.b:
            sources = {args.a: args.a, args.b: args.b}
        else:
            parser.error("give --a and --b, or two to four --source")
        make(args.name, sources, args.videos, args.clips, args.seed,
             CRITERIA if args.full_criteria else OVERALL)
    else:
        serve(args.name, args.port)


if __name__ == "__main__":
    main()
