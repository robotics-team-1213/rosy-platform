"""The shadow check's real-side parsing: the pipeline's health output and the joint unit (no MuJoCo, no arm)."""
import json
import math
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/sim"))
import omx_two_arm_shadow as shadow  # noqa: E402

JOINTS = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper")


def bus(arm, role, base):
    return dict(arm=arm, role=role, motors={j: dict(id=11 + k, position=base + k) for k, j in enumerate(JOINTS)})


def test_health_joints_takes_the_followers_five_body_joints():
    out = "\n".join(["not json", json.dumps(dict(stage="receipt", path="x")),
                     json.dumps(dict(stage="health", buses=[bus("arm_a", "follower", 0.), bus("arm_a", "leader", 50.), bus("arm_b", "follower", 10.)]))])
    assert shadow.health_joints(out) == {"arm_a": [0., 1., 2., 3., 4.], "arm_b": [10., 11., 12., 13., 14.]}


def test_health_joints_refuses_output_without_the_stage():
    try:
        shadow.health_joints('{"stage": "receipt"}')
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def test_norm_to_rad_centre_and_ends():
    assert abs(shadow.norm_to_rad(0.)) < 1e-3  # tick ~2048 is 0 rad
    assert abs(shadow.norm_to_rad(-100.) + math.pi) < 1e-9
    assert abs(shadow.norm_to_rad(100.) - (4095 * 2 * math.pi / 4096 - math.pi)) < 1e-9


def test_executor_candidates_list_smolvla_without_weakening_real_approval():
    omx_dir = Path(__file__).resolve().parents[1] / "deploy/robot/omx"
    sys.path.insert(0, str(omx_dir))
    try:
        import cell_executor  # noqa: E402
    finally:
        sys.path.remove(str(omx_dir))
    assert "smolvla" in cell_executor.EXECUTOR_CANDIDATES
    assert "smolvla" not in cell_executor.APPROVED_REAL_EXECUTORS
    assert cell_executor.APPROVED_REAL_EXECUTORS == frozenset({"ik_chunk"})


def _motor_health(arm, ticks):
    return {"schema_version": "rosy.motor-health.v1", "owner_id": arm,
            "motors": [{"joint": j, "present_raw": t} for j, t in zip(shadow.HEALTH_JOINTS, ticks)]}


def test_health_joints_accepts_motor_health_pair_without_bus_lock():
    raw = json.dumps(_motor_health("arm_a", [2048., 0., 4095., 1024., 3072.])) + json.dumps(_motor_health("arm_b", [2048.] * 5))
    joints = shadow.health_joints(raw)
    assert set(joints) == {"arm_a", "arm_b"}
    assert shadow.norm_to_rad(joints["arm_a"][1]) == pytest.approx(-math.pi)
    assert shadow.norm_to_rad(joints["arm_a"][2]) == pytest.approx(4095 * 2 * math.pi / 4096 - math.pi)
    assert abs(shadow.norm_to_rad(joints["arm_b"][0])) < 1e-2


def test_health_joints_refuses_incomplete_motor_health():
    try:
        shadow.health_joints(json.dumps(_motor_health("arm_a", [2048.] * 5)))
    except ValueError:
        return
    raise AssertionError("expected ValueError when arm_b motor-health is missing")


def test_shadow_risks_splits_active_and_idle_arms_and_gates():
    state = [0.0] * 12
    real = [math.radians(5.0)] + [0.0] * 5 + [math.radians(15.0)] + [0.0] * 5
    sim = [math.radians(2.0)] + [0.0] * 5 + [0.0] * 6
    passed = shadow.shadow_risks("arm_a", state, real, sim, max_shadow_deg=5.0, max_idle_deg=20.0)
    assert passed["active_arm_max_abs_real_minus_sim_deg"] == pytest.approx(3.0)
    assert passed["active_arm_max_step_deg"] == pytest.approx(5.0)
    assert passed["idle_arm_max_abs_delta_deg"] == pytest.approx(15.0)
    assert passed["l2_gate"] == {"passed": True, "reasons": []}
    failed = shadow.shadow_risks("arm_a", state, real, sim, max_shadow_deg=2.5, max_idle_deg=10.0)
    assert failed["l2_gate"]["passed"] is False and len(failed["l2_gate"]["reasons"]) == 2


