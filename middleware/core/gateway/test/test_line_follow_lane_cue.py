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
                                  **{"fleet_lane_cue_enabled": True, **overrides})
        self.m = LineFollowManager(self.events, config=config, clock=lambda: self.t)
        self.m._wall = lambda: WALL + self.t
        self.m.set_mode(LineFollowMode.CAMERA_LINE)
        self.feed()

    def feed(self, camera=True, ir_error=None):
        t, m = self.t, self.m
        stamp = round(t * 1e9)
        m.observe_return_pose(stamp_ns=stamp, source_now_ns=stamp, frame="odom", x=0.0, y=0.0,
                              yaw=self.yaw, received_at=t)
        if camera:
            m.observe(LineObservation(source=LineFollowMode.CAMERA_LINE, stamp=t, visible=True,
                                      error=0.0, confidence=0.9), received_at=t, source_now=t)
        m.observe(LineObservation(source=LineFollowMode.IR_LINE, stamp=t, visible=ir_error is not None,
                                  error=ir_error, confidence=0.9 if ir_error is not None else 0.0,
                                  ir_calibrated=True, calibration_revision=REV), received_at=t, source_now=t)

    def step(self, dt=0.1, **feed):
        self.t += dt
        self.feed(**feed)
        return self.m.tick(self.t + 0.01)

    def cue(self, state, seq, epoch="e", **extra):
        body = {"cue_id": f"c{seq}", "fleet_epoch": epoch, "seq": seq, "ttl_s": 1.0, "pose_stamp": WALL + self.t,
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
    rig.t += 0.5
    rig.cue("WRONG_WAY", 2, turn_deg=turn)
    return rig.step()


def test_wrong_way_debounces_turns_in_place_on_odom_and_stops_within_ten_degrees():
    rig = Rig()
    d = _wrong_way(rig)
    assert d.linear == 0 and d.angular < 0 and rig.m.status().reason == "fleet_wrong_way_turn"
    seq = 3
    while rig.yaw > math.radians(-165):
        rig.yaw -= math.radians(20)
        rig.cue("WRONG_WAY", seq, turn_deg=-170.0 - math.degrees(rig.yaw))
        seq += 1
        d = rig.step()
    assert d.linear > 0                                                  # done: the keep drives again
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
    rig.t += 3.0                                                        # Fleet silent: still held
    assert rig.step().linear == 0
    rig.cue("ON_LANE", 100)
    assert rig.step().linear > 0


def test_off_map_latches_past_the_ttl_and_a_stuck_decision_releases_it():
    rig = Rig()
    rig.cue("OFF_MAP", 1)
    assert rig.step().linear == 0 and rig.m.status().reason == "fleet_off_map"
    rig.t += 5.0
    assert rig.step().linear == 0                                        # fail-closed after expiry
    rig.m.release_lane_cue_latch(principal_ref="op")
    assert rig.step().linear > 0


def test_cue_lost_mid_pivot_latches():
    rig = Rig()
    _wrong_way(rig)
    rig.t += 1.5                                                        # no new cue: ttl 1 s ran out
    assert rig.step().linear == 0 and rig.m.status().reason == "fleet_cue_lost"


def test_no_pivot_without_a_fresh_camera_or_while_lost():
    rig = Rig()
    rig.cue("WRONG_WAY", 1, turn_deg=-170.0)
    rig.step()
    rig.t += 0.5
    rig.cue("WRONG_WAY", 2, turn_deg=-170.0)
    d = rig.step(0.4, camera=False)                                     # camera stale (> 0.3 s)
    assert (d.linear, d.angular) == (0, 0) and rig.m.status().reason == "observation_stale"


def test_ordering_epoch_and_pose_age():
    rig = Rig()
    assert rig.cue("ON_LANE", 5)[0]
    rig.t += 3.0
    rig.feed()
    assert rig.cue("ON_LANE", 4) == (False, "stale")                    # kept across expiry
    assert rig.cue("ON_LANE", 6)[0]
    assert rig.cue("ON_LANE", 1, epoch="other") == (False, "epoch_busy")
    rig.t += 2.0
    rig.feed()
    assert rig.cue("ON_LANE", 1, epoch="other")[0]                      # the old one expired
    body_old = rig.m.set_lane_cue({"cue_id": "x", "fleet_epoch": "other", "seq": 9, "ttl_s": 1.0,
                                   "pose_stamp": WALL + rig.t - 2.0, "state": "ON_LANE"}, now=rig.t)
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
    lf._config = replace(lf.config, fleet_lane_cue_enabled=True)
    body = {"cue_id": "c1", "fleet_epoch": "e", "seq": 1, "ttl_s": 1.0, "pose_stamp": 1.0, "state": "ON_LANE"}
    for headers in ({"Authorization": "Bearer rosy-dev-viewer"}, {"Authorization": "Bearer rosy-dev-operator"},
                    _token(svc, "screen", "operator", "pair-physical", "robot screen login")):
        assert client.post("/api/v1/line-follow/lane-cue", json=body, headers=headers).status_code == 403
    site = _token(svc, "site", "operator", "pair-physical", "site:rosy-site")
    reply = client.post("/api/v1/line-follow/lane-cue", json=body, headers=site)
    assert reply.status_code == 200 and reply.json() == {"accepted": False, "reason": "odom_stale"}
