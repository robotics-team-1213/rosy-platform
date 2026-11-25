#!/usr/bin/env python3
"""Guarded Torque-ON unlatch and slow recovery-park helpers for active `human-hold` sessions."""
from __future__ import annotations

import math
from typing import Any

UNSETTLED_FAULTS = ("park-slow did not settle at home", "fold-from-hold did not settle at home")


def request_live_unlatch(cell) -> tuple[bool, dict]:
    """Send `recover-unlatch` to a latched runner and verify it unlatched without releasing torque."""
    ack = cell.act("recover-unlatch")
    if not isinstance(ack, dict):
        return False, {"ok": False, "error": "invalid recover-unlatch reply"}
    if ack.get("ok") is True and ack.get("human_hold_latched") is not False:
        return False, {**ack, "ok": False, "error": "runner did not confirm hold release"}
    return ack.get("ok") is True, ack


def ensure_live_unlatch(cell, latched: dict, note_fn) -> tuple[bool, str | None]:
    """Unlatch an active `human-hold` once (recording an audit step), or return `(True, None)` if already clear."""
    if not latched.get("active"):
        return True, None
    ok_u, ack_u = request_live_unlatch(cell)
    note_fn({"step": "recover_unlatch", "ok": ok_u, "previous_fault": ack_u.get("previous_fault"),
             "error": ack_u.get("error")})
    if not ok_u:
        return False, ack_u.get("error")
    latched["active"] = False
    return True, None


def _finite_list(vals: Any, length: int) -> bool:
    return (
        isinstance(vals, (list, tuple))
        and len(vals) == length
        and all(not isinstance(v, bool) and isinstance(v, (int, float)) and math.isfinite(float(v)) for v in vals)
    )


def is_recoverable_fault(fault: Any, *, allow_unsettled: bool = True) -> bool:
    """Allow guarded Torque-ON recovery after hold/contact/pushing-at-rest (or unsettled recovery park from hold)."""
    return (not fault or fault == "human hold"
            or (isinstance(fault, str) and (fault.startswith(("contact", "pushing at rest"))
                                            or (allow_unsettled and fault in UNSETTLED_FAULTS))))


def _read_bus_motors(bus, reg: str, motors: list[str]) -> dict[str, Any]:
    if "read" not in vars(bus) and hasattr(bus, "model_ctrl_table") and hasattr(bus, "sync_read"):
        return bus.sync_read(reg, motors, normalize=False, num_retry=2)
    if callable(getattr(bus, "read", None)):
        return {m: bus.read(reg, m) for m in motors}
    raise ValueError(f"bus cannot read {reg}")


