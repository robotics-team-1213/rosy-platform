import pytest

from core_common.domain.capabilities import (
    CapabilityDescriptor,
    PresentationState,
    descriptors_from_cap001,
)
from core_common.domain.model import DeviceState
from core_common.domain.tasks import TaskKind

def test_pinky_hardware_flags_map_to_mobility_ids():
    ids = {d.id for d in descriptors_from_cap001({
        "navigation": {"goal_navigation": True, "return_home": True},
        "teleop": True,
        "slam": False,
        "swarm": {"follow": False, "lead": False},
        "docking": {"supported": False},
    })}
    assert "mobility.navigate" in ids
    assert "mobility.move" in ids
    assert "mobility.dock" not in ids
    assert "manipulate.pick" not in ids
    assert "scan_rfid" not in ids
    assert "infer" not in ids


def test_core_slice_has_no_motion_descriptors():
    ids = {d.id for d in descriptors_from_cap001({
        "navigation": {"goal_navigation": False, "return_home": False},
        "teleop": False,
        "slam": False,
        "swarm": {"follow": False, "lead": False},
        "docking": {"supported": False},
    })}
    assert ids == set()


_PINKY_FLAGS = {
    "navigation": {"goal_navigation": True, "return_home": True},
    "teleop": True,
    "slam": True,
    "swarm": {"follow": True, "lead": True},
    "docking": {"supported": False},
}


def test_safe_stop_keeps_ids_but_marks_them_unavailable():
    descriptors = descriptors_from_cap001(
        _PINKY_FLAGS, device_state=DeviceState.SAFE_STOP
    )
    by_id = {d.id: d for d in descriptors}
    assert by_id["mobility.move"].available is False
    assert by_id["mobility.navigate"].available is False
    assert by_id["mobility.move"].state == PresentationState.BLOCKED.value
    assert by_id["mobility.move"].reason == "device_state:SAFE_STOP"
    assert "manipulate.pick" not in by_id


def test_ready_marks_advertised_descriptors_available():
    descriptors = descriptors_from_cap001(
        _PINKY_FLAGS, device_state=DeviceState.READY
    )
    by_id = {d.id: d for d in descriptors}
    assert by_id["mobility.move"].available is True
    assert by_id["mobility.move"].state == PresentationState.AVAILABLE.value
    assert by_id["mobility.move"].reason is None
    assert by_id["perception.localize"].available is True


def test_degraded_is_degraded_fallback_with_a_server_reason():
    descriptors = descriptors_from_cap001(
        _PINKY_FLAGS, device_state=DeviceState.DEGRADED
    )
    move = {d.id: d for d in descriptors}["mobility.move"]
    assert move.available is True
    assert move.state == PresentationState.DEGRADED_FALLBACK.value
    assert move.reason == "device_state:DEGRADED"


def test_blocked_descriptor_without_reason_is_rejected():
    with pytest.raises(ValueError, match="reason"):
        CapabilityDescriptor(
            id="mobility.move",
            available=False,
            state=PresentationState.BLOCKED.value,
        )


def test_unsupported_flags_are_omitted_not_greyed():
    ids = {d.id for d in descriptors_from_cap001(_PINKY_FLAGS)}
    assert "mobility.dock" not in ids
    assert all(d.state != PresentationState.NOT_PROVIDED.value for d in
               descriptors_from_cap001(_PINKY_FLAGS))


def test_task_kinds_require_concept_ids_not_hardware_names():
    assert TaskKind.MOVE.concept_id == "mobility.move"
    assert TaskKind.NAVIGATE.concept_id == "mobility.navigate"
    assert TaskKind.FOLLOW.concept_id == "mobility.follow"
    assert TaskKind.DOCK.concept_id == "mobility.dock"
    assert TaskKind.MOVE.capability == "teleop"
