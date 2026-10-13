"""Compatibility exports for the CORE Drive line-follow composition."""

from core.drive.line_follow import (  # noqa: F401
    _optional_float, _flag, _whole, _line_follow_config,
    bind_motion_envelope, bind_stuck_recovery,
    check_bridge_floor_basis, bind_lane_return_motion,
)