def _verify_hardware_ready(runner, motion, temp_stop: int, *, allow_unsettled: bool = True) -> None:
    """Confirm guard intact/tracking, no overload hold, zero hw errors, torque ON, safe temps, and recoverable fault."""
    if not is_recoverable_fault(getattr(runner, "fault", None), allow_unsettled=allow_unsettled):
        raise ValueError(f"recovery refused after fault: {runner.fault}")
    if getattr(motion, "failed", False):
        raise ValueError("cannot recover: native guard failed")
    if motion is not None and not getattr(motion, "tracking", True):
        raise ValueError("cannot recover: guard is not tracking yet")
    if held := getattr(motion, "held", None):
        raise ValueError(f"cannot recover: native guard overload hold active on {', '.join(held)}")
    bus = getattr(getattr(runner, "robot", None), "bus", None)
    if motion is not None and callable(getattr(motion, "_check_hardware_errors", None)):
        try:
            motion._check_hardware_errors()
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"cannot recover: hardware error check failed ({exc})") from None
    elif bus is not None:
        from chunk_runner_guards import MOTORS
        from guarded_native_probe import is_hardware_fault, is_valid_hw_status

        try:
            errs = _read_bus_motors(bus, "Hardware_Error_Status", list(MOTORS))
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"cannot recover: hardware error read failed ({exc})") from None
        if not isinstance(errs, dict) or any(not is_valid_hw_status(errs.get(m)) for m in MOTORS):
            raise ValueError("cannot recover: invalid hardware error readback")
        if faulted := [m for m in MOTORS if is_hardware_fault(errs.get(m))]:
            raise ValueError(f"cannot recover: hardware error on {', '.join(faulted)}")
    if bus is not None:
        from chunk_runner_guards import MOTORS

        try:
            torques = _read_bus_motors(bus, "Torque_Enable", list(MOTORS))
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"cannot recover: torque read failed ({exc})") from None
        if not isinstance(torques, dict) or any(type(torques.get(m)) is not int or torques.get(m) != 1 for m in MOTORS):
            raise ValueError("cannot recover: torque is not enabled on all motors")
    fresh_h = None
    if callable(getattr(runner, "read_health", None)):
        try:
            fresh_h = runner.read_health()
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"cannot recover: motor health unreadable ({exc})") from None
        if fresh_h is None and bus is not None:
            raise ValueError("cannot recover: live motor health unavailable")
        if fresh_h is not None:
            if not isinstance(fresh_h, dict) or not _finite_list(fresh_h.get("temp_c"), 6):
                raise ValueError("cannot recover: invalid motor health")
            if max(float(v) for v in fresh_h["temp_c"]) >= temp_stop:
                raise ValueError(f"cannot recover: motor temperature {max(float(v) for v in fresh_h['temp_c']):g} C >= {temp_stop} C")
            runner.health = fresh_h
    health = fresh_h if fresh_h is not None else getattr(runner, "health", None)
    if isinstance(health, dict) and "temp_c" in health:
        if not _finite_list(health.get("temp_c"), 6):
            raise ValueError("cannot recover: invalid motor temperatures")
        if (hot := max(float(v) for v in health["temp_c"])) >= temp_stop:
            raise ValueError(f"cannot recover: motor temperature {hot:g} C >= {temp_stop} C")


def _check_recovery_preconditions(runner, *, require_latched: bool, require_torque_ack: bool) -> list[float]:
    from chunk_runner_interrupt import BLOCKED_DURING_CLOSE, OPERATOR_RELEASE

    if require_latched and not getattr(runner, "human_hold_latched", False):
        raise ValueError("recovery requires an active human hold")
    if require_torque_ack and not getattr(runner, "torque_hold_commanded", False):
        raise ValueError("recovery requires an acknowledged torque hold")
    if getattr(runner, "_interrupt", None) is not None:
        raise ValueError("cannot recover during an active shutdown interrupt")
    sigs = getattr(runner, "signals", None) or ()
    if any(s in BLOCKED_DURING_CLOSE or s != OPERATOR_RELEASE for s in sigs):
        raise ValueError("cannot recover with a pending shutdown signal")
    if getattr(runner, "_fifo_hold_seen", False):
        raise ValueError("cannot recover with a pending human-hold request")
    if getattr(runner, "chunk", None) is not None or getattr(runner, "queue", None):
        raise ValueError("cannot recover while a chunk or queue is active")
    if getattr(runner, "_stop_after_park", None):
        raise ValueError("cannot recover while stop-after-park is pending")
    if getattr(runner, "_release_until", None) is not None:
        raise ValueError("cannot recover while grip release is unconfirmed")
    lib = getattr(runner, "library", None)
    home = (lib.get("chunks") or {}).get("home") if isinstance(lib, dict) else None
    if not isinstance(home, list) or not home or not _finite_list(home[-1], 6):
        raise ValueError("recovery needs a valid home chunk")
    try:
        present = runner.present()
    except Exception:  # noqa: BLE001
        raise ValueError("cannot recover: encoder pose unreadable") from None
    if not _finite_list(present, 6):
        raise ValueError("cannot recover: encoder pose invalid")
    return [float(v) for v in present]


