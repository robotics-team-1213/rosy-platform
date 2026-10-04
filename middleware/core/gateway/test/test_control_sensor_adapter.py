"""Contract tests for the optional Rosy Control sensor-only adapter."""

import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from core.bridge.control_sensor_adapter import (
    ControlSensorAdapter,
    ControlSensorConfig,
    build_control_adapter,
)
from control.calibration_storage import merge_calibration
from control.sensor_provider import PROVIDER


def _provider_factories(**extra):
    """Real control-slice factories; production resolves the same object
    through the rosy.sensor_provider entry point (D-126 S1)."""
    factories = {
        "policy_factory": PROVIDER.make_policy,
        "calibration_loader": PROVIDER.load_snapshot,
    }
    factories.update(extra)
    return factories


class FakeSensorNode:
    def __init__(self, revision="sensor-revision", **kwargs):
        self.profile = SimpleNamespace(revision=revision)
        self.pub = None
        self.raw_zero_pub = None
        self.estop_pub = None
        self.decision_pub = None
        self.bind_calls = []
        self.destroyed = False
        self.factory_kwargs = kwargs

    def bind_policy_handoff(self, policy, required, applied_revision=None):
        self.bind_calls.append((policy, tuple(required), applied_revision))
        return applied_revision

    def destroy_node(self):
        self.destroyed = True


def test_default_configuration_is_disabled_and_has_no_sensor_node():
    calls = []

    adapter = ControlSensorAdapter(sensor_node_factory=lambda **kwargs: calls.append(kwargs))

    assert adapter.enabled is False
    assert adapter.node is None
    assert adapter.policy is None
    assert adapter.attach(object()) is False
    assert calls == []


def test_enabled_configuration_constructs_sensor_only_node_and_binds_applied_revision():
    created = []

    def factory(**kwargs):
        sensor = FakeSensorNode(**kwargs)
        created.append(sensor)
        return sensor

    adapter = ControlSensorAdapter(
        {
            "enabled": True,
            "required": ["lidar", "imu", "ir"],
            "max_age": 0.4,
            "parameters": {"sensor_timeout": 0.8},
        },
        sensor_node_factory=factory,
        **_provider_factories(),
    )

    assert adapter.enabled is True
    assert adapter.policy is not None
    assert adapter.policy.revision == "sensor-revision"
    assert len(created) == 1
    assert created[0].factory_kwargs == {
        "parameter_overrides": {"sensor_timeout": 0.8},
        "sensor_only": True,
    }
    assert len(created[0].bind_calls) == 1
    policy, required, revision = created[0].bind_calls[0]
    assert policy is adapter.policy
    assert required == ("lidar", "imu", "ir")
    assert revision == "sensor-revision"


def test_namespaced_worker_receives_the_core_namespace():
    received = []

    def factory(**kwargs):
        received.append(kwargs)
        return FakeSensorNode(**kwargs)

    ControlSensorAdapter({"enabled": True}, sensor_node_factory=factory,
                         namespace="/rosy_01", **_provider_factories())

    assert received == [{
        "parameter_overrides": {},
        "sensor_only": True,
        "namespace": "/rosy_01",
    }]


def test_adapter_can_bind_the_same_policy_to_core_safety_manager():
    sensor = FakeSensorNode()
    adapter = ControlSensorAdapter(
        {"enabled": True}, sensor_node_factory=lambda **kwargs: sensor,
        **_provider_factories()
    )

    class Safety:
        def __init__(self):
            self.bound = None

        def bind_control_policy(self, policy):
            self.bound = policy

    safety = Safety()
    assert adapter.bind_safety(safety) is True
    assert safety.bound is adapter.policy


def test_adapter_refuses_a_sensor_node_with_any_command_authority():
    def factory(**kwargs):
        node = FakeSensorNode(**kwargs)
        node.pub = object()
        return node

    with pytest.raises(ValueError, match="command authority"):
        ControlSensorAdapter({"enabled": True}, sensor_node_factory=factory,
                             **_provider_factories())


def test_adapter_attach_and_close_are_idempotent():
    sensor = FakeSensorNode()
    adapter = ControlSensorAdapter(
        {"enabled": True}, sensor_node_factory=lambda **kwargs: sensor,
        **_provider_factories()
    )

    class Executor:
        def __init__(self):
            self.added = []
            self.removed = []

        def add_node(self, node):
            self.added.append(node)

        def remove_node(self, node):
            self.removed.append(node)

    executor = Executor()
    assert adapter.attach(executor) is True
    assert adapter.attach(executor) is False
    assert adapter.detach(executor) is True
    assert adapter.detach(executor) is False
    assert adapter.close() is True
    assert adapter.close() is False
    assert executor.added == [sensor]
    assert executor.removed == [sensor]
    assert sensor.destroyed is True


