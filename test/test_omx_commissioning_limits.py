"""Finite commissioning caps must be applied with torque off and verified per write."""
import copy
import importlib.util
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).parents[1]


def module():
    directory = ROOT / "deploy/robot/omx"
    sys.path.insert(0, str(directory))
    try:
        spec = importlib.util.spec_from_file_location("commissioning_limits", directory / "commissioning_limits.py")
        result = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(result)
        return result
    finally:
        sys.path.remove(str(directory))


def motors():
    return [dict(id=i, model_number=1060 if i < 14 else 1200, torque_enabled=0,
                 hardware_error=0, operating_mode=4 if i < 16 else 5, drive_mode=0,
                 pwm_limit_raw=885, current_limit_raw=None if i < 14 else 1750,
                 velocity_limit_raw=265, profile_velocity_raw=0, profile_acceleration_raw=0,
                 homing_offset_raw=1024 if i == 14 else 0, goal_position_raw=2048,
                 position_raw=2048) for i in range(11, 17)]


def limits():
    return dict(pwm_limit_raw=20, current_limit_raw=50,
                profile_velocity_raw=1, profile_acceleration_raw=1)


def test_plan_only_reduces_supported_caps_without_motion_registers():
    m = module()
    before = motors()
    plan = m.plan_limits(before, limits())
    assert len(plan) == 21
    assert {(op["address"], op["size"]) for op in plan} == {(36, 2), (38, 2), (108, 4), (112, 4)}
    assert [op["id"] for op in plan if op["address"] == 38] == [14, 15, 16]
    assert before == motors()
    for op in plan:
        assert op["before"] != op["value"] and op["value"] > 0
    lowered = motors()
    for row in lowered:
        row.update({key: value for key, value in limits().items()
                    if key != "current_limit_raw" or row["id"] >= 14})
    assert m.plan_limits(lowered, limits()) == []


@pytest.mark.parametrize("field", list(limits()))
@pytest.mark.parametrize("value", [True, 0, -1, 1.5, float("nan"), 100000])
def test_invalid_caps_never_produce_writes(field, value):
    request = limits()
    request[field] = value
    with pytest.raises(ValueError):
        module().plan_limits(motors(), request)


@pytest.mark.parametrize("fault", ["torque", "error", "mode", "drive", "model", "duplicate", "missing",
                                   "increase_pwm", "increase_current", "increase_velocity", "increase_accel"])
def test_unsafe_or_unidentified_preconditions_reject_before_writes(fault):
    rows = motors()
    if fault == "duplicate":
        rows[-1] = copy.deepcopy(rows[0])
    elif fault == "missing":
        rows.pop()
    else:
        field, value = {"torque": ("torque_enabled", 1), "error": ("hardware_error", 8),
                        "mode": ("operating_mode", 3), "drive": ("drive_mode", 4),
                        "model": ("model_number", 1234), "increase_pwm": ("pwm_limit_raw", 10),
                        "increase_current": ("current_limit_raw", 20),
                        "increase_velocity": ("profile_velocity_raw", 0.5),
                        "increase_accel": ("profile_acceleration_raw", 0.5)}[fault]
        rows[-1][field] = value
    with pytest.raises(ValueError):
        module().plan_limits(rows, limits())


def packet(op, *, instruction=3):
    payload = op["address"].to_bytes(2, "little") + op["value"].to_bytes(op["size"], "little")
    return b"\xff\xff\xfd\x00" + bytes([op["id"]]) + (len(payload) + 3).to_bytes(2, "little") + bytes([instruction]) + payload + b"\x00\x00"


def test_transport_allows_only_one_exact_planned_write_and_existing_reads():
    m = module()
    op = m.plan_limits(motors(), limits())[0]
    sent = []
    write = m.one_write_guard(lambda data: sent.append(bytes(data)) or len(data), op)
    ping = b"\xff\xff\xfd\x00\x0b\x03\x00\x01\x00\x00"
    assert write(ping) == len(ping)
    wrong = dict(op, address=64, size=1, value=1)
    for data in [packet(wrong), packet(dict(op, value=op["value"] + 1)), packet(op, instruction=8)]:
        with pytest.raises(ValueError):
            write(data)
    assert write(packet(op)) == len(packet(op))
    with pytest.raises(ValueError):
        write(packet(op))
    assert sent == [ping, packet(op)]


class FakeBus:
    def __init__(self, *, lost_ack=False, mismatch=False):
        self.rows = motors()
        self.sent = []
        self.writePort = self.send
        self.lost_ack = lost_ack
        self.mismatch = mismatch
        self.reads = 0

    def send(self, data):
        self.sent.append(bytes(data))
        return len(data)

    def read(self, port):
        assert port is self
        self.reads += 1
        return copy.deepcopy(self.rows)

    def write(self, port, motor, address, size, value):
        assert port is self
        op = dict(id=motor, address=address, size=size, value=value)
        port.writePort(packet(op))
        field = {36: "pwm_limit_raw", 38: "current_limit_raw", 108: "profile_acceleration_raw", 112: "profile_velocity_raw"}[address]
        if not self.mismatch:
            self.rows[motor - 11][field] = value
        return (-1 if self.lost_ack else 0), 0


