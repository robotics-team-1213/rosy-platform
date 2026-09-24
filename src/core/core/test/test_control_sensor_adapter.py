"""Contract tests for the optional Rosy Control sensor-only adapter."""

import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from core.bridge.control_sensor_adapter import (
    ControlSensorAdapter,
    ControlSensorConfig,
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

    assert "ControlSensorAdapter" in init_source
    assert init_source.index("self.control_adapter") < init_source.index("self.bridge =")
    assert "self.control_adapter.attach(executor)" in run_source
    assert "self.control_adapter.detach(executor)" in run_source
    assert "self.control_adapter.close()" in shutdown_source


def test_core_node_binds_calibration_to_the_runtime_data_generation():
    path = Path(__file__).parents[1] / "core" / "node.py"
    source = path.read_text(encoding="utf-8")

    assert "ROSY_DATA_GENERATION" in source
    assert "active_generation" in source
    assert "sensor_cfg" in source


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
    setup_path = Path(__file__).parents[3] / "core" / "control" / "setup.py"
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
