"""Peer pose sharing API: GET /api/v1/peers, POST /api/v1/peers/beacon (design §4.2/§4.3).

The beacon route is the trust boundary (PEER_SHARE grant); the state snapshot
carries the peers rows only when the feature is wired on.
"""
from __future__ import annotations

import pytest

VIEWER = {"Authorization": "Bearer rosy-dev-viewer"}
OPERATOR = {"Authorization": "Bearer rosy-dev-operator"}


@pytest.fixture
def core(core_client):
    return core_client()


def _beacon(seq, *, boot="b1"):
    return {"schema_version": 1, "robot_id": "rosy_41", "boot_id": boot, "seq": seq,
            "map_id": "site-v1", "pose": {"x": 1.0, "y": 2.0, "yaw": 0.5},
            "localization_state": "LOCALIZED", "stamp": 3.0}


def test_peers_roundtrip_and_state_snapshot(core):
    client, services = core
    assert client.get("/api/v1/peers", headers=VIEWER).json() == {"peers": []}
    # default config keeps the feature off: the snapshot field stays additive-null
    assert client.get("/api/v1/robot/state", headers=VIEWER).json()["peers"] is None

    services.state.set_peers_provider(services.peers.snapshot)
    accepted = client.post("/api/v1/peers/beacon", headers=OPERATOR, json=_beacon(1))
    assert accepted.status_code == 202 and accepted.json() == {"accepted": True, "updated": True}
    stale = client.post("/api/v1/peers/beacon", headers=OPERATOR, json=_beacon(1))
    assert stale.json() == {"accepted": True, "updated": False}

    rows = client.get("/api/v1/peers", headers=VIEWER).json()["peers"]
    assert [row["robot_id"] for row in rows] == ["rosy_41"]
    assert rows[0]["pose"]["x"] == 1.0

    state = client.get("/api/v1/robot/state", headers=VIEWER).json()
    assert [row["robot_id"] for row in state["peers"]] == ["rosy_41"]


def test_beacon_needs_the_peer_share_grant(core):
    client, _ = core
    refused = client.post("/api/v1/peers/beacon", headers=VIEWER, json=_beacon(1))
    assert refused.status_code == 403
    assert refused.json()["error"]["detail"] == {"capability": "PEER_SHARE"}
    malformed = client.post("/api/v1/peers/beacon", headers=OPERATOR,
                            json={"robot_id": "x"})
    assert malformed.status_code == 422
