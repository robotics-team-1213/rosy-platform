"""D-395 Phase 2 lane B: snapshot, routes, capability and gating (contract §1, §2).

Contract: docs/plans/2026-10-01-d395-phase2-interfaces.md. The bridge is not
here (rclpy); `services.localization` is fed the same JSON the bridge relays,
and its decision/suspect publishers are captured.
"""

from __future__ import annotations

import json

import pytest

VIEWER = {"Authorization": "Bearer rosy-dev-viewer"}
OPERATOR = {"Authorization": "Bearer rosy-dev-operator"}
ADMIN = {"Authorization": "Bearer rosy-dev-admin"}


class _Clock:
    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def _state(state="UNKNOWN", frame="map", request_id=None) -> str:
    return json.dumps({"status": {"state": state, "pose_frame": frame, "request_id": request_id},
                       "pose": None, "stamp": 1.0})


def _report(request_id="req-1") -> str:
    return json.dumps({"request_id": request_id, "stamp": 5.0,
                       "candidates": [{"x": 1.0, "y": 2.0, "yaw": 0.0, "scan_fit": 0.9}]})


@pytest.fixture
def core(core_client):
    client, services = core_client()
    loc = services.localization
    sent = {"decision": [], "suspect": []}
    loc.publish_decision = sent["decision"].append
    loc.publish_suspect = sent["suspect"].append
    loc.clock = lambda: 777.25
    services.sent = sent
    return client, services


def _types(services, prefix="localization."):
    return [event for event in services.events.history() if event.type.startswith(prefix)]


# --- P2-1: snapshot -------------------------------------------------------------


def test_snapshot_localization_is_null_before_any_state(core):
    client, _ = core
    body = client.get("/api/v1/robot/state", headers=VIEWER).json()
    assert "localization" in body and body["localization"] is None


def test_snapshot_carries_the_robot_state(core):
    client, services = core
    services.localization.on_state(_state("CANDIDATES", request_id="req-1"))
    loc = client.get("/api/v1/robot/state", headers=VIEWER).json()["localization"]
    assert loc["state"] == "CANDIDATES" and loc["pose_frame"] == "map"
    assert loc["request_id"] == "req-1"


def test_snapshot_frame_is_odom_while_core_uses_odom(core):
    client, services = core
    services.localization.on_state(_state("LOCALIZED", frame="map"))
    services.localization.tick(odom_owns_pose=True)
    loc = client.get("/api/v1/robot/state", headers=VIEWER).json()["localization"]
    assert loc["pose_frame"] == "odom"


def test_snapshot_goes_unknown_when_the_state_topic_stops(core):
    client, services = core
    clock = _Clock()
    services.localization._monotonic = clock
    services.localization.on_state(_state("LOCALIZED"))
    clock.now += 3.5
    loc = client.get("/api/v1/robot/state", headers=VIEWER).json()["localization"]
    assert loc["state"] == "UNKNOWN" and loc["reason"] == "state_stale"


def test_localized_cancels_navigation_through_the_manager(core):
    _client, services = core
    cancels = []
    services.nav.cancel = lambda source="api", **_: cancels.append(source)
    services.localization.on_state(_state("CANDIDATES", request_id="req-1"))
    services.localization.on_state(_state("LOCALIZED"))
    assert cancels == ["localization"]
    assert [e.data["state"] for e in _types(services, "localization.state")] == [
        "CANDIDATES", "LOCALIZED"]
