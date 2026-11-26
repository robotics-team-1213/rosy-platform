"""Supervised session baseline repair must retain evidence and refuse uncertain writes."""
from contextlib import nullcontext
import json
from pathlib import Path

import pytest


@pytest.fixture
def recovery(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / "deploy/robot/omx"))
    import record_session_baseline as r

    rows = []
    for motor in range(11, 17):
        rows.append({
            **r.limits.BASELINE, "id": motor, "model_number": 1060 if motor < 14 else 1200,
            "torque_enabled": 0, "hardware_error": 0, "operating_mode": 4 if motor < 16 else 5,
            "drive_mode": 0, "homing_offset_raw": 0, "velocity_limit_raw": 256,
            "position_raw": {12: 500, 13: 3500}.get(motor, 2048),
            "current_limit_raw": None if motor < 14 else 50,
        })
    rows[0]["pwm_limit_raw"] = 885
    cal = {name: dict(id=motor, drive_mode=0, homing_offset=0, range_min=0, range_max=4095)
           for motor, name in enumerate(r.FOLLOWER_JOINTS, 11)}
    monkeypatch.setattr(r.limits, "state_root", lambda: tmp_path / "state")
    monkeypatch.setattr(r, "_bound_device", lambda arm, robot: Path("/dev/serial/by-id/fixture-follower"))
    monkeypatch.setattr(r, "_calibration", lambda arm, robot: cal)
    monkeypatch.setattr(r, "open_readonly_port", lambda device: nullcontext(None))
    monkeypatch.setattr(r, "read_motors", lambda port: rows)
    return r, rows, cal


@pytest.mark.parametrize("fault", ["torque", "pose", "offset", "missing_id", "increase", "uncertain", "readback", "success"])
def test_guarded_restore_and_restart_hold(recovery, monkeypatch, fault):
    r, rows, cal = recovery
    writes = []

    def writer(argv, *, read, owner):
        assert argv[2] == "--baseline"
        r.limits._refuse_pending(argv[1], owner=owner)
        read(None)
        writes.append(True)
        folder = Path(argv[-1])
        folder.mkdir()
        if fault == "uncertain":
            return 2
        if fault != "readback":
            rows[0]["pwm_limit_raw"] = 20
        (folder / "receipt.json").write_text(json.dumps({"configuration_verified": True, "error": None}))
        return 0

    monkeypatch.setattr(r.limits, "_commission", writer)
    if fault == "torque":
        rows[-1]["torque_enabled"] = 1
    elif fault == "pose":
        rows[1]["position_raw"] = 3000
    elif fault == "offset":
        rows[2]["homing_offset_raw"] = 1
    elif fault == "missing_id":
        del cal[r.FOLLOWER_JOINTS[0]]["id"]
    elif fault == "increase":
        rows[1]["pwm_limit_raw"] = 10
    if fault == "success":
        receipt = r.restore("arm_a", {})
        assert Path(receipt).is_file()
    else:
        with pytest.raises((SystemExit, ValueError)) as error:
            r.restore("arm_a", {})
        if fault in ("pose", "offset", "missing_id"):
            assert error.value.code == 78
    assert bool(writes) == (fault in ("success", "uncertain", "readback"))
    if fault in ("uncertain", "readback"):
        with pytest.raises(SystemExit, match="interrupted"):
            r.check_pending("arm_a")
        with pytest.raises(SystemExit, match="interrupted"):
            r.check_pending(None)
    else:
        r.check_pending("arm_a")
    r.check_pending("arm_b")
