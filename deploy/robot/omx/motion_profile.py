"""Compatibility imports for the installed pure OMX motion profiles."""

from omx_adapter.motion_profile import (
    GUARD_ACCEL_UNITS_S2 as GUARD_ACCEL_UNITS_S2,
    TemporalChunkEnsembler as TemporalChunkEnsembler,
    blend_chunks as blend_chunks,
    eased as eased,
    eased_progress as eased_progress,
    flow as flow,
    progress as progress,
    receding_horizon_splice as receding_horizon_splice,
    retime as retime,
    smooth as smooth,
    trapezoid as trapezoid,
)
