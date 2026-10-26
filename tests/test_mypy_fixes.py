"""Behaviour pinned where the T-33 type fixes touched more than annotations."""

import json

import pytest

from opendub import tts
from opendub.config import Settings
from opendub.web.jobs import JobOptions
from opendub.workdir import WorkDir


def test_a_malformed_manifest_entry_is_not_done(tmp_path):
    wd = WorkDir(tmp_path, "vid")
    wd.manifest_path.write_text(json.dumps({"tts": "not a dict", "mix": {}}))
    assert not wd.is_done("tts", {}) and not wd.is_done("mix", {}) and not wd.is_done("translate", {})


def test_a_cloned_voice_always_has_its_reference(tmp_path):
    ref = tmp_path / "ref.wav"
    assert tts.Voice("chatterbox", "es-ES-AlvaroNeural", "-10%", ref=ref).cloned_ref() == ref
    with pytest.raises(ValueError):
        tts.Voice("cosyvoice", "es-ES-AlvaroNeural", "-10%").cloned_ref()


def test_the_page_s_one_volume_goes_to_the_background_it_mixes_over(tmp_path):
    kept = JobOptions(url="x", separate=True, bg_volume=-6.0).settings(tmp_path)
    assert kept.music_volume_db == -6.0 and kept.bg_volume_db == Settings().bg_volume_db
    original = JobOptions(url="x", separate=False, bg_volume=-20.0).settings(tmp_path)
    assert original.bg_volume_db == -20.0 and original.music_volume_db == Settings().music_volume_db
