"""D-577 1 lane_lost rules for the Fleet stuck resolver: R3 preconditions and R5 hold reasons.

Pure, split out of stuck_resolver.py (size budget); StuckResolver._rule calls lane_lost_hold.
"""

from __future__ import annotations

from typing import Iterable, Mapping, Optional

from fleet.server.stuck_resolver import ResolverConfig, _map_pose, _peer_in_band


def lane_lost_hold(row, stuck, rows, chain, config: ResolverConfig) -> Optional[str]:
    """D-577 1: why R3 may not back off (the R5 reason), or None when every precondition holds.

    The rear clearance, blind spot and travelled path stay CORE's re-check (D-407 §4)."""
    if not stuck.get("local_enabled"):
        return "local_disabled"
    if int(stuck.get("attempts") or 0) >= int(stuck.get("max_attempts") or 0):
        return "attempts"
    if "R3" in chain.retired:
        return "refused"
    if chain.rule_answers >= config.rule_budget:
        return "rule_budget"
    # D-573: CORE reports `line_follow.crosswalk` null outside a zone and a mapping inside one.
    # Absent = this CORE does not report it (none does yet): fail closed.
    line_follow = (row.get("state") or {}).get("line_follow") or {}
    if "crosswalk" not in line_follow:
        return "crosswalk_unknown"
    if line_follow["crosswalk"] is not None:
        return "crosswalk"
    pose = row.get("map_pose")                    # set by the loop from the Fleet map pose service
    # UNKNOWN passes only for a robot Fleet never had a sighting source for; a lost pose holds.
    if isinstance(pose, Mapping) and (pose.get("state") != "UNKNOWN" or pose.get("sourced") is not False):
        age = pose.get("age_s")
        if (pose.get("state") != "LOCALIZED" or not isinstance(age, (int, float))
                or not 0.0 <= age <= config.pose_max_age_s):
            return "pose"
    behind = peer_behind(row, rows, config)
    if behind is None:
        return "peer_unknown"
    if behind:
        return "peer_behind"
    return None


def peer_behind(row: Mapping, rows: Iterable[Mapping], config: ResolverConfig) -> Optional[bool]:
    """D-577 1: R1's band mirrored behind the robot, on trust-gated map poses (D-395) only.

    None = an online peer exists and this robot's or a peer's pose is missing or untrusted:
    R3 must not back off blind (safety review 2026-10-09). No online peer = False."""
    others = [other for other in rows if other is not row and other.get("online", True)]
    if not others:
        return False
    return _peer_in_band(row, others, config, -1.0, pose_of=_map_pose, strict=True)