def test_core_node_owns_adapter_before_bridge_and_closes_it_with_executor():
    path = Path(__file__).parents[1] / "core" / "node.py"
    module = ast.parse(path.read_text(encoding="utf-8"))
    cls = next(node for node in module.body
               if isinstance(node, ast.ClassDef) and node.name == "RosyCoreNode")
    methods = {
        node.name: node for node in cls.body
        if isinstance(node, ast.FunctionDef)
    }
    init_source = ast.get_source_segment(path.read_text(encoding="utf-8"), methods["__init__"])
    run_source = ast.get_source_segment(path.read_text(encoding="utf-8"), methods["run"])
    shutdown_source = ast.get_source_segment(path.read_text(encoding="utf-8"), methods["shutdown"])

    assert "build_control_adapter" in init_source
    assert init_source.index("self.control_adapter") < init_source.index("self.bridge =")
    order = ["resolve_lidar_forward_deg(", "resolve_safety_params(", "build_control_adapter(",
             ".bind_safety(", "use_lidar_forward(", "set_safety_policy_provider("]
    positions = [init_source.index(token, init_source.index("local_overlay")) for token in order]
    assert positions == sorted(positions)
    assert "adapter_parameters=" not in path.read_text(encoding="utf-8")
    assert "self.control_adapter.attach(executor)" in run_source
    assert "self.control_adapter.detach(executor)" in run_source
    assert "self.control_adapter.close()" in shutdown_source


def test_core_node_no_longer_fills_the_retired_calibration_block():
    """D-400: build_control_adapter ignores `calibration`, so node.py has nothing to bind to."""
    source = (Path(__file__).parents[1] / "core" / "node.py").read_text(encoding="utf-8")

    assert "ROSY_DATA_GENERATION" not in source
    assert "active_generation" not in source


@pytest.mark.parametrize(
    "raw",
    [
        {"enabled": "true"},
        {"enabled": True, "required": []},
        {"enabled": True, "required": ["lidar", "lidar"]},
        {"enabled": True, "required": ["lidar", 1]},
        {"enabled": True, "max_age": 0},
        {"enabled": True, "max_age": 0.6},
        {"enabled": True, "parameters": []},
    ],
)
def test_configuration_rejects_unsafe_values(raw):
    with pytest.raises(ValueError):
        ControlSensorConfig.from_mapping(raw)


CALIBRATION_CONTEXT = {
    "robot_id": "rosy_01",
    "hardware_model": "Pinky Pro",
    "geometry_revision": "geometry-1",
    "sensor_revision": "sensors-1",
    "data_generation": "release-1",
}


def _calibrated_adapter_config(tmp_path):
    path = tmp_path / "calibration" / "rosy_01" / "calibration.yaml"
    merge_calibration(
        str(path),
        "safety_node: {ros__parameters: {imu_roll0: 1.0, lidar_yaw_offset: 3.1}}",
        context=CALIBRATION_CONTEXT,
        actor="maintainer",
    )
    return {
        "enabled": True,
        "calibration": {
            "required": True,
            "path": str(path),
            "data_root": str(tmp_path),
            "active_generation": "release-1",
            "context": CALIBRATION_CONTEXT,
        },
    }


def test_required_calibration_is_loaded_before_sensor_worker_creation(tmp_path):
    created = []

    def factory(**kwargs):
        node = FakeSensorNode(**kwargs)
        created.append(node)
        return node

    adapter = ControlSensorAdapter(_calibrated_adapter_config(tmp_path), sensor_node_factory=factory,
                                     **_provider_factories())

    assert created[0].factory_kwargs["parameter_overrides"] == {
        "imu_roll0": 1.0,
        "lidar_yaw_offset": 3.1,
    }
    assert adapter.calibration_revision == 1
    assert len(adapter.calibration_digest) == 64


def test_calibration_parameter_conflict_is_rejected_before_worker_creation(tmp_path):
    config = _calibrated_adapter_config(tmp_path)
    config["parameters"] = {"imu_roll0": 2.0}
    calls = []

    with pytest.raises(ValueError, match="conflict"):
        ControlSensorAdapter(config, sensor_node_factory=lambda **kwargs: calls.append(kwargs),
                             **_provider_factories())

    assert calls == []


