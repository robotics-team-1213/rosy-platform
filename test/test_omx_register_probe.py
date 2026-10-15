"""Commissioning reads cannot silently become motor writes."""
import importlib.util
from pathlib import Path

import pytest


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
