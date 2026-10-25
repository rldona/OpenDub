"""A whole dub end to end, without network or GPU (e2e_flow.py): the pipeline and the CLI."""

import json
import shutil

import pytest

from e2e_flow import VID, dub, install_fakes, make_video
from opendub.media import probe

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")


@pytest.fixture
def work(tmp_path, monkeypatch):
    make_video(tmp_path)
    install_fakes(monkeypatch.setattr)
    return tmp_path


def test_a_video_is_dubbed_kept_and_exported(work):
    from opendub import export
    from opendub.models import load_segments
    from opendub.workdir import WorkDir

    out = dub(work)
    wd = WorkDir(work, VID)
    streams = [s["codec_type"] for s in probe(out)["streams"]]
    assert streams == ["video", "audio"] and abs(float(probe(out)["format"]["duration"]) - 12) < 0.2
    assert [s.text for s in load_segments(wd.translation)][0] == "Frase número 1."
    assert len(list(wd.outputs_dir.glob("*-edge.mp4"))) == 1  # kept as a version
    assert "Frase número 4." in export.export(wd, "srt").read_text()
    assert [s["codec_type"] for s in probe(export.export(wd, "mkv"))["streams"]] == [
        "video", "audio", "audio", "subtitle", "subtitle"]
    assert all(wd.has(step) for step in ("download", "transcribe", "translate", "tts", "mix"))


def test_the_cli_dubs_retouches_and_exports(work):
    from typer.testing import CliRunner

    from opendub.cli import app
    from opendub.models import load_segments, save_segments
    from opendub.workdir import WorkDir

    runner = CliRunner()
    r = runner.invoke(app, ["dub", VID, "--work", str(work)])
    assert r.exit_code == 0, r.output
    wd = WorkDir(work, VID)
    segs = load_segments(wd.translation)
    segs[1].text = "Estamos doblando un vídeo corto."
    save_segments(wd.translation, segs)
    (wd.translation_edits).write_text(json.dumps({"2": {"source": "We are dubbing a short video.",
                                                       "text": segs[1].text}}))
    wd.invalidate_from("tts")
    r = runner.invoke(app, ["retouch", VID, "--work", str(work)])
    assert r.exit_code == 0, r.output
    clip = next(c for c in json.loads(wd.tts_index.read_text())["clips"] if c["id"] == 2)
    assert clip["text"] == "Estamos doblando un vídeo corto."
    assert len(list(wd.outputs_dir.glob("*-edge.mp4"))) == 2  # the retouch is a new version
    r = runner.invoke(app, ["export", VID, "--work", str(work), "-f", "srt"])
    assert r.exit_code == 0 and list(wd.outputs_dir.glob("*-edge.es.srt"))
    before = (wd.tts_index.stat().st_mtime_ns, wd.output.stat().st_mtime_ns)
    r = runner.invoke(app, ["dub", VID, "--work", str(work)])  # everything cached: nothing redone
    assert r.exit_code == 0 and (wd.tts_index.stat().st_mtime_ns, wd.output.stat().st_mtime_ns) == before


def test_the_stock_voice_path_needs_no_torch(tmp_path):
    """The macOS requirement: the edge path without separation runs without torch (run apart, so nothing
    the other tests imported counts)."""
    import subprocess
    import sys
    from pathlib import Path

    flow = Path(__file__).parent / "e2e_flow.py"
    r = subprocess.run([sys.executable, str(flow), str(tmp_path)], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0 and "ok:" in r.stdout, r.stderr[-1500:]


def test_each_phase_runs_on_its_own_from_the_cli(work, monkeypatch):
    from typer.testing import CliRunner

    from opendub import cosyvoice, diarize, indextts
    from opendub.cli import app
    from opendub.workdir import WorkDir

    runner = CliRunner()
    w = ["--work", str(work)]
    for args in (["transcribe", VID], ["translate", VID, "--chars-per-second", "15"], ["tts", VID], ["mix", VID]):
        r = runner.invoke(app, [*args, *w])
        assert r.exit_code == 0, (args, r.output)
    wd = WorkDir(work, VID)
    assert wd.output.exists() and all(wd.has(s) for s in ("transcribe", "translate", "tts", "mix"))
    assert runner.invoke(app, ["mix", "zzzzzzzzzzz", *w]).exit_code != 0  # no such video: phases missing
    installed = []
    for module, name in ((indextts, "indextts"), (cosyvoice, "cosyvoice"), (diarize, "nemotron")):
        monkeypatch.setattr(module, "setup", lambda home, n=name: installed.append(n))
        assert runner.invoke(app, ["setup-engine", name, "--path", str(work / name)]).exit_code == 0
    assert installed == ["indextts", "cosyvoice", "nemotron"]
    assert runner.invoke(app, ["setup-engine", "xtts"]).exit_code != 0
    assert runner.invoke(app, ["export", VID, *w, "-f", "avi"]).exit_code != 0
