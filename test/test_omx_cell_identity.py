"""cell_identity (D-996 3-4): a container's identity comes from read tags only; mismatch holds before the place."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "deploy/robot/omx"))
import cell_identity as ci  # noqa: E402

READ_100 = {"state": "read", "tag": 100}
NOTHING = {"state": "unreadable"}


def test_a_tag_counts_only_with_k_votes_and_other_markers_never_vote():
    assert ci.vote([{100, 50}, {100}, {100, 7}, set(), set()], k=3)["tag"] == 100
    assert ci.vote([{100}, {100}, set(), set(), set()], k=3)["state"] == "unreadable"
    assert ci.vote([{50}, {50}, {50}, {7}, {7}], k=3)["state"] == "unreadable"  # arm/ceiling ids are not tags
    assert ci.vote([{100, 101}, {100, 101}, {100, 101}], k=3) == {"state": "mismatch", "tags": [100, 101]}


def test_one_read_face_is_enough_but_two_faces_must_agree():
    assert ci.point(READ_100, NOTHING) == {"state": "read", "tag": 100}
    assert ci.point(NOTHING, NOTHING) == {"state": "unreadable"}
    assert ci.point(READ_100, {"state": "read", "tag": 101}) == {"state": "mismatch", "tags": [100, 101]}
    assert ci.point(READ_100, {"state": "mismatch", "tags": [102, 103]})["state"] == "mismatch"


def test_the_wrist_holds_a_mismatch_before_the_descent_and_an_unreadable_wrist_keeps_the_end():
    assert ci.place_gate(READ_100, {"state": "read", "tag": 101}) == {"place": False, "hold": "MISMATCH",
                                                                      "tags": [100, 101]}
    assert ci.place_gate(READ_100, NOTHING) == {"place": True, "tag": 100}
    assert ci.place_gate(NOTHING, READ_100) == {"place": True, "tag": 100}  # the wrist read it
    assert ci.place_gate(NOTHING, NOTHING)["hold"] == "UNREADABLE"  # no guess: a person decides


class Cell:
    def __init__(self, frames):
        self.frames = frames

    def frame(self, camera):
        assert camera == "wrist"
        return self.frames.pop(0)


def test_the_hover_hook_refuses_a_mismatch_and_queues_what_the_wrist_read(tmp_path, monkeypatch):
    end = tmp_path / "end.json"
    end.write_text('{"state": "read", "tag": 100}')
    queued = []
    monkeypatch.setattr(ci, "read_frames", lambda frames, k: {"state": "read", "tag": frames[0]})
    config = {"identity": {"end_path": str(end), "frames": 3, "k": 2, "arm_mission_id": "physical-1"}}
    run = ci.hook(config, Cell([101, 101, 101]), lambda *a: queued.append(a))
    assert run()["verdict"] == "refuse"
    assert queued == [("wrist", {"state": "read", "tag": 101}, "physical-1")]
    assert ci.hook(config, Cell([100] * 3), None)()["verdict"] == "pass"
    assert ci.hook({}, Cell([]), None) is None  # S and rescue carries have no identity step


def test_a_broken_identity_read_refuses_so_the_arm_parks(tmp_path):
    end = tmp_path / "end.json"
    end.write_text("{not json")
    out = ci.hook({"identity": {"end_path": str(end)}}, Cell([]), None)()
    assert out["verdict"] == "refuse" and "identity read failed" in out["why"]
    broken_queue = ci.hook({"identity": {"end_path": str(tmp_path / "none.json"), "frames": 1, "k": 1}},
                           Cell([None]), lambda *a: 1 / 0)
    assert broken_queue()["verdict"] in ("pass", "refuse")  # the gate answers even when the report cannot be queued
