"""D-400 3: safety worker parameters from CORE's own sources."""

import math

import pytest

from core.safety_params import SafetyParams, resolve_safety_params

BASE = dict(lidar_forward_deg=181.5, lidar_source="calibration record r1 sha256 abc",
            caps=(0.2, 0.8, 0.15, 0.6, 0.2, 0.8))


def test_lidar_and_envelope_come_from_core_values():
    params = resolve_safety_params(**BASE, overlay={})

    assert params.parameters["lidar_yaw_offset"] == pytest.approx(math.radians(181.5))
    assert params.parameters["safety_max_linear"] == 0.2
    assert params.parameters["safety_max_angular"] == 0.8
    assert params.sources["lidar_yaw_offset"] == "line_follow: calibration record r1 sha256 abc"
    assert params.sources["safety_max_linear"] == "core speed caps"
    assert params.sources["imu_roll0"] == "worker default"


def test_overlay_wins_and_is_recorded():
    params = resolve_safety_params(**BASE, overlay={"cliff_enable": False, "safety_max_linear": 0.25})

    assert params.parameters["cliff_enable"] is False
    assert params.parameters["safety_max_linear"] == 0.25
    assert params.sources["cliff_enable"] == "operator overlay"


@pytest.mark.parametrize("overlay, message", [
    ({"sensor_timeout": 1.0}, "not a safety policy parameter"),
    ({"safety_max_linear": 0.1}, "below the CORE speed cap"),
    ({"safety_max_angular": 0.5}, "below the CORE speed cap"),
    ({"lidar_yaw_offset": 3.3}, "line_follow"),
    ({"safety_max_linear": True}, "finite number"),
    ({"safety_max_angular": float("nan")}, "finite number"),
    ({"safety_max_linear": float("inf")}, "finite number"),
])
def test_overlay_refusals(overlay, message):
    with pytest.raises(ValueError, match=message):
        resolve_safety_params(**BASE, overlay=overlay)


@pytest.mark.parametrize("caps", [(), (0.2, 0.8, 0.15), (0.2,)])
def test_caps_must_be_non_empty_pairs(caps):
    with pytest.raises(ValueError, match="caps"):
        resolve_safety_params(**{**BASE, "caps": caps}, overlay={})


@pytest.mark.parametrize("caps", [(0.2, float("nan")), (float("inf"), 0.8), (True, 0.8)])
def test_caps_must_be_finite_numbers(caps):
    with pytest.raises(ValueError, match="caps"):
        resolve_safety_params(**{**BASE, "caps": caps}, overlay={})


@pytest.mark.parametrize("deg", [float("nan"), float("inf"), True])
def test_lidar_forward_must_be_finite_number(deg):
    with pytest.raises(ValueError, match="lidar_forward_deg"):
        resolve_safety_params(**{**BASE, "lidar_forward_deg": deg}, overlay={})


def test_result_is_frozen_and_returns_plain_copies():
    params = resolve_safety_params(**BASE, overlay={})
    assert type(params.parameters) is dict and type(params.sources) is dict

    params.parameters["safety_max_linear"] = 99.0
    params.sources.clear()
    again = resolve_safety_params(**BASE, overlay={})

    assert again.parameters["safety_max_linear"] == 0.2
    assert again.sources["imu_roll0"] == "worker default"
    with pytest.raises(Exception):
        params.revision = "x"
    assert isinstance(again, SafetyParams)


def test_revision_is_deterministic_and_tracks_values():
    a = resolve_safety_params(**BASE, overlay={})
    b = resolve_safety_params(**BASE, overlay={})
    c = resolve_safety_params(**{**BASE, "lidar_forward_deg": 180.0}, overlay={})

    assert a.revision == b.revision
    assert a.revision != c.revision
    assert len(a.revision) == 16
