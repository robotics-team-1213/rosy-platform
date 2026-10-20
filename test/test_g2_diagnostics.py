"""G2 terminal evidence stays observational and distinguishes known watchdog facts."""
import json
from pathlib import Path
import sys
import threading
import time
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).parents[1] / "deploy/robot/omx"))
GOAL = "11111111-1111-4111-8111-111111111111"


def event(kind="TERMINAL_UNKNOWN", *, sequence=21, command_id="cell-transfer", goal_id=GOAL):
    return NS(kind=kind, command_id=command_id, phase_id="transfer", goal_id=goal_id,
              sequence=sequence, observed_at_monotonic_s=101.5)


def runtime(reason="joint_state_stale", *, state="hold", command_id="cell-transfer", done=True):
    decision = NS(accepted=False, state=state, reason=reason, command_id=command_id,
                  cancel_outcome="requested", credentials="DO_NOT_RECORD")
    owner = NS(state=state, _state=state, _hold_reason=reason, _joint_state_wall=99.0,
               config=NS(max_joint_state_age_s=.5, action_timeout_s=45.0,
                         wall_clock_bound_factor=4.0, max_goal_duration_s=40.0),
               recovery_state=lambda: {"state": state, "reason": reason, "observed_sequence": 1231})
    handle = NS(done=lambda: done, status=None, cancel_acknowledged=None,
                _done=done, _status=None, _cancel_acknowledged=None)
    return NS(last_decision=decision, last_terminal_decision=decision, owner=owner,
              owner_clock="sim", monotonic=lambda: 43.5,
              latest_joint_state=NS(sequence=1231, received_at=42.9, positions={"joint1": .25}),
              _joint_state_intake=NS(_last_stamp_ns=42900000000), action_port=NS(last_handle=handle),
              credentials={"token": "DO_NOT_RECORD"})


def test_watchdog_terminal_keeps_matching_owner_reason_and_clock_snapshot(tmp_path):
    from g2_diagnostics import TerminalDiagnostics
    diagnostics = TerminalDiagnostics(tmp_path, wall_clock=lambda: 1000.0, steady_clock=lambda: 101.6)
    assert diagnostics.observe(event(), runtime()) is True
    assert diagnostics.close(timeout=1)
    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1
    value = json.loads(files[0].read_text())
    assert value["cause_classification"] == "WATCHDOG_DECISION"
    assert value["last_decision"]["reason"] == "joint_state_stale"
    assert value["event"]["goal_id"] == GOAL and value["event"]["phase_id"] == "transfer"
    assert value["clocks"] == {"owner": 43.5, "owner_clock": "sim", "steady": 101.6, "wall": 1000.0}
    assert value["joint_state"] == {"sequence": 1231, "received_at": 42.9,
                                    "positions": {"joint1": .25}, "positions_truncated": False}
    assert value["owner_joint_state_wall"] == 99.0
    assert value["last_source_stamp_ns"] == 42900000000
    assert value["bounds"] == {"max_joint_state_age_s": .5, "action_timeout_s": 45.0,
                               "wall_clock_bound_factor": 4.0, "max_goal_duration_s": 40.0}
    assert value["handle"]["done"] is True
    assert "DO_NOT_RECORD" not in files[0].read_text()


def test_active_unknown_does_not_invent_a_watchdog_cause(tmp_path):
    from g2_diagnostics import TerminalDiagnostics
    observed = runtime("active", state="active", done=False)
    observed.last_terminal_decision = runtime(command_id="previous-command").last_terminal_decision
    diagnostics = TerminalDiagnostics(tmp_path)
    assert diagnostics.observe(event(), observed)
    assert diagnostics.close(timeout=1)
    value = json.loads(next(tmp_path.glob("*.json")).read_text())
    assert value["cause_classification"] == "UNRESOLVED_ROS_EVENT"
    assert value["last_decision"]["reason"] == "active"
    assert value["handle"]["done"] is False


