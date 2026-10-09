"""D-472 LED identity orchestration and binding lifetime (addendum 4)."""

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core_common.protocol.overhead_detections import OverheadDetection, OverheadDetectionsPayload
from fleet.server.identity import IdentityConfig, IdentityError, IdentityService
from fleet.server.sightings import SightingSource
from fleet.server.tracking import TrackingService
from fleet.server.tracking_calibration import TrackingCalibrationStore
from fleet.server.tracking_routes import install_tracking_routes

SOURCE = SightingSource(source_id="ceiling_north", token="tok-north", robot_ids=("rosy_26", "rosy_60"),
                        map_id="map_v2_fleet", calibration_revision="cal-1", corner_marker_ids=None)
AUTH = "Bearer tok-north"


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class Robot:
    def __init__(self, color="amber", prefix="req"):
        self.calls, self.color, self.prefix = [], color, prefix

    async def identify_lamp(self, color=None):
        self.calls.append(color)
        return {"accepted": True, "request_id": f"{self.prefix}-{len(self.calls)}", "color": color or self.color}


def _setup(config=IdentityConfig()):
    clock = Clock()
    tracking = TrackingService([SOURCE], calibrations=TrackingCalibrationStore(), clock=clock)
    robots = {"rosy_26": Robot("blue"), "rosy_60": Robot("amber")}
    identity = IdentityService(lambda: robots, tracking=tracking, config=config, clock=clock)
    tracking.identity = identity
    return clock, tracking, identity, robots


def _moving(tracking, clock, *robot_ids, speed=0.1):
    tracking.observe_states([{"robot_id": rid, "online": True,
                              "state": {"velocity": {"linear": speed, "angular": 0.0}}}
                             for rid in robot_ids], now=clock.now)


def _detections(tracking, clock, *points, revision="cal-1", seq=[0]):
    seq[0] += 1
    tracking.accept(AUTH, OverheadDetectionsPayload(
        source_id="ceiling_north", map_id="map_v2_fleet", calibration_revision=revision,
        processor_revision="background-blob/1", captured_at=clock.now, seq=seq[0], status="OK",
        detections=tuple(OverheadDetection(x=x, y=y, footprint_m=0.18, score=0.9) for x, y in points)))


def _verdict(identity, request_id, state="matched", x=1.0, y=1.0, at=1001.0, **extra):
    return identity.accept_verdict(SOURCE, {
        "source_id": "ceiling_north", "map_id": "map_v2_fleet", "request_id": request_id,
        "state": state, "x": x, "y": y, "captured_at": at, "calibration_revision": "cal-1",
        "reason": None if state == "matched" else "multiple", "evidence": {"frames": 18}, **extra})


def _confirm(clock, tracking, identity, robot_id="rosy_60"):
    _moving(tracking, clock, robot_id)
    started = asyncio.run(identity.request(robot_id))
    clock.now += 6.2
    _detections(tracking, clock, (1.05, 1.0), (2.0, 1.0))
    return started, _verdict(identity, started["request_id"])


def test_a_standing_robot_is_asked_in_its_own_colour():
    """D-596 1: no IDENTIFY_NOT_MOVING; the robot is never told to move."""
    clock, tracking, identity, robots = _setup()
    with pytest.raises(IdentityError) as unknown:
        asyncio.run(identity.request("rosy_99"))
    assert unknown.value.status_code == 404
    started = asyncio.run(identity.request("rosy_60"))  # no state at all: parked
    assert robots["rosy_60"].calls == [None]  # the robot picks its configured colour
    assert started["color"] == "amber" and started["not_after"] - clock.now == 6.0
    assert tracking.config_for(AUTH)["identity_challenge"] == {
        "request_id": "req-1", "color": "amber", "not_before": 1000.0, "not_after": 1006.0}
    with pytest.raises(IdentityError) as again:
        asyncio.run(identity.request("rosy_60"))
    assert again.value.code == "IDENTIFY_BUSY" and robots["rosy_60"].calls == [None]
    clock.now += 8.1  # window + grace over without a verdict
    assert tracking.config_for(AUTH)["identity_challenges"] == []


