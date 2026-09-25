"""D-74: TaskKind work commands sink to ROS; system/host queries stay in CORE."""

import pytest

from core_common.capability import Capability, CapabilityError
from core_common.domain.command_mapping import (
    CORE_LOCAL_PREFIXES,
    TASK_ROS_INTERFACE,
    TASK_SINKS,
    WORK_PREFIXES,
    CommandSink,
    sink_for,
)
from core_common.domain.tasks import TaskKind


def test_every_task_kind_sinks_to_ros():
    assert set(TASK_SINKS) == set(TaskKind)
    assert set(TASK_ROS_INTERFACE) == set(TaskKind)
    for kind in TaskKind:
        assert sink_for(kind) is CommandSink.ROS
        assert TASK_ROS_INTERFACE[kind]


def test_queries_and_host_agent_are_not_ros_commands():
    for prefix in CORE_LOCAL_PREFIXES:
        assert prefix.startswith("/api/v1/")
        assert prefix not in WORK_PREFIXES
        assert "teleop" not in prefix
        assert "navigation" not in prefix
        assert "docking" not in prefix
        assert "swarm" not in prefix


def test_taskkind_require_keeps_cap001_flag_and_adds_concept_id():
    cap = Capability({"teleop": False})
    with pytest.raises(CapabilityError) as caught:
        TaskKind.MOVE.require(cap)
    assert caught.value.feature == "teleop"
    assert caught.value.concept_id == "mobility.move"


def test_work_prefixes_are_the_ros_bound_rest_surface():
    assert "/api/v1/system" not in WORK_PREFIXES
    assert "/api/v1/host" not in WORK_PREFIXES
    assert "/api/v1/teleop" in WORK_PREFIXES
    assert "/api/v1/navigation" in WORK_PREFIXES
