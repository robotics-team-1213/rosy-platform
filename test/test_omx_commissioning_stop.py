"""The independent commissioning stop can transmit only bounded torque-OFF writes."""
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


def module():
    directory = Path(__file__).parents[1] / "deploy/robot/omx"
    path = directory / "commissioning_stop.py"
    assert path.exists(), "Independent commissioning torque-OFF transport is missing"
    sys.path.insert(0, str(directory))
    try:
        spec = importlib.util.spec_from_file_location("commissioning_stop", path)
        result = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(result)
        return result
    finally:
        sys.path.remove(str(directory))


def packet(motor=16, address=64, value=0, instruction=3):
    # CRC is supplied by the real SDK; this test isolates the transport whitelist.
    return b"\xff\xff\xfd\x00" + bytes([motor, 6, 0, instruction]) + address.to_bytes(2, "little") + bytes([value, 0, 0])


def motors():
    return [dict(id=i, model_number=1060 if i < 14 else 1200,
                 torque_enabled=0, hardware_error=0) for i in range(11, 17)]


def test_only_one_exact_off_write_and_existing_read_packets_are_permitted():
    m = module(); sent = []
    guard = m.off_writer(lambda data: sent.append(data) or len(data), 16)
    ping = b"\xff\xff\xfd\x00\x10\x03\x00\x01\x00\x00"
    assert guard(ping) == len(ping)
    assert guard(packet()) == 13
    with pytest.raises(ValueError):
        guard(packet())
    assert sent == [ping, packet()]


@pytest.mark.parametrize("data", [packet(value=1), packet(motor=15), packet(motor=254),
                                  packet(address=116), packet(address=11), packet(instruction=8),
                                  packet()[:-1], packet() + b"\x00"])
def test_wrong_motor_enable_goal_mode_reboot_or_shape_never_reaches_transport(data):
    sent = []
    with pytest.raises(ValueError):
        module().off_writer(lambda data: sent.append(data), 16)(data)
    assert sent == []


def test_failed_or_short_write_is_not_retried():
    m = module(); sent = []
    def fail(data):
        sent.append(data)
        raise OSError("transport failed after unknown transmission")
    guard = m.off_writer(fail, 16)
    with pytest.raises(OSError):
        guard(packet())
    with pytest.raises(ValueError):
        guard(packet())
    assert len(sent) == 1
    guard = m.off_writer(lambda data: 1, 16)
    assert guard(packet()) == 1
    with pytest.raises(ValueError):
        guard(packet())


@pytest.mark.parametrize("ids", [[], [16, 16], [10], [17], [True], [16.0], ["16"]])
def test_invalid_stop_scope_never_calls_sdk(ids):
    with pytest.raises(ValueError):
        module().disable_torque(SimpleNamespace(writePort=lambda data: pytest.fail("sent")), ids,
                                write=lambda *args: pytest.fail("SDK called"))


@pytest.mark.parametrize("failure", ["none", "ack_lost", "sdk_exception", "still_on", "read_lost", "wrong_model"])
def test_attempt_all_admitted_motors_despite_one_failure_and_require_ack_plus_actual_off(failure):
    m = module(); sent = []; calls = []
    port = SimpleNamespace(writePort=lambda data: sent.append(data) or len(data))
    def write(port, motor):
        calls.append(motor)
        port.writePort(packet(motor=motor))
        if motor == 14 and failure == "ack_lost":
            return -3001, 0
        if motor == 14 and failure == "sdk_exception":
            raise OSError("ACK unknown")
        return 0, 0
    def read(port):
        if failure == "read_lost":
            raise OSError("read unavailable")
        rows = motors()
        if failure == "still_on": rows[-1]["torque_enabled"] = 1
        if failure == "wrong_model": rows[-1]["model_number"] = 1060
        return rows
    report = m.disable_torque(port, [14, 16], write=write, read=read)
    assert calls == [14, 16] and sent == [packet(motor=14), packet(motor=16)]
    assert report["stop_verified"] is (failure == "none")
    assert report["torque_off_readback"] is (failure in {"none", "ack_lost", "sdk_exception"})
    assert report["motion_admitted"] is False and report["physical_stop_verified"] is False
    # After any outcome the port is back to read-only.
    with pytest.raises(ValueError): port.writePort(packet(value=1))


def test_unselected_on_motor_is_reported_without_unrequested_off_write():
    rows = motors(); rows[0]["torque_enabled"] = 1
    sent = []; port = SimpleNamespace(writePort=lambda data: sent.append(data) or len(data))
    def write(port, motor):
        port.writePort(packet(motor=motor)); return 0, 0
    report = module().disable_torque(port, [16], write=write, read=lambda port: rows)
    assert report["stop_verified"] and report["motors"] == rows
    assert sent == [packet()]


def test_log_directory_failure_does_not_skip_stop_attempt(monkeypatch, tmp_path, capsys):
    m = module(); calls = []
    from contextlib import contextmanager
    @contextmanager
    def open_port(device):
        calls.append("open"); yield SimpleNamespace(ser=SimpleNamespace(fileno=lambda: 42))
    monkeypatch.setattr(m, "open_readonly_port", open_port)
    # Keep the fake fstat inside this module; pytest capture needs the real OS metadata.
    monkeypatch.setattr(m, "os", SimpleNamespace(
        geteuid=lambda: 1000, fstat=lambda fd: SimpleNamespace(st_rdev=123), fsync=m.os.fsync))
    monkeypatch.setattr(m, "disable_torque", lambda port, ids: calls.append(ids) or dict(stop_verified=True))
    output = tmp_path / "already-exists"; output.mkdir()
    result = m.main(["--device", "/dev/serial/by-id/confirmed", "--expected-device-id", "123",
                     "--ids", "16", "--output", str(output)])
    assert calls == ["open", [16]] and result == 2
    assert 'record_error' in capsys.readouterr().out and list(output.iterdir()) == []


def test_device_identity_mismatch_prevents_any_off_write(monkeypatch, tmp_path):
    m = module()
    from contextlib import contextmanager
    @contextmanager
    def open_port(device):
        yield SimpleNamespace(ser=SimpleNamespace(fileno=lambda: 42))
    monkeypatch.setattr(m, "open_readonly_port", open_port)
    monkeypatch.setattr(m, "os", SimpleNamespace(
        geteuid=lambda: 1000, fstat=lambda fd: SimpleNamespace(st_rdev=999), fsync=m.os.fsync))
    monkeypatch.setattr(m, "disable_torque", lambda *args: pytest.fail("wrong device written"))
    assert m.main(["--device", "/dev/serial/by-id/confirmed", "--expected-device-id", "123",
                   "--ids", "16", "--output", str(tmp_path / "record")]) == 2


def test_serial_cleanup_failure_after_verified_off_is_not_clean_exit(monkeypatch, tmp_path, capsys):
    m = module()
    from contextlib import contextmanager
    @contextmanager
    def open_port(device):
        yield SimpleNamespace(ser=SimpleNamespace(fileno=lambda: 42))
        raise OSError("serial close failed")
    monkeypatch.setattr(m, "open_readonly_port", open_port)
    monkeypatch.setattr(m, "os", SimpleNamespace(
        geteuid=lambda: 1000, fstat=lambda fd: SimpleNamespace(st_rdev=123), fsync=m.os.fsync))
    monkeypatch.setattr(m, "disable_torque", lambda port, ids: dict(stop_verified=True))
    result = m.main(["--device", "/dev/serial/by-id/confirmed", "--expected-device-id", "123",
                     "--ids", "16", "--output", str(tmp_path / "record")])
    assert result == 2
    assert 'serial close failed' in capsys.readouterr().out
