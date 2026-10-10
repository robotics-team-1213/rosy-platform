"""D-573 (c) wiring: the config flag and the scan feed of the CORE crosswalk gate."""
from types import SimpleNamespace

import pytest

from core.bridge import observation
from core.line_follow_wiring import _line_follow_config
from core_common.robot_body import PINKY_PRO as B
from core_features.line_follow.manager import LineFollowManager
from core_features.line_follow.model import LineFollowConfig, LineFollowMode

BODY = dict(body_front_x_m=B.front_x_m, body_rear_x_m=B.rear_x_m, body_half_width_m=B.half_width_m,
            body_rotation_radius_m=B.rotation_radius_m, body_lidar_x_m=B.lidar_x_m, obstacle_mode="path")


class Bus:
    def publish(self, *args, **kwargs):
        pass


def test_flag_defaults_off_and_must_be_a_yaml_boolean():
    assert _line_follow_config({}).crosswalk_gate_enabled is False
    with pytest.raises(ValueError):
        _line_follow_config({"crosswalk_gate_enabled": "true"})
    with pytest.raises(ValueError):
        LineFollowConfig(crosswalk_gate_enabled=True)          # no URDF body: refused at start
    assert _line_follow_config(dict(BODY, crosswalk_gate_enabled=True)).crosswalk_gate_enabled


@pytest.mark.parametrize("enabled", [True, False])
def test_the_scan_reaches_the_gate_only_when_enabled(enabled):
    manager = LineFollowManager(Bus(), clock=lambda: 1.0,
                                config=LineFollowConfig(**BODY, crosswalk_gate_enabled=enabled))
    manager.set_mode(LineFollowMode.CAMERA_LINE)
    sample = dict(ranges=[1.0, float("inf")] * 180, angle_min=-3.14159, angle_increment=0.01745,
                  range_min=0.15, range_max=8.0)
    observation.front_clearance(SimpleNamespace(loc_mission=None, line_follow=manager), sample,
                                received_at=1.0)
    scan = manager._xwalk_scan
    if not enabled:
        assert scan is None
        return
    assert scan.range_min == 0.15 and len(scan.rays) == 360
    assert scan.rays[1][1] is None                  # no return stays unknown


def test_removed_look_key_refuses_start_naming_the_new_key():
    with pytest.raises(ValueError, match="crosswalk_look_s.*crosswalk_clear_s"):
        _line_follow_config(dict(BODY, crosswalk_look_s=1.0))
    assert _line_follow_config(dict(BODY, crosswalk_clear_s=6.0)).crosswalk_clear_s == 6.0
