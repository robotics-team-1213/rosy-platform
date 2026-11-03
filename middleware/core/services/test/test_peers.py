"""Peer pose sharing: the peers table and the beacon sender (design §4.1/§4.3).

Pure: clock and transport are injected, no ROS, no network.
Design: docs/plans/2026-11-04-peer-pose-sharing-design.md.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from core_common.protocol.schemas import PeerBeacon, Pose
from core_features.peers.beacon import BeaconSender
from core_features.peers.manager import PeersManager


def beacon(seq, *, robot_id="rosy_41", boot_id="b1", x=1.0, state="LOCALIZED",
           map_id="site-v1"):
    return PeerBeacon(robot_id=robot_id, boot_id=boot_id, seq=seq, map_id=map_id,
                      pose=Pose(x=x, y=2.0, yaw=0.5) if state == "LOCALIZED" else None,
                      localization_state=state, stamp=0.0)


class FakeClock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def test_table_keeps_latest_and_ages_rows_out():
    clock = FakeClock()
    peers = PeersManager(now=clock, max_age_s=5.0)
    assert peers.observe(beacon(1)) is True
    rows = peers.snapshot()
    assert [row.robot_id for row in rows] == ["rosy_41"]
    assert rows[0].pose is not None and rows[0].age_s == 0.0
    clock.now += 5.5
    assert peers.snapshot() == []
    # evicted for age: a stale seq after eviction is accepted again
    assert peers.observe(beacon(1)) is True


def test_stale_seq_is_a_noop_but_a_new_boot_resets_it():
    peers = PeersManager(now=FakeClock())
    assert peers.observe(beacon(5)) is True
    assert peers.observe(beacon(5)) is False      # duplicate
    assert peers.observe(beacon(4)) is False      # stale
    assert peers.observe(beacon(6)) is True
    assert peers.observe(beacon(1, boot_id="b2")) is True  # rebooted peer


def test_nonfinite_pose_is_dropped_but_the_row_stays():
    peers = PeersManager(now=FakeClock())
    bad = PeerBeacon(robot_id="rosy_41", boot_id="b1", seq=1, map_id="m",
                     pose=Pose(x=float("inf"), y=0.0, yaw=0.0),
                     localization_state="LOCALIZED", stamp=0.0)
    assert peers.observe(bad) is True
    assert peers.snapshot()[0].pose is None


def snapshot_stub(state="LOCALIZED", map_id="site-v1"):
    return SimpleNamespace(map_id=map_id, pose=Pose(x=0.1, y=0.2, yaw=0.3),
                           localization=SimpleNamespace(state=state))


def test_beacon_hides_the_pose_unless_localized():
    sent = []
    sender = BeaconSender(robot_id="rosy_42", boot_id="b", snapshot=lambda: snapshot_stub(),
                          peers_cfg={"rate_hz": 1.0,
                                     "hosts": [{"host": "peer.local", "token": "t"}]},
                          poster=lambda url, token, payload, ca_file=None:
                          sent.append((url, token, payload)) or True,
                          clock=FakeClock())
    sender.tick()
    url, token, payload = sent[0]
    assert url == "https://peer.local:8080/api/v1/peers/beacon" and token == "t"
    assert payload["pose"] is not None and payload["seq"] == 1
    assert payload["robot_id"] == "rosy_42" and payload["map_id"] == "site-v1"
    sender.tick()
    assert sent[1][2]["seq"] == 2

    hiding = BeaconSender(robot_id="rosy_42", boot_id="b",
                          snapshot=lambda: snapshot_stub(state="UNKNOWN"),
                          peers_cfg={"hosts": [{"host": "p", "token": "t"}]},
                          poster=lambda *a, **k: True, clock=FakeClock())
    body = hiding.beacon().model_dump()
    assert body["pose"] is None and body["localization_state"] == "UNKNOWN"


def test_config_bounds_and_host_validation():
    with pytest.raises(ValueError):
        BeaconSender(robot_id="r", boot_id="b", snapshot=lambda: None,
                     peers_cfg={"rate_hz": 9.0, "hosts": [{"host": "p", "token": "t"}]},
                     poster=lambda *a, **k: True)
    with pytest.raises(ValueError):
        BeaconSender(robot_id="r", boot_id="b", snapshot=lambda: None,
                     peers_cfg={"hosts": [{"host": "p"}]},
                     poster=lambda *a, **k: True)
    idle = BeaconSender(robot_id="r", boot_id="b", snapshot=lambda: None,
                        peers_cfg={}, poster=lambda *a, **k: True)
    assert idle.hosts == [] and idle.tick() == 0


def test_a_failing_peer_never_raises():
    def poster(url, token, payload, ca_file=None):
        if "bad" in url:
            raise OSError("down")
        return True

    sender = BeaconSender(robot_id="r", boot_id="b", snapshot=lambda: snapshot_stub(),
                          peers_cfg={"hosts": [{"host": "good", "token": "t"},
                                               {"host": "bad", "token": "t"}]},
                          poster=poster, clock=FakeClock())
    assert sender.tick() == 1
