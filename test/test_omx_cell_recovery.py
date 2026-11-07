"""cell_recovery: an attempt's result and the top camera name the cause; each action is tried once per cause, then a person."""
import sys
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("cv2")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy/robot/omx"))
import cell_diagnose as dg  # noqa: E402
import cell_recovery as rc  # noqa: E402

CLEAN = np.full((480, 640, 3), 90, np.uint8)


def with_box(x, y):
    img = CLEAN.copy()
    img[y:y + 40, x:x + 40] = 240
    return img


def run(results, frames=None, push=lambda cause, attempt: True):
    results, frames, emitted = iter(results), iter(frames) if frames is not None else None, []
    return rc.carry(lambda: next(frames) if frames else CLEAN, lambda: {"result": next(results), "attempts": [{}]}, push,
                    expected_px=lambda attempt: [(100, 100)], emit=lambda *a: emitted.append(a)), emitted


def test_the_result_names_the_cause_and_hard_stops_are_never_retried():
    for result, cause in (("placed", "placed"), ("stopped: released after a stop at run lift_pick", "lift_stall"),
                          ("stopped: holding after a stop at run lift_pick", "held_stop"), ("stopped: still holding", "stuck_in_jaws"),
                          ("stopped: misaligned", "misaligned"), ("stopped: placed", "not_seen_placed"),
                          ("stopped: no usable object", "no_room"), ("stopped: 2 attempts", "no_progress"),
                          ("stopped: fault", "other"), ("aborted: 55 C", "other"), ("held: not reviewed", "other")):
        assert dg.attempt_cause(result) == cause
        assert dg.attempt_cause(result, True) == ("scene_moved" if cause in ("lift_stall", "misaligned", "not_seen_placed", "no_room", "no_progress") else cause)
    for cause in ("held_stop", "stuck_in_jaws", "other"):
        assert dg.RECOVERY[cause] == ["ask_person"]


def test_the_stall_hook_keeps_the_session_and_only_with_a_person_at_the_switch(monkeypatch):
    import cell_hooks

    class Raw:
        def __init__(self):
            self.sent = []

        def act(self, command):
            self.sent.append(command)
            return {"ok": True, "state": [0, 1, 2, 3, 4, 50], "target": [0, 1, 2, 3, 4, 50]}

        def frame(self, camera):
            raise OSError("no camera here")  # a missing frame must not stop the recovery

    class Gate:
        assessment = {"session_id": "s1", "library_sha256": "d1"}

    raw = Raw()
    config = {"_commissioning": {"person_at_switch": True}, "cameras": {"top": {}}, "arm_id": "arm_b"}
    monkeypatch.setattr(cell_hooks.Path, "mkdir", lambda *a, **k: None)
    out = cell_hooks.lift_stall(raw, config, lambda s: None)(Gate())
    assert out["result"] == "stuck" and raw.sent  # the fake's jaws never open: it stops at the first check
    assert all(c == "state" or c.startswith("checked s1 d1 jog ") for c in raw.sent) and any(c.startswith("checked") for c in raw.sent)
    assert cell_hooks.lift_stall(raw, {"_commissioning": {"person_at_switch": False}}, None) is None
    assert cell_hooks.lift_stall(raw, {}, None) is None


def test_a_placed_box_ends_it():
    out, emitted = run(["placed"])
    assert out["result"] == "placed" and len(out["rounds"]) == 1 and emitted[0][0] == "recovery"


def test_a_lift_stall_pushes_then_picks_again():
    pushes = []
    frames = [CLEAN, CLEAN, CLEAN, with_box(100, 100), with_box(100, 100), with_box(100, 100)]  # the push moved something
    out, _ = run(["stopped: released after a stop at run lift_pick", "placed"], frames, lambda c, a: pushes.append(c) or True)
    assert pushes == ["lift_stall"] and out["result"] == "placed" and [r["action"] for r in out["rounds"]] == ["push_clear", "done"]


def test_a_push_the_camera_saw_change_nothing_stops_and_so_does_a_refused_push():
    assert run(["stopped: no usable object"])[0]["result"] == "ask a person: no_room"  # every frame the same
    frames = [CLEAN, CLEAN, CLEAN, with_box(100, 100)]
    assert run(["stopped: no usable object"], frames, lambda c, a: False)[0]["result"] == "ask a person: no_room"


def test_the_same_cause_gets_each_action_once():
    calls = []
    frames = [CLEAN, CLEAN, CLEAN, with_box(100, 100)] + [with_box(100, 100)] * 6
    out, _ = run(["stopped: no usable object"] * 3, frames, lambda c, a: calls.append(c) or True)
    assert len(calls) == 1 and out["result"] == "ask a person: no_room"
    assert [r["action"] for r in out["rounds"]] == ["push_clear", "observe_again", "ask_person"]


def test_a_change_away_from_the_box_means_a_stale_plan_and_a_look_again():
    frames = [CLEAN, with_box(400, 300), with_box(400, 300), with_box(400, 300)]
    out, _ = run(["stopped: misaligned", "placed"], frames)
    assert out["rounds"][0]["cause"] == "scene_moved" and out["rounds"][0]["action"] == "observe_again" and out["result"] == "placed"
    assert run(["stopped: misaligned", "placed"], [CLEAN, with_box(100, 100), with_box(100, 100), with_box(100, 100)])[0]["rounds"][0]["cause"] == "misaligned"


def test_a_fault_never_tries_again_even_with_the_pile_moved():
    calls = []
    out, _ = run(["stopped: fault", "placed"], [CLEAN, with_box(400, 300)], lambda c, a: calls.append(c) or True)
    assert out["result"] == "ask a person: other" and not calls


def test_rounds_run_out_at_a_person():
    results = iter(["stopped: misaligned", "stopped: placed"])
    out = rc.carry(lambda: CLEAN, lambda: {"result": next(results)}, lambda c, a: True, expected_px=lambda a: [], emit=lambda *a: None, rounds=2)
    assert out["result"] == "ask a person: 2 rounds"