def _clear_hold_state(runner, target: list[float]) -> None:
    runner.target = list(target)
    runner.human_hold_latched = runner.torque_hold_commanded = runner._human_hold_ack_pending = False
    runner._human_hold_acked_req = runner._human_hold_req = runner._human_hold_overload_reported = None
    runner._human_hold_release_from = 0
    runner.fault = None
    runner.retreat_frames, runner.jog_path = [], []
    if hasattr(runner, "pending"):
        runner.pending.clear()
    runner.contact_ticks, runner.contact_start, runner.far_since, runner.overload_since = 0, None, None, None
    runner.home_since, runner.last_input, runner.samples, runner.last_body, runner.last_grip = None, runner.clock(), [], None, None
    runner.pace_floor, runner.paced, runner.pace_last, runner.trend = 0.0, 0, None, []
    runner.pitch_hold, runner.sway_peak, runner.speed_low, runner._damp_cooldown = 0.0, {}, 1.0, 0
    runner.policy_playback = runner.jaw_gate = runner._trailing_jaw_gate = None
    runner.jitter_buf, runner.jitter = [], {"shaking": False, "max_std": 0.0, "max_flips_hz": 0.0, "max_p2p": 0.0, "flagged": []}
    if hasattr(runner, "ensembler") and hasattr(runner.ensembler, "reset"):
        runner.ensembler.reset(list(target))


def recovery_park_path(library: dict, present: list, fps: int) -> list:
    """Build the guarded slow park path (transit speed <= 0.3) for `park-slow` / `fold-from-hold`."""
    from chunk_runner_guards import library_gripper_closed, library_transit_speed, parse_transit
    from omx_adapter.chunk_library import park_path

    return park_path(
        list(present), library["chunks"]["home"][-1], library_gripper_closed(library),
        fps, parse_transit(library), min(library_transit_speed(library), 0.3),
    )


def dispatch_recover_unlatch(runner, words: list[str], line: str, latch_error_fn, *, empty_margin: float = 2.0) -> bool:
    """Validate hardware/guard readiness and exit `human_hold_latched` with torque ON and zero jump."""
    from chunk_runner_guards import TEMP_STOP, library_gripper_closed

    if len(words) != 1:
        raise ValueError("recover-unlatch takes no arguments")
    present = _check_recovery_preconditions(runner, require_latched=True, require_torque_ack=True)
    motion = getattr(getattr(runner, "robot", None), "motion", None)
    _verify_hardware_ready(runner, motion, TEMP_STOP, allow_unsettled=True)
    lib = runner.library
    try:
        closed = library_gripper_closed(lib)
    except ValueError:
        closed = None
    prev_grip = float(runner.target[5]) if (getattr(runner, "target", None) is not None and len(runner.target) >= 6) else present[5]
    clamped_box = bool(getattr(runner, "holding", False)) or (
        closed is not None and prev_grip <= closed + 1.0 and present[5] > prev_grip + empty_margin
    )
    grip_target = prev_grip if clamped_box else present[5]
    synced_target = present[:5] + [grip_target]
    if motion is not None and callable(getattr(motion, "stop_streaming", None)):
        motion.stop_streaming()
    prev_fault = getattr(runner, "fault", None)
    runner.holding = bool(clamped_box and present[5] > grip_target + empty_margin)
    _clear_hold_state(runner, synced_target)
    runner._recovery_active = runner._recovery_live_flush = True
    runner.queue, runner.chunk, runner.played = [], None, []
    try:
        runner.report(command=line, ok=True, unlatched_from_hold=True, previous_fault=prev_fault, present=present)
    except OSError as write_error:
        latch_error_fn(runner, present, line, "status write failed after unlatch", write_error)
    if not runner.human_hold_latched:
        from chunk_runner_loop import publish_live
        publish_live(runner, state=present, best_effort=True)
    return True