def test_two_robots_on_one_source_blink_in_parallel_in_different_colours():
    """D-596 1: one request per colour per source; the second robot is asked for the free colour."""
    clock, tracking, identity, robots = _setup()
    robots["rosy_26"] = Robot("amber", prefix="b26")  # both amber: Fleet must name blue for the second
    first = asyncio.run(identity.request("rosy_60"))
    second = asyncio.run(identity.request("rosy_26"))
    assert (first["color"], second["color"]) == ("amber", "blue")
    assert robots["rosy_26"].calls == ["blue"]
    challenges = tracking.config_for(AUTH)["identity_challenges"]
    assert [(c["request_id"], c["color"]) for c in challenges] == [("req-1", "amber"), ("b26-1", "blue")]
    assert {p["robot_id"] for p in identity.snapshot()["pendings"]} == {"rosy_60", "rosy_26"}
    clock.now += 6.2
    _detections(tracking, clock, (1.05, 1.0), (2.0, 1.0))
    assert _verdict(identity, "req-1")["robot_id"] == "rosy_60"
    assert identity.confirmed_track_pose("rosy_60")["state"] == "CONFIRMED"
    assert [p["robot_id"] for p in identity.snapshot()["pendings"]] == ["rosy_26"]


def test_a_third_colour_request_on_a_busy_source_is_refused():
    clock, tracking, identity, robots = _setup()
    robots["rosy_70"] = Robot("blue")
    tracking.sources = (SightingSource(source_id="ceiling_north", token="tok-north",
                                       robot_ids=("rosy_26", "rosy_60", "rosy_70"), map_id="map_v2_fleet",
                                       calibration_revision="cal-1", corner_marker_ids=None),)
    asyncio.run(identity.request("rosy_60"))
    with pytest.raises(IdentityError) as same:
        asyncio.run(identity.request("rosy_26", "amber"))
    assert same.value.code == "IDENTIFY_BUSY" and robots["rosy_26"].calls == []
    asyncio.run(identity.request("rosy_26"))
    with pytest.raises(IdentityError) as full:
        asyncio.run(identity.request("rosy_70"))
    assert full.value.code == "IDENTIFY_BUSY" and robots["rosy_70"].calls == []


def test_a_matched_verdict_binds_the_continuing_track_for_d511_only():
    clock, tracking, identity, _ = _setup()
    _started, result = _confirm(clock, tracking, identity)
    assert result["state"] == "CONFIRMED"
    pose = identity.confirmed_track_pose("rosy_60")
    assert (pose["state"], pose["x"], pose["y"], pose["yaw"]) == ("CONFIRMED", 1.05, 1.0, None)
    assert pose["use"] == "observation-only" and pose["calibration_revision"] == "cal-1"
    clock.now += 0.3
    _detections(tracking, clock, (1.15, 1.02), (2.0, 1.0))  # it moved; the other did not
    assert identity.confirmed_track_pose("rosy_60")["x"] == 1.15
    assert identity.confirmed_track_pose("rosy_26")["state"] == "UNKNOWN"
    with pytest.raises(IdentityError) as again:
        asyncio.run(identity.request("rosy_60"))
    assert again.value.code == "IDENTIFY_ALREADY_CONFIRMED"


@pytest.mark.parametrize("step, reason", [
    (lambda c, t: _detections(t, c, (1.10, 1.0), (1.30, 1.0)), "overlap"),
    (lambda c, t: (setattr(t, "_revisions", lambda _s: {"cal-1", "cal-2"}),  # a new approved fit
                   _detections(t, c, (1.10, 1.0), revision="cal-2")), "calibration_changed"),
    (lambda c, t: setattr(c, "now", c.now + 1.5), "track_lost"),             # no frame continues it
    (lambda c, t: _detections(t, c, (1.80, 1.0)), None),                     # jumped: not continued
])
def test_the_binding_returns_to_unknown(step, reason):
    clock, tracking, identity, _ = _setup()
    _confirm(clock, tracking, identity)
    clock.now += 0.3
    step(clock, tracking)
    if reason is None:  # a frame without a continuation is a miss; track_lost_s later it is lost
        clock.now += 1.1
        reason = "track_lost"
    pose = identity.confirmed_track_pose("rosy_60")
    assert (pose["state"], pose["reason"], pose["x"]) == ("UNKNOWN", reason, None)


def test_identity_ttl_expires_a_followed_track():
    clock, tracking, identity, _ = _setup(IdentityConfig(identity_ttl_s=2.0))
    _confirm(clock, tracking, identity)
    for _ in range(8):
        clock.now += 0.3
        _detections(tracking, clock, (1.05, 1.0))
    assert identity.confirmed_track_pose("rosy_60")["reason"] == "ttl"


