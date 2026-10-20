"""Compatibility imports for :mod:`omx_adapter.contracts.target_evidence`."""

from .contracts.target_evidence import (
    _SHA256,
    _SELECTOR_KINDS,
    TargetResolutionError,
    _text,
    _box,
    ObjectCandidate,
    TargetSelector,
    TargetEvidence,
    _iou,
    _matches,
    resolve_target,
)

__all__ = [
    'TargetResolutionError',
    'ObjectCandidate',
    'TargetSelector',
    'TargetEvidence',
    'resolve_target',
]
