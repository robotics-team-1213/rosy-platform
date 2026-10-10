"""D-511 rev 1/2 + D-430 review: Fleet's lane cue in the CAMERA_LINE keep (IR first, off by default)."""

import math
from dataclasses import replace

import pytest

from core_features.line_follow.manager import (
    LineFollowConfig, LineFollowManager, LineFollowMode, LineObservation)

REV = "a" * 64
WALL = 1_800_000_000.0


class _Events:
    def __init__(self):
        self.seen = []

    def publish(self, name, **kwargs):
        self.seen.append((name, kwargs.get("data")))


class Rig:
    """A CAMERA_LINE manager with a moving clock, odom on CORE's wall clock, camera and IR."""

    def __init__(self, **overrides):
        self.t, self.yaw = 10.0, 0.0
        self.events = _Events()
        config = LineFollowConfig(ir_guard_enabled=True, ir_calibration_revision=REV,
                                  **{"fleet_lane_cue_enabled": True, "obstacle_mode": "path", **overrides})
        self.m = LineFollowManager(self.events, config=config, clock=lambda: self.t)
        self.m._wall = lambda: WALL + self.t
        self.m.set_mode(LineFollowMode.CAMERA_LINE)
        self.feed()

    def feed(self, camera=True, ir_error=None, ground=None):
        t, m = self.t, self.m
        self.fed = t
        stamp = round(t * 1e9)
        m.observe_return_pose(stamp_ns=stamp, source_now_ns=stamp, frame="odom", x=0.0, y=0.0,
                              yaw=self.yaw, received_at=t)
        if camera:
            extra = {} if ground is None else {"ground": ground}
            m.observe(LineObservation(source=LineFollowMode.CAMERA_LINE, stamp=t, visible=True,
                                      error=0.0, confidence=0.9, **extra), received_at=t, source_now=t)
        m.observe(LineObservation(source=LineFollowMode.IR_LINE, stamp=t, visible=ir_error is not None,
                                  error=ir_error, confidence=0.9 if ir_error is not None else 0.0,
                                  ir_calibrated=True, calibration_revision=REV), received_at=t, source_now=t)

    def wait(self, dt, **feed):
        """Time passes with odom (and camera) at 10 Hz, as on the robot; no tick."""
        while dt > 1e-9:
            self.t += min(0.1, dt)
            dt -= 0.1
            self.feed(**feed)

    def step(self, dt=0.1, **feed):
        self.t += dt
        self.feed(**feed)
        return self.m.tick(self.t + 0.01)

    def cue(self, state, seq, epoch="e", **extra):
        body = {"cue_id": f"c{seq}", "fleet_epoch": epoch, "seq": seq, "ttl_s": 1.0, "pose_stamp": WALL + self.fed,
                "state": state, "side": None, "bearing_deg": None, "turn_deg": None, "lane_heading_deg": None,
                "offset_m": None, "edge_id": None, "guide": None, **extra}
        return self.m.set_lane_cue(body, now=self.t)


def test_off_by_default_refuses_the_cue():
    rig = Rig(fleet_lane_cue_enabled=False)
    assert rig.cue("OFF_MAP", 1) == (False, "disabled")


def test_side_needs_two_cues_and_five_centimetres_then_turns_toward_the_centre_without_back_creep():
    rig = Rig()
    rig.cue("ON_LINE", 1, side="left", offset_m=-0.06)
    assert rig.step().angular == pytest.approx(0.0, abs=1e-9)            # one cue: not yet
    rig.cue("ON_LINE", 2, side="left", offset_m=-0.06)
    d = rig.step()
    assert d.angular == pytest.approx(0.5) and d.linear > 0
    assert rig.m.status().reason == "fleet_cue_left"
    rig.cue("ON_LINE", 3, side="left", offset_m=-0.03)                   # inside pose noise
    assert rig.step().angular == pytest.approx(0.0, abs=1e-9)


def test_ir_reading_wins_over_the_cue():
    rig = Rig()
    rig.cue("ON_LINE", 1, side="left", offset_m=-0.06)
    rig.cue("ON_LINE", 2, side="left", offset_m=-0.06)
    assert rig.step(ir_error=-0.9).angular == pytest.approx(-0.5)        # line under the left IR


