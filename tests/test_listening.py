"""The blind listening tools (docs/bench/listening): the same seed, the same session; answers per engine."""

import json
import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "docs" / "bench" / "listening"))
import session  # noqa: E402
import summary  # noqa: E402


@pytest.fixture
def work(tmp_path, monkeypatch):
    vid = tmp_path / "abcdefghijk"
    vid.mkdir()
    segs = [{"id": i + 1, "start": i * 4.0, "end": i * 4.0 + 3.5, "text": f"s{i}"} for i in range(60)]
    (vid / "segments.json").write_text(json.dumps(segs))
    monkeypatch.setattr(session, "WORK", tmp_path)
    return tmp_path


def test_fragments_last_10_to_15_s_and_a_seed_makes_them_again(work):
    assert all(10 <= end - start <= 15 for start, end in session.windows("abcdefghijk"))
    first = session.pick("abcdefghijk", 4, random.Random(7))
    assert session.pick("abcdefghijk", 4, random.Random(7)) == first
    assert len(first) == 4 and first == sorted(first)  # one in each quarter of the video
    for seed in range(30):  # no stretch is heard twice, even where a window runs into the next part
        picked = session.pick("abcdefghijk", 6, random.Random(seed))
        assert all(a[1] <= b[0] for a, b in zip(picked, picked[1:]))


def test_answers_are_given_back_per_engine():
    s = {"a": "chatterbox", "b": "chatterbox-es", "fragments": [
        {"id": "f01", "video": "v", "start": 1.0, "end": 12.0, "versions": {"a": "x-chatterbox", "b": "y-chatterbox-es"},
         "order": {"1": "b", "2": "a"}}]}
    data = {"answers": {"f01": {"ratings": {"1": {"naturalness": 5, "meaning": 4, "sync": 4},
                                            "2": {"naturalness": 3, "meaning": 4, "sync": 3}}, "prefer": "1"}}}
    r = session.reveal(s, data)["f01"]
    assert r["ratings"]["chatterbox-es"]["naturalness"] == 5 and r["ratings"]["chatterbox"]["naturalness"] == 3
    assert r["prefer"] == "chatterbox-es"
    total = summary.summarize({"name": "t", "a": "chatterbox", "b": "chatterbox-es", "revealed": {"f01": r}})
    assert total["means"]["chatterbox-es"]["naturalness"] == 5 and total["prefer"]["chatterbox-es"] == 1
