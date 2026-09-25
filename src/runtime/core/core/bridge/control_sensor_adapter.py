"""Optional Rosy Control sensor-only worker owned by CORE.

The adapter is deliberately small: ``control`` owns sensor classification,
policy evidence, calibration file formats and the ROS worker, while CORE owns
the policy consumer and the only final ``cmd_vel`` publisher.  CORE never
imports ``control`` statically (D-126 S1): the worker, policy and calibration
loader arrive through the ``rosy.sensor_provider`` entry point
(``control.sensor_provider:PROVIDER``) or through explicit constructor
injection, which is what host tests use.  All validation — profile revision,
sensor-only mode, command-authority deny-list, calibration context/generation
binding and the measured-parameter allow-list — stays here and operates on
duck-typed provider data, so a missing or wrong-shaped provider fails closed.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import math
from typing import Any, Callable, Optional


_DEFAULT_REQUIRED = ("lidar", "imu", "ir")
_COMMAND_AUTHORITY_FIELDS = ("pub", "raw_zero_pub", "estop_pub", "decision_pub")
_CALIBRATION_CONTEXT_FIELDS = frozenset({
    "robot_id", "hardware_model", "geometry_revision", "sensor_revision", "data_generation",
})
_CALIBRATION_PARAMETER_FIELDS = frozenset({
    "cliff_raw_max", "cliff_clear_raw", "cliff_mode", "cmd_linear_sign",
    "imu_roll0", "imu_pitch0", "lidar_yaw_offset",
})


@dataclass(frozen=True)
class ControlSensorConfig:
    """Validated configuration for the optional worker.

    ``max_age`` is capped at the policy contract's 500 ms lease.  Parameters
    are copied into an immutable tuple so a caller cannot change the worker's
    startup contract after validation.
    """

    enabled: bool = False
    required: tuple[str, ...] = _DEFAULT_REQUIRED
    max_age: float = 0.5
    parameters: tuple[tuple[str, Any], ...] = ()
    calibration: tuple[tuple[str, Any], ...] = ()

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any] | None) -> "ControlSensorConfig":
        if raw is None:
            raw = {}
        if not isinstance(raw, Mapping):
            raise ValueError("control sensor adapter config must be a mapping")

        enabled = raw.get("enabled", False)
        if type(enabled) is not bool:
            raise ValueError("control sensor adapter enabled must be a boolean")

        required_raw = raw.get("required", _DEFAULT_REQUIRED)
        if not isinstance(required_raw, (tuple, list)) or not required_raw:
            raise ValueError("control sensor adapter required streams are invalid")
        required = tuple(required_raw)
        if (any(type(name) is not str or not name.strip() for name in required) or
                len(set(required)) != len(required)):
            raise ValueError("control sensor adapter required streams must be unique names")

        max_age = raw.get("max_age", 0.5)
        if (type(max_age) not in (int, float) or not math.isfinite(float(max_age)) or
                not 0.0 < float(max_age) <= 0.5):
            raise ValueError("control sensor adapter max_age must be in (0, 0.5]")

        parameters_raw = raw.get("parameters", {})
        if not isinstance(parameters_raw, Mapping):
            raise ValueError("control sensor adapter parameters must be a mapping")
        parameters = tuple(parameters_raw.items())
        if any(type(name) is not str or not name.strip() for name, _ in parameters):
            raise ValueError("control sensor adapter parameter names must be non-empty")

        calibration_raw = raw.get("calibration", {})
        if calibration_raw is None:
            calibration_raw = {}
        if not isinstance(calibration_raw, Mapping):
            raise ValueError("control sensor adapter calibration must be a mapping")
        calibration_required = calibration_raw.get("required", False)
        if type(calibration_required) is not bool:
            raise ValueError("control sensor adapter calibration required must be a boolean")
        path = calibration_raw.get("path")
        data_root = calibration_raw.get("data_root", "/var/lib/rosy")
        active_generation = calibration_raw.get("active_generation")
        context = calibration_raw.get("context")
        if calibration_required:
            if (type(path) is not str or not path.strip() or
                    type(data_root) is not str or not data_root.strip() or
                    type(active_generation) is not str or not active_generation.strip() or
                    not isinstance(context, Mapping) or
                    set(context) != _CALIBRATION_CONTEXT_FIELDS or
                    any(type(value) is not str or not value.strip() or value != value.strip()
                        or len(value) > 128 for value in context.values())):
                raise ValueError(
                    "required calibration needs path, data_root, active_generation and complete context"
                )
        elif path is not None and type(path) is not str:
            raise ValueError("control sensor adapter calibration path must be a string")
        calibration = tuple(calibration_raw.items())

        return cls(enabled=enabled, required=required, max_age=float(max_age),
                   parameters=parameters, calibration=calibration)

    @property
    def parameter_overrides(self) -> dict[str, Any]:
        return dict(self.parameters)

    @property
    def calibration_config(self) -> dict[str, Any]:
        return dict(self.calibration)


_PROVIDER_GROUP = "rosy.sensor_provider"
_PROVIDER_NAME = "control"


def _resolve_provider_factory(attr: str):
    """Load one control-slice factory without statically importing control.

    Raises a fail-closed ValueError when the control slice is not installed.
    Host tests bypass this entirely through constructor injection.
    """
    from importlib import metadata

    try:
        entry_points = metadata.entry_points(group=_PROVIDER_GROUP)
    except Exception as exc:
        raise ValueError(
            "enabled sensor adapter cannot discover the sensor provider "
            f"({_PROVIDER_GROUP} lookup failed)"
        ) from exc
    matches = [ep for ep in entry_points if ep.name == _PROVIDER_NAME]
    if not matches:
        raise ValueError(
            "enabled sensor adapter needs the control slice installed "
            f"(entry point {_PROVIDER_GROUP} [{_PROVIDER_NAME}] not found)"
        )
    provider = matches[0].load()
    factory = getattr(provider, attr, None)
    if not callable(factory):
        raise ValueError(f"sensor provider has no {attr!r} factory")
    return factory


def _load_required_calibration(config: ControlSensorConfig, loader):
    """Load only a context-bound, generation-bound calibration snapshot."""

    calibration = config.calibration_config

    snapshot = loader(
        calibration["path"],
        calibration["context"],
        calibration["active_generation"],
        calibration["data_root"],
    )
    parameters = snapshot.node_parameters("safety_node")
    unknown = set(parameters) - _CALIBRATION_PARAMETER_FIELDS
    if unknown:
        raise ValueError(
            "calibration contains parameters outside the safety measured set: "
            + ", ".join(sorted(unknown))
        )
    return snapshot, parameters


class ControlSensorAdapter:
    """Lifecycle owner for the optional ``SafetyNode(sensor_only=True)``.

    The adapter has no command path of its own.  It creates a ROS-free
    ``CommandPolicy`` and asks the sensor worker to hand evidence to that
    policy.  CORE binds the same policy to ``SafetyManager``; this keeps the
    final command decision in CORE and makes the worker independently
    replaceable in tests.
    """

    def __init__(self, raw_config: Mapping[str, Any] | None = None, *,
                 sensor_node_factory: Optional[Callable[..., Any]] = None,
                 policy_factory: Optional[Callable[..., Any]] = None,
                 calibration_loader: Optional[Callable[..., Any]] = None,
                 namespace: str | None = None) -> None:
        self.config = ControlSensorConfig.from_mapping(raw_config)
        self.node = None
        self.policy = None
        self._executor = None
        self._closed = False
        self._calibration_snapshot = None

        if not self.config.enabled:
            return

        factory = sensor_node_factory or _resolve_provider_factory("make_node")
        make_policy = policy_factory or _resolve_provider_factory("make_policy")
        parameters = self.config.parameter_overrides
        if self.config.calibration_config.get("required", False):
            load_snapshot = calibration_loader or _resolve_provider_factory("load_snapshot")
            snapshot, calibrated = _load_required_calibration(self.config, load_snapshot)
            conflicts = {
                key for key in calibrated.keys() & parameters.keys()
                if calibrated[key] != parameters[key]
            }
            if conflicts:
                raise ValueError(
                    "explicit sensor parameters conflict with required calibration: "
                    + ", ".join(sorted(conflicts))
                )
            parameters = {**calibrated, **parameters}
            self._calibration_snapshot = snapshot
        kwargs = {
            "parameter_overrides": parameters,
            "sensor_only": True,
        }
        if namespace is not None:
            kwargs["namespace"] = namespace
        node = factory(**kwargs)
        try:
            refresh_profile = getattr(node, "refresh_profile", None)
            if callable(refresh_profile):
                # The worker's initial bootstrap profile is not the effective
                # parameter readback.  Bind only after it has produced the
                # revision that will actually label its observations.
                refresh_profile()
            revision = getattr(getattr(node, "profile", None), "revision", None)
            if type(revision) is not str or not revision.strip():
                raise ValueError("sensor worker has no applied profile revision")
            if getattr(node, "_sensor_only", True) is not True:
                raise ValueError("sensor worker must run in sensor-only mode")
            if any(getattr(node, name, None) is not None
                   for name in _COMMAND_AUTHORITY_FIELDS):
                raise ValueError("sensor worker exposes command authority")
            if not callable(getattr(node, "bind_policy_handoff", None)):
                raise ValueError("sensor worker has no policy handoff")

            observations = getattr(node, "observations", None)
            if observations is not None and hasattr(observations, "max_age"):
                observations.max_age = self.config.max_age

            policy = make_policy(revision)
            node.bind_policy_handoff(policy, self.config.required,
                                     applied_revision=revision)
        except Exception:
            destroy = getattr(node, "destroy_node", None)
            if callable(destroy):
                destroy()
            raise

        self.node = node
        self.policy = policy

    @property
    def enabled(self) -> bool:
        return self.config.enabled

    @property
    def revision(self) -> str | None:
        return None if self.policy is None else self.policy.revision

    @property
    def calibration_revision(self) -> int | None:
        return None if self._calibration_snapshot is None else self._calibration_snapshot.revision

    @property
    def calibration_digest(self) -> str | None:
        return None if self._calibration_snapshot is None else self._calibration_snapshot.digest

    def bind_safety(self, safety: Any) -> bool:
        """Bind the worker policy to CORE's safety consumer when enabled."""
        if not self.enabled:
            return False
        if self.policy is None or not callable(getattr(safety, "bind_control_policy", None)):
            raise ValueError("enabled sensor adapter cannot bind its policy")
        safety.bind_control_policy(self.policy)
        return True

    def attach(self, executor: Any) -> bool:
        if self.node is None or self._closed or self._executor is not None:
            return False
        executor.add_node(self.node)
        self._executor = executor
        return True

    def detach(self, executor: Any) -> bool:
        if self.node is None or self._executor is not executor:
            return False
        executor.remove_node(self.node)
        self._executor = None
        return True

    def close(self) -> bool:
        if self.node is None or self._closed:
            return False
        if self._executor is not None:
            try:
                self._executor.remove_node(self.node)
            finally:
                self._executor = None
        self.node.destroy_node()
        self._closed = True
        return True
