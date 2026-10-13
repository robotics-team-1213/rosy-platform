"""D-674: automatic law -> existing rule/AI candidate -> dispatch admission.

CORE remains the final writer; loop/closed_loop own dispatch and readback.
"""


def selection_receipt(assessment, action, *, source_sha256, config_sha256, mixed):
    from dataclasses import asdict
    import json
    from fleet.stuck.resolver import Answer, Escalate, Hold
    from rosy.contracts.learning.incident_rule import validate_rule
    if type(mixed) is not bool or action is not None and not isinstance(action, (Answer, Escalate)):
        raise ValueError('INVALID_ACTUAL_RULE_SELECTION')
    request = assessment.request
    if action is not None and (action.robot_id, action.stuck_id) != (request.subject_id, request.case_id):
        raise ValueError('RULE_SELECTION_SCOPE_CHANGED')
    selection = dict(kind='NONE', rule=None, decision=None, reason=None, yield_m=None, yield_turn_rad=None)
    if isinstance(action, Answer):
        selection.update(kind='ANSWER', rule=action.rule, decision=action.decision, reason=action.escalate,
                         yield_m=action.yield_m, yield_turn_rad=action.yield_turn_rad)
        if action.realign is not None:             # D-622: bind the manoeuvre body without copying its pose
            from hashlib import sha256
            selection['realign_sha256'] = sha256(json.dumps(
                action.realign, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
        mixed = mixed or action.rule == 'ai'
    elif isinstance(action, Escalate):
        selection.update(kind='HOLD' if isinstance(action, Hold) else 'HANDOFF', reason=action.reason)
    return validate_rule(dict(schema='rosy.incident.rule_selection/1',
        assessment=json.loads(json.dumps(asdict(assessment))), selection=selection,
        source_sha256=source_sha256, config_sha256=config_sha256, strategy='MIXED' if mixed else 'RULE_ONLY',
        verification='selected_not_executed', action_admissible=False, outcome=None))


def law_hold(row, *, decision=None, stuck_id=None):
    """First non-overridable automatic-dispatch refusal; None permits the next stage."""
    if row is None or not row.get("online", True):
        return "offline"
    state = row.get("state") or {}
    if (state.get("safety") or {}).get("estop"):
        return "estop"
    if state.get("activity"):
        return "calibration"
    if stuck_id is not None:
        stuck = (state.get("line_follow") or {}).get("stuck") or {}
        if stuck.get("stuck_id") != stuck_id:
            return "stuck_changed"
    if row.get("trip") and decision is not None and decision != "WAIT":
        return "trip"
    return None


def ai_hold(resolver, answer, selected, current, rows):
    """Revalidate the original AI candidate after admission awaits; WAIT retains its human handoff."""
    from fleet.stuck import ai_first, lane_lost

    if answer.rule != "ai" or answer.decision == "WAIT":
        return None
    proposal = (selected or {}).get("ai_proposal")
    if not proposal or proposal != current.get("ai_proposal"):
        return "ai_proposal_changed"
    rid, first = answer.robot_id, resolver.ai_first
    vlm = str(proposal.get("source", "")).startswith("vlm:")
    if vlm and (first is None or not first.on(rid)):
        return "ai_disabled"
    stuck = current["state"]["line_follow"]["stuck"]
    if first is not None and first.on(rid):
        key = ai_first.problem_key(current, "stuck", stuck.get("cause"), resolver.at_crosswalk(rid))
        if key in first.human_classes():
            return f"human_class:{key}"
        if vlm:
            invalid = first.evidence_invalid(proposal, rid)
            if invalid is not None:
                return invalid
    chain = resolver._chains.get(rid)
    if chain is None:
        return "stuck_changed"
    if not vlm:
        return lane_lost.ai_proposal_invalid(proposal, current, stuck, rows, chain,
                                             resolver.config, resolver._painted())
    verdict, candidate = ai_first._check(resolver, first, proposal, current, stuck, rows, chain,
                                         chain.started_at, 0.0, [], counted=True)
    if verdict != "forwarded":
        return verdict
    return None if candidate == answer else "ai_candidate_changed"


def candidate(resolver, now, row, stuck, rows, chain):
    """Existing D-577/D-610 selection, after the resolver's law and lifecycle checks."""
    from fleet.stuck.ai_first import ai_answer
    from fleet.stuck.resolver import Answer, LOST_LIKE

    rid, sid = str(row["robot_id"]), str(stuck["stuck_id"])
    if stuck.get("cause") in LOST_LIKE and resolver.at_crosswalk(rid):
        return Answer(rid, sid, "WAIT", "R5", escalate="crosswalk_human")
    if rid in resolver.realign.robots:                # D-622: standalone REALIGN, CORE re-checks
        held = chain.held.get(sid) or ""
        if held.startswith("realign_hold:"):          # the hold WAIT was sent but never handed over
            return resolver._escalate(chain, rid, sid, held)
        from fleet.stuck.realign import select
        realign, why = select(row, rows, resolver.realign, now=resolver._wall(),
                              attempt=chain.realign_attempts+1)
        if ("R9" in chain.retired or chain.rule_answers >= resolver.config.rule_budget
                or resolver.at_crosswalk(rid)):
            realign, why = None, "realign_budget_or_crosswalk"
        if realign is None:
            if chain.observing is not None:           # re-observation sends no WAIT: hand over directly
                return resolver._escalate(chain, rid, sid, f"realign_hold:{why}")
            return Answer(rid, sid, "WAIT", "R5", escalate=f"realign_hold:{why}")
        return Answer(rid, sid, "REALIGN", "R9", realign=realign)
    proposed = ai_answer(resolver, now, row, stuck, rows, chain)
    if proposed is not None:
        return None if proposed == "wait" else proposed
    rule = resolver._rule(row, stuck, rows, chain)
    ai = next((fact["kind"] for fact in row.get("ai_facts") or ()), None)
    if ai is not None and rule is not None and rule[1] == "BACK_AND_RETRY":
        rule = ("R5", "WAIT", f"ai:{ai}")
    if rule is not None and rule[1] == "ESCALATE":
        return resolver._escalate(chain, rid, sid, "meet")
    if rule is not None and rule[1] == "RESUME":
        rule = ("meet", "WAIT")  # Resume only after a completed meet segment.
    if rule is None:
        return resolver._escalate(chain, rid, sid, "no_rule")
    if rid in resolver.autonomous_robots and rule[1] in chain.unresolved:
        return resolver._escalate(chain, rid, sid, "unresolved:" + rule[1])
    if rule[0] == "R5":
        return Answer(rid, sid, "WAIT", "R5", escalate=f"{stuck.get('cause')}_hold:{rule[2]}")
    if chain.rule_answers >= resolver.config.rule_budget and chain.retries.get(sid) != 1:
        return resolver._escalate(chain, rid, sid, "rule_budget")
    if stuck.get("cause") in LOST_LIKE and rule[1] not in ("WAIT", "BACK_AND_RETRY"):
        return resolver._escalate(chain, rid, sid, "no_rule")
    if len(rule) == 4:
        return Answer(rid, sid, rule[1], rule[0], yield_m=rule[3], yield_turn_rad=rule[2])
    return Answer(rid, sid, rule[1], rule[0])
