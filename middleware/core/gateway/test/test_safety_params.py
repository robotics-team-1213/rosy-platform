"""D-400 3: safety worker parameters from CORE's own sources."""

import math

import pytest

from core.safety_params import SafetyParams, resolve_safety_params, simulation_sensors

BASE = dict(lidar_forward_deg=181.5, lidar_source="calibration record r1 sha256 abc",
            caps=((0.2, 0.8), (0.15, 0.6), (0.2, 0.8)))


def test_lidar_and_envelope_come_from_core_values():
    params = resolve_safety_params(**BASE, overlay={})

    assert params.parameters["lidar_yaw_offset"] == pytest.approx(math.radians(181.5))
    assert params.parameters["safety_max_linear"] == 0.2
    assert params.parameters["safety_max_angular"] == 0.8
    assert params.sources["lidar_yaw_offset"] == (
        "unused while lidar_use_tf (TF = URDF nominal); "
        "line_follow uses: calibration record r1 sha256 abc")
    assert params.sources["lidar_use_tf"] == "worker default"
    assert params.sources["cliff_enable"] == "worker default"
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
    ({"safety_max_linear": 1.5}, r"must be in \(0, 1.0\]"),
    ({"safety_max_angular": 3.5}, r"must be in \(0, 3.0\]"),
    ({"imu_roll0": True}, "finite number"),
    ({"cmd_linear_sign": float("nan")}, "finite number"),
    ({"cliff_raw_max": 800.0}, "must be an int"),
    ({"cliff_clear_raw": True}, "must be an int"),
    ({"cliff_mode": "medium"}, "must be one of"),
    ({"cliff_enable": 1}, "must be a bool"),
    ({"lidar_use_tf": "no"}, "must be a bool"),
    ({"safety_max_angular": float("nan")}, "finite number"),
    ({"safety_max_linear": float("inf")}, "finite number"),
])
def test_overlay_refusals(overlay, message):
    with pytest.raises(ValueError, match=message):
        resolve_safety_params(**BASE, overlay=overlay)


@pytest.mark.parametrize("caps", [
    (), ((0.2,),), ((0.2, 0.8, 0.1),), ([0.2, 0.8],), ((0.2, float("nan")),),
    ((float("inf"), 0.8),), ((True, 0.8),)])
def test_caps_must_be_finite_pairs(caps):
    with pytest.raises(ValueError, match="caps"):
        resolve_safety_params(**{**BASE, "caps": caps}, overlay={})


@pytest.mark.parametrize("caps", [((1.5, 0.8),), ((0.2, 3.5),), ((0.0, 0.8),)])
def test_caps_outside_worker_bounds_are_refused(caps):
    with pytest.raises(ValueError, match="CORE speed cap"):
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


def test_overlay_types_are_coerced_for_the_worker():
    params = resolve_safety_params(**BASE, overlay={
        "imu_roll0": 1, "safety_max_linear": 1, "cliff_raw_max": 700, "cliff_mode": "high"})

    assert type(params.parameters["imu_roll0"]) is float
    assert type(params.parameters["safety_max_linear"]) is float
    assert params.parameters["cliff_raw_max"] == 700
    assert params.parameters["cliff_mode"] == "high"


def test_lidar_offset_source_when_tf_is_off():
    params = resolve_safety_params(**BASE, overlay={"lidar_use_tf": False})

    assert params.parameters["lidar_use_tf"] is False
    assert params.sources["lidar_yaw_offset"] == "line_follow: calibration record r1 sha256 abc"
    assert params.sources["lidar_use_tf"] == "operator overlay"


@pytest.mark.parametrize("source", ["", None, 3])
def test_lidar_source_must_be_non_empty_str(source):
    with pytest.raises(ValueError, match="lidar_source"):
        resolve_safety_params(**{**BASE, "lidar_source": source}, overlay={})


def test_revision_ignores_source_text():
    a = resolve_safety_params(**BASE, overlay={})
    b = resolve_safety_params(**{**BASE, "lidar_source": "hand value"}, overlay={})

    assert a.revision == b.revision


# ---- Gazebo sensor fidelity: one explicit sim flag, never inferred on the device ----

SIM_KEYS = {"accept_simulation_scans": True, "imu_angular_velocity_unit": "rad_s", "use_sim_time": True}


def test_device_parameters_carry_no_simulation_keys():
    params = resolve_safety_params(**BASE, overlay={})
    assert not set(SIM_KEYS) & set(params.parameters)
    assert params.revision == resolve_safety_params(**BASE, overlay={}, simulation=False).revision


def test_simulation_adds_the_gazebo_sensor_keys_and_changes_the_revision():
    device = resolve_safety_params(**BASE, overlay={})
    sim = resolve_safety_params(**BASE, overlay={}, simulation=True)
    assert {k: sim.parameters[k] for k in SIM_KEYS} == SIM_KEYS
    assert all(sim.sources[k] == "simulation_sensors" for k in SIM_KEYS)
    assert sim.revision != device.revision


@pytest.mark.parametrize("key", sorted(SIM_KEYS))
def test_overlay_cannot_set_simulation_keys(key):
    with pytest.raises(ValueError, match="not a safety policy parameter"):
        resolve_safety_params(**BASE, overlay={key: SIM_KEYS[key]})


def test_simulation_sensors_flag_is_explicit_and_needs_sim_time():
    assert simulation_sensors({}, use_sim_time=True) is False
    assert simulation_sensors({"mode": "enforce"}, use_sim_time=False) is False
    assert simulation_sensors({"simulation_sensors": False}, use_sim_time=False) is False
    assert simulation_sensors({"simulation_sensors": True}, use_sim_time=True) is True
    with pytest.raises(ValueError, match="use_sim_time"):
        simulation_sensors({"simulation_sensors": True}, use_sim_time=False)
    with pytest.raises(ValueError, match="bool"):
        simulation_sensors({"simulation_sensors": "true"}, use_sim_time=True)
