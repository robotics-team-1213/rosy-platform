"""D-344 §12: 카메라 차선 추종 중 IR 차선 이탈 감시."""

import pytest

from core_features.line_follow.manager import (
    LineFollowConfig, LineFollowManager, LineFollowMode, LineObservation)

REV = "a" * 64


class _Events:
    def publish(self, *args, **kwargs):
        pass


def _manager(**overrides):
    config = LineFollowConfig(ir_guard_enabled=True, ir_calibration_revision=REV, **overrides)
    m = LineFollowManager(_Events(), config=config, clock=lambda: 10.0)
    m.set_mode(LineFollowMode.CAMERA_LINE)
    return m


def _camera(m, t, error=0.0):
    m.observe(LineObservation(source=LineFollowMode.CAMERA_LINE, stamp=t, visible=True,
                              error=error, confidence=0.9), received_at=t, source_now=t)


def _ir(m, t, error=None, *, calibrated=True, revision=REV):
    m.observe(LineObservation(source=LineFollowMode.IR_LINE, stamp=t, visible=error is not None,
                              error=error, confidence=0.9 if error is not None else 0.0,
                              ir_calibrated=calibrated, calibration_revision=revision),
              received_at=t, source_now=t)


def test_clear_floor_tracks_by_camera():
    m = _manager()
    _camera(m, 10.0, error=0.2)
    _ir(m, 10.0)                                     # 세 IR 모두 바닥 — 선 없음
    d = m.tick(10.05)
    assert d.linear > 0 and d.angular == pytest.approx(-0.16)
    assert m.status().reason == "tracking"


def test_boundary_under_left_sensor_steers_right_even_if_camera_says_left():
    m = _manager()
    _camera(m, 10.0, error=-0.5)                     # 카메라는 왼쪽으로 가라고 한다(선 위 무게중심)
    _ir(m, 10.0, error=-0.9)                         # 그러나 왼쪽 IR 밑에 흰 경계선
    d = m.tick(10.05)
    assert d.angular == pytest.approx(-0.5) and d.linear > 0
    assert m.status().reason == "lane_edge_left"


def test_boundary_under_right_sensor_steers_left_slower():
    m = _manager()
    _camera(m, 10.0, error=0.0)
    _ir(m, 10.0)
    free = m.tick(10.01).linear
    assert free > 0
    _ir(m, 10.02, error=0.8)
    d = m.tick(10.05)
    assert d.angular == pytest.approx(0.5) and d.linear == pytest.approx(free * 0.5)
    assert m.status().reason == "lane_edge_right"


def test_line_under_centre_sensor_is_a_crossing_and_holds_without_lost_latch():
    m = _manager()
    for step in range(40):
        t = 10.0 + step * 0.1
        _camera(m, t)
        _ir(m, t, error=0.0)
        d = m.tick(t + 0.01)
        assert d.linear == 0 and d.angular == 0
    assert m.status().state == "HOLD" and m.status().reason == "lane_departure"
    _camera(m, 14.2)
    _ir(m, 14.2)                                      # 운전자가 수동으로 빼 놓았다
    assert m.tick(14.21).linear > 0


@pytest.mark.parametrize("feed", ["none", "stale", "uncalibrated", "wrong_revision"])
def test_enabled_guard_without_trustworthy_ir_holds(feed):
    m = _manager()
    _camera(m, 10.5)
    if feed == "stale":
        _ir(m, 10.0)
    elif feed == "uncalibrated":
        _ir(m, 10.5, calibrated=False, revision=None)
    elif feed == "wrong_revision":
        _ir(m, 10.5, revision="b" * 64)
    assert m.tick(10.51).linear == 0
    assert m.status().reason == "lane_guard_stale"


def test_guard_off_by_default_ignores_ir():
    m = LineFollowManager(_Events(), config=LineFollowConfig(), clock=lambda: 10.0)
    m.set_mode(LineFollowMode.CAMERA_LINE)
    _camera(m, 10.0)
    _ir(m, 10.0, error=0.0)
    assert m.tick(10.05).linear > 0


def test_guard_config_is_validated():
    with pytest.raises(ValueError):
        LineFollowConfig(ir_guard_enabled="false")
    with pytest.raises(ValueError):
        LineFollowConfig(ir_guard_edge_error=1.0)
    with pytest.raises(ValueError):
        LineFollowConfig(ir_guard_speed_scale=1.5)


def test_nominal_ground_evidence_needs_a_driver_hold():
    """D-364 §3: estimated floor geometry drives only while someone holds 'go'."""
    m = LineFollowManager(_Events(), config=LineFollowConfig(), clock=lambda: 10.0)
    m.set_mode(LineFollowMode.CAMERA_LINE)
    obs = LineObservation(source=LineFollowMode.CAMERA_LINE, stamp=10.0, visible=True,
                          error=0.0, confidence=0.9, ground="NOMINAL")
    m.observe(obs, received_at=10.0, source_now=10.0)
    assert m.tick(10.05).linear == 0
    assert m.status().reason == "nominal_ground_requires_driver"
    m.set_mode(LineFollowMode.CAMERA_LINE, hold_s=0.5)
    m.observe(obs, received_at=10.0, source_now=10.0)
    assert m.tick(10.05).linear > 0
    with pytest.raises(ValueError):
        LineObservation(source=LineFollowMode.IR_LINE, stamp=1.0, visible=False, error=None,
                        confidence=0.0, ground="NOMINAL")