def test_watchdog_transition_keeps_decision_time_separate_from_later_snapshots(tmp_path):
    from g2_diagnostics import TerminalDiagnostics
    actual = runtime()
    actual.owner.watchdog_observation = NS(reason='joint_state_stale', command_id='cell-transfer',
        command_id_truncated=False, owner_now=42.6, owner_now_steady_before=99.95,
        owner_now_steady_after=99.96, steady_now=100.0, joint_sequence=1200,
        joint_received_at=42.0, source_age_s=.6, joint_wall=99.4, active_started_at=35.,
        active_wall=92.4, wall_now=None, max_joint_state_age_s=.5, action_timeout_s=45.,
        wall_clock_bound_factor=4., credentials='PRIVATE', intake=NS(stamp_ns=42600000000,
            source_now_ns=42000000000, received_at=42., callback_entered_steady=99.8,
            intake_received_steady=99.9, intake_observed_steady=99.91, accepted=False,
            intake_sequence=1200, rejection_code='STAMP_REJECTED', credentials='PRIVATE'))
    diagnostics = TerminalDiagnostics(tmp_path)
    assert diagnostics.observe(event(), actual)
    assert diagnostics.close(timeout=1)
    raw = next(tmp_path.glob('*.json')).read_text()
    value = json.loads(raw)
    captured = value['watchdog_transition']
    assert captured['owner_now_steady_before'] == 99.95
    assert captured['owner_now_steady_after'] == 99.96
    assert captured['matches_event_command'] is True
    assert captured['owner_now'] == 42.6 and captured['joint_sequence'] == 1200
    assert captured['source_age_s'] == .6 and captured['wall_now'] is None
    assert captured['intake'] == dict(stamp_ns=42600000000, source_now_ns=42000000000,
        received_at=42., callback_entered_steady=99.8, intake_received_steady=99.9,
        intake_observed_steady=99.91, accepted=False, intake_sequence=1200, rejection_code='STAMP_REJECTED')
    assert value['clocks']['owner'] == 43.5 and value['joint_state']['sequence'] == 1231
    assert value['snapshot_atomic'] is False and 'PRIVATE' not in raw


def test_absent_watchdog_transition_stays_absent(tmp_path):
    from g2_diagnostics import TerminalDiagnostics
    diagnostics = TerminalDiagnostics(tmp_path)
    assert diagnostics.observe(event(), runtime())
    assert diagnostics.close(timeout=1)
    value = json.loads(next(tmp_path.glob('*.json')).read_text())
    assert value['watchdog_transition'] is None


def test_other_command_or_truncated_transition_cannot_match_current_event(tmp_path):
    from g2_diagnostics import TerminalDiagnostics
    for index, (command, truncated) in enumerate((('previous-command', False), ('cell-transfer', True))):
        actual = runtime()
        actual.owner.watchdog_observation = NS(reason='joint_state_stale', command_id=command,
            command_id_truncated=truncated, owner_now=float('nan'), joint_sequence=-1,
            owner_now_steady_before=True, owner_now_steady_after=float('inf'), token='PRIVATE')
        diagnostics = TerminalDiagnostics(tmp_path / str(index))
        assert diagnostics.observe(event(), actual)
        assert diagnostics.close(timeout=1)
        raw = next((tmp_path / str(index)).glob('*.json')).read_text()
        captured = json.loads(raw)['watchdog_transition']
        assert captured['matches_event_command'] is False
        assert captured['owner_now'] is None and captured['joint_sequence'] is None
        assert captured['owner_now_steady_before'] is None
        assert captured['owner_now_steady_after'] is None
        assert captured['intake'] is None
        assert 'PRIVATE' not in raw


def test_decision_intake_only_exports_bounded_typed_provenance(tmp_path):
    from g2_diagnostics import TerminalDiagnostics
    actual = runtime()
    actual.owner.watchdog_observation = NS(reason='joint_state_stale', command_id='cell-transfer',
        command_id_truncated=False, intake=NS(stamp_ns=True, source_now_ns=-1, received_at=float('nan'),
            callback_entered_steady=100., intake_received_steady=100.1, intake_observed_steady=100.2,
            accepted=1, intake_sequence=2**80, rejection_code='PRIVATE', payload='PRIVATE'))
    diagnostics = TerminalDiagnostics(tmp_path)
    assert diagnostics.observe(event(), actual)
    assert diagnostics.close(timeout=1)
    raw = next(tmp_path.glob('*.json')).read_text()
    provenance = json.loads(raw)['watchdog_transition']['intake']
    assert provenance == dict(stamp_ns=None, source_now_ns=None, received_at=None,
        callback_entered_steady=100., intake_received_steady=100.1, intake_observed_steady=100.2,
        accepted=None, intake_sequence=None, rejection_code=None)
    assert 'PRIVATE' not in raw


