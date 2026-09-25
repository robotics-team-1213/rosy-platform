"""S3: server-side freshness judgment. Client must not invent thresholds."""

from core_common.protocol.evidence import (
    STALE_POSE_S,
    STALE_VELOCITY_S,
    EvidenceState,
    judge,
)
from core_features.state.manager import StateManager


class Clock:
    def __init__(self, t: float = 1_000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


def test_state_manager_reads_overlay_thresholds():
    clock = Clock(1_000.0)
    state = StateManager("rosy_01", clock=clock, stale_after_s={"pose": 0.1})
    state.set_pose(0.0, 0.0, 0.0)
    clock.t += 0.2
    snap = state.snapshot()
    assert snap.evidence["pose"].evidence is EvidenceState.DELAYED
    assert snap.evidence["pose"].stale_after_s == 0.1


def test_no_source_is_unavailable():
    record = judge(has_source=False, received_at=None, now=10.0, stale_after_s=0.5)
    assert record.evidence is EvidenceState.UNAVAILABLE
    assert record.received_at is None
    assert record.stale_after_s == 0.5


def test_source_never_received_is_disconnected():
    record = judge(has_source=True, received_at=None, now=10.0, stale_after_s=0.5)
    assert record.evidence is EvidenceState.DISCONNECTED


def test_sample_within_threshold_is_fresh():
    record = judge(has_source=True, received_at=9.8, now=10.0, stale_after_s=0.5)
    assert record.evidence is EvidenceState.FRESH
    assert record.received_at is not None


def test_sample_older_than_threshold_is_delayed():
    record = judge(has_source=True, received_at=9.0, now=10.0, stale_after_s=0.5)
    assert record.evidence is EvidenceState.DELAYED


def test_snapshot_starts_disconnected_then_fresh_then_delayed():
    clock = Clock(1_000.0)
    state = StateManager("rosy_01", clock=clock)
    first = state.snapshot()
    assert first.evidence["pose"].evidence is EvidenceState.DISCONNECTED
    assert first.evidence["velocity"].stale_after_s == STALE_VELOCITY_S
    assert first.evidence["pose"].stale_after_s == STALE_POSE_S

    state.set_pose(1.0, 2.0, 0.0)
    state.set_velocity(0.1, 0.0)
    fresh = state.snapshot()
    assert fresh.evidence["pose"].evidence is EvidenceState.FRESH
    assert fresh.evidence["velocity"].evidence is EvidenceState.FRESH

    clock.t += 0.6
    mixed = state.snapshot()
    assert mixed.evidence["velocity"].evidence is EvidenceState.DELAYED
    assert mixed.evidence["pose"].evidence is EvidenceState.FRESH

    clock.t += 2.0
    late = state.snapshot()
    assert late.evidence["pose"].evidence is EvidenceState.DELAYED


def test_snapshot_json_exposes_server_strings_and_thresholds():
    clock = Clock(1_000.0)
    state = StateManager("rosy_01", clock=clock)
    state.set_pose(0.0, 0.0, 0.0)
    payload = state.snapshot().model_dump(mode="json")
    pose = payload["evidence"]["pose"]
    assert pose["evidence"] == "fresh"
    assert pose["stale_after_s"] == STALE_POSE_S
    assert pose["received_at"]
