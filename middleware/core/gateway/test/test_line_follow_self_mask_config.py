"""CORE reads line_follow.lidar_self_mask (robot body returns) into LineFollowConfig."""
import pytest

from core.services import _line_follow_config


def test_core_config_parses_the_mask():
    cfg = _line_follow_config({"lidar_self_mask": [{"from_deg": -66, "to_deg": -52, "max_range_m": 0.17}]})
    assert cfg.lidar_self_mask == ((-66.0, -52.0, 0.17),)
    assert _line_follow_config({}).lidar_self_mask == ()


def test_a_malformed_mask_refuses_the_config():
    with pytest.raises(ValueError):
        _line_follow_config({"lidar_self_mask": [{"from_deg": -66, "to_deg": -52, "max_range_m": 0.5}]})
