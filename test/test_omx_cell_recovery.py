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
                          ("stopped: no usable object", "no_room"), ("stopped: no usable object (packed)", "no_room"),
                          ("stopped: no usable object (tangled pile)", "pile"), ("stopped: 2 attempts", "no_progress"),
                          ("stopped: fault", "other"), ("aborted: 55 C", "other"), ("held: not reviewed", "other")):
        assert dg.attempt_cause(result) == cause
        assert dg.attempt_cause(result, True) == ("scene_moved" if cause in ("lift_stall", "misaligned", "not_seen_placed", "no_room", "pile", "no_progress") else cause)
    for cause in ("held_stop", "stuck_in_jaws", "other"):
        assert dg.RECOVERY[cause] == ["ask_person"]


def test_the_refusals_name_the_obstacle_type_and_a_pile_outranks_packed_boxes():
    room, pile = {"why": "no finger room: 4.0 / 26.0 mm free beside it"}, {"why": "tangled blob"}
    assert dg.obstacle_type([room]) == "packed" and dg.obstacle_type([room, pile]) == "tangled pile"
    assert dg.obstacle_type([{"why": "not inside the camera view"}]) == "edge of view" and dg.obstacle_type([]) is None


def test_a_box_at_the_view_edge_or_past_the_pan_limit_goes_to_a_person_never_to_a_push():
    """2026-11-13 arm_s: both were refused as packed, so the recovery would have pushed at a box it could not see or reach."""
    edge = {"why": "edge of view: a side is past the camera's view, 25.3 / 7.0 mm free beside it"}
    far = {"why": "out of reach: pan -161.0 deg past the joint1 limit"}
    room = {"why": "no finger room: 4.0 / 26.0 mm free beside it"}
    assert dg.obstacle_type([edge]) == "edge of view" and dg.obstacle_type([far]) == "out of reach"
    assert dg.obstacle_type([far, edge, room]) == "packed"  # a push can still free the packed one
    for kind, cause in (("edge of view", "edge_of_view"), ("out of reach", "out_of_reach")):
        assert dg.attempt_cause(f"stopped: no usable object ({kind})", True) == cause
        out, _ = run([f"stopped: no usable object ({kind})"])
        assert out["result"] == f"ask a person: {cause}" and out["rounds"][0]["action"] == "ask_person" and out["ask"] == dg.ASK[cause]


def test_a_box_at_the_edge_of_the_view_is_unseen_not_packed():
    """2026-11-13 arm_s: a box on Pinky at the top of the frame read as no finger room, and the recovery would push it."""
    import cell_auto_safety
    px = lambda p: (100 + p[0] * 1000, 100 + (p[1] - 0.1) * 1000)  # noqa: E731  1 px per mm
    box = {"raw_m": [0.0, 0.1], "width_mm": 30, "length_mm": 60, "long_axis_deg": 0.0}
    mask = np.zeros((120, 200), np.uint8)  # the view ends 5 mm past its +y side
    mask[85:116, 70:131] = 255
    room = cell_auto_safety.finger_room(mask, (0, 0, 200, 120), px, box)
    assert room["margin_mm"] is None and room["unseen"]
    assert cell_auto_safety.finger_room(np.pad(mask, ((0, 80), (0, 0))), (0, 0, 200, 200), px, box)["margin_mm"] is not None


def test_the_pan_limit_names_a_box_out_of_reach():
    import cell_auto_pick_plan as plan
    config = {"plan": {"limits": {"joints_rad": {"joint1": [-2.6, 2.6]}}}}  # +-149 deg
    assert plan.past_pan_limit(config, (-0.187, -0.065)) == -160.8
    assert plan.past_pan_limit(config, (-0.15, -0.12)) is None and plan.past_pan_limit({"plan": {}}, (-0.187, -0.065)) is None


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


def test_any_stop_keeps_one_frame_per_camera_and_a_dead_camera_does_not_stop_it(monkeypatch, tmp_path):
    import cell_hooks
    import omx_incident

    class Cell:
        def frame(self, camera):
            if camera == "side":
                raise OSError("unplugged")
            return CLEAN

    monkeypatch.setattr(omx_incident, "STILLS", tmp_path / "stills")
    cell_hooks.stills(Cell(), {"arm_id": "arm_b", "cameras": {"top": {}, "side": {}, "wrist": {}}})()
    assert sorted(p.name for p in (tmp_path / "stills").iterdir()) == ["arm_b-top.jpg", "arm_b-wrist.jpg"]


