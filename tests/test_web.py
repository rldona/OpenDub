"""Web API with the pipeline simulated: nothing is downloaded or synthesized."""

import json
import threading
import time

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from opendub.log import Progress, log, phase  # noqa: E402
from opendub.web.app import create_app  # noqa: E402

VID, VID2 = "17kBVfGjI8c", "rwF-X5STYks"


class FakePipeline:
    """Reports like the real phases (phase(), Progress, log) and can be held mid-run."""

    def __init__(self, fail_in: str | None = None):
        self.release = threading.Event()
        self.started = threading.Event()
        self.fail_in = fail_in
        self.runs: list[tuple[str, object]] = []
        self.hold = False

    def __call__(self, url, settings):
        self.runs.append((url, settings))
        self.started.set()
        with phase("Download"):
            log.info("Fetching video info…")
        with phase("TTS"):
            with Progress(transient=True) as progress:
                task = progress.add_task("Cloning voice", total=4)
                for _ in range(4):
                    progress.advance(task)
            log.warning("Quality check: 1 cloned clip(s) failed, retrying with another seed…")
            if self.hold:
                self.release.wait(5)
            if self.fail_in == "TTS":
                raise SystemExit("Claude did not return a valid response for ids 1–25")
        with phase("Mix"):
            log.info("Output: [bold]work/x/output.mp4[/]")


@pytest.fixture(autouse=True)
def engines_installed(monkeypatch):
    """Every cloning engine counts as installed, whatever this machine has (see test_engines_*)."""
    from opendub.web import videos

    real = videos.engines
    monkeypatch.setattr(videos, "engines", lambda settings=None: [
        {**e, "installed": True, "setup": None} for e in real(settings)])
    return real


def client(tmp_path, runner):
    app = create_app(tmp_path / "work", runner=runner, allowed_hosts=("testserver",))
    return TestClient(app)


