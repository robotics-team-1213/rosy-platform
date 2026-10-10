"""D-577 (d) deterministic analyzers for the stuck causes seen on the field (2026-10-10).

Facts only (D-577 3): what the AI PC sees, never what to do. Input is the polled Fleet snapshot
(``state``, ``line_stuck``); no frames, no robot access. Same snapshot sequence, same facts.

- ``rear_blocked``: the robot's rear is not clear for a back-off. Evidence is CORE's own word: an open
  stuck's ``rear_state: blocked`` (hub event) or a refused back-off ``rear_blocked`` that the robot has
  not moved away from since (odom within ``MOVED_M``).
- ``path_blocked_by_robot``: a stuck robot has a peer's body in its front band, on D-395 trusted map
  poses only (an odom pose of another robot is another frame, so LEGACY poses never count).
- ``stalled``: line following on, no open stuck, zero command and no movement for ``STALL_S``: a HOLD
  CORE does not report (low light / over-exposure, D-407 keeps those out of the 5 s report).

Proposals (D-577 개정 2026-10-10, 사용자: "AI PC 제안 → Fleet 검증 후 실행"): for each open stuck one CORE word
with its reason. A blocked rear or a robot ahead proposes WAIT (Fleet then hands the stuck to a person);
otherwise BACK_AND_RETRY, which Fleet forwards only when its preconditions hold and CORE re-checks.
"""

from __future__ import annotations

import math
from typing import Optional

VERSION = "1"
SOURCE = f"analyzer:stuck_scene@{VERSION}"
TTL_S = 3.0
MOVED_M = 0.05            # same as D-577 (d) stalled / waiting_but_moving
STALL_S = 20.0            # D-577 (d) stalled
REFUSAL_KEEP_S = 120.0
# Fleet resolver R1 band (ResolverConfig): reach 0.30 + peer radius 0.083, half width 0.15.
BAND_AHEAD_M, BAND_HALF_M = 0.383, 0.15


def _pose(row: dict) -> Optional[tuple[float, float, float]]:
    pose = (row.get("state") or {}).get("pose") or {}
    try:
        return float(pose["x"]), float(pose["y"]), float(pose.get("yaw") or 0.0)
    except (KeyError, TypeError, ValueError):
        return None


def _map_pose(row: dict):
    """Trusted map pose only: localization reported (not LEGACY odom) and trusted (D-395)."""
    badge = row.get("localization") or {}
    if not row.get("online") or badge.get("trusted") is not True or badge.get("legacy") is not False:
        return None
    return _pose(row)


