"""cell_requests: what a person in the cell is asked to measure or check, and what the answer decides (D-951 addendum)."""
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy/robot/omx"))
import cell_requests as cr  # noqa: E402


def measure(**over):
    return dict(dict(id="belt-end-1", kind="measure", item="belt", question="axis to belt end", how=["tape from the axis"],
                     candidates=dict(sim=156, camera=215), unit="mm", tolerance=20), **over)


def test_a_reading_decides_between_the_candidates(tmp_path):
    cr.open_request(measure(), root=tmp_path)
    assert [r["id"] for r in cr.listing(tmp_path)] == ["belt-end-1"]
    got = cr.answer("belt-end-1", by="operator", value=212, note="tape", root=tmp_path)
    assert got["status"] == "answered" and got["answer"]["verdict"] == "camera" and got["answer"]["by"] == "operator"
    assert cr.listing(tmp_path) == [] and len(cr.listing(tmp_path, everything=True)) == 1
    events = [json.loads(line)["event"] for line in (tmp_path / "history.jsonl").read_text(encoding="utf-8").splitlines()]
    assert events == ["open", "answer"]


@pytest.mark.parametrize("value, verdict", [(150, "sim"), (176, "sim"), (185, "neither"), (240, "neither")])
def test_a_reading_outside_every_tolerance_supports_neither(tmp_path, value, verdict):
    cr.open_request(measure(), root=tmp_path)
    assert cr.answer("belt-end-1", by="op", value=value, root=tmp_path)["answer"]["verdict"] == verdict


def test_one_answer_per_request(tmp_path):
    cr.open_request(measure(), root=tmp_path)
    cr.answer("belt-end-1", by="op", value=215, root=tmp_path)
    with pytest.raises(ValueError, match="already answered"):
        cr.answer("belt-end-1", by="op", value=156, root=tmp_path)
    with pytest.raises(ValueError, match="exists"):
        cr.open_request(measure(), root=tmp_path)


@pytest.mark.parametrize("bad, why", [
    (dict(candidates=dict(sim=156)), "two or more candidates"),
    (dict(candidates=dict(sim=156, camera=180)), "closer than twice the tolerance"),
    (dict(tolerance=0), "positive tolerance"),
    (dict(id="../x"), "letters, digits"),
    (dict(kind="guess"), "kind must be"),
    (dict(question=" "), "needs question"),
])
def test_a_request_that_cannot_decide_is_refused(tmp_path, bad, why):
    with pytest.raises(ValueError, match=why):
        cr.open_request(measure(**bad), root=tmp_path)


def test_answers_name_who_and_match_the_kind(tmp_path):
    cr.open_request(measure(), root=tmp_path)
    with pytest.raises(ValueError, match="names who"):
        cr.answer("belt-end-1", by=" ", value=215, root=tmp_path)
    with pytest.raises(ValueError, match="--value"):
        cr.answer("belt-end-1", by="op", result="pass", root=tmp_path)
    cr.open_request(dict(id="known-pose-1", kind="check", item="arm_b", question="tip over the mark", how=["switch"],
                         steps=["a person at the switch", "move to the known pose"]), root=tmp_path)
    with pytest.raises(ValueError, match="pass or fail"):
        cr.answer("known-pose-1", by="op", value=1, root=tmp_path)
    assert cr.answer("known-pose-1", by="op", result="fail", root=tmp_path)["answer"]["result"] == "fail"


def test_the_image_is_kept_beside_the_request(tmp_path):
    image = tmp_path / "frame.png"
    image.write_bytes(b"\x89PNG")
    store = tmp_path / "store"
    got = cr.open_request(measure(), image=image, root=store)
    assert got["image"] == "belt-end-1.png" and (store / "belt-end-1.png").read_bytes() == b"\x89PNG"


def test_the_command_line_round_trip(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ROSY_CELL_REQUESTS", str(tmp_path))
    req = tmp_path.parent / "req.json"
    req.write_text(json.dumps(measure()), encoding="utf-8")
    assert cr.main(["open", str(req)]) == 0
    assert cr.main(["answer", "belt-end-1", "--value", "214", "--by", "operator"]) == 0
    assert json.loads(capsys.readouterr().out.splitlines()[-1])["verdict"] == "camera"
    assert cr.main(["answer", "belt-end-1", "--value", "214", "--by", "operator"]) == 2
