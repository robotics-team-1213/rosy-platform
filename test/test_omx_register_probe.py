"""Commissioning reads cannot silently become motor writes."""
import importlib.util
from pathlib import Path

import pytest
from types import SimpleNamespace


def probe():
    path = Path(__file__).resolve().parents[1] / "deploy/robot/omx/register_probe.py"
    spec = importlib.util.spec_from_file_location("register_probe", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_only_exact_unicast_ping_and_register_read_packets_pass():
    module = probe()
    ping = bytes([255, 255, 253, 0, 11, 3, 0, 1, 0, 0])
    read = bytes([255, 255, 253, 0, 16, 7, 0, 2, 0, 0, 147, 0, 0, 0])
    assert module.read_packet_allowed(ping)
    assert module.read_packet_allowed(read)
    for instruction in (3, 4, 5, 6, 8, 16, 131, 146):
        assert not module.read_packet_allowed(ping[:7] + bytes([instruction]) + ping[8:])
    for invalid in (b"", ping[:-1], ping + ping, ping[:4] + b"\xfe" + ping[5:],
                    read[:8] + b"\x01" + read[9:]):
        assert not module.read_packet_allowed(invalid)


def test_register_decoding_preserves_signed_position_and_rejects_unknown_models():
    module = probe()
    raw = bytearray(147)
    raw[132:136] = (-5).to_bytes(4, "little", signed=True)
    raw[64] = 1
    row = module.decode_registers(1060, raw)
    assert row["position_raw"] == -5
    assert row["torque_enabled"] == 1
    with pytest.raises(ValueError):
        module.decode_registers(9999, raw)
    with pytest.raises(ValueError):
        module.decode_registers(1060, raw[:-1])


def test_transport_refuses_before_any_bytes_are_written():
    module = probe()
    sent = []
    write = module.readonly_writer(lambda packet: sent.append(packet))
    with pytest.raises(ValueError):
        write(bytes([255, 255, 253, 0, 11, 3, 0, 8, 0, 0]))
    assert sent == []


def test_startup_registers_are_read_without_changing_transport_allowlist():
    module = probe()
    raw = bytearray(147)
    fields = {"goal_position_raw": (116, 4, -2048, True),
              "goal_current_raw": (102, 2, -20, True),
              "profile_acceleration_raw": (108, 4, 12, False),
              "profile_velocity_raw": (112, 4, 15, False),
              "current_limit_raw": (38, 2, 100, False),
              "pwm_limit_raw": (36, 2, 200, False),
              "bus_watchdog_raw": (98, 1, 0, False),
              "position_p_gain_raw": (84, 2, 1500, False),
              "position_i_gain_raw": (82, 2, 0, False),
              "position_d_gain_raw": (80, 2, 600, False)}
    for address, size, value, signed in fields.values():
        raw[address:address + size] = value.to_bytes(size, "little", signed=signed)
    for model in (1060, 1200):
        row = module.decode_registers(model, raw)
        expected = {key: item[2] for key, item in fields.items()}
        if model == 1060:  # XL430 has no current-control registers at these addresses.
            expected.update(goal_current_raw=None, current_limit_raw=None)
        assert {key: row[key] for key in fields} == expected


@pytest.mark.parametrize("model", [1060, 1200])
@pytest.mark.parametrize("wire,expected", [(0, 0), (127, 127), (255, -1)])
def test_bus_watchdog_preserves_documented_error_sentinel(model, wire, expected):
    raw = bytearray(147)
    raw[98] = wire
    assert probe().decode_registers(model, raw)["bus_watchdog_raw"] == expected


@pytest.mark.parametrize("status,owners,allowed", [(0, "123", True), (0, "123 456", False),
                                                  (1, "", False), (0, "456", False)])
def test_post_lock_ownership_must_be_exclusively_this_process(monkeypatch, status, owners, allowed):
    module = probe()
    monkeypatch.setattr(module.subprocess, "run", lambda *a, **k:
                        SimpleNamespace(returncode=status, stdout=owners))
    if allowed:
        module.check_exclusive_owner("/dev/test", 123)
    else:
        with pytest.raises(RuntimeError):
            module.check_exclusive_owner("/dev/test", 123)
