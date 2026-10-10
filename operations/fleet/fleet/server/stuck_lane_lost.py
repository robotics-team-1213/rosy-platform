"""D-577 1 lane_lost rules for the Fleet stuck resolver: R3 preconditions and R5 hold reasons.

Pure, split out of stuck_resolver.py (size budget); StuckResolver._rule calls lane_lost_hold.
"""

from __future__ import annotations

from typing import Iterable, Mapping, Optional

from fleet.server.stuck_resolver import Answer, ResolverConfig, _map_pose, _peer_in_band, peer_ahead
from fleet.site_map import _inside, _point_segment

#: D-573 1 / D-577 1: R3 holds within this of a site-map crosswalk. Robot URDF rear 0.076 m + the
#: D-407 back-off cap 0.20 m, with the 0.057 m half width (hypot 0.282), rounded up.
# ponytail: one body size for every robot, as ResolverConfig.peer_band_half_width_m.
CROSSWALK_REACH_M = 0.29


def lane_lost_hold(row, stuck, rows, chain, config: ResolverConfig, rule: str = "R3", *,
                   painted=None) -> Optional[str]:
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
    # D-573 6 개정 2026-10-10: CORE reports `line_follow.crosswalk` null outside every zone, a mapping
    # near one and `state: unknown` when it cannot know. Absent = an older CORE: fail closed.
    line_follow = (row.get("state") or {}).get("line_follow") or {}
    if "crosswalk" not in line_follow:
        return "crosswalk_unknown"
    if line_follow["crosswalk"] is not None:
        crosswalk = line_follow["crosswalk"]
        return "crosswalk_unknown" if isinstance(crosswalk, Mapping) and crosswalk.get("state") == "unknown" else "crosswalk"
    pose = row.get("map_pose")                    # set by the loop from the Fleet map pose service
    # UNKNOWN passes only for a robot Fleet never had a sighting source for; a lost pose holds.
    if isinstance(pose, Mapping) and (pose.get("state") != "UNKNOWN" or pose.get("sourced") is not False):
        age = pose.get("age_s")
        if (pose.get("state") != "LOCALIZED" or not isinstance(age, (int, float))
                or not 0.0 <= age <= config.pose_max_age_s):
            return "pose"
    # D-573 1: the site-map crosswalk is the reference, CORE's camera only confirms. Measured on the
    # trusted map pose (D-395); without one, or with no Fleet sighting source, Fleet cannot tell.
    if painted is not None and painted.crosswalks:
        me = _trusted_map_pose(row)
        if me is None or (isinstance(pose, Mapping) and pose.get("state") == "UNKNOWN"):
            return "crosswalk_unknown"
        if any(_inside(me[:2], polygon) or min(_point_segment(me[:2], a, b) for a, b in zip(
                polygon, polygon[1:] + polygon[:1])) <= CROSSWALK_REACH_M for polygon in painted.crosswalks):
            return "crosswalk"
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
#: meet geometry and MANUAL hands the robot to a person: neither comes from the AI PC. RESUME never: the
#: rules never RESUME a stuck and the AI is stricter (Safety-Review 2026-10-10). A trip robot takes only
#: WAIT (D-517 5). crosswalk_blocked is a person's (D-573).
AI_WORDS = {cause: ("WAIT", "BACK_AND_RETRY", "ABORT") for cause in ("lane_lost", "no_motion", "obstacle_ahead")}