def wait_status(c, vid, statuses=("done", "error"), timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        job = c.get(f"/jobs/{vid}").json()
        if job["status"] in statuses:
            return job
        time.sleep(0.02)
    raise AssertionError(f"job {vid} still {job['status']}")


def read_events(c, vid, headers=None):
    events = []
    with c.stream("GET", f"/jobs/{vid}/events", headers=headers or {}) as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        for line in r.iter_lines():
            if line.startswith("data: ") and line != "data: {}":
                events.append(json.loads(line[6:]))
    return events


def test_job_runs_and_streams_phases_progress_and_logs(tmp_path):
    fake = FakePipeline()
    c = client(tmp_path, fake)
    r = c.post("/jobs", json={"url": f"https://www.youtube.com/watch?v={VID}", "engine": "auto"})
    assert r.status_code == 200 and r.json()["id"] == VID
    assert wait_status(c, VID)["status"] == "done"

    events = read_events(c, VID)
    kinds = [e["type"] for e in events]
    assert kinds[0] == "status" and events[0]["status"] == "queued" and events[-1]["status"] == "done"
    phases = [(e["name"], e["state"]) for e in events if e["type"] == "phase"]
    assert phases == [("Download", "start"), ("Download", "done"), ("TTS", "start"), ("TTS", "done"),
                      ("Mix", "start"), ("Mix", "done")]
    progress = [e for e in events if e["type"] == "progress"]
    assert progress[-1] == {**progress[-1], "task": "Cloning voice", "completed": 4, "total": 4}
    logs = [e for e in events if e["type"] == "log"]
    assert any(e["level"] == "warning" and "Quality check" in e["message"] for e in logs)
    assert any(e["message"] == "Output: work/x/output.mp4" for e in logs), [e["message"] for e in logs]  # markup stripped
    assert len({e["message"] for e in logs}) == len(logs)  # each record once
    assert [e["seq"] for e in events] == list(range(len(events)))

    settings = fake.runs[0][1]
    assert settings.engine == "auto" and settings.separate and settings.music_volume_db == 0.0
    saved = json.loads((tmp_path / "work" / VID / "job.json").read_text())
    assert saved["status"] == "done" and saved["options"]["engine"] == "auto"


def test_events_resume_after_last_event_id(tmp_path):
    c = client(tmp_path, FakePipeline())
    c.post("/jobs", json={"url": VID})
    wait_status(c, VID)
    everything = read_events(c, VID)
    rest = read_events(c, VID, headers={"Last-Event-ID": str(everything[4]["seq"])})
    assert rest == everything[5:]


def test_same_video_twice_returns_the_running_job_and_others_wait(tmp_path):
    fake = FakePipeline()
    fake.hold = True
    c = client(tmp_path, fake)
    c.post("/jobs", json={"url": VID})
    assert fake.started.wait(5)
    again = c.post("/jobs", json={"url": f"https://youtu.be/{VID}", "engine": "indextts"}).json()
    assert again["id"] == VID and again["status"] == "running" and again["options"]["engine"] == "auto"
    c.post("/jobs", json={"url": VID2})
    assert [j["id"] for j in c.get("/jobs").json()] == [VID, VID2]
    assert c.get(f"/jobs/{VID2}").json()["status"] == "queued"  # one at a time
    fake.release.set()
    wait_status(c, VID)
    wait_status(c, VID2)
    assert [url for url, _ in fake.runs] == [VID, VID2]
    assert c.get("/jobs").json() == []


def test_failed_job_reports_the_error(tmp_path):
    c = client(tmp_path, FakePipeline(fail_in="TTS"))
    c.post("/jobs", json={"url": VID})
    job = wait_status(c, VID)
    assert job["status"] == "error" and "Claude did not return" in job["error"]
    events = read_events(c, VID)
    assert ("TTS", "error") in [(e["name"], e["state"]) for e in events if e["type"] == "phase"]
    assert events[-1]["status"] == "error"


def test_interrupted_jobs_are_marked_on_restart(tmp_path):
    folder = tmp_path / "work" / VID
    folder.mkdir(parents=True)
    (folder / "job.json").write_text(json.dumps({"id": VID, "status": "running", "options": {"url": VID}}))
    c = client(tmp_path, FakePipeline())
    job = c.get(f"/jobs/{VID}").json()
    assert job["status"] == "error" and "Interrupted" in job["error"]


def test_rejects_bad_input_and_foreign_hosts(tmp_path):
    c = client(tmp_path, FakePipeline())
    assert c.post("/jobs", json={"url": ""}).status_code == 422
    assert c.post("/jobs", json={"url": VID, "engine": "qwen"}).status_code == 422
    assert c.get("/jobs/../../etc/passwd/events").status_code == 404
    other = TestClient(create_app(tmp_path / "work", runner=FakePipeline()), base_url="http://evil.example")
    assert other.get("/jobs").status_code == 400


def test_index_page_is_served(tmp_path):
    """The built React app (frontend/, `npm run build`) and every asset it loads."""
    import re

    c = client(tmp_path, FakePipeline())
    r = c.get("/")
    assert r.status_code == 200 and '<div id="root">' in r.text
    assets = re.findall(r'(?:src|href)="(/static/[^"]+)"', r.text)
    assert any(a.endswith(".js") for a in assets) and any(a.endswith(".css") for a in assets)
    for asset in assets:
        assert c.get(asset).status_code == 200, asset


def test_status_reports_version_and_jobs(tmp_path):
    fake = FakePipeline()
    fake.hold = True
    c = client(tmp_path, fake)
    c.post("/jobs", json={"url": VID})
    assert fake.started.wait(5)
    c.post("/jobs", json={"url": VID2})
    status = c.get("/status").json()
    assert status["running"] == 1 and status["queued"] == 1 and status["work_root"] == "work" and status["version"]
    fake.release.set()
    wait_status(c, VID2)


# --- videos, translation, clips with problems ---------------------------------
def make_video(root, vid=VID, engine="edge"):
    """A work folder as a finished dub leaves it."""
    from opendub.models import Segment, save_segments
    from opendub.workdir import WorkDir

    wd = WorkDir(root, vid)
    wd.meta.write_text(json.dumps({"id": vid, "title": "How do earthquakes happen?", "duration": 155}))
    originals = [Segment(1, 0.0, 2.0, "Earthquakes are common."), Segment(2, 3.0, 5.0, "But why?"),
                 Segment(3, 6.0, 8.0, "Let's rewind.")]
    save_segments(wd.segments, originals)
    save_segments(wd.translation, [Segment(1, 0.0, 2.0, "Los terremotos son frecuentes."),
                                   Segment(2, 3.0, 5.0, "¿Pero por qué?"), Segment(3, 6.0, 8.0, "Retrocedamos.")])
    clips = [{"id": i, "start": s.start, "slot": 3.0, "raw_duration": 2.0, "tempo": t, "duration": 2.0,
              "overflow": 0.0, "file": f"tts/{i:04d}.wav", "text": txt, "voice": v, "factor": 1.0}
             for i, s, t, txt, v in [
                 (1, originals[0], 1.2, "Los terremotos son frecuentes.", engine),
                 (2, originals[1], 1.0, "¿Por qué?", "edge" if engine != "edge" else engine),
                 (3, originals[2], 1.0, "Retrocedamos.", f"{engine} (seed+1)" if engine != "edge" else engine)]]
    wd.tts_index.write_text(json.dumps({"engine": engine, "model": "m", "reference_f0_hz": 139.0, "clips": clips}))
    wd.tts_dir.mkdir()
    for i in (1, 2, 3):
        (wd.tts_dir / f"{i:04d}.wav").write_bytes(b"RIFF....WAVE")
    wd.overflow_log.write_text(
        "#1 @0.00s: lasts 2.50s at 1.25x, slot 2.40s (+0.10s) · Los terremotos son frecuentes.\n"
        "#2 @3.00s: cloned voice failed the quality check, used edge-tts · ¿Por qué?\n"
        "#3 delayed 0.09s in the mix\n")
    wd.output.write_bytes(bytes(range(256)) * 8)
    wd.thumbnail.write_bytes(b"\xff\xd8jpeg")
    for step in ("download", "transcribe", "translate", "tts", "mix"):
        wd.mark_done(step, {"step": step})
    (root / "voice_rates.json").write_text(json.dumps({"es-ES-AlvaroNeural -10%": 15.0}))
    return wd


def test_videos_list_status_and_media(tmp_path):
    c = client(tmp_path, FakePipeline())
    make_video(tmp_path / "work")
    (tmp_path / "work" / "_bench").mkdir()  # not a video id: ignored
    [v] = c.get("/videos").json()
    assert v["id"] == VID and v["title"] == "How do earthquakes happen?" and v["status"] == "done"
    assert v["duration"] == 155 and v["clips"] == 3 and v["sped_up"] == 1 and v["shortened"] == 1
    assert v["issues"] == 3 and v["reference_f0_hz"] == 139.0
    r = c.get(f"/videos/{VID}/output.mp4", headers={"Range": "bytes=100-199"})
    assert r.status_code == 206 and r.headers["content-range"] == "bytes 100-199/2048" and len(r.content) == 100
    assert c.get(f"/videos/{VID}/thumbnail").headers["content-type"] == "image/jpeg"
    assert c.get("/videos/AAAAAAAAAAA").status_code == 404
    assert not (tmp_path / "work" / "AAAAAAAAAAA").exists()  # unknown ids create nothing


def test_missing_thumbnail_is_fetched_once(tmp_path, monkeypatch):
    from opendub import download

    c = client(tmp_path, FakePipeline())
    wd = make_video(tmp_path / "work")
    wd.thumbnail.unlink()
    calls = []
    monkeypatch.setattr(download, "thumbnail", lambda wd_: calls.append(1) or False)
    assert c.get(f"/videos/{VID}/thumbnail").status_code == 404
    assert c.get(f"/videos/{VID}/thumbnail").status_code == 404
    assert len(calls) == 1


def test_video_states_follow_jobs(tmp_path):
    fake = FakePipeline()
    fake.hold = True
    c = client(tmp_path, fake)
    wd = make_video(tmp_path / "work")
    c.post("/jobs", json={"url": VID})
    assert fake.started.wait(5)
    assert c.get(f"/videos/{VID}").json()["status"] == "running"
    fake.release.set()
    wait_status(c, VID)
    wd.output.unlink()
    assert c.get(f"/videos/{VID}").json()["status"] == "pending"


def test_translation_shows_slots_and_limits(tmp_path):
    c = client(tmp_path, FakePipeline())
    make_video(tmp_path / "work")
    data = c.get(f"/videos/{VID}/translation").json()
    first, last = data["segments"][0], data["segments"][-1]
    assert first["original"] == "Earthquakes are common." and first["text"] == "Los terremotos son frecuentes."
    assert first["slot"] == 3.0 and first["max_chars"] == 45  # up to the next segment, at 15 chars/s
    assert last["slot"] == 3.0  # the last one borrows 1 s of silence
    assert data["chars_per_second"] == 15.0 and data["needs_regeneration"] is False


def test_saving_the_translation_invalidates_tts_and_mix_only(tmp_path):
    from opendub.models import load_segments
    from opendub.workdir import WorkDir

    fake = FakePipeline()
    c = client(tmp_path, fake)
    wd = make_video(tmp_path / "work")
    r = c.put(f"/videos/{VID}/translation", json=[{"id": 2, "text": "  ¿Y por qué?  "}])
    assert r.status_code == 200 and r.json()["needs_regeneration"] is True
    assert load_segments(wd.translation)[1].text == "¿Y por qué?"
    wd = WorkDir(tmp_path / "work", VID)
    assert wd.has("translate") and not wd.has("tts") and not wd.has("mix")
    assert c.put(f"/videos/{VID}/translation", json=[{"id": 99, "text": "x"}]).status_code == 422
    assert c.put(f"/videos/{VID}/translation", json=[{"id": 1, "text": ""}]).status_code == 422


def test_translation_is_locked_while_its_video_is_dubbed(tmp_path):
    fake = FakePipeline()
    fake.hold = True
    c = client(tmp_path, fake)
    make_video(tmp_path / "work")
    c.post("/jobs", json={"url": VID})
    assert fake.started.wait(5)
    assert c.put(f"/videos/{VID}/translation", json=[{"id": 1, "text": "Hola."}]).status_code == 409
    fake.release.set()
    wait_status(c, VID)


def test_issues_list_overflow_fallback_repairs_and_delays(tmp_path):
    c = client(tmp_path, FakePipeline())
    make_video(tmp_path / "work", engine="chatterbox")
    issues = c.get(f"/videos/{VID}/issues").json()
    kinds = [(i["kind"], i["id"]) for i in issues]
    assert kinds == [("fallback", 2), ("overflow", 1), ("repaired", 3), ("delayed", 3)]
    fallback = issues[0]
    assert fallback["start"] == 3.0 and fallback["text"] == "¿Por qué?"
    assert fallback["wav"] == f"/videos/{VID}/tts/0002.wav"
    assert c.get(fallback["wav"]).status_code == 200
    assert c.get(f"/videos/{VID}/tts/..%2Fmeta.json").status_code == 404
    assert c.get(f"/videos/{VID}/tts/meta.json").status_code == 404


def test_models_are_released_after_each_job(tmp_path, monkeypatch):
    from opendub import pipeline

    released = []
    monkeypatch.setattr(pipeline, "release_models", lambda: released.append(1))
    c = client(tmp_path, FakePipeline(fail_in="TTS"))
    c.post("/jobs", json={"url": VID})
    wait_status(c, VID)
    end = time.monotonic() + 2
    while not released and time.monotonic() < end:
        time.sleep(0.01)
    assert released == [1]  # also when the job fails


def test_first_ctrl_c_only_warns_while_a_dub_runs():
    from types import SimpleNamespace

    from opendub.web.app import ExitGuard

    jobs = []
    now = [100.0]
    guard = ExitGuard(SimpleNamespace(active=lambda: jobs), window=5, clock=lambda: now[0])
    assert guard.allow(exiting=False)  # idle: stops at once
    jobs.append(SimpleNamespace(id=VID, status="running"))
    assert not guard.allow(exiting=False)  # first Ctrl+C: warning only
    now[0] += 2
    assert guard.allow(exiting=False)  # second within 5 s: stop
    now[0] += 10
    assert not guard.allow(exiting=False)  # much later: warns again
    assert guard.allow(exiting=True)  # already exiting: never blocks


def test_media_run_behaves_like_subprocess_run():
    import subprocess

    from opendub import media

    r = media.run(["sh", "-c", "cat; echo err >&2"], input="hola", capture_output=True, text=True)
    assert (r.returncode, r.stdout, r.stderr) == (0, "hola", "err\n")
    with pytest.raises(subprocess.CalledProcessError):
        media.run(["sh", "-c", "exit 3"], check=True)
    with pytest.raises(subprocess.TimeoutExpired):
        media.run(["sleep", "5"], timeout=0.2)
    # nothing left running (finished ones drop out of the WeakSet once collected; other tests' may linger)
    assert not [p for p in media._children if p.poll() is None]


def test_ytdlp_children_join_the_web_server_session_rules(monkeypatch):
    import os
    import subprocess

    from yt_dlp.utils import Popen as YtdlpPopen

    from opendub import download, media  # noqa: F401  (download adopts yt-dlp's Popen)

    monkeypatch.setattr(media, "CHILD_SESSION", True)
    with YtdlpPopen(["sleep", "2"], stdout=subprocess.DEVNULL) as proc:
        assert os.getsid(proc.pid) != os.getsid(0)  # out of the terminal's Ctrl+C
        assert proc in media._children
        media.stop_children()  # a confirmed Ctrl+C ends it
        assert proc.wait(timeout=2) != 0
    monkeypatch.setattr(media, "CHILD_SESSION", False)
    with YtdlpPopen(["true"]) as proc:
        assert os.getsid(proc.pid) == os.getsid(0)  # the CLI: unchanged


def test_engines_say_which_are_installed_and_how(tmp_path, monkeypatch, engines_installed):
    from opendub import cosyvoice, indextts
    from opendub.config import Settings
    from opendub.web import videos

    nowhere = Settings(indextts_dir=tmp_path / "ix", cosyvoice_dir=tmp_path / "cv")
    listed = {e["id"]: e for e in engines_installed(nowhere)}
    assert list(listed) == ["auto", "chatterbox", "indextts", "cosyvoice"]
    assert not listed["cosyvoice"]["installed"] and "setup-engine cosyvoice" in listed["cosyvoice"]["setup"]
    assert not listed["indextts"]["installed"]
    assert listed["auto"]["installed"] == listed["chatterbox"]["installed"]  # CosyVoice only when installed
    assert not cosyvoice.installed(tmp_path / "cv") and indextts.paths(tmp_path / "ix")[0] == tmp_path / "ix" / "repo"

    # a job with an engine that isn't installed is refused with the command that installs it
    monkeypatch.setattr(videos, "engines", lambda settings=None: engines_installed(nowhere))
    fake = FakePipeline()
    c = client(tmp_path, fake)
    assert c.get("/engines").json()[3]["id"] == "cosyvoice"
    r = c.post("/jobs", json={"url": VID, "engine": "cosyvoice"})
    assert r.status_code == 422 and "setup-engine cosyvoice" in r.json()["detail"]["message"]
    assert c.post("/jobs", json={"url": VID, "tts": "edge", "engine": "cosyvoice"}).status_code == 200  # no cloning
    assert fake.runs == [] or fake.runs[0][1].tts == "edge"


def test_another_engine_keeps_the_translation(tmp_path):
    fake = FakePipeline()
    c = client(tmp_path, fake)
    c.post("/jobs", json={"url": VID, "engine": "cosyvoice", "keep_translation": True})
    job = wait_status(c, VID)
    assert job["options"]["engine"] == "cosyvoice" and job["options"]["keep_translation"] is True
    settings = fake.runs[0][1]
    assert settings.engine == "cosyvoice" and settings.keep_translation and settings.tts == "clone"


def test_style_global_and_per_video_and_glossary_issues(tmp_path):
    c = client(tmp_path, FakePipeline())
    wd = make_video(tmp_path / "work")
    assert c.get("/style").json()["register"] == "auto"
    r = c.put("/style", json={"register": "tu", "terms": [{"source": "earthquakes", "target": "seísmos"}]})
    assert r.status_code == 200 and r.json()["terms"] == [{"source": "earthquakes", "target": "seísmos"}]
    assert c.put("/style", json={"register": "vos"}).status_code == 422

    data = c.get(f"/videos/{VID}/style").json()
    assert data["applied"]["register"] == "tu" and data["used"] == ["earthquakes"]
    assert data["stale"] is True  # translated before the style existed
    issues = c.get(f"/videos/{VID}/issues").json()
    assert ("glossary", 1) in [(i["kind"], i["id"]) for i in issues]

    r = c.put(f"/videos/{VID}/style", json={"register": "usted", "terms": [{"source": "Earthquakes", "target": "terremotos"}]})
    data = r.json()
    assert data["applied"]["register"] == "usted"
    assert data["applied"]["terms"] == [{"source": "Earthquakes", "target": "terremotos"}]  # the video's wins
    assert "glossary" not in [i["kind"] for i in c.get(f"/videos/{VID}/issues").json()]

    # the translation remembers the style it was made with
    from opendub import style

    st = style.merge(style.read(wd.path.parent / style.FILE), style.read(wd.path / style.FILE))
    wd.translation_style.write_text(json.dumps(style.snapshot(st, ["Earthquakes are common.", "But why?", "Let's rewind."])))
    assert c.get(f"/videos/{VID}/style").json()["stale"] is False
    c.put(f"/videos/{VID}/style", json={})
    assert not (wd.path / style.FILE).exists()


def test_retouch_queues_a_job_with_the_last_options(tmp_path):
    fake = FakePipeline()
    c = client(tmp_path, fake)
    wd = make_video(tmp_path / "work", engine="chatterbox")
    (wd.path / "job.json").write_text(json.dumps({"id": VID, "status": "done", "error": None, "options": {
        "url": VID, "separate": True, "tts": "clone", "engine": "chatterbox", "voice": "es-ES-AlvaroNeural",
        "bg_volume": -3.0, "keep_translation": True}}))
    assert c.post(f"/videos/{VID}/retouch", json={}).status_code == 422  # nothing edited, no take
    assert c.post(f"/videos/{VID}/retouch", json={"takes": [99]}).status_code == 422
    assert c.post("/videos/AAAAAAAAAAA/retouch", json={}).status_code == 404

    c.put(f"/videos/{VID}/translation", json=[{"id": 1, "text": "Los terremotos son habituales."}])
    assert c.get(f"/videos/{VID}/translation").json()["pending"] == [1]
    r = c.post(f"/videos/{VID}/retouch", json={"takes": [3, 3]})
    assert r.status_code == 200 and r.json()["segments"] == [1, 3]
    wait_status(c, VID)
    _, settings = fake.runs[-1]
    assert settings.retouch == (3,) and settings.music_volume_db == -3.0 and settings.engine == "chatterbox"

    # a plain dub afterwards is not a retouch, even though job.json remembers one
    c.post("/jobs", json={"url": VID})
    wait_status(c, VID)
    assert fake.runs[-1][1].retouch is None


def test_retouch_needs_a_cloned_voice_for_takes(tmp_path):
    c = client(tmp_path, FakePipeline())
    make_video(tmp_path / "work", engine="edge")
    r = c.post(f"/videos/{VID}/retouch", json={"takes": [2]})
    assert r.status_code == 422 and "cloned voice" in r.json()["detail"]["message"]


def test_versions_export_and_their_exports_go_with_them(tmp_path):
    c = client(tmp_path, FakePipeline())
    wd = make_video(tmp_path / "work")
    wd.outputs_dir.mkdir()
    old = wd.outputs_dir / "20261024-090000-edge"
    old.with_suffix(".mp4").write_bytes(b"old")
    old.with_suffix(".tts.json").write_text(wd.tts_index.read_text())
    r = c.get(f"/videos/{VID}/outputs/20261024-090000-edge/export/srt")
    assert r.status_code == 200 and "Los terremotos son frecuentes." in r.text
    assert r.headers["content-disposition"].endswith(f'filename="{VID}.20261024-090000-edge.es.srt"')
    assert "Earthquakes are common." in c.get(f"/videos/{VID}/outputs/20261024-090000-edge/export/srt-orig").text
    assert c.get(f"/videos/{VID}/outputs/20261024-090000-edge/export/avi").status_code == 404
    assert c.get(f"/videos/{VID}/outputs/20261024-000000-edge/export/srt").status_code == 404
    assert c.get(f"/videos/{VID}/outputs/latest/export/srt").status_code == 404  # output.mp4 isn't kept here
    assert c.delete(f"/videos/{VID}/outputs/20261024-090000-edge").status_code == 200
    assert not list(wd.outputs_dir.glob("20261024-090000-edge*"))


def _with_speakers(wd):
    """make_video's dub, as if diarized: A says 1 and 3, B says 2."""
    from opendub.models import load_segments, save_segments

    wd.diarization.write_text(json.dumps({"turns": [], "speakers": {
        "A": {"seconds": 400.0, "f0_hz": 120.0}, "B": {"seconds": 90.0, "f0_hz": 210.0}}}))
    for path in (wd.segments, wd.translation):
        segs = load_segments(path)
        for s in segs:
            s.speaker = "B" if s.id == 2 else "A"
        save_segments(path, segs)
    index = json.loads(wd.tts_index.read_text())
    index["sources"] = {str(s.id): s.text for s in load_segments(wd.translation)}
    index["speakers"] = {"1": "A", "2": "B", "3": "A"}
    index["speaker_voices"] = {"A": {"engine": "chatterbox", "voice": None, "reference": "clone_ref_A.wav",
                                     "gender": "male", "stock": "es-ES-AlvaroNeural"},
                               "B": {"engine": "edge", "voice": "es-ES-ElviraNeural", "reference": None,
                                     "gender": "female", "stock": None}}
    wd.tts_index.write_text(json.dumps(index))
    (wd.path / "clone_ref_A.wav").write_bytes(b"RIFF....WAVE")


def test_speakers_list_rename_reassign_and_merge(tmp_path):
    c = client(tmp_path, FakePipeline())
    wd = make_video(tmp_path / "work", engine="chatterbox")
    assert c.get(f"/videos/{VID}/speakers").json() == []  # one voice
    _with_speakers(wd)
    a, b = c.get(f"/videos/{VID}/speakers").json()
    assert (a["id"], a["gender"], a["sentences"], a["voice"]["engine"]) == ("A", "male", 2, "chatterbox")
    assert (b["gender"], b["voice"]["voice"], b["sample"]) == ("female", "es-ES-ElviraNeural", None)
    assert c.get(a["sample"]).status_code == 200
    assert c.get(f"/videos/{VID}/speakers/B.wav").status_code == 404

    assert c.put(f"/videos/{VID}/speakers/A", json={"name": "Andy"}).json()[0]["name"] == "Andy"
    assert c.put(f"/videos/{VID}/speakers/Z", json={"name": "x"}).status_code == 404

    r = c.put(f"/videos/{VID}/segments/speakers", json=[{"id": 3, "speaker": "B"}])
    assert r.status_code == 200
    assert [s["speaker"] for s in r.json()["translation"]["segments"]] == ["A", "B", "B"]
    assert r.json()["translation"]["pending"] == [3]  # a retouch speaks it with B's voice
    assert c.put(f"/videos/{VID}/segments/speakers", json=[{"id": 3, "speaker": "C"}]).status_code == 422
    assert c.put(f"/videos/{VID}/segments/speakers", json=[{"id": 9, "speaker": "A"}]).status_code == 422

    r = c.post(f"/videos/{VID}/speakers/B/merge", json={"into": "A"})
    assert r.json()["moved"] == 2
    assert {s["speaker"] for s in r.json()["translation"]["segments"]} == {"A"}
    assert c.post(f"/videos/{VID}/speakers/A/merge", json={"into": "A"}).status_code == 422
    # kept for a translation made again
    assert json.loads((wd.path / "speakers.json").read_text())["segments"] == {"3": "A", "2": "A"}


def test_several_voices_need_the_diarizer(tmp_path, monkeypatch):
    from opendub.web import videos

    fake = FakePipeline()
    c = client(tmp_path, fake)
    monkeypatch.setattr(videos, "diarizer", lambda settings=None: {"installed": False, "setup": "uv run x"})
    r = c.post("/jobs", json={"url": VID, "multi_speaker": True})
    assert r.status_code == 422 and "uv run x" in r.json()["detail"]["message"]
    assert c.get("/status").json()["diarizer"]["installed"] is False
    monkeypatch.setattr(videos, "diarizer", lambda settings=None: {"installed": True, "setup": None})
    c.post("/jobs", json={"url": VID, "multi_speaker": True})
    wait_status(c, VID)
    assert fake.runs[-1][1].multi_speaker is True


def test_a_dub_without_an_engine_picks_automatically(tmp_path):
    fake = FakePipeline()
    c = client(tmp_path, fake)
    assert c.post("/jobs", json={"url": VID}).status_code == 200
    wait_status(c, VID)
    assert fake.runs[-1][1].engine == "auto"  # CosyVoice with several voices, Chatterbox with one


def test_errors_carry_a_code_the_page_translates(tmp_path):
    c = client(tmp_path, FakePipeline())
    detail = c.get("/videos/zzzzzzzzzzz/translation").json()["detail"]
    assert detail == {"code": "unknown_video", "message": "Unknown video", "params": {}}
    detail = c.post("/jobs/AAAAAAAAAAA/cancel").json()["detail"]
    assert detail["code"] == "no_job"


def test_the_library_reads_a_version_again_only_when_its_files_change(tmp_path, monkeypatch):
    import os

    from opendub import mix
    from opendub.web import videos
    from opendub.workdir import WorkDir

    wd = make_video(tmp_path)
    mix.archive(WorkDir(tmp_path, VID))
    read = []
    real = videos.issues
    monkeypatch.setattr(videos, "issues", lambda wd, version=None: read.append(version) or real(wd, version))
    first = videos.outputs(wd)
    assert videos.outputs(wd) == first and len(read) == 1  # the second listing reads nothing
    wd.overflow_log.write_text(wd.overflow_log.read_text() + "#2 delayed 0.30s in the mix\n")
    os.utime(wd.overflow_log, ns=(1, wd.overflow_log.stat().st_mtime_ns + 10**9))
    assert videos.outputs(wd)[0]["issues"] == first[0]["issues"] + 1 and len(read) == 2  # changed: read again
    (tmp_path / "style.json").write_text(json.dumps({"terms": [{"source": "rewind", "target": "rebobinar"}]}))
    assert videos.outputs(wd)[0]["issues"] == first[0]["issues"] + 2 and len(read) == 3  # a new glossary term


def test_a_video_says_whether_its_latest_dub_had_several_voices(tmp_path):
    wd = make_video(tmp_path / "work")
    c = client(tmp_path, FakePipeline())
    assert c.get(f"/videos/{VID}").json()["several_voices"] is False
    index = json.loads(wd.tts_index.read_text())
    wd.tts_index.write_text(json.dumps(index | {"speakers": {"1": "A", "2": "B", "3": "A"}}))  # dubbed from the CLI
    assert c.get(f"/videos/{VID}").json()["several_voices"] is True


def test_a_job_that_asks_for_review_ends_waiting_for_it(tmp_path):
    from opendub import pipeline

    def stops(url, settings):
        assert settings.review
        raise pipeline.ReviewPending("Translation ready to review")

    c = client(tmp_path, stops)
    assert c.post("/jobs", json={"url": VID, "review": True}).status_code == 200
    job = wait_status(c, VID, ("review", "done", "error"))
    assert job["status"] == "review" and job["finished"] and job["options"]["review"] is True


def test_a_common_failure_keeps_its_code_for_the_page(tmp_path):
    from opendub.errors import PhaseError

    def offline(url, settings):
        raise PhaseError("claude_unreachable", "Can't reach Claude (api.anthropic.com)", host="api.anthropic.com")

    c = client(tmp_path, offline)
    make_video(tmp_path / "work")  # dubbed before: this time the translation can't reach Claude
    assert c.post("/jobs", json={"url": VID}).status_code == 200
    job = wait_status(c, VID)
    assert job["status"] == "error" and job["error"] == "Can't reach Claude (api.anthropic.com)"
    assert job["error_code"] == "claude_unreachable" and job["error_params"] == {"host": "api.anthropic.com"}
    status = [e for e in read_events(c, VID) if e["type"] == "status"][-1]
    assert status["error_code"] == "claude_unreachable" and status["error_params"] == {"host": "api.anthropic.com"}
    assert json.loads((tmp_path / "work" / VID / "job.json").read_text())["error_code"] == "claude_unreachable"
    video = c.get(f"/videos/{VID}").json()
    assert video["status"] == "error" and video["error_code"] == "claude_unreachable"


def test_the_translation_goes_out_as_subtitles_and_comes_back(tmp_path):
    c = client(tmp_path, FakePipeline())
    make_video(tmp_path / "work")
    r = c.get(f"/videos/{VID}/translation/export/vtt")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/vtt")
    fixed = r.text.replace("¿Pero por qué?", "Pero ¿por qué?")
    r = c.post(f"/videos/{VID}/translation/import", json={"name": "fixed.vtt", "text": fixed})
    assert r.status_code == 200 and r.json()["imported"] == {"texts": [2], "speakers": []}
    assert next(s for s in r.json()["translation"]["segments"] if s["id"] == 2)["text"] == "Pero ¿por qué?"
    bad = c.post(f"/videos/{VID}/translation/import", json={"name": "x.vtt", "text": "WEBVTT\n\n00:01:00.000 --> 00:01:01.000\nSobra."})
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "bad_subtitles"
    assert c.get(f"/videos/{VID}/translation/export/docx").status_code == 404


def test_several_engines_dub_one_after_another_and_a_failure_stops_the_rest(tmp_path):
    fake = FakePipeline()
    c = client(tmp_path, fake)
    r = c.post("/jobs", json={"url": VID, "engine": "chatterbox", "then": ["indextts", "cosyvoice"]})
    assert r.status_code == 200 and r.json()["options"]["then"] == ["indextts", "cosyvoice"]
    end = time.monotonic() + 5
    while len(fake.runs) < 3 and time.monotonic() < end:
        time.sleep(0.02)
    wait_status(c, VID)
    assert [s.engine for _, s in fake.runs] == ["chatterbox", "indextts", "cosyvoice"]
    assert c.get(f"/jobs/{VID}").json()["options"]["then"] == []

    failing = FakePipeline(fail_in="TTS")
    c = client(tmp_path / "again", failing)
    c.post("/jobs", json={"url": VID, "engine": "indextts", "then": ["cosyvoice"]})
    assert wait_status(c, VID)["status"] == "error"
    time.sleep(0.2)
    assert [s.engine for _, s in failing.runs] == ["indextts"]  # the rest isn't dubbed

    assert c.post("/jobs", json={"url": VID, "tts": "edge", "then": ["cosyvoice"]}).status_code == 422


def test_more_engines_join_the_queue_of_a_video_being_dubbed(tmp_path):
    fake = FakePipeline()
    fake.hold = True
    c = client(tmp_path, fake)
    c.post("/jobs", json={"url": VID, "engine": "cosyvoice"})
    assert fake.started.wait(5)
    r = c.post(f"/jobs/{VID}/then", json={"engines": ["indextts", "cosyvoice", "indextts"]})
    assert r.status_code == 200 and r.json()["options"]["then"] == ["indextts"]  # no repeats, not the running one
    fake.release.set()
    end = time.monotonic() + 5
    while len(fake.runs) < 2 and time.monotonic() < end:
        time.sleep(0.02)
    wait_status(c, VID)
    assert [s.engine for _, s in fake.runs] == ["cosyvoice", "indextts"]
    assert c.post(f"/jobs/{VID}/then", json={"engines": ["chatterbox"]}).status_code == 404  # nothing running