def _wrong_way(rig, turn=-170.0):
    rig.cue("WRONG_WAY", 1, turn_deg=turn)
    assert rig.step().linear > 0                                        # one cue: debounce, keep drives
    rig.wait(0.5)
    rig.cue("WRONG_WAY", 2, turn_deg=turn)
    return rig.step()


def test_wrong_way_debounces_turns_in_place_on_odom_and_stops_within_ten_degrees():
    rig = Rig()
    d = _wrong_way(rig)
    assert d.linear == 0 and d.angular < 0 and rig.m.status().reason == "fleet_wrong_way_turn"
    for seq in range(3, 100):                                           # odom follows at 0.5 rad/s
        rig.yaw -= 0.05
        rig.cue("WRONG_WAY", seq, turn_deg=-170.0 - math.degrees(rig.yaw))
        d = rig.step()
        if d.linear > 0:
            break
    assert d.linear > 0, rig.m.status().reason                          # done: the keep drives again
    assert -180.0 <= math.degrees(rig.yaw) <= -155.0
    assert any(name == "nav.lane_cue" and data["action"] == "pivot" for name, data in rig.events.seen)


def test_a_pivot_that_odom_does_not_confirm_latches_hold_until_a_normal_cue():
    rig = Rig()
    _wrong_way(rig)
    for seq in range(3, 40):                                            # odom yaw never moves
        rig.cue("WRONG_WAY", seq, turn_deg=-170.0)
        d = rig.step(0.25)
        if rig.m.status().reason == "fleet_turn_unconfirmed":
            break
    assert (d.linear, d.angular) == (0, 0) and rig.m.status().reason == "fleet_turn_unconfirmed"
    rig.wait(3.0)                                                        # Fleet silent: still held
    assert rig.step().linear == 0
    rig.cue("ON_LANE", 100)
    assert rig.step().linear > 0


def test_off_map_latches_past_the_ttl_and_a_stuck_decision_releases_it():
    rig = Rig()
    rig.cue("OFF_MAP", 1)
    assert rig.step().linear == 0 and rig.m.status().reason == "fleet_off_map"
    rig.wait(5.0)
    assert rig.step().linear == 0                                        # fail-closed after expiry
    rig.m.release_lane_cue_latch(principal_ref="op")
    assert rig.step().linear > 0


def test_cue_lost_mid_pivot_latches():
    rig = Rig()
    _wrong_way(rig)
    rig.wait(1.5)                                                        # no new cue: ttl 1 s ran out
    assert rig.step().linear == 0 and rig.m.status().reason == "fleet_cue_lost"


def test_no_pivot_without_a_fresh_camera_or_while_lost():
    rig = Rig()
    rig.cue("WRONG_WAY", 1, turn_deg=-170.0)
    rig.step()
    rig.wait(0.5)
    rig.cue("WRONG_WAY", 2, turn_deg=-170.0)
    d = rig.step(0.4, camera=False)                                     # camera stale (> 0.3 s)
    assert (d.linear, d.angular) == (0, 0) and rig.m.status().reason == "camera_observation_stale"


def test_ordering_epoch_and_pose_age():
    rig = Rig()
    assert rig.cue("ON_LANE", 5)[0]
    rig.wait(3.0)
    rig.feed()
    assert rig.cue("ON_LANE", 4) == (False, "stale")                    # kept across expiry
    assert rig.cue("ON_LANE", 6)[0]
    assert rig.cue("ON_LANE", 1, epoch="other") == (False, "epoch_busy")
    rig.wait(2.0)
    rig.feed()
    assert rig.cue("ON_LANE", 1, epoch="other")[0]                      # the old one expired
    body_old = rig.m.set_lane_cue({"cue_id": "x", "fleet_epoch": "other", "seq": 9, "ttl_s": 1.0,
                                   "pose_stamp": WALL + rig.fed - 2.0, "state": "ON_LANE"}, now=rig.t)
    assert body_old == (False, "pose_stale")