def test_invalid_required_calibration_fails_closed_before_worker_creation(tmp_path):
    config = _calibrated_adapter_config(tmp_path)
    config["calibration"]["active_generation"] = "release-2"
    calls = []

    with pytest.raises(ValueError, match="generation"):
        ControlSensorAdapter(config, sensor_node_factory=lambda **kwargs: calls.append(kwargs),
                             **_provider_factories())

    assert calls == []


def test_calibration_rejects_parameters_outside_the_measured_safety_set(tmp_path):
    config = _calibrated_adapter_config(tmp_path)
    path = Path(config["calibration"]["path"])
    merge_calibration(
        str(path),
        "safety_node: {ros__parameters: {imu_roll0: 1.0, unsafe_motor_limit: 0.1}}",
        context=CALIBRATION_CONTEXT,
        actor="maintainer",
    )
    calls = []

    with pytest.raises(ValueError, match="measured set"):
        ControlSensorAdapter(config, sensor_node_factory=lambda **kwargs: calls.append(kwargs),
                             **_provider_factories())

    assert calls == []


def test_disabled_adapter_does_not_touch_an_invalid_calibration_path():
    adapter = ControlSensorAdapter({
        "enabled": False,
        "calibration": {
            "required": True,
            "path": "/does/not/exist",
            "data_root": "/does/not/exist",
            "active_generation": "release-1",
            "context": CALIBRATION_CONTEXT,
        },
    }, sensor_node_factory=lambda **kwargs: pytest.fail("disabled adapter created worker"))

    assert adapter.enabled is False
    assert adapter.calibration_revision is None


def test_control_registers_the_sensor_provider_entry_point():
    """D-126 S1 wiring: the provider CORE resolves must be declared.

    Mutation-proven: delete the entry point line from control/setup.py and
    this test goes red while production silently loses its default worker.
    """
    setup_path = (Path(__file__).parents[4] / "middleware") / "perception" / "setup.py"
    tree = ast.parse(setup_path.read_text(encoding="utf-8"))
    setup_call = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "setup"
    )
    entry_points = next(
        kw.value for kw in setup_call.keywords if kw.arg == "entry_points"
    )
    groups = {
        key.value: [entry.value for entry in value.elts]
        for key, value in zip(entry_points.keys, entry_points.values)
        if isinstance(key, ast.Constant)
    }
    assert "rosy.sensor_provider" in groups
    assert "control = control.sensor_provider:PROVIDER" in groups["rosy.sensor_provider"]


def test_sensor_provider_surface_is_host_importable():
    """The provider object exposes the three factories without ROS."""
    assert callable(PROVIDER.make_node)
    assert callable(PROVIDER.make_policy)
    assert callable(PROVIDER.load_snapshot)
    assert PROVIDER.make_policy("probe-revision").revision == "probe-revision"


def test_enabled_adapter_without_provider_fails_closed_with_install_hint():
    # Isolate the missing-provider contract even when the full ROS overlay has
    # installed the control entry point (for example on the native ARM runner).
    with patch("importlib.metadata.entry_points", return_value=()):
        with pytest.raises(ValueError, match="control slice"):
            ControlSensorAdapter({"enabled": True})


@pytest.mark.parametrize("raw, mode, enabled", [
    ({}, "off", False),
    ({"mode": "off"}, "off", False),
    ({"mode": "shadow"}, "shadow", True),
    ({"mode": "enforce"}, "enforce", True),
    ({"enabled": True}, "enforce", True),
    ({"enabled": False}, "off", False),
])
def test_mode_parsing_and_enabled_compat(raw, mode, enabled):
    config = ControlSensorConfig.from_mapping(raw)

    assert config.mode == mode
    assert config.enabled is enabled


@pytest.mark.parametrize("raw, message", [
    ({"mode": False}, "quote"),            # YAML 1.1 reads bare off as False
    ({"mode": "on"}, "off, shadow or enforce"),
    ({"mode": "shadow", "enabled": True}, "not both"),
    ({"mode": "shadow", "stale_hold_s": 0}, "stale_hold_s"),
    ({"mode": "shadow", "stale_hold_s": 5.5}, "stale_hold_s"),
    ({"mode": "shadow", "stale_hold_s": True}, "stale_hold_s"),
])
def test_mode_and_stale_hold_reject_invalid_values(raw, message):
    with pytest.raises(ValueError, match=message):
        ControlSensorConfig.from_mapping(raw)


