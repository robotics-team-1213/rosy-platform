"""Compatibility imports for the installed pure OMX motion profiles."""
from pathlib import Path
import sys

_ADAPTER_SRC = str(Path(__file__).resolve().parents[3] / "middleware/devices/omx/adapter")
if _ADAPTER_SRC not in sys.path:
    sys.path.insert(0, _ADAPTER_SRC)

from omx_adapter.motion_profile import (  # noqa: E402
    GUARD_ACCEL_UNITS_S2 as GUARD_ACCEL_UNITS_S2,
    TemporalChunkEnsembler as TemporalChunkEnsembler,
    blend_chunks as blend_chunks,
    compile_smooth_chunk as compile_smooth_chunk,
    eased as eased,
    eased_progress as eased_progress,
    flow as flow,
    progress as progress,
    receding_horizon_splice as receding_horizon_splice,
    retime as retime,
    smooth as smooth,
    trapezoid as trapezoid,
    upgrade_linear_chunk as upgrade_linear_chunk,
)
