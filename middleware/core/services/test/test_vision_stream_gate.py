"""D-368 driver stream gate, library tier: last-wins driver, single slot, eviction."""

import pytest

from core_features.vision.stream import DriverStreamGate, StreamRefused


def test_open_requires_an_accepted_teleop_first():
    gate = DriverStreamGate()
    with pytest.raises(StreamRefused) as refused:
        gate.open("tok-a")
    assert refused.value.code == "CAMERA_STREAM_NOT_DRIVER"
    assert refused.value.status == 409


def test_accepted_teleop_grants_the_single_slot():
    gate = DriverStreamGate()
    gate.on_teleop("tok-a")
    gate.open("tok-a")
    with pytest.raises(StreamRefused) as refused:
        gate.open("tok-a")   # even the driver: one stream at a time
    assert refused.value.code == "CAMERA_STREAM_BUSY"
    assert gate.stream_owner() == "tok-a"
    gate.close("tok-a")
    assert gate.stream_owner() is None
    gate.open("tok-a")       # reusable after close
    gate.close("tok-a")


def test_another_token_teleop_evicts_the_open_stream():
    gate = DriverStreamGate()
    gate.on_teleop("tok-a")
    gate.open("tok-a")
    gate.on_teleop("tok-b")  # seat change: last-wins, no lease timer
    assert gate.driver() == "tok-b"
    assert gate.stream_owner() is None       # slot freed for the new driver
    with pytest.raises(StreamRefused) as refused:
        gate.open("tok-a")
    assert refused.value.code == "CAMERA_STREAM_NOT_DRIVER"
    gate.open("tok-b")
    gate.close("tok-b")


def test_close_is_idempotent_and_only_the_holder_frees():
    gate = DriverStreamGate()
    gate.on_teleop("tok-a")
    gate.open("tok-a")
    gate.close("tok-b")                       # not the holder: no effect
    assert gate.stream_owner() == "tok-a"
    gate.close("tok-a")
    gate.close("tok-a")                       # double close: fine
    assert gate.stream_owner() is None


def test_empty_token_is_ignored_and_snapshot_has_no_secrets():
    gate = DriverStreamGate()
    gate.on_teleop("   ")
    assert gate.driver() is None
    gate.on_teleop("tok-a")
    snapshot = gate.snapshot()
    assert snapshot == {"driver": "tok-a", "driver_at": snapshot["driver_at"],
                        "stream_open": False}
    assert "token" not in str(snapshot)
