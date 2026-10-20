"""Compatibility imports for :mod:`omx_adapter.contracts.gripper_contract`."""

from .contracts.gripper_contract import (
    GripperReadbackError,
    GripperObservation,
    HoldReceipt,
    ReleaseReceipt,
    _require_fresh,
    verify_held_object,
    verify_released_object,
)

__all__ = [
    'GripperReadbackError',
    'GripperObservation',
    'HoldReceipt',
    'ReleaseReceipt',
    'verify_held_object',
    'verify_released_object',
]
