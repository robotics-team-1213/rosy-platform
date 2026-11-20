"""SLAM health: classify a stream of samples as ok / degraded / lost, with hysteresis (pure; no ROS, no motion).

It only returns a state and the reasons; it never stops, restarts or switches anything. What to do about
"lost" (stop first, Fleet-gated restart on the site wall map) is a separate decision (SLAM fallback ADR).

Every threshold below is an UNMEASURED proposal taken from the panel of 2026-11-18. Tune them from logged real SLAM
runs (including a deliberate map re-save and a kidnapped robot) before anything acts on this verdict.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

OK, DEGRADED, LOST = "ok", "degraded", "lost"
_RANK = {OK: 0, DEGRADED: 1, LOST: 2}

JUMP_M = 0.10            # map->odom correction between updates that nobody commanded
AGREEMENT_MIN = 0.7      # scan-to-wall agreement fraction at the SLAM pose (D-395 monitor uses 0.85 at 4 cm)
GAP_M = 0.30             # slam_camera_gap_m (D-1022); coarse on purpose, the camera is itself off by about 0.33 m
LOST_CONSECUTIVE = 3     # a lost condition must hold this many samples in a row
RECOVER_CONSECUTIVE = 10  # good samples in a row before leaving degraded / lost
MIN_DWELL_S = 60.0       # no state change sooner than this after the last one, except going to lost


@dataclass(frozen=True)
class Sample:
    t: float                                  # seconds, increasing
    map_verdict: Optional[str] = None         # tools/capture/map_health verdict: ok / warn / fail
    agreement: Optional[float] = None         # 0..1
    jump_m: Optional[float] = None            # map->odom correction since the last sample
    gap_m: Optional[float] = None             # slam_camera_gap_m
    moving: bool = False                      # the robot is being commanded to move: a correction then is expected


@dataclass(frozen=True)
class Health:
    state: str
    reasons: tuple[str, ...] = ()


class SlamHealth:
    def __init__(self) -> None:
        self.state, self._reasons = OK, ()
        self._changed_at: Optional[float] = None
        self._run = {"map_odom_jump": 0, "scan_wall_agreement_low": 0, "slam_camera_gap": 0}
        self._good = 0

    def update(self, s: Sample) -> Health:
        if all(v is None for v in (s.map_verdict, s.agreement, s.jump_m, s.gap_m)):
            return Health(self.state, self._reasons)  # no evidence is neither bad nor good
        bad = {"map_odom_jump": s.jump_m is not None and s.jump_m > JUMP_M and not s.moving,
               "scan_wall_agreement_low": s.agreement is not None and s.agreement < AGREEMENT_MIN,
               "slam_camera_gap": s.gap_m is not None and s.gap_m > GAP_M}
        seen = {"map_odom_jump": s.jump_m is not None, "scan_wall_agreement_low": s.agreement is not None,
                "slam_camera_gap": s.gap_m is not None}
        for key, is_bad in bad.items():
            if is_bad:
                self._run[key] += 1
            elif seen[key]:  # a field a sample does not carry leaves its run alone
                self._run[key] = 0
        lost = tuple(k for k, n in self._run.items() if n >= LOST_CONSECUTIVE)
        map_fail = s.map_verdict == "fail"
        self._good = 0 if map_fail or any(bad.values()) else self._good + 1
        target, reasons = (LOST, lost) if lost else (DEGRADED, ("map_verdict_fail",)) if map_fail else (OK, ())
        waited = self._changed_at is None or s.t - self._changed_at >= MIN_DWELL_S
        if _RANK[target] > _RANK[self.state]:
            if target == LOST or waited:  # worse is never held back for going to lost
                self._move(target, reasons, s.t)
        elif self.state != OK and self._good >= RECOVER_CONSECUTIVE and waited:
            self._move(OK, (), s.t)
        elif target == self.state:
            self._reasons = reasons
        return Health(self.state, self._reasons)

    def _move(self, state: str, reasons: tuple[str, ...], t: float) -> None:
        self.state, self._reasons, self._changed_at = state, reasons, t


def classify(samples: Iterable[Sample]) -> list[Health]:
    """The verdict after each sample of a stream, starting from ok."""
    tracker = SlamHealth()
    return [tracker.update(s) for s in samples]
