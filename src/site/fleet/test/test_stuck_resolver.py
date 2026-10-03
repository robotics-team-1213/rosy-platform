"""D-438 resolver core: chains, budgets, deadline, rules R1-R3, CORE response handling."""

from fleet.server.stuck_resolver import Answer, Escalate, ResolverConfig, StuckResolver


def _row(robot_id="rosy_01", stuck=None, *, mode="CAMERA_LINE", pose=(0.0, 0.0, 0.0),
         online=True, estop=False):
    state = {"robot_id": robot_id, "safety": {"estop": estop},
             "pose": None if pose is None else {"x": pose[0], "y": pose[1], "yaw": pose[2]},
             "line_follow": {"mode": mode, "state": "HOLD" if stuck else "TRACKING",
                             "stuck": stuck}}
    return {"robot_id": robot_id, "online": online, "state": state}


def _stuck(stuck_id="stuck-1", cause="obstacle_ahead", *, local=True, attempts=0, max_attempts=2):
    return {"stuck_id": stuck_id, "cause": cause, "phase": "ASKING", "local_enabled": local,
            "attempts": attempts, "max_attempts": max_attempts}


def test_r2_backs_off_from_a_static_obstacle_once_per_stuck():
    r = StuckResolver(ResolverConfig())
    first = r.step(0.0, [_row(stuck=_stuck())])
    assert first == [Answer("rosy_01", "stuck-1", "BACK_AND_RETRY", "R2")]
    r.sent(first[0], 0.0)
    assert r.step(1.0, [_row(stuck=_stuck())]) == []          # one answer per stuck


def test_r1_waits_for_a_peer_in_the_front_band():
    r = StuckResolver(ResolverConfig())
    me = _row("rosy_01", _stuck(), pose=(0.0, 0.0, 0.0))
    peer = _row("rosy_02", None, pose=(0.20, 0.03, 3.14))
    assert r.step(0.0, [me, peer]) == [Answer("rosy_01", "stuck-1", "WAIT", "R1")]


def test_r1_ignores_a_peer_behind_or_beside_and_unknown_poses():
    r = StuckResolver(ResolverConfig())
    me = _row("rosy_01", _stuck(), pose=(0.0, 0.0, 0.0))
    behind = _row("rosy_02", None, pose=(-0.20, 0.0, 0.0))
    beside = _row("rosy_03", None, pose=(0.10, 0.40, 0.0))
    assert r.step(0.0, [me, behind, beside])[0].rule == "R2"
    r2 = StuckResolver(ResolverConfig())
    assert r2.step(0.0, [_row("rosy_01", _stuck(), pose=None),
                         _row("rosy_02", None, pose=(0.2, 0.0, 0.0))])[0].rule == "R2"


def test_r3_backs_off_on_lane_lost():
    r = StuckResolver(ResolverConfig())
    assert r.step(0.0, [_row(stuck=_stuck(cause="lane_lost"))]) == [
        Answer("rosy_01", "stuck-1", "BACK_AND_RETRY", "R3")]


def test_no_back_off_without_local_recovery_escalates():
    r = StuckResolver(ResolverConfig())
    assert r.step(0.0, [_row(stuck=_stuck(local=False))]) == [
        Escalate("rosy_01", "stuck-1", "no_rule")]
    assert r.step(1.0, [_row(stuck=_stuck(local=False))]) == []      # escalate once


def test_attempts_exhausted_escalates():
    r = StuckResolver(ResolverConfig())
    assert r.step(0.0, [_row(stuck=_stuck(attempts=2, max_attempts=2))]) == [
        Escalate("rosy_01", "stuck-1", "no_rule")]


def test_chain_budget_counts_restucks_of_any_close_kind():
    r = StuckResolver(ResolverConfig(rule_budget=2, restuck_s=30.0))
    for i, t in ((1, 0.0), (2, 10.0)):
        a = r.step(t, [_row(stuck=_stuck(f"stuck-{i}"))])[0]
        r.sent(a, t)
        r.step(t + 1.0, [_row(stuck=None)])                          # closed (any reason)
    assert r.step(20.0, [_row(stuck=_stuck("stuck-3"))]) == [
        Escalate("rosy_01", "stuck-3", "rule_budget")]