def test_stale_hold_defaults_to_two_seconds():
    assert ControlSensorConfig.from_mapping({"mode": "shadow"}).stale_hold_s == 2.0


def test_packaged_default_merged_with_legacy_enabled_overlay_is_enforce():
    import yaml
    from core_common.config import _deep_merge
    default_path = ((Path(__file__).resolve().parents[4] / "contracts") / "foundation" / "config" /
                    "rosy_default.yaml")
    default = yaml.safe_load(default_path.read_text(encoding="utf-8"))

    merged = _deep_merge(default, {"control": {"sensor_adapter": {"enabled": True}}})

    assert ControlSensorConfig.from_mapping(merged["control"]["sensor_adapter"]).mode == "enforce"


class RecordingSafety:
    def __init__(self):
        self.calls = []

    def bind_control_policy(self, policy):
        self.calls.append(("enforce", policy))

    def bind_shadow_control_policy(self, policy):
        self.calls.append(("shadow", policy))


def test_bind_safety_follows_the_mode():
    for mode in ("shadow", "enforce"):
        adapter = ControlSensorAdapter({"mode": mode}, sensor_node_factory=lambda **k: FakeSensorNode(**k),
                                       **_provider_factories())
        safety = RecordingSafety()

        assert adapter.bind_safety(safety) is True
        assert safety.calls == [(mode, adapter.policy)]


def _policy_only():
    return {"policy_factory": PROVIDER.make_policy}


def test_build_passes_resolved_parameters_and_ignores_the_calibration_block():
    created = []

    def factory(**kwargs):
        created.append(kwargs)
        return FakeSensorNode(**kwargs)

    adapter, notes = build_control_adapter(
        {"mode": "shadow", "parameters": {"cliff_enable": False},
         "calibration": {"required": True, "path": "/x"}},
        parameters={"lidar_yaw_offset": 3.17, "cliff_enable": False},
        sensor_node_factory=factory, **_policy_only())

    assert adapter.config.mode == "shadow"
    assert created[0]["parameter_overrides"] == {"lidar_yaw_offset": 3.17, "cliff_enable": False}
    assert notes == ["control.sensor_adapter.calibration is ignored (D-400 3); use the calibration store"]


def test_shadow_construction_failure_falls_back_to_off():
    def broken(**kwargs):
        raise ValueError("no IR stream")

    adapter, notes = build_control_adapter({"mode": "shadow"}, parameters={},
                                           sensor_node_factory=broken, **_policy_only())

    assert adapter.config.mode == "off"
    assert adapter.mode_error == "ValueError: no IR stream"
    assert notes == ["shadow sensor adapter failed, running with the policy off: ValueError: no IR stream"]
    safety = RecordingSafety()
    assert adapter.bind_safety(safety) is False
    assert safety.calls == []


def test_shadow_non_value_error_also_falls_back_to_off():
    def broken(**kwargs):
        raise RuntimeError("rclpy not initialised")

    adapter, notes = build_control_adapter({"mode": "shadow"}, parameters={},
                                           sensor_node_factory=broken, **_policy_only())

    assert adapter.config.mode == "off"
    assert adapter.mode_error == "RuntimeError: rclpy not initialised"
    assert notes == ["shadow sensor adapter failed, running with the policy off: RuntimeError: rclpy not initialised"]


def test_enforce_construction_failure_still_refuses_start():
    def broken(**kwargs):
        raise ValueError("no IR stream")

    with pytest.raises(ValueError, match="no IR stream"):
        build_control_adapter({"mode": "enforce"}, parameters={},
                              sensor_node_factory=broken, **_policy_only())


def test_invalid_mode_in_shadow_config_is_still_a_config_error():
    with pytest.raises(ValueError, match="off, shadow or enforce"):
        build_control_adapter({"mode": "on"}, parameters={})


def test_shadow_with_control_policy_required_is_a_config_error():
    # Design 3.1: shadow never binds a deciding policy, so policy_required would
    # latch every command. Rejected before any worker is built.
    with pytest.raises(ValueError, match="control_policy_required"):
        build_control_adapter({"mode": "shadow"}, parameters={}, policy_required=True)


def test_off_mode_builds_no_worker_and_binds_nothing():
    calls = []
    adapter, notes = build_control_adapter(
        {"mode": "off"}, parameters={"lidar_yaw_offset": 3.17},
        sensor_node_factory=lambda **k: calls.append(k), **_policy_only())
    safety = RecordingSafety()

    assert adapter.config.mode == "off"
    assert calls == []
    assert notes == []
    assert adapter.bind_safety(safety) is False
    assert safety.calls == []


