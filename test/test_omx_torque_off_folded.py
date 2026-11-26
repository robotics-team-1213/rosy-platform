"""torque_off_folded: a folded follower is released and its caps verified; an extended or locked arm is refused."""
import importlib.util
import json
from pathlib import Path
import sys

import pytest

DIR = Path(__file__).parents[1] / "deploy/robot/omx"
sys.path.insert(0, str(DIR))
import cell_job_spec  # noqa: E402
import cell_torque_off_folded as job  # noqa: E402
import record_session  # noqa: E402

FOLDED = [2000, 500, 3500, 2000, 2000, 2000]  # joint2 -75, joint3 +75 on a 0..4000 range
EXTENDED = [2000, 2000, 2000, 2000, 2000, 2000]
CAL = {name: {"id": 11 + i, "drive_mode": 0, "homing_offset": 0, "range_min": 0, "range_max": 4000}
       for i, name in enumerate(job.FOLLOWER_JOINTS if hasattr(job, "FOLLOWER_JOINTS") else
                                ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper"))}


class Bus:
    def __init__(self, motors, stuck=False):
        self.motors, self.motor, self.stuck, self.writes = motors, None, stuck, []

    def read(self, name):
        return self.motors[self.motor][name]

    def cleanup_read(self, name):
        return self.read(name)

    def cleanup_write(self, name, value):
        self.writes.append((self.motor, name, value))
        if not (self.stuck and name == "torque"):
            self.motors[self.motor][name] = value

    def close(self):
        pass


def motors(positions, torque=1, pwm=20):
    out = {}
    for motor, pos in zip(job.MOTORS, positions):
        model, mode = record_session.FOLLOWER[motor]
        out[motor] = {"model": model, "mode": mode, "torque": torque, "hw_error": 0, "present_pos": pos,
                      "pwm_limit": pwm, "current_limit": 50, "profile_acc": 1, "profile_vel": 1}
    return out


class Guard:
    closed = False

    def close(self):
        Guard.closed = True


def run(positions=FOLDED, *, torque=1, pwm=20, stuck=False, lock=None, baseline=None, cal=CAL):
    state = motors(positions, torque, pwm)
    bus = Bus(state, stuck)
    clock = iter(range(0, 1000, 10))
    session = record_session.Session(open_bus=lambda which: bus, systemctl=lambda *a: "", run=None, log=lambda **k: None,
                                     sleep=lambda s: None, clock=lambda: next(clock))
    calls = []

    def fix(device, out_dir):
        calls.append(device)
        for m in state.values():
            m["pwm_limit"] = 20
        return 0

    Guard.closed = False
    try:
        res = job.release("arm_s", "/dev/serial/by-id/x", open_bus=lambda: bus, lock=lock or (lambda arm: Guard()),
                          session=session, calibration=cal, baseline=baseline or fix, out_dir=Path("o"))
        return res, bus, calls, None
    except job.Refused as exc:
        return None, bus, calls, exc


def test_folded_arm_torque_off_with_before_after():
    res, bus, calls, err = run()
    assert err is None and calls == []
    assert {m: v["torque"] for m, v in res["before"].items()} == {m: 1 for m in job.MOTORS}
    assert {m: v["torque"] for m, v in res["after"].items()} == {m: 0 for m in job.MOTORS}
    assert res["after"][12]["position"] == 500 and res["baseline"] == {"restored": False} and Guard.closed


def test_raised_caps_are_restored_by_baseline_job():
    res, _, calls, err = run(pwm=300)
    assert err is None and calls == ["/dev/serial/by-id/x"] and res["baseline"] == {"restored": True}


def test_baseline_failure_is_an_error():
    _, _, _, err = run(pwm=300, baseline=lambda d, o: 2)
    assert (err.code, err.exit_code) == ("BASELINE_NOT_RESTORED", job.ERROR)


def test_extended_arm_is_refused_without_any_write():
    _, bus, _, err = run(EXTENDED)
    assert (err.code, err.exit_code) == ("NOT_FOLDED", job.REJECTED) and bus.writes == [] and Guard.closed


def test_missing_calibration_refuses():
    _, bus, _, err = run(cal=None)
    assert err.code == "CALIBRATION_MISSING" and bus.writes == []


def test_lock_held_refuses_before_opening_the_port():
    def held(arm):
        raise SystemExit("another OMX session holds session-arm_s.lock")

    _, bus, _, err = run(lock=held)
    assert err.code == "SESSION_LOCK_HELD" and bus.writes == []


def test_unconfirmed_torque_off_is_an_error():
    _, _, _, err = run(stuck=True)
    assert (err.code, err.exit_code) == ("TORQUE_OFF_UNCONFIRMED", job.ERROR)


@pytest.mark.skipif(not hasattr(__import__("os"), "getuid"), reason="POSIX flock")
def test_real_arm_lock_is_exclusive(tmp_path, monkeypatch):
    import fcntl
    import joint_tune
    monkeypatch.setenv("ROSY_OMX_HOME", str(tmp_path))
    with (tmp_path / "session-arm_s.lock").open("a") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        _, bus, _, err = run(lock=joint_tune.session_lock)
    assert err.code == "SESSION_LOCK_HELD" and bus.writes == []


def test_main_prints_structured_result_and_exit_code(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("ROSY_JOB_PRINCIPAL", "cell-job-human:tester")
    cfg = tmp_path / "rc.json"
    cfg.write_text(json.dumps({"robot": {"port": "/dev/serial/by-id/x", "id": "arm_s_follower"}}))
    for positions, code, reason in ((FOLDED, 0, None), (EXTENDED, 2, "NOT_FOLDED")):
        bus = Bus(motors(positions))
        session = record_session.Session(open_bus=lambda w, b=bus: b, systemctl=lambda *a: "", run=None, log=lambda **k: None)
        rc = job.main(["--arm", "arm_s", "--config", str(cfg)], open_bus=lambda b=bus: b,
                      session=session, lock=lambda arm: Guard(), calibration=CAL)
        out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
        assert (rc, out["reason_code"], out["ok"]) == (code, reason, code == 0) and out["principal"] == "cell-job-human:tester"
        assert out["before"]["11"]["torque"] == 1 and ("after" in out) == (code == 0)


def test_config_of_another_arm_is_refused(tmp_path, capsys):
    cfg = tmp_path / "rc.json"
    cfg.write_text(json.dumps({"robot": {"port": "/dev/serial/by-id/x", "id": "arm_b_follower"}}))
    bus = Bus(motors(FOLDED))
    assert job.main(["--arm", "arm_a", "--config", str(cfg)], open_bus=lambda: bus, lock=lambda a: Guard(), calibration=CAL,
                    session=None) == job.REJECTED
    assert json.loads(capsys.readouterr().out)["reason_code"] == "ARM_CONFIG_MISMATCH" and bus.writes == []


def test_pose_change_before_the_write_is_refused():
    class Moving(Bus):
        reads = 0

        def read(self, name):
            if name == "present_pos":
                Moving.reads += 1
                return FOLDED[self.motor - 11] if Moving.reads <= 6 else EXTENDED[self.motor - 11]
            return super().read(name)

    bus = Moving(motors(FOLDED))
    session = record_session.Session(open_bus=lambda w: bus, systemctl=lambda *a: "", run=None, log=lambda **k: None)
    with pytest.raises(job.Refused) as err:
        job.release("arm_s", "/dev/serial/by-id/x", open_bus=lambda: bus, lock=lambda a: Guard(), session=session,
                    calibration=CAL, baseline=lambda d, o: 0, out_dir=Path("o"))
    assert err.value.code == "NOT_FOLDED" and bus.writes == []


def test_job_is_not_moving_and_needs_no_person(tmp_path):
    (tmp_path / "rc.json").write_text("{}")
    spec = cell_job_spec.JOBS["torque_off_folded"]
    params = {"arm": "arm_s", "config": "rc.json"}
    argv = cell_job_spec.build_argv(spec, params, tmp_path)
    assert argv[-4:] == ["--arm", "arm_s", "--config", "rc.json"] and not cell_job_spec.moves_arm(spec, params)
