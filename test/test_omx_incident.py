"""omx_incident: an arm session that ends in trouble is collected, decided by measurement, recorded as a decision
row and an agenda, recovered only by an allowed reboot, and held for a person (arm_b 2026-11-03 13:27)."""
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "deploy/robot/omx"))
import omx_incident as oi  # noqa: E402

HOME = [0.8, -62.2, 51.8, 51.4, 45.0, 54.4]


@pytest.fixture(autouse=True)
def isolated_arm_home(tmp_path, monkeypatch):
    monkeypatch.setenv("ROSY_OMX_HOME", str(tmp_path / "arm-home"))


def test_hold_survives_a_new_recording_directory(tmp_path, monkeypatch):
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    monkeypatch.chdir(first)
    oi.handle(session(first), "arm_b")
    monkeypatch.chdir(second)
    with pytest.raises(SystemExit, match="held for a person"):
        oi.refuse_if_held("arm_b")
    oi.refuse_if_held("arm_a")


@pytest.mark.parametrize("bad_read", ["transport", "packet"])
def test_reboot_refuses_failed_torque_readback(tmp_path, monkeypatch, bad_read):
    from types import SimpleNamespace

    rebooted, closed = [], []
    port = SimpleNamespace(openPort=lambda: True, setBaudRate=lambda baud: True,
                           closePort=lambda: closed.append(True))

    def read(bus, motor, address):
        if motor == 13 and address == 64:
            return (0, -3001, 0) if bad_read == "transport" else (0, 0, 1)
        return (32 if address == 70 and motor == 13 else 0, 0, 0)

    packet = SimpleNamespace(read1ByteTxRx=read,
                             reboot=lambda bus, motor: rebooted.append(motor) or (0, 0))
    monkeypatch.setitem(sys.modules, "dynamixel_sdk", SimpleNamespace(
        COMM_SUCCESS=0, PortHandler=lambda device: port, PacketHandler=lambda version: packet))
    monkeypatch.setattr(oi.time, "sleep", lambda seconds: None)
    result = oi.reboot_latched("fake-follower")([13])
    assert rebooted == []
    assert result.get("error") or result.get("refused")
    assert closed == [True]


@pytest.mark.parametrize("failure", [None, "ack-transport", "ack-packet", "after-transport",
                                    "after-packet", "torque-on", "still-latched"])
def test_reboot_requires_valid_ack_and_clean_readback(monkeypatch, failure):
    from types import SimpleNamespace

    rebooted, closed = [], []
    port = SimpleNamespace(openPort=lambda: True, setBaudRate=lambda baud: True,
                           closePort=lambda: closed.append(True))

    def read(bus, motor, address):
        if rebooted and motor == 13:
            if failure == "after-transport":
                return 0, -3001, 0
            if failure == "after-packet":
                return 0, 0, 1
            if failure == "torque-on" and address == 64:
                return 1, 0, 0
        fault = motor == 13 and address == 70 and (not rebooted or failure == "still-latched")
        return (32 if fault else 0), 0, (128 if fault else 0)

    def reboot(bus, motor):
        rebooted.append(motor)
        return (-3001 if failure == "ack-transport" else 0), (1 if failure == "ack-packet" else 0)

    packet = SimpleNamespace(read1ByteTxRx=read, reboot=reboot)
    monkeypatch.setitem(sys.modules, "dynamixel_sdk", SimpleNamespace(
        COMM_SUCCESS=0, PortHandler=lambda device: port, PacketHandler=lambda version: packet))
    monkeypatch.setattr(oi.time, "sleep", lambda seconds: None)
    result = oi.reboot_latched("fake-follower")([13])
    assert closed == [True]
    if failure is None:
        assert result["rebooted"] == [13]
    else:
        assert "rebooted" not in result
        assert result.get("error") or result.get("refused")


