"""ROS names of one OMX instance graph (D-778 §1, D-779).

Two OMX arms on one host each run their own controller graph. The owner, probes and readiness
checks reach that graph through its namespace, never through hard-coded root names. "/" is the
root graph, which keeps the single-arm simulation path unchanged.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass

ENV = "ROSY_OMX_ROS_NAMESPACE"
_NAMESPACE = re.compile(r"(?:/[A-Za-z_][A-Za-z0-9_]*)+")


def validate_namespace(namespace: str) -> str:
    if namespace != "/" and not (isinstance(namespace, str) and _NAMESPACE.fullmatch(namespace)):
        raise ValueError("namespace must be an absolute ROS namespace without a trailing slash")
    return namespace


@dataclass(frozen=True)
class InstanceNames:
    """Absolute names inside one instance graph; /clock stays global (one simulation clock)."""

    namespace: str = "/"

    def __post_init__(self) -> None:
        validate_namespace(self.namespace)

    @property
    def prefix(self) -> str:
        return self.namespace.rstrip("/")

    @property
    def joint_state_topic(self) -> str:
        return self.prefix + "/joint_states"

    @property
    def trajectory_action(self) -> str:
        return self.prefix + "/arm_controller/follow_joint_trajectory"

    @property
    def list_controllers_service(self) -> str:
        return self.prefix + "/controller_manager/list_controllers"


def namespace_from_environment(environ: Mapping[str, str] | None = None) -> str:
    """The instance namespace from ROSY_OMX_ROS_NAMESPACE; unset means the root graph."""
    value = (os.environ if environ is None else environ).get(ENV, "/")
    return validate_namespace(value)


def names_from_environment(environ: Mapping[str, str] | None = None) -> InstanceNames:
    return InstanceNames(namespace_from_environment(environ))


__all__ = ["ENV", "InstanceNames", "names_from_environment", "namespace_from_environment",
           "validate_namespace"]
