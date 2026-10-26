"""Arm S live state and guard motor health become valid Fleet ArmObservations; stale or repeated rows are not sent."""
import importlib.util
import json
import math
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).parents[1]
OMX = ROOT / "deploy/robot/omx"
sys.path.insert(0, str(OMX))
try:
    spec = importlib.util.spec_from_file_location("arm_status_bridge", OMX / "arm_status_bridge.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
finally:
    sys.path.remove(str(OMX))


def test_follower_units_convert_to_dynamixel_radians():
    rad = m.to_radians([0.0, -50.0, 50.0, 100.0, -100.0, 50.0])
    assert rad["joint1"] == pytest.approx(0.0, abs=0.002)  # tick 2047.5 is about 0 rad
    assert rad["joint2"] == pytest.approx(-math.pi / 2, abs=0.002)
    assert rad["joint4"] == pytest.approx(math.pi, abs=0.002) and rad["joint5"] == pytest.approx(-math.pi, abs=0.002)
    assert rad["gripper_joint_1"] == pytest.approx(0.0, abs=0.002)  # gripper 50 of 0..100


def test_conversion_preserves_the_followers_calibrated_tick_range():
    calibration = {motor: {"range_min": 1024, "range_max": 3072} for motor in m.MOTORS}
    rad = m.to_radians([-100, 100, 0, 0, 0, 25], calibration)
    assert rad["joint1"] == pytest.approx(-math.pi / 2, abs=0.00001)
    assert rad["joint2"] == pytest.approx(math.pi / 2, abs=0.00001)
    assert rad["gripper_joint_1"] == pytest.approx(-math.pi / 4, abs=0.00001)


def test_only_fresh_newer_rows_are_sent():
    row = {"t": 100.0, "state": [0, 0, 0, 0, 0, 50]}
    assert m.fresh_sample(row, None, 100.5) is not None
    assert m.fresh_sample(row, 100.0, 100.5) is None          # already sent
    assert m.fresh_sample(row, None, 103.0) is None           # runner stopped: stale
    assert m.fresh_sample({"t": 100.0}, None, 100.5) is None  # no state


def test_the_sample_is_a_valid_fleet_arm_observation():
    sys.path.insert(0, str(ROOT / "contracts/foundation"))
    try:
        observations = pytest.importorskip("core_common.protocol.workcell_observations")
    finally:
        sys.path.remove(str(ROOT / "contracts/foundation"))
    sample = m.fresh_sample({"t": 1792850000.5, "state": [29.0, -17.8, 24.7, 43.1, -33.3, 46.6]}, None, 1792850000.6)
    observation = observations.ArmObservation(epoch="a" * 32, sequence=1, captured_at=sample.captured_at,
                                              positions=sample.value)
    assert set(observation.positions) == set(m.JOINTS)


ARM_ID, NOW = "omx_s", 1792850000.0


def _snapshot(tmp_path, status="active", owner=ARM_ID, motors=m.MOTORS, reasons=()):
    """The shape chunk_runner's MotorHealth monitor publishes (LeRobot motor names, group "follower")."""
    rows = [dict(joint=name, id=11 + i, group="follower", command_raw=2048.0, present_raw=2050.0, error_deg=0.18,
                 pwm=120.0, pwm_limit=885.0, pwm_utilization=0.14, temperature_c=41.0, temperature_limit_c=80.0,
                 voltage_v=12.1, min_voltage_v=9.5, max_voltage_v=14.0, warnings=[], observed_at=NOW - 0.2)
            for i, name in enumerate(motors)]
    row = dict(schema_version="rosy.motor-health.v1", owner_id=owner, session_id="12345678-1234-4234-8234-123456789abc",
               status=status, observed_at=NOW - 0.2, expected_motor_count=len(rows), motors=rows,
               stop_reasons=list(reasons))
    if status != "active":
        row["terminal_at"] = NOW - 0.1
    path = (tmp_path / "motor-health-current.json").resolve()
    path.write_text(json.dumps(row))
    return path


def test_guard_health_is_renamed_to_the_registered_arm_or_dropped(tmp_path):
    health, _ = m.arm_health(_snapshot(tmp_path), ARM_ID, NOW)
    assert [(x.joint, x.group, x.id) for x in health.motors] == [(j, ARM_ID, 11 + i) for i, j in enumerate(m.JOINTS)]
    assert health.evidence == "fresh" and health.status == "active"
    assert m.arm_health(_snapshot(tmp_path, owner="omx"), ARM_ID, NOW) == (None, None)       # another owner
    assert m.arm_health(_snapshot(tmp_path, motors=m.MOTORS[:5]), ARM_ID, NOW) == (None, None)  # partial
    assert m.arm_health(tmp_path.resolve() / "missing.json", ARM_ID, NOW) == (None, None)


def test_a_guard_fault_goes_once_without_positions(tmp_path):
    fault = m.arm_health(_snapshot(tmp_path, "fault", reasons=["following error"]), ARM_ID, NOW)
    sample = m.next_sample({}, fault, NOW - 1, NOW)                  # the runner exited: no live row
    assert sample.value is None and sample.motor_health.stop_reasons == ["following error"]
    assert m.next_sample({}, fault, sample.captured_at, NOW) is None  # not repeated
    assert m.next_sample({}, fault, None, NOW + 5) is None            # too old for Fleet's clock window
    active = m.arm_health(_snapshot(tmp_path), ARM_ID, NOW)
    live = m.next_sample({"t": NOW, "state": [0, 0, 0, 0, 0, 50]}, active, None, NOW)
    assert live.value and live.motor_health.status == "active"


def test_fleet_stores_and_serves_the_guard_fault(tmp_path):
    from hashlib import sha256
    from core_common.protocol.workcell_observations import ArmObservation, WorkcellObservationManifest
    from fleet.server.workcell_observations import WorkcellObservations

    manifest = WorkcellObservationManifest.model_validate({"schema": "rosy.workcell-observations/1", "workcells": [{
        "workcell_id": "cell_s", "label": "Cell S", "arms": [{
            "source_id": "omx_arm_s", "arm_id": ARM_ID, "label": "Arm S", "board_id": "EXAMPLE-BOARD",
            "joint_topic": "/omx_commissioning/omx_s/joint_states", "joint_names": m.JOINTS,
            "token_env": "EXAMPLE_ARM", "credential_sha256": sha256(b"arm-secret").hexdigest()}],
        "cameras": [{"source_id": "top", "label": "Top", "role": "overhead", "arm_id": None,
            "image_topic": "/top/image_raw", "device_path": "/dev/v4l/by-path/example-top",
            "token_env": "EXAMPLE_TOP", "credential_sha256": sha256(b"top-secret").hexdigest()}]}]})
    clock = [NOW]
    fleet = WorkcellObservations(manifest, {"omx_arm_s": "arm-secret"},
                                 wall=lambda: clock[0], monotonic=lambda: clock[0])

    def post(sequence, sample):
        fleet.ingest("omx_arm_s", "arm-secret", ArmObservation(epoch="a" * 32, sequence=sequence,
            captured_at=sample.captured_at, positions=sample.value, motor_health=sample.motor_health))
        return fleet.snapshot()["workcells"][0]["arms"][0]

    active = m.arm_health(_snapshot(tmp_path), ARM_ID, NOW)
    arm = post(1, m.next_sample({"t": NOW - 0.3, "state": [0, 0, 0, 0, 0, 50]}, active, None, NOW))
    assert arm["fresh"] and arm["motor_health"]["status"] == "active"
    assert arm["motor_health"]["motors"][0]["joint"] == "joint1"
    clock[0] = NOW + 3
    stale = fleet.snapshot()["workcells"][0]["arms"][0]
    assert not stale["fresh"] and stale["positions"] is None
    assert stale["motor_health"]["evidence"] == "delayed"
    clock[0] = NOW
    fault = m.arm_health(_snapshot(tmp_path, "fault", reasons=["following error"]), ARM_ID, NOW)
    arm = post(2, m.next_sample({}, fault, NOW - 0.3, NOW))
    assert arm["positions"] is None and arm["motor_health"]["status"] == "fault"
    assert arm["motor_health"]["stop_reasons"] == ["following error"]


@pytest.mark.parametrize("status", ["fault", "ended"])
def test_terminal_guard_health_does_not_need_a_live_file(tmp_path, monkeypatch, status):
    import types

    sent = []

    class Sender:
        def __init__(self, *args, **kwargs):
            pass

        def send(self, sample):
            sent.append(sample)

    def finish(_):
        raise InterruptedError

    monkeypatch.setitem(sys.modules, "workcell_observation_bridge", types.SimpleNamespace(ArmSender=Sender))
    monkeypatch.setenv("EXAMPLE_TOKEN", "example-token")
    monkeypatch.setattr(m.time, "time", lambda: NOW)
    monkeypatch.setattr(m.time, "sleep", finish)
    path = _snapshot(tmp_path, status, reasons=["session ended"] if status == "ended" else ["following error"])
    with pytest.raises(InterruptedError):
        m.main(["--live", str(tmp_path / "missing-live.json"), "--fleet-url", "https://fleet.example.invalid",
                "--source-id", "omx_arm_s", "--token-env", "EXAMPLE_TOKEN", "--arm-id", ARM_ID,
                "--health-file", str(path)])
    assert len(sent) == 1 and sent[0].value is None and sent[0].motor_health.status == status


def test_held_live_fault_never_becomes_a_terminal_guard_fault():
    sample = m.next_sample({"t": NOW, "state": [0, 0, 0, 0, 0, 50],
                            "fault": "contact", "health": {"temperature": 80}}, (None, None), None, NOW)
    assert sample.value and sample.motor_health is None


def test_managed_arm_s_service_has_private_explicit_bindings_and_release_ownership():
    import yaml

    unit = "rosy-omx-arm-status.service"
    text = (OMX / unit).read_text()
    env = (OMX / "arm-status.env.example").read_text()
    assert "EnvironmentFile=%h/.config/rosy/omx-arm-status.env" in text
    assert "UMask=0077" in text and "NoNewPrivileges=true" in text
    for flag, binding in {"live": "LIVE", "source-id": "SOURCE_ID", "arm-id": "ARM_ID",
                          "calibration": "CALIBRATION", "health-file": "HEALTH_FILE",
                          "fleet-url": "FLEET_URL", "ca-file": "CA_FILE"}.items():
        assert f'--{flag} "$ROSY_ARM_STATUS_{binding}"' in text
        assert f"ROSY_ARM_STATUS_{binding}=" in env
    assert "--token-env ROSY_ARM_S_TOKEN" in text
    assert "ROSY_ARM_S_TOKEN=\n" in env
    assert "current-env/bin/python" in env and "current/deploy/robot/omx/arm_status_bridge.py" in env
    assert "current/contracts/foundation" in env and "current/operations/overhead" in env
    entry = yaml.safe_load((ROOT / "deploy/hosts/services.yaml").read_text())["roles"]["site"][unit]
    assert entry["channel"] == "autoupdate" and entry["template"] == f"deploy/robot/omx/{unit}"
    cfg = json.loads((OMX / "omx-devices-autoupdate.json.example").read_text())
    assert unit in cfg["units"] and f"deploy/robot/omx/{unit}" in cfg["unit_files"]
    assert "arm_status_bridge" in cfg["smoke"]


def test_missing_producer_credential_refuses_startup(monkeypatch):
    monkeypatch.delenv("ROSY_ARM_S_TOKEN", raising=False)
    with pytest.raises(SystemExit, match="ROSY_ARM_S_TOKEN is not set"):
        m.main(["--live", "missing.json", "--fleet-url", "https://fleet.example.invalid",
                "--source-id", "omx_arm_s", "--token-env", "ROSY_ARM_S_TOKEN"])