def test_apply_records_intent_before_send_and_verifies_each_register(tmp_path):
    m = module()
    bus = FakeBus()
    events = []

    def record(event):
        if event["event"] == "write_intent":
            assert len(bus.sent) == sum(e["event"] == "verified" for e in events)
        events.append(copy.deepcopy(event))

    receipt = m.configure_limits(bus, limits(), record, read=bus.read, write=bus.write)
    assert receipt["configuration_verified"] and receipt["motion_admitted"] is False
    assert len(bus.sent) == 21 and bus.reads >= 22
    assert sum(e["event"] == "verified" for e in events) == 21
    assert receipt["uncertain_write"] is None


@pytest.mark.parametrize("lost_ack,mismatch", [(True, False), (False, True)])
def test_failure_keeps_originals_stops_without_retry_or_rollback(lost_ack, mismatch):
    m = module()
    bus = FakeBus(lost_ack=lost_ack, mismatch=mismatch)
    events = []
    with pytest.raises(RuntimeError):
        m.configure_limits(bus, limits(), events.append, read=bus.read, write=bus.write)
    assert len(bus.sent) == 1
    assert events[0]["event"] == "before" and events[0]["motors"] == motors()
    assert events[-1]["event"] == "failed" and events[-1]["uncertain_write"] is not None
    assert events[-1]["after"] is not None
    with pytest.raises(ValueError):
        bus.writePort(packet(dict(id=11, address=64, size=1, value=1)))


def test_recording_failure_prevents_device_write():
    bus = FakeBus()

    def record(event):
        if event["event"] == "write_intent":
            raise OSError("disk full")

    with pytest.raises(OSError):
        module().configure_limits(bus, limits(), record, read=bus.read, write=bus.write)
    assert bus.sent == []


@pytest.mark.parametrize("address,size,value", [(64, 1, 1), (116, 4, 2048), (11, 1, 3), (36, 2, 0)])
def test_transport_independently_rejects_non_cap_or_unbounded_plan(address, size, value):
    sent = []
    with pytest.raises(ValueError):
        module().one_write_guard(sent.append, dict(id=11, address=address, size=size, value=value))
    assert sent == []


@pytest.mark.parametrize("field", ["profile_velocity_raw", "profile_acceleration_raw"])
def test_previously_finite_profiles_cannot_be_increased(field):
    rows = motors()
    rows[0][field] = 1
    request = limits()
    request[field] = 2
    with pytest.raises(ValueError):
        module().plan_limits(rows, request)


def test_post_write_torque_or_unrelated_register_change_stops_next_write():
    for field, value in [("torque_enabled", 1), ("homing_offset_raw", 99)]:
        bus = FakeBus()
        original = bus.write

        def mutate(*args):
            result = original(*args)
            bus.rows[-1][field] = value
            return result

        with pytest.raises((ValueError, RuntimeError)):
            module().configure_limits(bus, limits(), lambda event: None, read=bus.read, write=mutate)
        assert len(bus.sent) == 1


def test_durable_verified_record_failure_stops_next_write():
    bus = FakeBus()

    def record(event):
        if event["event"] == "verified":
            raise OSError("journal fsync failed")

    with pytest.raises(OSError):
        module().configure_limits(bus, limits(), record, read=bus.read, write=bus.write)
    assert len(bus.sent) == 1


def test_cli_refuses_existing_output_before_any_port_open(tmp_path, monkeypatch):
    m = module()
    import json
    request = tmp_path / "limits.json"
    request.write_text(json.dumps(limits()))
    output = tmp_path / "existing"
    output.mkdir()
    monkeypatch.setattr(m.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(m, "open_readonly_port", lambda device: pytest.fail("port opened"))
    with pytest.raises(FileExistsError):
        m.main(["--device", "/dev/serial/by-id/test", "--limits", str(request), "--output", str(output)])


def test_baseline_option_lowers_caps_a_session_left_raised_without_a_limits_file(tmp_path, monkeypatch):
    import contextlib
    m = module()
    seen = {}

    def configure(port, requested, record):
        seen.update(requested)
        record({"event": "complete"})

    monkeypatch.setattr(m.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(m, "open_readonly_port", lambda device: contextlib.nullcontext())
    monkeypatch.setattr(m, "configure_limits", configure)
    assert m.main(["--device", "/dev/serial/by-id/test", "--baseline", "--output", str(tmp_path / "out")]) == 0
    assert seen == limits()
    raised = motors()  # 2026-10-24: a session ended with every follower at PWM 300 / Current 500
    for row in raised:
        row["pwm_limit_raw"] = 300
        row["current_limit_raw"] = None if row["id"] < 14 else 500
    caps = {(op["id"], op["field"], op["value"]) for op in m.plan_limits(raised, seen)
            if op["field"] in ("pwm_limit_raw", "current_limit_raw")}
    assert caps == ({(i, "pwm_limit_raw", 20) for i in range(11, 17)}
                    | {(i, "current_limit_raw", 50) for i in range(14, 17)})


def test_slow_durable_intent_cannot_send_after_deadline(monkeypatch):
    m = module()
    now = [0]
    monkeypatch.setattr(m.time, "monotonic", lambda: now[0])
    bus = FakeBus()
    events = []

    def record(event):
        events.append(copy.deepcopy(event))
        if event["event"] == "write_intent":
            now[0] = 16

    with pytest.raises(RuntimeError, match="deadline"):
        m.configure_limits(bus, limits(), record, read=bus.read, write=bus.write)
    assert bus.sent == []
    assert events[-1]["event"] == "failed" and events[-1]["uncertain_write"] is None