def queue_recovery_park(runner, words: list[str], *, checked: bool, empty_margin: float = 2.0) -> None:
    """Admit `park-slow` or `checked ... fold-from-hold <j0..j5>` with occupied-jaw and hardware refusals."""
    from chunk_policy_playback import halt_policy_gate
    from chunk_runner_guards import TEMP_STOP, library_gripper_closed

    verb = words[0]
    from_hold = verb == "fold-from-hold"
    if from_hold and not (checked and getattr(runner, "human_hold_latched", False) and getattr(runner, "torque_hold_commanded", False)):
        raise ValueError("fold-from-hold needs a checked command and an acknowledged human hold")
    present = _check_recovery_preconditions(runner, require_latched=from_hold, require_torque_ack=from_hold)
    motion = getattr(getattr(runner, "robot", None), "motion", None)
    _verify_hardware_ready(runner, motion, TEMP_STOP, allow_unsettled=from_hold)
    if from_hold:
        start = [round(v, 2) for v in present]
        if len(words) != 7:
            raise ValueError("fold-from-hold start differs from the checked corridor")
        try:
            asked = [float(v) for v in words[1:]]
        except (TypeError, ValueError, OverflowError):
            raise ValueError("fold-from-hold start differs from the checked corridor") from None
        if not all(math.isfinite(v) for v in asked) or asked != start:
            raise ValueError("fold-from-hold start differs from the checked corridor")
    elif len(words) != 1:
        raise ValueError("park-slow takes no arguments")
    else:
        start = present
    closed = library_gripper_closed(runner.library)
    t_grip = float(runner.target[5]) if (getattr(runner, "target", None) is not None and len(runner.target) >= 6) else present[5]
    if getattr(runner, "holding", False) or (t_grip <= closed + 1.0 and present[5] > t_grip + empty_margin):
        raise ValueError(f"{verb} refused with an occupied gripper")
    if motion is not None and callable(getattr(motion, "stop_streaming", None)):
        motion.stop_streaming()
    halt_policy_gate(runner)
    frames = recovery_park_path(runner.library, start, runner.fps)
    _clear_hold_state(runner, start)
    runner._recovery_active = runner._recovery_live_flush = True
    runner.queue, runner.chunk, runner.settle_since, runner.played = frames, verb, None, []