def test_a_placed_box_ends_it():
    out, emitted = run(["placed"])
    assert out["result"] == "placed" and len(out["rounds"]) == 1 and emitted[0][0] == "recovery"


def test_a_lift_stall_pushes_then_picks_again():
    pushes = []
    frames = [CLEAN, CLEAN, CLEAN, with_box(100, 100), with_box(100, 100), with_box(100, 100)]  # the push moved something
    out, _ = run(["stopped: released after a stop at run lift_pick", "placed"], frames, lambda c, a: pushes.append(c) or True)
    assert pushes == ["lift_stall"] and out["result"] == "placed" and [r["action"] for r in out["rounds"]] == ["push_clear", "done"]


@pytest.mark.parametrize("by, first", [("model", "slow_down"), ("nobody", "slow_down"), ("measurement", "push_clear")])
def test_only_a_measured_cause_reorders_the_table(by, first):
    """cell_why reads a moving joint as undetermined, so a model's answer now fills the row more often: it must not steer."""
    frames = iter([CLEAN, CLEAN, CLEAN, with_box(100, 100), with_box(100, 100), with_box(100, 100)])
    results = iter(["stopped: released after a stop at run lift_pick", "placed"])
    out = rc.carry(lambda: next(frames), lambda: {"result": next(results), "attempts": [{}]}, lambda c, a: True,
                   expected_px=lambda a: [(100, 100)], emit=lambda *a: None, slow=lambda: True,
                   explain=lambda cause, o: {"hypothesis": "blocked", "by": by})
    assert [r["action"] for r in out["rounds"]] == [first, "done"]


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


def test_no_retry_starts_from_an_arm_that_did_not_come_home():
    results = iter(["stopped: misaligned", "placed"])
    out = rc.carry(lambda: CLEAN, lambda: {"result": next(results)}, lambda c, a: True, expected_px=lambda a: [], emit=lambda *a: None, folded=lambda: False)
    assert out["result"] == "ask a person: misaligned" and [r["action"] for r in out["rounds"]] == ["ask_person"]
    results = iter(["placed"])
    assert rc.carry(lambda: CLEAN, lambda: {"result": next(results)}, lambda c, a: True, expected_px=lambda a: [], emit=lambda *a: None,
                    folded=lambda: False)["result"] == "placed"  # a placed box asks nothing more
    home = [0.0, -60.0, 50.0, 50.0, 45.0]
    assert rc.at_home([1.5, -60.0, 50.0, 50.0, 45.0, 90.0], home) and not rc.at_home([3.0, -60.0, 50.0, 50.0, 45.0, 0.0], home)
    assert not rc.at_home(None, home)


def test_a_contact_replans_only_once_the_pile_moved():
    contact = "stopped: beside -> ask_person"
    assert dg.attempt_cause(contact) == "contact" and dg.attempt_cause(contact, True) == "scene_moved"
    assert dg.attempt_cause("stopped: pivot: stopped") == "calibrate" and dg.attempt_cause("stopped: pivot: stopped", True) == "calibrate"
    assert dg.attempt_cause("stopped: no clear pivot point within reach") == "calibrate"  # no plan yet: a push has nothing to act on
    for hard in ("stopped: holding after a stop at run lift_pick", "stopped: still holding", "stopped: fault"):
        assert dg.attempt_cause(hard, True) != "scene_moved"


def test_a_site_camera_frame_is_kept_on_each_failure_row_and_never_chooses_the_action():
    seen = []
    def observe():
        seen.append(1)
        return {"frame": None, "why": "unreachable"}
    out = rc.carry(lambda: CLEAN, iter([{"result": r, "attempts": [{}]} for r in ("stopped: misaligned", "placed")]).__next__,
                   lambda cause, attempt: True, expected_px=lambda attempt: [(100, 100)], emit=lambda *a: None, observe=observe)
    assert out["result"] == "placed" and len(seen) == 1
    assert out["rounds"][0]["evidence"] == {"frame": None, "why": "unreachable"} and "evidence" not in out["rounds"][1]
    assert [r["action"] for r in out["rounds"]] == [r["action"] for r in run(["stopped: misaligned", "placed"])[0]["rounds"]]