class Analyzer:
    def __init__(self) -> None:
        self._refused: dict[str, tuple[float, tuple, str]] = {}   # robot -> (at, odom pose, answer ref)
        self._still: dict[str, tuple[float, tuple]] = {}           # robot -> (since, odom pose)
        self._seen: set[str] = set()
        self._primed = False
        self._proposed: set[tuple] = set()
        self.proposals: list[dict] = []            # this cycle's new proposals (service posts them)

    def __call__(self, snapshot: dict) -> list[dict]:
        now = float(snapshot.get("observed_at") or 0.0)
        rows = [r for r in (snapshot.get("state") or {}).get("robots") or [] if r.get("robot_id")]
        by_id = {str(r["robot_id"]): r for r in rows}
        pending = {str(p.get("robot_id")): p for p in (snapshot.get("line_stuck") or {}).get("pending") or []}
        facts: list[dict] = []

        def fact(kind, robot_ids, value, confidence, evidence):
            facts.append({"kind": kind, "robot_ids": robot_ids, "value": value, "confidence": confidence,
                          "evidence": evidence, "source": SOURCE, "observed_at": now, "ttl_s": TTL_S})

        for answer in (snapshot.get("line_stuck") or {}).get("answers") or []:
            ref = f"{answer.get('robot_id')}/{answer.get('stuck_id')}@{answer.get('at')}"
            if ref in self._seen:
                continue
            self._seen.add(ref)       # ponytail: grows by one per Fleet answer; restart clears it
            rid = str(answer.get("robot_id"))
            if (self._primed and "rear_blocked" in str(answer.get("message") or "") and rid in by_id
                    and _pose(by_id[rid]) is not None):
                self._refused[rid] = (now, _pose(by_id[rid]), ref)
        self._primed = True           # answers already in Fleet at start are history, not news
        for rid, row in by_id.items():
            stuck = pending.get(rid)
            pose = _pose(row)
            # rear_blocked
            if stuck is not None and stuck.get("rear_state") == "blocked":
                fact("rear_blocked", [rid], {"rear_clearance_m": stuck.get("rear_clearance_m")}, 0.9,
                     {"stuck_id": stuck.get("stuck_id"), "rear_state": "blocked"})
            elif rid in self._refused:
                at, where, ref = self._refused[rid]
                if (pose is None or now - at > REFUSAL_KEEP_S
                        or math.hypot(pose[0] - where[0], pose[1] - where[1]) > MOVED_M):
                    del self._refused[rid]
                else:
                    fact("rear_blocked", [rid], {"refused_back_off": True}, 0.8, {"core_refusal": ref})
            # path_blocked_by_robot
            me = _map_pose(row)
            if stuck is not None and me is not None:
                c, s = math.cos(me[2]), math.sin(me[2])
                for oid, other in by_id.items():
                    peer = _map_pose(other) if oid != rid else None
                    if peer is None:
                        continue
                    dx, dy = peer[0] - me[0], peer[1] - me[1]
                    ahead, side = c * dx + s * dy, -s * dx + c * dy
                    if 0.0 < ahead <= BAND_AHEAD_M and abs(side) <= BAND_HALF_M:
                        fact("path_blocked_by_robot", [rid, oid], {"ahead_m": round(ahead, 3)}, 0.8,
                             {"stuck_id": stuck.get("stuck_id"), "pose": "map_trusted"})
                        break
            # stalled
            lf = (row.get("state") or {}).get("line_follow") or {}
            moving = abs(float(lf.get("linear") or 0.0)) > 1e-6 or abs(float(lf.get("angular") or 0.0)) > 1e-6
            if (lf.get("mode") in (None, "OFF") or lf.get("stuck") or stuck is not None or moving
                    or pose is None or not row.get("online")):
                self._still.pop(rid, None)
                continue
            since, where = self._still.setdefault(rid, (now, pose))
            if math.hypot(pose[0] - where[0], pose[1] - where[1]) > MOVED_M:
                self._still[rid] = (now, pose)
            elif now - since >= STALL_S:
                fact("stalled", [rid], {"reason": lf.get("reason"), "state": lf.get("state"),
                                        "still_s": round(now - since, 1)}, 0.9, {"line_follow_mode": lf.get("mode")})
        self.proposals = []
        for rid, stuck in pending.items():
            cause, sid = stuck.get("cause"), stuck.get("stuck_id")
            if cause not in ("lane_lost", "no_motion", "obstacle_ahead") or not sid:
                continue
            kinds = {f["kind"] for f in facts if f["robot_ids"][0] == rid}
            if "rear_blocked" in kinds:
                decision, reason, confidence = "WAIT", "rear_blocked", 0.8
            elif "path_blocked_by_robot" in kinds:
                decision, reason, confidence = "WAIT", "robot_ahead", 0.8
            else:
                decision, reason, confidence = "BACK_AND_RETRY", f"{cause}_back_off", 0.6
            key = (rid, sid, decision, reason)
            if key in self._proposed:
                continue
            self._proposed.add(key)                  # ponytail: one entry per proposal; restart clears it
            self.proposals.append({"robot_id": rid, "stuck_id": sid, "decision": decision, "reason": reason,
                                   "confidence": confidence, "source": SOURCE, "observed_at": now, "ttl_s": 6.0,
                                   "evidence": {"cause": cause, "detail": stuck.get("detail"),
                                                "facts": sorted(kinds)}})
        return facts
