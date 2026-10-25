"""A hung engine doesn't hang the job, and a job can be cancelled (engines.speak, JobManager.cancel)."""

import json
import sys
import threading
import time
import wave

import pytest

from opendub import engines, log, translate
from opendub.config import Settings

HANGS = """
import json, sys
print(json.dumps({"ready": True, "device": "cpu", "load_s": 0}), flush=True)
for line in sys.stdin:
    pass  # never answers
"""


def test_a_hung_worker_is_restarted_once_then_the_clip_is_left_for_the_quality_check(tmp_path, monkeypatch):
    script = tmp_path / "hangs.py"
    script.write_text(HANGS)
    started = []

    def start():
        started.append(1)
        return engines.Worker("fake", __import__("pathlib").Path(sys.executable), script, [], tmp_path,
                              tmp_path / "fake.log")

    monkeypatch.setattr(engines, "clip_timeout", lambda text: 0.3)
    out = tmp_path / "clip.wav"
    t = time.monotonic()
    assert engines.speak("fake", start, "Hola.", tmp_path / "ref.wav", out, 1.0, 0) is False
    assert len(started) == 2 and time.monotonic() - t < 5  # killed and started again once, not stuck
    with wave.open(str(out)) as w:
        assert w.getnframes() / w.getframerate() == pytest.approx(0.1)  # a beep the QC finds abnormal
    engines.shutdown()


def test_claude_is_not_called_again_once_cancelled(monkeypatch):
    monkeypatch.setattr(translate, "_call_cli", lambda *a: pytest.fail("no call after a cancel"))
    log.request_cancel()
    try:
        with pytest.raises(log.Cancelled):
            translate._ask("s", "{}", [1], Settings())
    finally:
        log.clear_cancel()


pytest.importorskip("fastapi")
from test_web import VID, VID2, client, read_events, wait_status  # noqa: E402


class Ticking:
    """A dub whose voice phase advances a progress bar until it is cancelled."""

    def __init__(self):
        self.started = threading.Event()
        self.runs = []

    def __call__(self, url, settings):
        self.runs.append(url)
        with log.phase("TTS"):
            with log.Progress(transient=True) as progress:
                task = progress.add_task("Cloning voice", total=1000)
                self.started.set()
                for _ in range(1000):
                    time.sleep(0.01)
                    progress.advance(task)


def test_a_running_job_stops_and_is_marked_cancelled(tmp_path):
    fake = Ticking()
    c = client(tmp_path, fake)
    c.post("/jobs", json={"url": VID})
    assert fake.started.wait(5)
    assert c.post(f"/jobs/{VID}/cancel").json()["id"] == VID
    job = wait_status(c, VID, statuses=("cancelled", "done", "error"))
    assert job["status"] == "cancelled" and job["error"] is None
    events = read_events(c, VID)  # the stream ends
    assert events[-1] == {**events[-1], "type": "status", "status": "cancelled"}
    saved = json.loads((tmp_path / "work" / VID / "job.json").read_text())
    assert saved["status"] == "cancelled"


def test_a_queued_job_never_runs_once_cancelled(tmp_path):
    fake = Ticking()
    c = client(tmp_path, fake)
    c.post("/jobs", json={"url": VID})
    assert fake.started.wait(5)
    c.post("/jobs", json={"url": VID2})
    assert c.post(f"/jobs/{VID2}/cancel").json()["status"] == "cancelled"
    c.post(f"/jobs/{VID}/cancel")
    wait_status(c, VID, statuses=("cancelled",))
    time.sleep(0.3)
    assert fake.runs == [VID]  # the second never started
    assert c.post("/jobs/AAAAAAAAAAA/cancel").status_code == 404