@pytest.mark.parametrize("calibration", [None, {}, {"required": False, "path": "/x"}])
def test_calibration_block_without_required_produces_no_note(calibration):
    raw = {"mode": "off"}
    if calibration is not None:
        raw["calibration"] = calibration

    _, notes = build_control_adapter(raw, parameters={})

    assert notes == []


def test_legacy_enabled_config_builds_an_enforce_binding():
    adapter, notes = build_control_adapter(
        {"enabled": True}, parameters={},
        sensor_node_factory=lambda **k: FakeSensorNode(**k), **_policy_only())
    safety = RecordingSafety()

    assert adapter.config.mode == "enforce"
    assert adapter.bind_safety(safety) is True
    assert safety.calls == [("enforce", adapter.policy)]


class DestroyFailsNode(FakeSensorNode):
    def destroy_node(self):
        super().destroy_node()
        raise OSError("destroy failed")


def test_shadow_late_failure_destroys_the_created_node_and_falls_back():
    nodes = []

    def factory(**kwargs):
        nodes.append(FakeSensorNode(revision="", **kwargs))
        return nodes[-1]

    adapter, notes = build_control_adapter({"mode": "shadow"}, parameters={},
                                           sensor_node_factory=factory, **_policy_only())

    assert nodes[0].destroyed is True
    assert adapter.config.mode == "off"
    assert "no applied profile revision" in adapter.mode_error
    assert "no applied profile revision" in notes[0]


def test_cleanup_failure_never_replaces_the_original_error():
    def factory(**kwargs):
        return DestroyFailsNode(revision="", **kwargs)

    with pytest.raises(ValueError, match="no applied profile revision"):
        build_control_adapter({"mode": "enforce"}, parameters={},
                              sensor_node_factory=factory, **_policy_only())
    adapter, _ = build_control_adapter({"mode": "shadow"}, parameters={},
                                       sensor_node_factory=factory, **_policy_only())
    assert adapter.mode_error == "ValueError: sensor worker has no applied profile revision"


@pytest.mark.parametrize("calibration", [{"required": True, "path": "/x"}, {"required": 1}, "yes"])
def test_enforce_refuses_a_calibration_block_that_asks_for_it(calibration):
    with pytest.raises(ValueError, match="retired"):
        build_control_adapter({"mode": "enforce", "calibration": calibration}, parameters={})


@pytest.mark.parametrize("calibration", [{"required": 1}, "yes"])
def test_shadow_notes_a_malformed_calibration_block(calibration):
    adapter, notes = build_control_adapter(
        {"mode": "shadow", "calibration": calibration}, parameters={},
        sensor_node_factory=lambda **k: FakeSensorNode(**k), **_policy_only())

    assert adapter.config.mode == "shadow"
    assert notes == ["control.sensor_adapter.calibration is ignored (D-400 3); use the calibration store"]


def test_enforce_builds_with_calibration_required_false():
    adapter, notes = build_control_adapter(
        {"mode": "enforce", "calibration": {"required": False}}, parameters={},
        sensor_node_factory=lambda **k: FakeSensorNode(**k), **_policy_only())

    assert adapter.config.mode == "enforce"
    assert notes == []


@pytest.mark.parametrize("mode", ["off", "shadow", "enforce"])
def test_unknown_keyword_is_a_type_error_in_every_mode(mode):
    with pytest.raises(TypeError):
        build_control_adapter({"mode": mode}, parameters={}, namspace="x")


def test_shadow_failure_with_an_empty_message_still_explains_itself():
    def broken(**kwargs):
        raise RuntimeError("")

    adapter, _ = build_control_adapter({"mode": "shadow"}, parameters={},
                                       sensor_node_factory=broken, **_policy_only())

    assert adapter.mode_error == "RuntimeError: "


@pytest.mark.parametrize("mode, required", [("shadow", False), ("enforce", True)])
def test_policy_required_matching_the_mode_builds_and_binds(mode, required):
    adapter, _ = build_control_adapter(
        {"mode": mode}, parameters={}, policy_required=required,
        sensor_node_factory=lambda **k: FakeSensorNode(**k), **_policy_only())
    safety = RecordingSafety()

    assert adapter.bind_safety(safety) is True
    assert safety.calls == [(mode, adapter.policy)]
