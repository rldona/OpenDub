from opentranslator.workdir import WorkDir, dependents


def test_dependents_follow_the_phase_graph():
    assert dependents("download") == {"transcribe", "translate", "tts", "separate", "mix"}
    assert dependents("tts") == {"mix"}
    assert dependents("separate") == {"mix"}
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
