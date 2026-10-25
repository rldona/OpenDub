"""One process per video: the CLI and the web never write the same files at once (WorkDir.lock)."""

import subprocess
import sys
import time

import pytest

from opendub.workdir import WorkDir

VID = "abcdefghijk"
HOLD = """
import sys, time
from pathlib import Path
from opendub.workdir import WorkDir
wd = WorkDir(Path(sys.argv[1]), "abcdefghijk")
with wd.lock("opendub tts"):
    print("ready", flush=True)
    time.sleep(30)
"""


@pytest.fixture
def held(tmp_path):
    """Another process holding the video, as a CLI phase would."""
    proc = subprocess.Popen([sys.executable, "-c", HOLD, str(tmp_path)], stdout=subprocess.PIPE, text=True)
    assert proc.stdout.readline().strip() == "ready"
    yield WorkDir(tmp_path, VID)
    proc.kill()
    proc.wait()


def test_a_second_process_stops_at_once_and_says_who(held):
    assert held.holder().startswith("pid ") and held.holder().endswith("opendub tts")
    started = time.monotonic()
    with pytest.raises(SystemExit, match=r"Another OpenDub process is working on this video \(pid \d+, opendub tts\)"):
        with held.lock("dub"):
            pass
    assert time.monotonic() - started < 1


def test_the_lock_goes_with_the_process(tmp_path):
    wd = WorkDir(tmp_path, VID)
    with wd.lock("dub"):
        assert wd.holder() == f"pid {__import__('os').getpid()}, dub"
    assert wd.holder() is None
    with wd.lock("retouch"):  # free again
        pass


def test_the_web_refuses_edits_while_another_process_holds_the_video(tmp_path):
    pytest.importorskip("fastapi")
    from test_web import FakePipeline, client, make_video

    c = client(tmp_path, FakePipeline())
    wd = make_video(tmp_path / "work")
    with wd.lock("opendub dub"):
        r = c.put(f"/videos/{wd.path.name}/translation", json=[{"id": 1, "text": "Hola."}])
        assert r.status_code == 409 and "opendub dub" in r.json()["detail"]
        assert c.post(f"/videos/{wd.path.name}/retouch", json={"takes": [1]}).status_code == 409
    assert c.put(f"/videos/{wd.path.name}/translation", json=[{"id": 1, "text": "Hola."}]).status_code == 200


def test_a_dub_doesnt_start_on_a_held_video(held, monkeypatch):
    from opendub import pipeline
    from opendub.config import Settings

    monkeypatch.setattr(pipeline, "_dub", lambda *a: pytest.fail("must not start"))
    with pytest.raises(SystemExit, match="Another OpenDub process"):
        pipeline.dub(VID, Settings(work_root=held.path.parent))
