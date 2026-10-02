"""D-395 S1 ground-truth judge: a reported map pose against the Gazebo model pose.

Pure (no ROS, no gz): the bench driver (`d395_s1_bench.py`) feeds it the CORE
snapshot pose and the `gz model -p` text. map_v2_fleet's map frame is the Gazebo
world frame and its 180-degree twin of a pose is the point reflection through
the origin with yaw + pi (`fleet.localization.service_logic.mirror`).
"""

from __future__ import annotations

import math
import re
from typing import Optional

#: S1 pass box (task brief): within 5 cm and 5 degrees of the truth.
XY_TOL_M = 0.05
YAW_TOL_RAD = math.radians(5.0)
#: A pose this close to the truth's twin (and not to the truth) is a mirror lock.
MIRROR_XY_M = 0.25
MIRROR_YAW_RAD = math.radians(60.0)

_NUM = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"
_TRIPLE = re.compile(rf"\[\s*({_NUM})\s+({_NUM})\s+({_NUM})\s*\]")


def wrap(angle: float) -> float:
    return math.atan2(math.sin(angle), math.cos(angle))


def mirror(pose):
    return (-pose[0], -pose[1], wrap(pose[2] + math.pi))


def parse_gz_model_pose(text: str) -> Optional[tuple[float, float, float]]:
    """(x, y, yaw) from `gz model -m NAME -p` output: an XYZ triple then an RPY triple."""
    triples = _TRIPLE.findall(text or "")
    if len(triples) < 2:
        return None
    (x, y, _z), (_r, _p, yaw) = triples[0], triples[1]
    return float(x), float(y), float(yaw)


def judge(reported, truth) -> dict:
    """Errors of `reported` against `truth`, the S1 pass flag and the mirror-lock flag."""
    err_xy = math.dist(reported[:2], truth[:2])
    err_yaw = abs(wrap(reported[2] - truth[2]))
    twin = mirror(truth)
    at_twin = (math.dist(reported[:2], twin[:2]) <= MIRROR_XY_M
               and abs(wrap(reported[2] - twin[2])) <= MIRROR_YAW_RAD)
    return {
        "err_xy_m": round(err_xy, 4),
        "err_yaw_deg": round(math.degrees(err_yaw), 2),
        "ok": err_xy <= XY_TOL_M and err_yaw <= YAW_TOL_RAD,
        "mirror": at_twin and err_xy > MIRROR_XY_M,
    }
