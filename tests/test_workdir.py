from opendub.workdir import WorkDir, dependents


def test_dependents_follow_the_phase_graph():
    assert dependents("download") == {"transcribe", "translate", "tts", "separate", "diarize", "mix"}
    assert dependents("tts") == {"mix"}
    assert dependents("separate") == {"diarize", "mix"}
    assert dependents("mix") == set()


def test_redoing_tts_keeps_the_separation(tmp_path):
    wd = WorkDir(tmp_path, "vid")
    for step in ("download", "transcribe", "translate", "tts", "separate", "mix"):
        wd.mark_done(step, {"v": 1})
    wd.mark_done("tts", {"v": 2})
    assert wd.has("separate") and wd.has("translate")
    assert not wd.has("mix")


def test_invalidate_from_download_clears_everything(tmp_path):
    wd = WorkDir(tmp_path, "vid")
    for step in ("download", "transcribe", "separate"):
        wd.mark_done(step, {})
    wd.invalidate_from("download")
    assert not any(wd.has(s) for s in ("download", "transcribe", "separate"))


def test_an_interrupted_save_keeps_the_previous_state(tmp_path, monkeypatch):
    import os

    import pytest

    from opendub import workdir

    wd = WorkDir(tmp_path, "vid")
    wd.mark_done("download", {"v": 1})
    before = wd.manifest_path.read_text()

    def killed(src, dst):
        raise KeyboardInterrupt  # the process dies between writing and replacing

    monkeypatch.setattr(os, "replace", killed)
    with pytest.raises(KeyboardInterrupt):
        wd.mark_done("transcribe", {"v": 1})
    assert wd.manifest_path.read_text() == before  # never half written
    assert not list(tmp_path.glob("vid/.*.tmp"))  # and no temporary left behind
    monkeypatch.undo()
    workdir.write_text_atomic(wd.manifest_path, "{}")
    assert wd.manifest_path.read_text() == "{}"


def test_no_state_file_is_written_in_place():
    from pathlib import Path

    src = Path(__file__).parents[1] / "src" / "opendub"
    offenders = [str(p) for p in src.rglob("*.py") if "workers" not in p.parts
                 and "write_text(json.dumps" in p.read_text(encoding="utf-8")]
    assert offenders == []