def test_intake_attempt_rejection_and_raw_owner_joint_are_separate_allowlisted_facts(tmp_path):
    from g2_diagnostics import TerminalDiagnostics
    actual = runtime()
    actual.owner._joint_state = NS(sequence=1200, received_at=42.0, positions={'PRIVATE': 'PRIVATE'})
    actual._joint_state_intake.last_attempt = dict(stamp_ns=44000000000, source_now_ns=43500000000,
        received_at=43.5, prior_accepted_stamp_ns=42900000000, accepted=False,
        rejection_code='STAMP_REJECTED', error_type='ValueError', wall_received_at=101.4, token='PRIVATE')
    actual._joint_state_intake.last_rejection = actual._joint_state_intake.last_attempt
    actual._joint_state_intake.attempt_count = 201
    actual._joint_state_intake.accepted_count = 123
    actual._joint_state_intake.rejected_count = 78
    diagnostics = TerminalDiagnostics(tmp_path)
    assert diagnostics.observe(event(), actual)
    assert diagnostics.close(timeout=1)
    raw = next(tmp_path.glob('*.json')).read_text()
    value = json.loads(raw)
    assert value['owner_joint_state'] == {'sequence': 1200, 'received_at': 42.0}
    assert value['joint_state']['sequence'] == 1231
    assert value['intake_last_attempt'] == {key: item for key, item in
        actual._joint_state_intake.last_attempt.items() if key != 'token'}
    assert value['intake_last_rejection'] == value['intake_last_attempt']
    assert value['intake_counts'] == {'attempt_count': 201, 'accepted_count': 123, 'rejected_count': 78}
    assert value['snapshot_atomic'] is False
    assert 'PRIVATE' not in raw


def test_feedback_and_duplicate_terminal_never_create_extra_records(tmp_path):
    from g2_diagnostics import TerminalDiagnostics
    diagnostics = TerminalDiagnostics(tmp_path)
    assert diagnostics.observe(event("RUNNING_FEEDBACK"), None)
    assert list(tmp_path.iterdir()) == []
    assert diagnostics.observe(event(), runtime())
    assert diagnostics.observe(event(sequence=22), runtime("active", state="active"))
    assert diagnostics.close(timeout=1)
    assert len(list(tmp_path.iterdir())) == 1
    assert json.loads(next(tmp_path.glob("*.json")).read_text())["last_decision"]["reason"] == "joint_state_stale"


def test_acceptance_unknown_without_goal_keeps_uncertainty_and_safe_filename(tmp_path):
    from g2_diagnostics import TerminalDiagnostics
    diagnostics = TerminalDiagnostics(tmp_path)
    assert diagnostics.observe(
        event("GOAL_ACCEPTANCE_UNKNOWN", command_id="../../command", goal_id=None), runtime(done=False))
    assert diagnostics.close(timeout=1)
    path = next(tmp_path.glob("*.json"))
    assert path.parent == tmp_path and len(path.stem) == 64
    value = json.loads(path.read_text())
    assert value["event"]["goal_id"] is None
    assert value["cause_classification"] == "UNRESOLVED_ROS_EVENT"


def test_diagnostic_io_failure_is_visible_and_does_not_mask_pilot_or_hold(tmp_path, capsys):
    from g2_diagnostics import TerminalDiagnostics, dispatch_g2_event
    blocked = tmp_path / "blocked"
    blocked.write_text("not a directory")
    diagnostics = TerminalDiagnostics(blocked)
    seen = []
    actual = runtime()
    holder = {"owner": NS(runtime=actual), "pilot": NS(on_goal_event=lambda item: seen.append(item))}
    dispatch_g2_event(event(), holder=holder, diagnostics=diagnostics)
    assert diagnostics.close(timeout=1)
    assert actual.owner.state == "hold" and seen[0].kind == "TERMINAL_UNKNOWN"
    assert "G2_TERMINAL_DIAGNOSTIC_FAILED" in capsys.readouterr().err
    dispatch_g2_event(event(), holder=holder, diagnostics=diagnostics)
    assert len(seen) == 2


def test_diagnostic_count_and_positions_are_bounded(tmp_path, capsys):
    from g2_diagnostics import TerminalDiagnostics
    diagnostics = TerminalDiagnostics(tmp_path, max_records=2)
    actual = runtime()
    actual.latest_joint_state.positions = {"joint" + str(index): float(index) for index in range(100)}
    assert diagnostics.observe(event(command_id="command-1"), actual)
    assert diagnostics.observe(event(command_id="command-2"), actual)
    assert diagnostics.observe(event(command_id="command-3"), actual) is False
    assert diagnostics.close(timeout=1)
    assert len(list(tmp_path.iterdir())) == 2
    for path in tmp_path.iterdir():
        value = json.loads(path.read_text())
        assert len(value["joint_state"]["positions"]) == 32
        assert value["joint_state"]["positions_truncated"] is True
        assert path.stat().st_size <= 16384
    assert "RECORD_LIMIT" in capsys.readouterr().err