def run_fold_session_cli(args, recover_fn, schema: str) -> int:
    """Execute `cell_auto_fold.py` CLI fold/unlatch inside an arm session with fail-safe hold cleanup."""
    import json
    import os
    from pathlib import Path

    import cell_choices
    import cell_corridor
    import cell_params as prm
    import cell_pipeline as cp
    import cell_pivot
    import cell_place_fit
    import cell_recovery_plan as crp
    import cell_space
    import cell_unwedge
    import omx_tcp
    from cell_envelope import digest
    from cell_observe import predicted_pixel
    from omx_adapter.chunk_library import NAMES, park_path

    arm, cell, space, home, choices_path, moved_out, latched_out = args.arm, None, None, [], None, [], []
    choice_key = "auto_fold.candidate"
    try:
        config = cell_place_fit.with_tiers(json.loads(args.config.read_text(encoding="utf-8")))[0]
        params = config["params"] = prm.load(config.get("params_path"))["values"]
        calibration = json.loads(Path(config["calibration_path"]).expanduser().read_text())
        library = json.loads(args.library.read_text())
        home, closed = library["chunks"]["home"][-1], float(library["gripper_closed"])
        transit = {NAMES.index(k): float(v) for k, v in library.get("transit", {}).items()} or None
        cell = cp.FifoCell(Path(config["io"]).expanduser(), config["cameras"])
        space = cell_space.Space(Path(config.get("space_dir", "~/rosy-omx/space")).expanduser())
        to_px = lambda p: predicted_pixel(config, calibration, args.site, p)  # noqa: E731
        tcp_x_m = omx_tcp.config_tcp(config) or library.get("tcp_x_m")
        clear_z_m = prm.get(params, "corridor.clear_z_m", cell_corridor.CLEAR_Z_M)
        bounds = crp.joint_bounds(config)
        choices_path = Path(config.get("work_dir") or ".") / f"auto-fold-choices-{arm}.json"
        choices = cell_choices.Choices(choices_path)
        for name in crp.extended_candidate_names():
            choices.offer(choice_key, name, "D-1048")
        choices.save()
        plan = lambda s: park_path(list(s), home, closed, library["fps"], transit, library.get("transit_speed", 0.85))  # noqa: E731
        low = lambda s: crp.fk_z(s, tcp_x_m=tcp_x_m) < clear_z_m  # noqa: E731
        look = crp.build_multi_site_look(cell, config, calibration, args.site, args.roi, params, to_px, tcp_x_m)
        load_check = crp.make_load_checker(config, library, params)
        advisor = None
        if args.vlm_url or args.vlm_config:
            from cell_recovery_advisor import build_advisor_from_args

            adv_plan = (lambda s: recovery_park_path(library, s, library["fps"])) if args.unlatch_hold else plan  # noqa: E731
            advisor = build_advisor_from_args(args, config, cell, arm=args.arm, home=home, plan=adv_plan,
                                              bounds=bounds, tcp_x_m=tcp_x_m, clear_z_m=clear_z_m)

        def reserve(frames):
            r = cell_corridor.runs([cell_pivot.joints_tcp(f, tcp_x_m=tcp_x_m)[:3] for f in frames])
            lane = cell_corridor.corridor(r[0] + r[1], to_px, (args.roi[3] - args.roi[1], args.roi[2] - args.roi[0]),
                                          args.roi, prm.get(params, "corridor.half_width_mm", cell_corridor.HALF_WIDTH_MM))
            return space.reserve(arm, lane, ttl_s=360.0)

        result = recover_fn(
            cell, home, closed, plan=plan, look=look, reserve=reserve, release=lambda: space.release(arm),
            release_and_rise=cell_unwedge.release_and_rise, low=low, order=lambda n: choices.ranked(choice_key, n),
            release_unmoved=bool(args.supervised and not args.unlatch_hold), moved_out=moved_out, latched_out=latched_out,
            allow_live_unlatch=args.unlatch_hold, advisor=advisor, load_check=load_check,
            bounds=bounds, tcp_x_m=tcp_x_m, clear_z_m=clear_z_m, extended_detours=True,
            held_plan=lambda s: recovery_park_path(library, s, library["fps"]), library_sha256=digest(library),
        )
    except Exception as exc:  # whatever broke, keep torque ON if moved/latched/unlatch-hold; else stop now when supervised
        err = f"ERROR: {type(exc).__name__}: {str(exc)[:160]}"
        if space is not None and not moved_out:
            space.release(arm)
        can_stop = bool(args.supervised and not args.unlatch_hold and not moved_out and not latched_out)
        if cell is None:
            result = {"schema": schema, "result": "held", "reason": err, "hold_ok": None,
                      **({"unmoved": True} if can_stop else {}), "steps": []}
        else:
            stopped = cell.act("stop now") if can_stop else {}
            if stopped.get("ok") is True:
                result = {"schema": schema, "result": "held", "reason": err, "hold_ok": None,
                          "ended": "stop_now", "unmoved": True, "steps": []}
            else:
                result = {"schema": schema, "result": "held", "reason": err,
                          "hold_ok": cell.act("human-hold").get("ok"), "steps": []}
    result["incident_id"] = None if args.supervised else os.environ["ROSY_RECOVERY_INCIDENT"]
    result["home"], result["supervised"] = list(home), bool(args.supervised)
    if choices_path is not None:
        result["choices_path"] = str(choices_path)
    if result["result"] == "folded":
        result["stop"] = cell.act("stop")  # at home: the runner's stop folds nothing more and turns torque OFF
    args.out.write_text(json.dumps(result, default=str, indent=1))
    print(json.dumps({k: result.get(k) for k in ("result", "reason", "candidate")}))
    return 0 if result["result"] == "folded" else 3
