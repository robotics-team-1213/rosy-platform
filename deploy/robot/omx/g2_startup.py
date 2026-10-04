"""SIM_STARTUP_HOME fixture through the existing owner's durable Pilot seat."""
import math
import secrets
import threading
import time


def prepare_home(runtime, profile, target, *, wall_clock=time.monotonic, sleep=time.sleep):
    from omx_adapter.command_owner import TrajectoryCommand

    config = runtime.owner.config
    current = runtime.latest_joint_state
    now = runtime.monotonic()
    if (current is None or runtime.owner.state != "ready"
            or not 0 <= now-current.received_at <= profile.max_joint_state_age_s
            or any(name not in current.positions for name in config.joint_names)):
        raise RuntimeError("SIM startup initial joint state is not fresh and ready")
    if set(target) != set(config.joint_names) or any(not math.isfinite(q) for q in target.values()):
        raise ValueError("SIM startup target must match the reviewed joint map")
    delta = max(abs(target[n]-current.positions[n]) for n in config.joint_names)
    duration = max(3., 2.*delta/(min(profile.velocity_limits.values())*profile.planning_limit_fraction))
    bound = profile.action_timeout_s * profile.wall_clock_bound_factor + 30.
    start_wall, start_sim = wall_clock(), now
    deadline = start_wall + bound
    admission = runtime.control_admission
    token, seat = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    command_id = "g2-startup-home-" + secrets.token_hex(16)
    command = TrajectoryCommand(
        workcell_id=config.workcell_id, instance_id=config.instance_id,
        command_id=command_id, session_id=runtime.owner.session_id, owner="pilot_sim",
        positions=target, duration_s=duration, source_state_sequence=current.sequence,
        calibration_revision=config.calibration_revision, joint_names=config.joint_names,
        expected_start_state_positions={n: current.positions[n] for n in config.joint_names},
        start_state_tolerances={n: profile.start_state_tolerance_rad for n in config.joint_names})
    events, lock = {}, threading.RLock()

    def event_sink(event):
        with lock:
            if event.command_id != command_id:
                raise RuntimeError("SIM startup event has the wrong command")
            admission.note_goal(command_id, event.kind, event.goal_id)
            if event.kind == "GOAL_ACCEPTED":
                if not event.goal_id or (events.get("goal_id") and events["goal_id"] != event.goal_id):
                    events["error"] = "startup acceptance is uncertain"
                events["goal_id"] = event.goal_id
            elif event.kind == "TERMINAL_RESULT":
                if (not events.get("goal_id") or events["goal_id"] != event.goal_id
                        or event.status != 4 or event.result_code != 0):
                    events["error"] = "startup terminal result is not matching success"
                else:
                    events["terminal_sequence"] = runtime.latest_joint_state.sequence
                    events["terminal_sim"] = runtime.monotonic()
            elif event.kind in {"GOAL_REJECTED", "GOAL_ACCEPTANCE_UNKNOWN", "TERMINAL_UNKNOWN"}:
                events["error"] = "startup outcome is uncertain: " + event.kind
                if event.kind == "GOAL_REJECTED":
                    admission.note_rejected(command_id)
        return True

    # Never clear a reserved intent after an unknown submission or missing result.
    admission.acquire(token, seat, ttl_s=bound+30.)
    admission.reserve_pilot(seat, command_id)
    runtime.register_phase_event_sink(command_id, event_sink)
    decision = runtime.submit(command)
    if not decision.accepted:
        if decision.reason != "action_submission_failed":
            admission.note_rejected(command_id)
        raise RuntimeError("SIM startup goal rejected: " + decision.reason)
    stable_since, stable_sample_stamp, last_sequence = None, None, current.sequence
    while wall_clock() < deadline:
        with lock:
            if events.get("error"):
                raise RuntimeError(events["error"])
            terminal_sequence = events.get("terminal_sequence")
            terminal_sim = events.get("terminal_sim")
        sample = runtime.latest_joint_state
        stamp = runtime.monotonic()
        valid = (terminal_sequence is not None and sample is not None
                 and sample.sequence > terminal_sequence and sample.sequence >= last_sequence
                 and sample.received_at > terminal_sim
                 and 0 <= stamp-sample.received_at <= profile.max_joint_state_age_s
                 and runtime.owner.state == "ready"
                 and all(math.isfinite(sample.positions.get(n, float("nan")))
                         and abs(sample.positions[n]-target[n]) <= (
                             profile.start_state_tolerance_rad if n == profile.gripper_joint
                             else profile.home_joint_tolerance_rad) for n in config.joint_names))
        if valid:
            new_sample = sample.sequence > last_sequence
            if stable_since is None:
                stable_since, stable_sample_stamp = wall_clock(), sample.received_at
            last_sequence = sample.sequence
            if (new_sample and sample.received_at > stable_sample_stamp
                    and wall_clock()-stable_since >= .5):
                admission.release(token, seat)
                admission.run_action_admission(lambda: None)
                return {"fixture": "SIM_STARTUP_HOME", "result": "READY", "command_id": command_id,
                        "session_id": command.session_id, "ros_goal_id": events["goal_id"],
                        "terminal_status": 4, "terminal_result_code": 0, "seat_reconciled": True,
                        "target": dict(target), "profile_revision": getattr(profile, "revision", None),
                        "initial_sequence": current.sequence, "initial_positions": dict(current.positions),
                        "final_sequence": sample.sequence, "final_positions": dict(sample.positions),
                        "elapsed_wall_s": wall_clock()-start_wall, "elapsed_sim_s": stamp-start_sim}
        else:
            stable_since, stable_sample_stamp = None, None
        sleep(.05)
    raise RuntimeError("SIM startup home readiness timed out; admission remains fenced")


def hold_startup(owner):
    """Keep existing stop/readback IPC available without automatically moving home.

    Reserved Pilot admission does not authorize bypassing UNKNOWN LocalStop.
    A future startup goal needs explicit authorization, an open generation's
    final submit fence, and exact-goal StopLocal cancellation before execution.
    """
    owner.runner.enabled = False
    return {"fixture": "SIM_STARTUP_HOME", "result": "HOLD",
            "reason": "STARTUP_AUTHORIZATION_REQUIRED"}
