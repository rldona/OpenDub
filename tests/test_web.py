"""Web API with the pipeline simulated: nothing is downloaded or synthesized."""

import json
import threading
import time

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from opentranslator.log import Progress, log, phase  # noqa: E402
from opentranslator.web.app import create_app  # noqa: E402

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
    r = client(tmp_path, FakePipeline()).get("/")
    assert r.status_code == 200 and "<html" in r.text.lower()


# --- videos, translation, clips with problems ---------------------------------
def make_video(root, vid=VID, engine="edge"):
    """A work folder as a finished dub leaves it."""
    from opentranslator.models import Segment, save_segments
    from opentranslator.workdir import WorkDir

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
    from opentranslator import download

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
    from opentranslator.models import load_segments
    from opentranslator.workdir import WorkDir

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