def test_chain_ends_after_restuck_window_or_mode_change():
    r = StuckResolver(ResolverConfig(rule_budget=1, restuck_s=30.0))
    r.sent(r.step(0.0, [_row(stuck=_stuck("stuck-1"))])[0], 0.0)
    r.step(1.0, [_row(stuck=None)])
    assert r.step(40.0, [_row(stuck=_stuck("stuck-2"))])[0].stuck_id == "stuck-2"  # new chain
    r.sent(Answer("rosy_01", "stuck-2", "BACK_AND_RETRY", "R2"), 40.0)
    r.step(41.0, [_row(stuck=None, mode="OFF")])
    assert isinstance(r.step(42.0, [_row(stuck=_stuck("stuck-3"))])[0], Answer)


def test_restuck_after_resolver_resume_goes_to_human():
    r = StuckResolver(ResolverConfig())
    r.sent(Answer("rosy_01", "stuck-1", "RESUME", "R1"), 0.0)
    r.step(0.0, [_row(stuck=_stuck("stuck-1"))])
    r.step(1.0, [_row(stuck=None)])
    assert r.step(5.0, [_row(stuck=_stuck("stuck-2"))]) == [
        Escalate("rosy_01", "stuck-2", "restuck_after_resume")]


def test_deadline_escalates():
    r = StuckResolver(ResolverConfig(escalate_after_s=60.0))
    r.sent(r.step(0.0, [_row(stuck=_stuck())])[0], 0.0)
    assert r.step(61.0, [_row(stuck=_stuck())]) == [Escalate("rosy_01", "stuck-1", "deadline")]


def test_refused_retires_the_rule_and_tries_the_next():
    r = StuckResolver(ResolverConfig())
    me = _row("rosy_01", _stuck(), pose=(0.0, 0.0, 0.0))
    peer = _row("rosy_02", None, pose=(0.20, 0.0, 3.14))
    a = r.step(0.0, [me, peer])[0]
    assert a.rule == "R1"
    r.sent(a, 0.0)
    r.result(a, code="STUCK_DECISION_REFUSED")
    b = r.step(1.0, [me, peer])[0]
    assert (b.decision, b.rule) == ("BACK_AND_RETRY", "R2")


def test_mismatch_forgets_and_other_codes_escalate():
    r = StuckResolver(ResolverConfig())
    a = r.step(0.0, [_row(stuck=_stuck())])[0]
    r.sent(a, 0.0)
    r.result(a, code="STUCK_ID_MISMATCH")
    assert r.step(1.0, [_row(stuck=_stuck())]) == []                 # same id: still answered
    r2 = StuckResolver(ResolverConfig())
    a2 = r2.step(0.0, [_row(stuck=_stuck())])[0]
    r2.sent(a2, 0.0)
    assert r2.result(a2, code="CALIBRATION_ACTIVE") == Escalate("rosy_01", "stuck-1",
                                                               "core:CALIBRATION_ACTIVE")


def test_transport_failure_retries_once_then_escalates():
    r = StuckResolver(ResolverConfig())
    a = r.step(0.0, [_row(stuck=_stuck())])[0]
    r.sent(a, 0.0)
    assert r.result(a, code="ROBOT_UNREACHABLE") is None
    again = r.step(1.0, [_row(stuck=_stuck())])
    assert again == [a]
    r.sent(a, 1.0)
    assert r.result(a, code="ROBOT_UNREACHABLE") == Escalate("rosy_01", "stuck-1",
                                                            "core:ROBOT_UNREACHABLE")


def test_human_claim_silences_the_resolver():
    r = StuckResolver(ResolverConfig())
    r.claim("rosy_01", "stuck-1")
    assert r.step(0.0, [_row(stuck=_stuck())]) == []


def test_offline_and_estop_robots_are_left_alone():
    r = StuckResolver(ResolverConfig())
    assert r.step(0.0, [_row(stuck=_stuck(), online=False)]) == []
    assert r.step(0.0, [_row(stuck=_stuck(), estop=True)]) == [
        Escalate("rosy_01", "stuck-1", "estop")]