def test_verdicts_that_do_not_fit_bind_nothing():
    clock, tracking, identity, _ = _setup()
    _moving(tracking, clock, "rosy_60")
    started = asyncio.run(identity.request("rosy_60"))
    clock.now += 6.2
    _detections(tracking, clock, (1.05, 1.0))
    with pytest.raises(IdentityError) as wrong:
        _verdict(identity, "req-other")
    assert wrong.value.code == "IDENTIFY_NOT_PENDING"
    with pytest.raises(IdentityError):
        _verdict(identity, started["request_id"], at=990.0)  # outside the window
    assert _verdict(identity, started["request_id"], state="ambiguous")["state"] == "UNKNOWN"
    assert _verdict(identity, started["request_id"], x=3.0)["reason"] == "track_lost"
    assert identity.confirmed_track_pose("rosy_60")["state"] == "UNKNOWN"


def test_window_is_capped_at_six_seconds_and_auto_is_on_by_default():
    with pytest.raises(ValueError):
        IdentityConfig(window_s=7.0)
    with pytest.raises(ValueError):
        IdentityConfig.from_mapping({"window": 3})
    assert IdentityConfig().auto_request is True and IdentityConfig().auto_min_interval_s == 30.0
    clock, tracking, identity, robots = _setup(IdentityConfig(auto_request=False))
    _moving(tracking, clock, "rosy_26")
    assert asyncio.run(identity.tick()) == [] and robots["rosy_26"].calls == []
    clock, tracking, identity, robots = _setup()
    _moving(tracking, clock, "rosy_26", "rosy_60")
    assert asyncio.run(identity.tick()) == []  # moving alone is no trigger any more (D-596 2)
    assert robots["rosy_26"].calls == robots["rosy_60"].calls == []


def test_verdict_and_readback_routes():
    clock, tracking, identity, _ = _setup()
    app = FastAPI()
    install_tracking_routes(app, tracking=tracking, require_operator=lambda: None,
                            read_guard=[], operator_guard=[])
    client = TestClient(app)
    _moving(tracking, clock, "rosy_60")
    started = asyncio.run(identity.request("rosy_60"))
    clock.now += 6.2
    _detections(tracking, clock, (1.05, 1.0))
    body = {"source_id": "ceiling_north", "map_id": "map_v2_fleet", "request_id": started["request_id"],
            "processor_revision": "led-identity/1", "state": "matched", "x": 1.0, "y": 1.0,
            "captured_at": 1005.0, "calibration_revision": "cal-1", "evidence": {}}
    assert client.post("/api/fleet/detections/identity", json=body).status_code == 401
    assert client.post("/api/fleet/detections/identity", json={**body, "jpeg": "x"},
                       headers={"Authorization": AUTH}).status_code == 422
    answer = client.post("/api/fleet/detections/identity", json=body, headers={"Authorization": AUTH})
    assert answer.json()["state"] == "CONFIRMED"
    readback = client.get("/api/fleet/tracking/identity").json()
    row = next(r for r in readback["robots"] if r["robot_id"] == "rosy_60")
    assert row["state"] == "CONFIRMED" and readback["use"] == "observation-only"


def test_two_bindings_that_meet_on_one_blob_both_return_to_unknown():
    # Review 2026-10-08: A's blob hidden, B's within track_step_m of A -> A must not take B's blob.
    clock, tracking, identity, _ = _setup()
    _confirm(clock, tracking, identity, "rosy_60")                  # A at (1.05, 1.0)
    _moving(tracking, clock, "rosy_26")
    started = asyncio.run(identity.request("rosy_26"))
    for _ in range(20):                                              # through the 6 s window
        clock.now += 0.31
        _detections(tracking, clock, (1.05, 1.0), (1.40, 1.0))
    assert _verdict(identity, started["request_id"], x=1.40, at=clock.now - 1.0)["state"] == "CONFIRMED"
    assert identity.confirmed_track_pose("rosy_60")["state"] == "CONFIRMED"
    clock.now += 0.3
    _detections(tracking, clock, (1.25, 1.0))                        # A hidden, B moved next to A
    for robot_id in ("rosy_60", "rosy_26"):
        pose = identity.confirmed_track_pose(robot_id)
        assert (pose["state"], pose["reason"]) == ("UNKNOWN", "overlap")


def test_a_future_stamped_track_reports_its_negative_age():
    """Review 2026-10-08: age_s is not clamped at 0, so D-511 can refuse a future stamp like map pose."""
    clock, tracking, identity, _ = _setup()
    _confirm(clock, tracking, identity)
    clock.now -= 0.2                       # the site clock is behind the detection stamp
    assert identity.confirmed_track_pose("rosy_60")["age_s"] == pytest.approx(-0.2)
