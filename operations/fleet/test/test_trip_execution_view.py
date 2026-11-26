"""Fleet command lifecycle and odometry are independently observable for one trip."""

from types import SimpleNamespace

import pytest

from fleet.server.trip_live import trip_execution


def snapshot(linear=0.0, angular=0.0):
    return {"robot_id": "rosy_42", "timestamp": "2026-11-26T03:00:00.100Z",
            "velocity": {"linear": linear, "angular": angular},
            "evidence": {"velocity": {"evidence": "fresh", "sampled_at": "2026-11-26T03:00:00Z",
                                      "stale_after_s": .5}}}


def test_measurement_can_follow_or_predate_an_accepted_command_and_show_motion_under_hold():
    view = {"robot_id": "rosy_42", "state": "running", "detail": {}}
    live = SimpleNamespace(command_ack_mono=8., active_route={"points": 12}, last_goal=None, sent=None)
    def read(state, start=10.):
        return trip_execution(view, live, (state, start, start + .1))

    assert read(snapshot())["phase"] == "stationary"
    assert read(snapshot(angular=.3))["phase"] == "moving"
    assert read(snapshot(.04), start=8.)["phase"] == "dispatched"
    view["detail"]["peer_wait"] = {"command_robot_id": "rosy_42", "stage": "pre_dispatch_peer_check",
                                  "dispatch_attempted": False, "waiting_on": ["rosy_45"]}
    receipt = read(snapshot(.03))
    assert (receipt["phase"], receipt["motion"], receipt["waiting_on"]) == ("pre_dispatch_wait", "moving", ["rosy_45"])
    view["hold"] = {"reason": "fleet_hold", "stop": {"confirmed": False}}
    assert read(snapshot())["reason"] == "fleet_hold_unconfirmed"
    view["state"] = "canceled"
    receipt = read(snapshot())
    assert (receipt["phase"], receipt["motion"], receipt["waiting_on"]) == ("terminal", "unknown", [])


@pytest.mark.parametrize("change", ["negative_age", "stale_source", "stale_cache", "bool", "nan", "other_robot",
                                    "delayed", "no_sample", "legacy_receipt_only", "offline", "short_ttl"])
def test_stale_invalid_and_other_device_velocity_cannot_establish_motion(change):
    row = snapshot(.04)
    ev = row["evidence"]["velocity"]
    start, now = 10., 10.1
    if change == "negative_age":
        ev["sampled_at"] = "2026-11-26T03:00:01Z"
    elif change == "stale_source":
        ev["sampled_at"] = "2026-11-26T02:59:59Z"
    elif change == "stale_cache":
        now = 11.
    elif change == "short_ttl":
        ev["stale_after_s"] = .05
    elif change == "other_robot":
        row["robot_id"] = "rosy_45"
    elif change == "delayed":
        ev["evidence"] = "delayed"
    elif change == "no_sample":
        ev.update(sampled_at=None, received_at=row["timestamp"])
    elif change == "legacy_receipt_only":
        del ev["sampled_at"]
        ev["received_at"] = row["timestamp"]
    elif change == "offline":
        row["online"] = False
    else:
        row["velocity"]["linear"] = True if change == "bool" else float("nan")
    live = SimpleNamespace(command_ack_mono=8., active_route={"points": 12}, last_goal=None, sent=None)
    view = {"robot_id": "rosy_42", "state": "running", "detail": {}}
    result = trip_execution(view, live, (row, start, now))
    assert (result["phase"], result["motion"], result["sampled_at"]) == ("dispatched", "unknown", None)


def test_cache_read_is_bound_to_current_transport_and_generation():
    from fleet.server.map_pose_service import MapPoseService

    transport = object()
    current = {"rosy_42": transport}
    poses = MapPoseService(lambda: current.keys(), client_identity=current.get, clock=lambda: 10.1)
    key = ("rosy_42", True)
    generation = poses._source_scopes.generation("rosy_42")
    row = snapshot()
    def keep(client, scope):
        poses._kept[key] = (10., 2, (row, SimpleNamespace(client=client, generation=scope)))

    keep(transport, generation)
    assert poses.cached_motion_sample("rosy_42") == (row, 10., 10.1)
    keep(object(), generation)
    assert poses.cached_motion_sample("rosy_42") is None
    keep(transport, generation + 1)
    assert poses.cached_motion_sample("rosy_42") is None
    assert poses.cached_motion_sample("rosy_45") is None
