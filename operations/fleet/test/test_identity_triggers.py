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

    async def identify_lamp(self, color=None, quiet=False):
        self.calls.append((color, quiet))
        return {"accepted": True, "request_id": f"{self.name}-{len(self.calls)}", "color": color or self.color}


def _site():
    clock = Clock()
    source = SightingSource(source_id="ceiling_north", token="tok", robot_ids=("rosy_40", "rosy_41"),
                            map_id="map_v2_fleet", calibration_revision="cal-1", corner_marker_ids=None,
                            robot_markers=(("rosy_40", 40), ("rosy_41", 41)))
    tracking = TrackingService([source], calibrations=TrackingCalibrationStore(), clock=clock)
    robots = {"rosy_40": Robot("r40", "amber"), "rosy_41": Robot("r41", "amber")}
    identity = IdentityService(lambda: robots, tracking=tracking, clock=clock)
    tracking.identity = identity
    seq = iter(range(1, 1000))

    def frame(*detections):
        tracking.observe_states([{"robot_id": rid, "online": True, "state": dict(SAFE)} for rid in robots],
                                now=clock.now)
        tracking.accept("Bearer tok", OverheadDetectionsPayload(
            source_id="ceiling_north", map_id="map_v2_fleet", calibration_revision="cal-1",
            processor_revision="background-blob/1", captured_at=clock.now, seq=next(seq), status="OK",
            detections=tuple(OverheadDetection(x=x, y=y, footprint_m=0.18, score=0.9, marker_id=m)
                             for x, y, m in detections)))
    return clock, source, identity, robots, frame


def test_tick_asks_lost_robots_silently_in_blue_only_and_backs_off():
    clock, _source, identity, robots, frame = _site()
    hidden = ((1.1, 1.0, None), (2.1, 1.0, None))
    frame((1.0, 1.0, 40), (2.0, 1.0, 41))
    assert asyncio.run(identity.tick()) == []
    clock.now += 0.5
    frame(*hidden)                                             # both markers hidden, blobs remain
    assert asyncio.run(identity.tick()) == []
    asked = {}

    def tick(step):
        clock.now += step
        frame(*hidden)
        for started in asyncio.run(identity.tick()):
            asked.setdefault(started["robot_id"], []).append(round(clock.now - 1000.5, 1))
            assert (started["color"], started["trigger"]) == ("blue", "marker_missing")

    tick(3.0)
    assert asked == {"rosy_40": [3.0]}                         # blue is busy: rosy_41 waits (never amber)
    for _ in range(80):                                        # 800 s later
        tick(10.0)
    assert asked["rosy_41"][0] == 13.0
    # Marker still hidden: 30 s, then 2 min, then every 5 min (D-596 7).
    assert [b - a for a, b in zip(asked["rosy_40"], asked["rosy_40"][1:])][:4] == [30.0, 120.0, 300.0, 300.0]
    assert all(quiet for _color, quiet in robots["rosy_40"].calls)
    clock.now += 0.5
    frame((1.0, 1.0, 40), (2.1, 1.0, None))                    # marker seen again: the backoff restarts
    asyncio.run(identity.tick())
    assert identity.triggers.backoff("rosy_40") == 1


def _verdict(identity, source, request_id, x, y, at):
    return identity.accept_verdict(source, {
        "source_id": "ceiling_north", "map_id": "map_v2_fleet", "request_id": request_id, "state": "matched",
        "x": x, "y": y, "captured_at": at, "calibration_revision": "cal-1", "evidence": {}})


def test_a_caution_lamp_decoy_elsewhere_is_never_named():
    """D-596 7: caution blinks amber 1 s on / 1 s off like the amber identify. Vision may match a robot in
    caution; Fleet names a blob only within auto_near_m of where the asked robot was last seen."""
    clock, source, identity, robots, frame = _site()
    frame((1.0, 1.0, 40))
    identity.triggers.due(clock.now, identity.tracking.snapshot(), {}, watched={"rosy_40", "rosy_41"},
                          skip=set(), last_reason={})          # remembers rosy_40's marker at (1.0, 1.0)
    started = asyncio.run(identity.request("rosy_40", "amber"))
    clock.now += 6.2
    frame((1.1, 1.0, None), (2.5, 1.0, None))                 # asked robot and a caution decoy
    decoy = _verdict(identity, source, started["request_id"], 2.5, 1.0, clock.now - 1.0)
    assert (decoy["state"], decoy["reason"]) == ("UNKNOWN", "far_from_robot")
    real = _verdict(identity, source, started["request_id"], 1.1, 1.0, clock.now - 1.0)
    assert real["state"] == "CONFIRMED"
    # Amber for a robot Fleet never placed: refused (it could be any caution lamp).
    other = asyncio.run(identity.request("rosy_41", "amber"))
    clock.now += 6.2
    frame((1.1, 1.0, None), (2.5, 1.0, None))
    assert _verdict(identity, source, other["request_id"], 2.5, 1.0, clock.now - 1.0)["reason"] == "no_prediction"
