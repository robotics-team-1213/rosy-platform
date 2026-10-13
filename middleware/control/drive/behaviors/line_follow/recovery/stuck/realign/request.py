"""D-607 8 REALIGN answer shape and limits (see the package docstring)."""
from __future__ import annotations

import math
from typing import Optional

KINDS = ("PIVOT", "KTURN")
MAX_ANGLE_RAD = math.pi / 2
MAX_BACK_M = 0.08
MIN_BACK_RADIUS_M = 0.05
MIN_FWD_RADIUS_M = 0.02
MAX_REALIGNS = 2


def _number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def request_refusal(req: Optional[dict]) -> Optional[str]:
    """The answer's own shape (D-607 8); None = well formed."""
    if not isinstance(req, dict) or not _number(req.get("angle_rad")) or not _number(req.get("pose_stamp")):
        return "realign_unset"
    if req.get("kind") not in KINDS:
        return "realign_kind"
    if abs(req["angle_rad"]) > MAX_ANGLE_RAD + 1e-9:
        return "realign_angle"
    if req["kind"] == "KTURN" and not (
            all(_number(req.get(k)) for k in ("back_m", "back_radius_m", "fwd_radius_m"))
            and 0.0 < req["back_m"] <= MAX_BACK_M and req["back_radius_m"] >= MIN_BACK_RADIUS_M
            and req["fwd_radius_m"] >= MIN_FWD_RADIUS_M):
        return "realign_unset"
    if req["kind"] == "PIVOT" and req.get("turn_spot") is not True:
        return "realign_kind"            # D-607 8: a PIVOT only on a map turn spot
    return None