def test_observer_does_not_wait_for_or_call_owner_public_snapshot_under_owner_lock(tmp_path):
    from g2_diagnostics import TerminalDiagnostics
    actual = runtime()
    class GuardedOwner:
        _state, _hold_reason, _joint_state_wall = "hold", "joint_state_stale", 99.0
        config = actual.owner.config
        def __init__(self):
            self.lock = threading.RLock()
        @property
        def state(self):
            with self.lock:
                raise AssertionError("observer entered owner public snapshot")
        def recovery_state(self):
            with self.lock:
                raise AssertionError("observer entered owner public snapshot")
    actual.owner = GuardedOwner()
    result = []
    diagnostics = TerminalDiagnostics(tmp_path)
    with actual.owner.lock:
        worker = threading.Thread(target=lambda: result.append(diagnostics.observe(event(), actual)),
                                  daemon=True)
        worker.start()
        worker.join(.3)
        finished_while_locked = not worker.is_alive()
    worker.join(2)
    assert finished_while_locked and result == [True]
    assert diagnostics.close(timeout=1)


def test_observer_does_not_wait_for_handle_public_getters_under_handle_lock(tmp_path):
    from g2_diagnostics import TerminalDiagnostics
    actual = runtime()
    class GuardedHandle:
        _done, _status, _cancel_acknowledged = True, None, None
        def __init__(self):
            self.lock = threading.RLock()
        def done(self):
            with self.lock:
                raise AssertionError("observer entered handle public getter")
        @property
        def status(self):
            with self.lock:
                raise AssertionError("observer entered handle public getter")
        @property
        def cancel_acknowledged(self):
            with self.lock:
                raise AssertionError("observer entered handle public getter")
    actual.action_port.last_handle = GuardedHandle()
    result = []
    diagnostics = TerminalDiagnostics(tmp_path)
    with actual.action_port.last_handle.lock:
        worker = threading.Thread(target=lambda: result.append(diagnostics.observe(event(), actual)),
                                  daemon=True)
        worker.start()
        worker.join(.3)
        finished_while_locked = not worker.is_alive()
    worker.join(2)
    assert finished_while_locked and result == [True]
    assert diagnostics.close(timeout=1)


def test_parked_disk_does_not_block_pilot_callback_delivery_or_cancel_lock(tmp_path, monkeypatch):
    import g2_diagnostics as module
    entered, release, pilot_seen, cancelled = (threading.Event() for _ in range(4))
    original = module.write_json
    def parked(path, payload):
        entered.set()
        assert release.wait(3)
        original(path, payload)
    monkeypatch.setattr(module, "write_json", parked)
    diagnostics = module.TerminalDiagnostics(tmp_path)
    delivery_lock = threading.Lock()
    holder = {"owner": NS(runtime=runtime()), "pilot": NS(on_goal_event=lambda _: pilot_seen.set())}
    def deliver():
        with delivery_lock:
            module.dispatch_g2_event(event(), holder=holder, diagnostics=diagnostics)
    def cancel_callback():
        with delivery_lock:
            cancelled.set()
    callback = threading.Thread(target=deliver, daemon=True)
    callback.start()
    assert entered.wait(1)
    cancel = threading.Thread(target=cancel_callback, daemon=True)
    cancel.start()
    try:
        callback.join(.3)
        assert not callback.is_alive() and pilot_seen.is_set()
        assert cancelled.wait(.3)
        started = time.monotonic()
        assert diagnostics.close(timeout=.05) is False
        assert time.monotonic() - started < .3
    finally:
        release.set()
        callback.join(2)
        cancel.join(2)
        if hasattr(diagnostics, "close"):
            diagnostics.close(timeout=1)


def test_parked_stderr_does_not_block_overflow_callback_or_bounded_close(tmp_path, monkeypatch):
    import g2_diagnostics as module
    entered, release = threading.Event(), threading.Event()
    class ParkedStderr:
        def write(self, text):
            entered.set()
            release.wait(3)
            return len(text)
        def flush(self):
            release.wait(3)
    monkeypatch.setattr(module.sys, "stderr", ParkedStderr())
    blocked = tmp_path / "blocked"
    blocked.write_text("not a directory")
    diagnostics = module.TerminalDiagnostics(blocked, max_records=1)
    pilots, closed = [], []
    holder = {"owner": NS(runtime=runtime()), "pilot": NS(on_goal_event=lambda item: pilots.append(item.command_id))}
    module.dispatch_g2_event(event(), holder=holder, diagnostics=diagnostics)
    assert entered.wait(1)  # The writer is now blocked reporting its filesystem error.
    callback = threading.Thread(target=lambda: module.dispatch_g2_event(
        event(command_id="another-command"), holder=holder, diagnostics=diagnostics), daemon=True)
    closer = threading.Thread(target=lambda: closed.append(diagnostics.close(timeout=.05)), daemon=True)
    try:
        callback.start()
        callback.join(.3)
        closer.start()
        closer.join(.3)
        assert not callback.is_alive() and pilots == ["cell-transfer", "another-command"]
        assert not closer.is_alive() and closed == [False]
    finally:
        release.set()
        callback.join(2)
        if closer.ident is not None:
            closer.join(2)
        diagnostics.close(timeout=1)
