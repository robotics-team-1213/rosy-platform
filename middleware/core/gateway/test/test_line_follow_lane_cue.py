"""D-511 rev 1: Fleet's lane return cue in the CAMERA_LINE keep (IR first, off by default)."""

import pytest

from core_features.line_follow.manager import (
    LineFollowConfig, LineFollowManager, LineFollowMode, LineObservation)

REV = "a" * 64


class _Events:
    def publish(self, *args, **kwargs):
        pass


def _manager(**overrides):
    config = LineFollowConfig(ir_guard_enabled=True, ir_calibration_revision=REV,
                              **{"fleet_lane_cue_enabled": True, **overrides})
    m = LineFollowManager(_Events(), config=config, clock=lambda: 10.0)
    m.set_mode(LineFollowMode.CAMERA_LINE)
    return m


def _feed(m, t, ir_error=None):
    m.observe(LineObservation(source=LineFollowMode.CAMERA_LINE, stamp=t, visible=True,
                              error=0.0, confidence=0.9), received_at=t, source_now=t)
    m.observe(LineObservation(source=LineFollowMode.IR_LINE, stamp=t, visible=ir_error is not None,
                              error=ir_error, confidence=0.9 if ir_error is not None else 0.0,
                              ir_calibrated=True, calibration_revision=REV), received_at=t, source_now=t)


def _cue(state, seq=1, **extra):
    return {"cue_id": f"c{seq}", "fleet_epoch": "e", "seq": seq, "ttl_s": 1.0, "state": state,
            "side": None, "bearing_deg": None, "turn_deg": None, "lane_heading_deg": None,
            "offset_m": None, "edge_id": None, "guide": None, **extra}


def test_off_by_default_refuses_the_cue():
    m = _manager(fleet_lane_cue_enabled=False)
    assert m.set_lane_cue(_cue("OFF_MAP"), now=10.0) == (False, "disabled")


def test_on_line_side_steers_toward_the_centre_through_the_ir_edge_branch():
    m = _manager()
    _feed(m, 10.0)
    assert m.set_lane_cue(_cue("ON_LINE", side="left"), now=10.0)[0]
    d = m.tick(10.05)
    assert d.angular == pytest.approx(0.5) and d.linear > 0       # centre is left: turn left
    assert m.status().reason == "lane_edge_right"


def test_ir_reading_wins_over_the_cue():
    m = _manager()
    _feed(m, 10.0, ir_error=-0.9)                                  # line under the left IR
    m.set_lane_cue(_cue("ON_LINE", side="left"), now=10.0)
    assert m.tick(10.05).angular == pytest.approx(-0.5)


def test_wrong_way_turns_in_place_then_keep_drives():
    m = _manager()
    _feed(m, 10.0)
    m.set_lane_cue(_cue("WRONG_WAY", turn_deg=-170.0), now=10.0)
    d = m.tick(10.05)
    assert d.linear == 0 and d.angular < 0 and m.status().reason == "fleet_wrong_way_turn"
    m.set_lane_cue(_cue("WRONG_WAY", seq=2, turn_deg=10.0), now=10.1)
    _feed(m, 10.1)
    assert m.tick(10.15).linear > 0


def test_off_map_holds_and_an_expired_cue_lets_go():
    m = _manager()
    _feed(m, 10.0)
    m.set_lane_cue(_cue("OFF_MAP"), now=10.0)
    d = m.tick(10.05)
    assert (d.linear, d.angular) == (0, 0) and m.status().reason == "fleet_off_map"
    _feed(m, 11.2)
    assert m.tick(11.25).linear > 0                                 # ttl 1 s passed


def test_older_seq_is_stale():
    m = _manager()
    assert m.set_lane_cue(_cue("ON_LANE", seq=5), now=10.0)[0]
    assert m.set_lane_cue(_cue("OFF_MAP", seq=4), now=10.1) == (False, "stale")



def test_guide_is_kept_for_the_keep_and_shown():
    m = _manager()
    guide = {"ahead_m": 0.4, "heading_ahead_deg": 12.0, "curvature_1pm": 0.5, "to_end_m": 1.2,
             "next_place_id": "NE_line", "ring": False}
    assert m.set_lane_cue(_cue("ON_LANE", guide=guide), now=10.0)[0]
    assert m.lane_cue_status(10.0)["guide"] == guide