def test_mode_change_drops_cue_and_latch():
    rig = Rig()
    rig.cue("OFF_MAP", 1)
    rig.step()
    rig.m.set_mode(LineFollowMode.CAMERA_LINE)
    assert rig.m.lane_cue_status() is None
    assert rig.step().linear > 0


def test_guide_is_kept_and_shown():
    rig = Rig()
    guide = {"ahead_m": 0.4, "heading_ahead_deg": 12.0, "curvature_1pm": 0.5, "to_end_m": 1.2,
             "next_place_id": "NE_line", "ring": False}
    assert rig.cue("ON_LANE", 1, guide=guide)[0]
    assert rig.m.lane_cue_status()["guide"] == guide
    assert rig.m.status().lane_cue["guide"] == guide


# ---- API ----------------------------------------------------------------------------------------

def _token(svc, name, role, source, label):
    from core_api_web.api.deps import new_token_record, stored_token_entries
    plain = name + "-" + "t" * 24
    svc.config["auth"]["tokens"].extend(stored_token_entries([new_token_record(plain, role, label, source=source)]))
    return {"Authorization": "Bearer " + plain}


def test_api_only_the_fleet_site_token_may_post_and_the_wiring_answers(core_client):
    client, svc = core_client()
    lf = svc.line_follow
    lf._config = replace(lf.config, fleet_lane_cue_enabled=True, obstacle_mode="path")
    body = {"cue_id": "c1", "fleet_epoch": "e", "seq": 1, "ttl_s": 1.0, "pose_stamp": 1.0, "state": "ON_LANE"}
    for headers in ({"Authorization": "Bearer rosy-dev-viewer"}, {"Authorization": "Bearer rosy-dev-operator"},
                    _token(svc, "screen", "operator", "pair-physical", "robot screen login")):
        assert client.post("/api/v1/line-follow/lane-cue", json=body, headers=headers).status_code == 403
    site = _token(svc, "site", "operator", "pair-physical", "site:rosy-site")
    reply = client.post("/api/v1/line-follow/lane-cue", json=body, headers=site)
    assert reply.status_code == 200 and reply.json() == {"accepted": False, "reason": "odom_stale"}


PINKY = dict(body_lidar_x_m=-0.017, body_rear_x_m=-0.076, body_rotation_radius_m=0.08257,
             body_half_width_m=0.05655, body_front_x_m=0.04205, body_ultrasonic_x_m=0.0267,
             cruise_speed=0.04, obstacle_path_horizon_m=0.30,
             obstacle_corridor_half_width_m=0.072, obstacle_release_s=0.0)


def test_the_body_stop_measures_the_pivot_on_its_rotation_circle():
    """D-430 review 2: a point beside the body (inside the rotation circle, off the straight path)
    lets the keep drive straight but holds the cue's turn in place."""
    rig = Rig(**PINKY)
    beside = [(0.0, 0.075 + 0.002 * k) for k in range(3)]       # LiDAR frame, left of the body

    def step(dt=0.1):
        rig.t += dt
        rig.feed()
        rig.m.observe_body_points(beside, range_min=0.05, received_at=rig.t)
        rig.m.observe_scan_points(beside, received_at=rig.t)
        return rig.m.tick(rig.t + 0.01)

    assert step().linear > 0                                        # straight: nothing in the path
    rig.cue("WRONG_WAY", 1, turn_deg=170.0)
    step()
    rig.wait(0.5)
    rig.cue("WRONG_WAY", 2, turn_deg=170.0)
    d = step()
    assert (d.linear, d.angular) == (0, 0) and rig.m.status().reason == "obstacle_ahead"


def test_off_map_is_taken_with_an_old_pose_stamp_and_latches():
    """Re-review 1: Fleet sends OFF_MAP after >= 3 s without a sighting, with an old stamp."""
    rig = Rig()
    body = {"cue_id": "c1", "fleet_epoch": "e", "seq": 1, "ttl_s": 1.0, "pose_stamp": WALL + rig.fed - 5.0,
            "state": "OFF_MAP"}
    assert rig.m.set_lane_cue(body, now=rig.t) == (True, None)
    assert rig.step().linear == 0 and rig.m.status().reason == "fleet_off_map"