def session(tmp_path, *, latched=True, last=HOME, status=(), windup=True):
    io = tmp_path / "chunk-io-b"
    io.mkdir()
    rows = [{"command": "run park", "ok": True, "state": last, "t": 101.0}] + list(status)
    (io / "chunk-status.jsonl").write_text("\n".join(json.dumps(r) for r in rows))
    library = tmp_path / "lib.json"
    library.write_text(json.dumps({"chunks": {"home": [HOME]}}))
    log = tmp_path / "motor-health-1.jsonl"
    samples = []
    for k in range(8):
        pwm = 30 if k < 3 or not windup else 261 + 17 * (k - 3)
        samples.append({"event": "sample", "sample_time": 200.0 + k, "motors": [
            {"joint": j, "usb_port": "/dev/serial/by-id/usb-ROBOTIS_OpenRB-150_7F31FF061D2D-if00",
             "command_raw": 3134 if j == "elbow_flex" else 2048,
             "present_raw": 3123 if j == "elbow_flex" and k >= 3 and windup else (3134 if j == "elbow_flex" else 2048),
             "pwm": pwm if j == "elbow_flex" else 0, "pwm_limit": 600} for j in oi.push_replay.jp.MOTORS]})
    log.write_text("\n".join(json.dumps(s) for s in samples))
    faults = tmp_path / "faults"
    faults.mkdir()
    (faults / "arm_b_follower-20261103T042721-a3644c.json").write_text(json.dumps({"session_id": "s1"}))
    record = {"safe_end": not latched, "started": 100.0, "torque_after": {str(i): 0 for i in range(11, 17)},
              "hardware_faults": {"13": {"hw_error": 32, "packet_alert": True}} if latched else {},
              "chunks": {"io": str(io), "library": str(library)}, "motor_health_log": str(log),
              "motor_health_state": str(tmp_path / "motor-health-current.json"), "motor_health_owner": "arm_b_follower",
              "motor_health_session": "s1"}
    path = tmp_path / "session.json"
    path.write_text(json.dumps(record))
    return path


def test_the_13_27_overload_is_rebooted_recorded_as_an_agenda_and_held_for_a_person(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rebooted = []
    out = oi.handle(session(tmp_path), "arm_b", act=lambda ids: rebooted.append(ids) or {"rebooted": ids})
    assert rebooted == [[13]] and out["decision"]["hold"] and out["facts"]["folded"]
    assert "overload" in out["decision"]["reason"] and "wind-up" in out["decision"]["reason"]
    assert out["facts"]["frames"][0].endswith("a3644c-top.jpg")
    agenda = (Path(out["folder"]) / "agenda.md").read_text()
    assert "HOLD" in agenda and "omx_incident.py clear --arm arm_b" in agenda
    row = json.loads((tmp_path / "decisions.jsonl").read_text().splitlines()[-1])
    assert row["stage"] == "incident" and row["chosen"] == ["reboot_latched", "hold_for_person"]
    with pytest.raises(SystemExit, match="held for a person"):
        oi.refuse_if_held("arm_b")
    assert oi.main(["clear", "--arm", "arm_b", "--by", "operator", "--note", "box removed from the jaws"]) == 0
    oi.refuse_if_held("arm_b")
    assert json.loads((tmp_path / "decisions.jsonl").read_text().splitlines()[-1])["by"] == "person"


def test_an_arm_that_is_not_folded_is_never_rebooted(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    out = oi.handle(session(tmp_path, last=[0.8, -20.0, 10.0, 51.4, 45.0, 54.4]), "arm_b",
                    act=lambda ids: pytest.fail("rebooted an extended arm"))
    assert out["decision"]["hold"] and not out["decision"]["actions"] and "not folded" in out["decision"]["reason"]


def test_a_clean_session_is_no_incident_and_a_reopened_catch_is_a_note_without_hold(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert oi.handle(session(tmp_path, latched=False, windup=False), "arm_b") == {"incident": False}
    caught = {"command": "grip", "ok": False, "caught": True, "error": "the jaws stopped; reopened", "t": 150.0}
    (tmp_path / "x").mkdir()
    out = oi.handle(session(tmp_path / "x", latched=False, windup=False, status=[caught]), "arm_b")
    assert out["incident"] and not out["decision"]["hold"] and oi.held("arm_b") is None
