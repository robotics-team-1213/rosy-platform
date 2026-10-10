"""D-577 1 lane_lost rules for the Fleet stuck resolver: R3 preconditions and R5 hold reasons.

Pure, split out of stuck_resolver.py (size budget); StuckResolver._rule calls lane_lost_hold.
"""

from __future__ import annotations

from typing import Iterable, Mapping, Optional

from fleet.server.stuck_resolver import ResolverConfig, _map_pose, _peer_in_band


def lane_lost_hold(row, stuck, rows, chain, config: ResolverConfig, rule: str = "R3") -> Optional[str]:
    """D-577 1: why R3 may not back off (the R5 reason), or None when every precondition holds.

    The rear clearance, blind spot and travelled path stay CORE's re-check (D-407 §4)."""
    if not stuck.get("local_enabled"):
        return "local_disabled"
    if int(stuck.get("attempts") or 0) >= int(stuck.get("max_attempts") or 0):
        return "attempts"
    if rule in chain.retired:
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
    if behind is None and rule != "R6":
        # D-577 개정 2026-10-10: a no_motion stuck (R6) is not held for an unknown peer pose; CORE's
        # D-407 body re-check (rear clearance, blind band, trail) before and during the back-off decides.
        return "peer_unknown"
    if behind:
        return "peer_behind"
    return None


def peer_behind(row: Mapping, rows: Iterable[Mapping], config: ResolverConfig) -> Optional[bool]:
    """D-577 1: R1's band mirrored behind the robot, on trusted map poses (D-395) only.

    None = an online peer exists and this robot's or a peer's pose is missing, untrusted or
    LEGACY (no `localization`: an odom pose, not the painted map; D-577 남은 항목 1, closed
    2026-10-10): R3 must not back off blind. No online peer = False."""
    others = [other for other in rows if other is not row and other.get("online", True)]
    if not others:
        return False
    return _peer_in_band(row, others, config, -1.0, pose_of=_trusted_map_pose, strict=True)


def _trusted_map_pose(row: Mapping):
    from fleet.localization.trust import LEGACY, classify

    state = row.get("state")
    if not isinstance(state, Mapping) or classify(state) == LEGACY:
        return None
    return _map_pose(row)


#: D-577 개정 2026-10-10: the CORE words an AI PC proposal may carry per stuck cause. YIELD needs Fleet's
#: meet geometry and MANUAL hands the robot to a person: neither comes from the AI PC. RESUME never on a
#: lost lane (D-438 §3). A trip robot takes only WAIT (D-517 5). crosswalk_blocked is a person's (D-573).
AI_WORDS = {"lane_lost": ("WAIT", "BACK_AND_RETRY", "ABORT"), "no_motion": ("WAIT", "BACK_AND_RETRY", "ABORT"),
            "obstacle_ahead": ("WAIT", "BACK_AND_RETRY", "RESUME", "ABORT")}


def ai_proposal_invalid(proposal, row, stuck, rows, chain, config: ResolverConfig) -> Optional[str]:
    """Why Fleet refuses this proposal (then its rules answer), or None to forward it to CORE."""
    cause, decision = stuck.get("cause"), proposal["decision"]
    if row.get("trip") and decision != "WAIT":
        return "trip"
    if decision not in AI_WORDS.get(cause, ()):
        return "word_not_allowed"
    if "ai" in chain.retired:
        return "core_refused_before"
    if decision != "BACK_AND_RETRY":
        return None
    if stuck.get("rear_state") == "blocked":
        return "rear_blocked"
    if cause == "obstacle_ahead":
        if not stuck.get("local_enabled"):
            return "local_disabled"
        if int(stuck.get("attempts") or 0) >= int(stuck.get("max_attempts") or 0):
            return "attempts"
        if chain.rule_answers >= config.rule_budget:
            return "rule_budget"
        if ((row.get("state") or {}).get("line_follow") or {}).get("crosswalk") is not None:
            return "crosswalk"
        return "peer_behind" if peer_behind(row, rows, config) else None
    return lane_lost_hold(row, stuck, rows, chain, config, rule="R3" if cause == "lane_lost" else "R6")
