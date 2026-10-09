"""D-596 2: automatic LED identify requests — trigger rules, rate limit, E-stop, parallel colours."""

import asyncio

from core_common.protocol.overhead_detections import OverheadDetection, OverheadDetectionsPayload
from fleet.server.identity import IdentityConfig, IdentityService
from fleet.server.identity_triggers import AutoTriggers
from fleet.server.sightings import SightingSource
from fleet.server.tracking import TrackingService
from fleet.server.tracking_calibration import TrackingCalibrationStore

CONFIG = IdentityConfig()
WATCHED = {"rosy_40", "rosy_41"}
SAFE = {"safety": {"estop": False}}


def _snap(robots=(), unknown=()):
    return {"robots": list(robots), "unknown": [{"x": x, "y": y, "marker_id": None} for x, y in unknown]}


def _marker(rid, x, y):
    return {"robot_id": rid, "status": "MARKER", "camera": {"x": x, "y": y}}


def _due(triggers, now, snapshot, states=None, skip=(), last=None):
    states = {rid: SAFE for rid in WATCHED} if states is None else states
    return triggers.due(now, snapshot, states, watched=WATCHED, skip=set(skip), last_reason=last or {})


def test_marker_missing_with_a_blob_near_its_last_place_asks_after_the_delay():
    triggers = AutoTriggers(CONFIG)
    assert _due(triggers, 0.0, _snap([_marker("rosy_40", 1.0, 1.0)])) == []
    lost = {"robot_id": "rosy_40", "status": "NO_POSE"}
    assert _due(triggers, 1.0, _snap([lost], [(1.2, 1.0)])) == []         # 0 s missing
    assert _due(triggers, 3.5, _snap([lost], [(1.2, 1.0)])) == []         # 2.5 s < 3 s
    assert _due(triggers, 4.1, _snap([lost], [(1.2, 1.0)])) == [("rosy_40", "marker_missing")]
    assert _due(triggers, 4.1, _snap([lost], [(2.0, 1.0)])) == []         # blob too far (> 0.5 m)
    assert _due(triggers, 4.1, _snap([lost], [(1.2, 1.0)]), skip={"rosy_40"}) == []


def test_never_during_an_estop_or_without_a_fresh_state():
    triggers = AutoTriggers(CONFIG)
    _due(triggers, 0.0, _snap([_marker("rosy_40", 1.0, 1.0)]))
    lost = _snap([{"robot_id": "rosy_40", "status": "NO_POSE"}], [(1.0, 1.0)])
    for state in ({"safety": {"estop": True}}, {"safety": {}}, None):
        assert _due(triggers, 10.0, lost, states={"rosy_40": state, "rosy_41": SAFE}) == []


def test_a_merged_pair_that_splits_again_is_asked():
    triggers = AutoTriggers(CONFIG)
    row = {"robot_id": "rosy_41", "status": "NO_POSE", "pose": {"x": 2.0, "y": 1.0}}
    merged = _snap([row], [(2.0, 1.0), (2.2, 1.0)])                       # 0.2 m < overlap 0.30
    assert _due(triggers, 0.0, merged, last={"rosy_41": "overlap"}) == []
    apart = _snap([row], [(2.0, 1.0), (2.6, 1.0)])
    assert _due(triggers, 1.0, apart, last={"rosy_41": "overlap"}) == [("rosy_41", "split")]
    assert _due(triggers, 1.0, apart, last={"rosy_41": "ttl"}) == []


def test_an_odom_reset_is_asked_once():
    triggers = AutoTriggers(CONFIG)
    at = lambda x: {"rosy_40": {**SAFE, "pose": {"x": x, "y": 0.0}}, "rosy_41": SAFE}
    blob = _snap(unknown=[(3.0, 3.0)])
    assert _due(triggers, 0.0, blob, states=at(1.5)) == []
    assert _due(triggers, 1.0, blob, states=at(0.0)) == [("rosy_40", "odom_reset")]
    triggers.asked("rosy_40")
    assert _due(triggers, 2.0, blob, states=at(0.0)) == []


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class Robot:
    def __init__(self, name, color):
        self.name, self.color, self.calls = name, color, []

    async def identify_lamp(self, color=None):
        self.calls.append(color)
        return {"accepted": True, "request_id": f"{self.name}-{len(self.calls)}", "color": color or self.color}


def test_tick_asks_both_lost_robots_in_parallel_in_two_colours_once_per_interval():
    clock = Clock()
    source = SightingSource(source_id="ceiling_north", token="tok", robot_ids=("rosy_40", "rosy_41"),
                            map_id="map_v2_fleet", calibration_revision="cal-1", corner_marker_ids=None,
                            robot_markers=(("rosy_40", 40), ("rosy_41", 41)))
    tracking = TrackingService([source], calibrations=TrackingCalibrationStore(), clock=clock)
    robots = {"rosy_40": Robot("r40", "amber"), "rosy_41": Robot("r41", "amber")}
    identity = IdentityService(lambda: robots, tracking=tracking, clock=clock)
    tracking.identity = identity
    seq = iter(range(1, 100))

    def frame(*detections):
        tracking.observe_states([{"robot_id": rid, "online": True, "state": dict(SAFE)} for rid in robots],
                                now=clock.now)
        tracking.accept("Bearer tok", OverheadDetectionsPayload(
            source_id="ceiling_north", map_id="map_v2_fleet", calibration_revision="cal-1",
            processor_revision="background-blob/1", captured_at=clock.now, seq=next(seq), status="OK",
            detections=tuple(OverheadDetection(x=x, y=y, footprint_m=0.18, score=0.9, marker_id=m)
                             for x, y, m in detections)))

    frame((1.0, 1.0, 40), (2.0, 1.0, 41))
    assert asyncio.run(identity.tick()) == []
    clock.now += 0.5
    frame((1.1, 1.0, None), (2.1, 1.0, None))                  # both markers hidden, blobs remain
    assert asyncio.run(identity.tick()) == []
    clock.now += 3.0
    frame((1.1, 1.0, None), (2.1, 1.0, None))
    started = asyncio.run(identity.tick())
    assert sorted((s["robot_id"], s["color"], s["trigger"]) for s in started) == [
        ("rosy_40", "amber", "marker_missing"), ("rosy_41", "blue", "marker_missing")]
    assert robots["rosy_40"].calls == [None] and robots["rosy_41"].calls == ["blue"]
    clock.now += 10.0                                          # windows over, nothing confirmed
    frame((1.1, 1.0, None), (2.1, 1.0, None))
    assert asyncio.run(identity.tick()) == []                  # 30 s per robot
    clock.now += 21.0
    frame((1.1, 1.0, None), (2.1, 1.0, None))
    assert len(asyncio.run(identity.tick())) == 2