@pytest.mark.parametrize("signs", [(179.0, -179.0, 179.0), (-178.0, 178.0, -179.0)])
def test_a_turn_near_180_keeps_its_sign_and_ends_on_progress(signs):
    """Re-review 3: Fleet's sign flips near 180 deg; the streak keeps the first sign, the pivot
    ends after ~180 deg of odom progress, not at once on a wrapped angle."""
    rig = Rig()
    rig.cue("WRONG_WAY", 1, turn_deg=signs[0])
    rig.step()
    rig.wait(0.5)
    rig.cue("WRONG_WAY", 2, turn_deg=signs[1])
    d = rig.step()
    first = 1 if signs[0] > 0 else -1
    assert d.linear == 0 and d.angular * first > 0
    for seq in range(3, 100):
        rig.yaw = math.remainder(rig.yaw + first * 0.05, 2 * math.pi)
        rig.cue("WRONG_WAY", seq, turn_deg=signs[seq % 3])
        d = rig.step()
        if d.linear > 0:
            break
    assert d.linear > 0 and (seq - 2) * 0.05 >= math.radians(165), (seq, rig.m.status().reason)


def test_pivot_is_zeroed_by_the_authority_and_its_deadline_latches_without_restart():
    rig = Rig(authority_required=True)
    rig.cue("WRONG_WAY", 1, turn_deg=-170.0)
    rig.step()
    rig.wait(0.5)
    rig.cue("WRONG_WAY", 2, turn_deg=-170.0)
    d = rig.step()
    assert (d.linear, d.angular) == (0, 0) and rig.m._pivot is not None   # D-517 authority: no GO
    for seq in range(3, 60):
        rig.cue("WRONG_WAY", seq, turn_deg=-170.0)
        rig.step(0.25)
        if rig.m._cue_latch:
            break
    assert rig.m._cue_latch == "fleet_turn_unconfirmed"
    rig.m._config = replace(rig.m.config, authority_required=False)  # the gate releases
    rig.cue("WRONG_WAY", 99, turn_deg=-170.0)
    assert rig.step().angular == 0 and rig.m.status().reason == "fleet_turn_unconfirmed"


@pytest.mark.parametrize("owner", ["junction_armed", "junction_aborted", "crosswalk_zone"])
def test_no_pivot_start_while_a_junction_or_crosswalk_owns_the_heading(owner):
    rig = Rig()
    if owner == "crosswalk_zone":
        rig.m._xwalk._zone = object()
    else:
        rig.m._junction = {"state": owner.split("_")[1], "action": "left", "place_id": "P"}
    rig.cue("WRONG_WAY", 1, turn_deg=-170.0)
    rig.step()
    rig.wait(0.5)
    rig.cue("WRONG_WAY", 2, turn_deg=-170.0)
    rig.step()
    assert rig.m._pivot is None and rig.m.status().reason != "fleet_wrong_way_turn"


def test_no_pivot_while_lost_or_on_nominal_ground():
    rig = Rig()
    rig.m._lost_latched = True
    rig.cue("WRONG_WAY", 1, turn_deg=-170.0)
    rig.step()
    rig.wait(0.5)
    rig.cue("WRONG_WAY", 2, turn_deg=-170.0)
    d = rig.step(ir_error=-0.9)                                      # IR sees a line: LOST stays latched
    assert d.angular == 0 and rig.m.status().state == "LOST"
    rig = Rig()
    rig.cue("WRONG_WAY", 1, turn_deg=-170.0)
    rig.step(ground="NOMINAL")
    rig.wait(0.5)
    rig.cue("WRONG_WAY", 2, turn_deg=-170.0)
    d = rig.step(ground="NOMINAL")
    assert d.angular == 0 and rig.m.status().reason == "nominal_ground_requires_driver"


def test_enabling_needs_the_path_obstacle_mode():
    with pytest.raises(ValueError, match="obstacle_mode path"):
        LineFollowConfig(fleet_lane_cue_enabled=True, obstacle_mode="sector")
