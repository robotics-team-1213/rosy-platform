"""D-596 2: automatic LED identify requests — trigger rules, rate limit, E-stop, parallel colours."""

import asyncio

from core_common.protocol.overhead_detections import OverheadDetection, OverheadDetectionsPayload
from fleet.server.identity import IdentityConfig, IdentityError, IdentityService
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


class _MapPose:
    def __init__(self, x, y, state="DEGRADED", dead_reckon_m=0.0):
        self.x, self.y, self.state, self.dead_reckon_m = x, y, state, dead_reckon_m


def _scored(*blobs):
    return [{"x": x, "y": y, "score": score, "marker_id": None} for x, y, score in blobs]


def test_the_expected_place_follows_the_robot_off_its_last_marker_place():
    """Site 2026-10-10 11:08: rosy_41's last marker place (0.38, -0.47) held a ghost blob (score 0.716,
    background learned with the robot there) while Fleet's map pose had bridged the robot by odom to
    (0.962, -0.011). The ghost must not be the robot; the robot's own blob near the bridge is."""
    triggers = AutoTriggers(CONFIG)
    _due(triggers, 0.0, _snap([_marker("rosy_41", 0.38, -0.47)]))
    lost = {"robot_id": "rosy_41", "status": "NO_POSE"}
    bridged = {"rosy_41": _MapPose(0.962, -0.011, dead_reckon_m=1.2)}
    ghost_and_sliver = {"robots": [lost], "unknown": _scored((0.397, -0.500, 0.716), (0.9719, -0.2046, 0.054))}
    due = triggers.due(10.0, ghost_and_sliver, {"rosy_40": SAFE, "rosy_41": SAFE}, watched=WATCHED,
                       skip=set(), last_reason={}, map_poses=bridged)
    assert due == []                                  # ghost 0.75 m off the bridge, sliver below MIN_BLOB_SCORE
    robot = {"robots": [lost], "unknown": _scored((0.397, -0.500, 0.716), (0.95, -0.12, 0.8))}
    due = triggers.due(14.0, robot, {"rosy_40": SAFE, "rosy_41": SAFE}, watched=WATCHED,
                       skip=set(), last_reason={}, map_poses=bridged)
    assert due == [("rosy_41", "marker_missing")]
    x, y, radius = triggers.expected("rosy_41", bridged["rosy_41"])
    assert (x, y) == (0.962, -0.011) and radius == 0.5 + 0.15 * 1.2
    # No map pose (UNKNOWN after an odom reset): the last marker place, as before.
    assert triggers.expected("rosy_41", _MapPose(None, None, "UNKNOWN")) == (0.38, -0.47, 0.5)


def test_a_robot_in_caution_is_not_asked():
    """rosy-face keeps the caution lamp (line-follow HOLD, dock failed) and refuses the blink (D-472 5)."""
    triggers = AutoTriggers(CONFIG)
    _due(triggers, 0.0, _snap([_marker("rosy_41", 1.0, 1.0)]))
    lost = _snap([{"robot_id": "rosy_41", "status": "NO_POSE"}], [(1.1, 1.0)])
    hold = {**SAFE, "line_follow": {"mode": "CAMERA_LINE", "state": "HOLD"}}
    assert _due(triggers, 10.0, lost, states={"rosy_40": SAFE, "rosy_41": hold}) == []
    off = {**SAFE, "line_follow": {"mode": "OFF", "state": "HOLD"}}
    assert _due(triggers, 14.0, lost, states={"rosy_40": SAFE, "rosy_41": off}) == [("rosy_41", "marker_missing")]


def test_an_operator_request_to_a_robot_in_caution_is_refused_with_its_reason():
    clock, _source, identity, robots, frame = _site()
    frame((1.0, 1.0, None))
    identity.tracking.observe_states([{"robot_id": "rosy_41", "online": True, "state": {
        **SAFE, "line_follow": {"mode": "CAMERA_LINE", "state": "HOLD"}}}], now=clock.now)
    try:
        asyncio.run(identity.request("rosy_41"))
    except IdentityError as exc:
        assert (exc.status_code, exc.code) == (409, "IDENTIFY_ROBOT_CAUTION")
    else:
        raise AssertionError("a robot in caution was asked to blink")
    assert robots["rosy_41"].calls == []


def test_a_verdict_is_checked_against_the_bridged_place_not_the_old_marker_place():
    clock, source, identity, robots, frame = _site()
    frame((0.38, -0.47, 41))
    identity.triggers.due(clock.now, identity.tracking.snapshot(), {}, watched={"rosy_41"},
                          skip=set(), last_reason={})          # last marker place (0.38, -0.47)
    identity.map_pose = lambda rid: _MapPose(0.962, -0.011, dead_reckon_m=1.2) if rid == "rosy_41" else None
    started = asyncio.run(identity.request("rosy_41"))
    clock.now += 6.2
    frame((0.397, -0.500, None), (0.95, -0.05, None))           # ghost at the old place, robot at the bridge
    ghost = _verdict(identity, source, started["request_id"], 0.397, -0.500, clock.now - 1.0)
    assert (ghost["state"], ghost["reason"]) == ("UNKNOWN", "far_from_robot")
    real = _verdict(identity, source, started["request_id"], 0.95, -0.05, clock.now - 1.0)
    assert real["state"] == "CONFIRMED"