def test_compare_supports_belt_steps_without_blocking(monkeypatch, tmp_path):
    from contextlib import nullcontext
    import types
    import numpy as np
    from PIL import Image
    import omx_two_arm_policy as pol
    import omx_two_arm_sites as sites
    import omx_two_arm_teacher as teaching

    snap = tmp_path / "snap"
    snap.mkdir()
    for label in shadow.REAL_VIEWS.values():
        Image.fromarray(np.zeros((8, 8, 3), dtype=np.uint8)).save(snap / f"{label}.jpg")
    (snap / "snapshot.json").write_text(json.dumps({"captured_at": 1.0, "joints": {a: [0.0] * 5 for a in sites.ARMS}}), encoding="utf-8")

    layout = sites.Layout()
    fake_world = types.SimpleNamespace(
        layout=layout,
        model=object(),
        q={a: slice(k * 6, k * 6 + 6) for k, a in enumerate(sites.ARMS)},
        mimic={a: 0 for a in sites.ARMS},
        render=lambda *_a: np.zeros((*pol.SHAPE, 3), dtype=np.uint8),
    )
    belt_calls = []

    class FakeTeacher:
        def __init__(self, _w, seed=0):
            pass
        def fresh(self, _h):
            return types.SimpleNamespace(qpos=np.zeros(24))
        def belt_in(self, _d, plan, _idle):
            belt_calls.append(plan["id"])

    class FakeDriver:
        def __init__(self):
            self.kind, self.has_goal, self.world, self.layout = "smolvla", False, fake_world, layout
            self.torch = types.SimpleNamespace(inference_mode=nullcontext)
            self.policy = types.SimpleNamespace(reset=lambda: None)
        def act(self, *_a, **_k):
            return np.zeros(12, dtype=np.float32)

    monkeypatch.setitem(sys.modules, "mujoco", types.SimpleNamespace(mj_forward=lambda *_a: None))
    monkeypatch.setitem(sys.modules, "torch", types.SimpleNamespace(cuda=types.SimpleNamespace(is_available=lambda: True)))
    monkeypatch.setattr(shadow, "teacher_first", lambda *_a: np.zeros(12, dtype=np.float32))
    monkeypatch.setattr(teaching, "Teacher", FakeTeacher)
    monkeypatch.setattr(pol, "Driver", lambda *_a, **_k: FakeDriver())
    monkeypatch.setattr(pol, "sheet", lambda imgs: next(iter(imgs.values())))

    rc = shadow.main(["compare", "--model", "m", "--steps-file", "s", "--snapshot", str(snap),
                      "--task", "stack", "--step", "s1", "--skill", "grasp", "--out", str(tmp_path / "out")])
    assert rc == 0 and belt_calls == ["s1"]

    rc_multi = shadow.main(["compare", "--model", "m", "--steps-file", "s", "--snapshot", str(snap),
                            "--task", "stack", "--step", "s1,s2", "--skill", "grasp",
                            "--max-shadow-deg", "5.0", "--out", str(tmp_path / "out_multi")])
    assert rc_multi == 0 and belt_calls == ["s1", "s1", "s2"]
    summary = json.loads((tmp_path / "out_multi" / "shadow.json").read_text(encoding="utf-8"))
    assert [r["step"] for r in summary["steps"]] == ["s1", "s2"] and summary["l2_gate"]["passed"] is True
    assert summary["ranked_steps"] == ["s1", "s2"]
    assert (tmp_path / "out_multi" / "s1-shadow.json").is_file() and (tmp_path / "out_multi" / "s2-shadow.json").is_file()

    rc_all = shadow.main(["compare", "--model", "m", "--steps-file", "s", "--snapshot", str(snap),
                          "--task", "stack", "--step", "all", "--skill", "grasp", "--out", str(tmp_path / "out_all")])
    assert rc_all == 0 and len(json.loads((tmp_path / "out_all" / "shadow.json").read_text(encoding="utf-8"))["ranked_steps"]) == 9