def ai_proposal_invalid(proposal, row, stuck, rows, chain, config: ResolverConfig, painted=None) -> Optional[str]:
    """Why Fleet refuses this proposal (then its rules answer), or None to forward it to CORE.

    Safety-Review 2026-10-10 (user: keep AI acting, strengthen the checks): the AI may only make Fleet more
    restrictive. WAIT always passes the envelope. ABORT (lane following off, IDLE) only outside a crosswalk
    zone CORE reports (an idle robot in a zone is a person's, D-573). BACK_AND_RETRY only when every R3
    precondition holds (strict: no R6 peer waiver), no acting AI fact is live for the robot, the rear is not
    ``blocked`` and, with a peer ahead, R1 was tried first. RESUME is not an AI word."""
    cause, decision = stuck.get("cause"), proposal["decision"]
    if row.get("trip") and decision != "WAIT":
        return "trip"
    if decision not in AI_WORDS.get(cause, ()):
        return "word_not_allowed"
    if "ai" in chain.retired:
        return "core_refused_before"
    if decision == "WAIT":
        return None
    line_follow = (row.get("state") or {}).get("line_follow") or {}
    if "crosswalk" not in line_follow:
        return "crosswalk_unknown"
    if line_follow["crosswalk"] is not None:            # D-573 6: CORE `state: unknown` is not "outside"
        crosswalk = line_follow["crosswalk"]
        return "crosswalk_unknown" if isinstance(crosswalk, Mapping) and crosswalk.get("state") == "unknown" \
            else "crosswalk"
    if decision == "ABORT":
        return None
    fact = next((fact["kind"] for fact in row.get("ai_facts") or ()), None)
    if fact is not None:
        return f"ai_fact:{fact}"
    if stuck.get("rear_state") == "blocked":          # BACK_AND_RETRY from here on
        return "rear_blocked"
    if cause == "obstacle_ahead" and "R1" not in chain.retired and peer_ahead(row, rows, config):
        return "peer_ahead"                           # the rules send R1 WAIT first
    return lane_lost_hold(row, stuck, rows, chain, config, rule="R3", painted=painted)


def ai_answer(resolver, now, row, stuck, rows, chain):
    """D-577 개정 2026-10-10: the AI PC proposes, Fleet checks the envelope, CORE re-checks.

    An Answer for a valid proposal, "wait" while an acting robot's AI PC still has time, or None: the
    rules answer. Every judged proposal goes to ``resolver.ai_verdicts`` (audit), each one only once."""
    rid, sid = str(row["robot_id"]), str(stuck["stuck_id"])
    proposal = row.get("ai_proposal")
    if proposal is not None and proposal["stuck_id"] != sid:
        _judge(resolver, chain, proposal, now, "stuck_mismatch")
        proposal = None
    if proposal is None:
        waiting = row.get("ai_wait") and now - chain.seen_at < resolver.config.ai_wait_s
        return "wait" if waiting else None
    verdict = _judge(resolver, chain, proposal, now, None, row, stuck, rows)
    if verdict is not None and verdict != "forwarded" and proposal["decision"] == "ABORT":
        # Safety-Review 2026-10-10: the AI wanted the robot stopped; a held ABORT stops it (R5 WAIT) and hands
        # it to a person instead of letting the rules move it in the same tick.
        return Answer(rid, sid, "WAIT", "R5", escalate=f"ai_abort_held:{verdict}")
    if verdict != "forwarded":
        return None
    decision = proposal["decision"]
    # A WAIT holds and an ABORT idles the robot: both also raise the human row (D-577 1 R5 shape).
    escalate = {"WAIT": "ai_wait", "ABORT": "ai_abort"}.get(decision)
    return Answer(rid, sid, decision, "ai", escalate=f"{escalate}:{proposal['reason']}" if escalate else None)


def ai_late(resolver, now, row, chain) -> None:
    """A proposal for a stuck already answered (or yielding): audit it, act on nothing."""
    proposal = row.get("ai_proposal")
    if proposal is not None:
        _judge(resolver, chain, proposal, now, "after_answer")


def _judge(resolver, chain, proposal, now, verdict, row=None, stuck=None, rows=None) -> Optional[str]:
    key = (proposal["stuck_id"], proposal["decision"], proposal["reason"])
    if key in chain.ai_judged:
        return None
    chain.ai_judged.add(key)
    if verdict is None:
        verdict = ai_proposal_invalid(proposal, row, stuck, rows, chain, resolver.config,
                                      resolver._painted()) or "forwarded"
    resolver.ai_verdicts.append({**proposal, "verdict": verdict, "judged_at": now})
    return verdict
