"""load_model (fit from standstill motor-health samples) and load_predict (ok / risky / unknown before motion)."""
import json
import math
from pathlib import Path
import sys

import pytest

np = pytest.importorskip("numpy")
OMX = Path(__file__).parents[1] / "deploy/robot/omx"
sys.path.insert(0, str(OMX))
try:
    import load_model
    import load_predict as lp
finally:
    sys.path.remove(str(OMX))

PORT = "/dev/serial/by-id/usb-ROBOTIS_OpenRB-150_7F31D1FE5032FF061D2D-if00"
CAPS = {"shoulder_pan": 300, "shoulder_lift": 600, "elbow_flex": 600, "wrist_flex": 300, "wrist_roll": 300, "gripper": 300}


def gravity(pose, scale=1.0):
    """The true hold PWM of a synthetic arm: lift carries all links, elbow two, wrist one (signs +,+)."""
    a1, a2, a3 = lp.angles(pose, (1, 1))
    return [0, scale * (150 * math.sin(a1) + 100 * math.sin(a2) + 40 * math.sin(a3)),
            scale * (90 * math.sin(a2) + 40 * math.sin(a3)), scale * 35 * math.sin(a3), 0, 0]


def raw(u):
    return round((u + 100) * 4095 / 200)


def log(path, poses, scale=1.0, hold=8, noise=0):
    """A health log holding each pose `hold` seconds at 1 Hz (and a moving gap before the next one)."""
    rows, t = [], 100.0
    for k, pose in enumerate(poses):
        for s in range(hold):
            pwm = gravity(pose, scale)
            motors = [{"joint": j, "usb_port": PORT, "command_raw": raw(pose[i]), "present_raw": raw(pose[i]),
                       "pwm": round(pwm[i] + noise * ((k + s) % 3 - 1)), "pwm_limit": CAPS[j], "hardware_error": 0}
                      for i, j in enumerate(load_model.BODY6)]
            rows.append({"event": "sample", "sample_time": t, "motors": motors})
            t += 1.0
        t += 10  # a gap: the next pose is a new window
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n{cut")


def hot(poses, joint):
    return max(poses, key=lambda p: abs(gravity(p)[joint]))


def calm(poses):
    return min(poses, key=lambda p: max(abs(v) for v in gravity(p)))


@pytest.fixture
def model(tmp_path):
    rng = np.random.default_rng(1)
    poses = [[0, *map(float, rng.uniform(-40, 40, 3)), 0, 50] for _ in range(60)]
    for n in range(8):  # eight sessions of the same poses, so every cell has samples to keep
        log(tmp_path / f"motor-health-{n}.jsonl", poses, noise=2)
    return load_model.build(sorted(map(str, tmp_path.glob("motor-health-*.jsonl"))), min_cell=5), poses


def test_the_builder_recovers_the_signs_and_a_small_error_per_joint(model):
    arm = model[0]["arms"]["FF061D2D"]
    assert arm["signs"] == [1, 1] and arm["samples"] > 1000
    assert all(j["rms"] < 5 and j["holdout_rms"] < 5 and j["cap"] == CAPS[n] for n, j in arm["joints"].items())


def test_a_known_pose_is_ok_a_heavier_one_risky_and_a_pose_off_the_data_unknown(model):
    m, poses = model
    lib = {"fps": 30, "chunks": {"hold": [calm(poses)] * 31}}
    assert lp.check(m, PORT, lib)["verdict"] == "ok"
    heavy = {"fps": 30, "chunks": {"hold": [hot(poses, 1)] * 31}}
    arm = m["arms"]["FF061D2D"]
    arm["joints"]["shoulder_lift"]["cap"] = abs(gravity(hot(poses, 1))[1]) * 1.2  # the hold takes 80 % of this cap
    out = lp.check(m, PORT, heavy)
    assert out["verdict"] == "risky" and out["chunks"]["hold"]["risky"] == ["shoulder_lift"]
    arm["joints"]["shoulder_lift"]["cap"] = 600
    off = {"fps": 30, "chunks": {"reach": [[0, -90, 90, 90, 0, 50]] * 2}}
    out = lp.check(m, PORT, off)
    assert out["verdict"] == "unknown" and "cell" in out["chunks"]["reach"]["unknown"]
    assert lp.check(m, "/dev/serial/by-id/usb-0000FFFFFFFF-if00", lib)["verdict"] == "unknown"  # another arm: no guess


def test_refuse_raises_for_risky_and_for_unknown_only_when_asked(model):
    m, poses = model
    m["arms"]["FF061D2D"]["joints"]["elbow_flex"]["cap"] = abs(gravity(hot(poses, 2))[2]) * 1.2
    rows = []
    with pytest.raises(ValueError, match="risky"):
        lp.refuse(m, PORT, {"fps": 30, "chunks": {"hold": [hot(poses, 2)] * 3}}, status=rows.append)
    assert rows[0]["event"] == "load_check" and rows[0]["verdict"] == "risky"
    off = {"fps": 30, "chunks": {"reach": [[0, -90, 90, 90, 0, 50]]}}
    assert lp.refuse(m, PORT, off, status=rows.append)["verdict"] == "unknown"
    with pytest.raises(ValueError, match="unknown"):
        lp.refuse(m, PORT, off, {"loadcheck.refuse_unknown": 1}, status=rows.append)


def test_the_runner_refuses_a_risky_load_before_replacing_its_plan(model, tmp_path):
    import test_omx_chunk_runner as cr  # the runner's own fake robot and library
    m, poses = model
    m["arms"]["FF061D2D"]["joints"]["shoulder_lift"]["cap"] = abs(gravity(hot(poses, 1))[1]) * 1.2
    path = tmp_path / "risky.json"
    path.write_text(json.dumps(dict(cr.library(), fps=30, chunks={"hold": [hot(poses, 1)] * 3, "home": [calm(poses)] * 3})))
    status = []
    runner = cr.m.Runner(cr.Robot(), cr.library(), fps=30, status=status.append,
                         plan_check=lambda lib: lp.refuse(m, PORT, lib, status=status.append))
    runner.target = list(cr.HOME)
    runner.command(f"load {path}")  # a refused load is reported, the session goes on
    assert status[-1]["ok"] is False and "risky" in status[-1]["error"]
    assert "hold" not in runner.library["chunks"]  # the old plan stays
