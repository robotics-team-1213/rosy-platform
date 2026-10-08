"""D-520 2: the line_follow.arc status record (split from schemas.py, which has no size room)."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class LineArcIrCorrection(BaseModel):
    """D-520 2: the one IR correction of an arc (side: left | right, phase: away | level | done)."""

    side: Optional[str] = None
    phase: Optional[str] = None
    away_m: float = 0.0
    level_m: float = 0.0
    used: bool = False


class LineArcStatus(BaseModel):
    """D-520 2: the map-guided arc after a junction instruction's turn (state: running | ended |
    stopped). Fleet reads from_place_id and a new arc_seq as the instruction carried."""

    arc_seq: int
    from_place_id: Optional[str] = None
    end_place_id: str
    curvature_1pm: float
    length_m: float
    travelled_m: float = 0.0
    state: str = "running"
    reason: Optional[str] = None
    ir_correction: LineArcIrCorrection = Field(default_factory=LineArcIrCorrection)

