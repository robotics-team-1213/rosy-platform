"""Multi-strategy fallback candidates, family classification, and upward unwedge helpers (D-1048)."""
from __future__ import annotations

import math


def candidate_family(name: str) -> str:
    """Group recovery candidates sharing one physical lift/release strategy for distinct runtime fallback."""
    if name.startswith("open_elbow_lift_"):
        return "open_elbow_lift"
    if name.startswith("elbow_lift_"):
        return "elbow_lift"
    if name.startswith("lift_"):
        return "shoulder_lift"
    if name.startswith("elbow_clear_"):
        return "elbow_clear"
    if name.startswith("pan"):
        return "pan"
    if name in ("park", "fold-from-hold"):
        return "park"
    return name


def extended_candidate_names() -> list[str]:
    """Return every tier-1 candidate name that `build_candidates(..., extended=True)` may produce."""
    return [
        "park",
        "lift_then_park", "lift_pan+10", "lift_pan-10",
        "open_elbow_lift_then_park", "open_elbow_lift_pan+10", "open_elbow_lift_pan-10",
        "elbow_lift_then_park", "elbow_lift_pan+10", "elbow_lift_pan-10",
        "pan+5", "pan-5", "pan+10", "pan-10", "pan+15", "pan-15",
        "elbow_clear_then_park",
    ]


def unwedge_pull_dips(state: list[float], target: list[float], home: list[float], size: float,
                      clear_z_m: float, tcp_x_m: float | None = None) -> bool:
    """Return True if an elbow_flex pull would dip TCP z below clear_z_m while lift can still rise."""
    from cell_recovery_plan import fk_z

    z_now = fk_z(state, tcp_x_m=tcp_x_m)
    if z_now >= clear_z_m or (home[1] - target[1]) * (home[1] - state[1]) <= 0:
        return False
    probe = list(state)
    probe[2] += max(-size, min(size, home[2] - target[2]))
    return fk_z(probe, tcp_x_m=tcp_x_m) < z_now - 0.001


def unwedge_pull_or_ascend(status: dict, action: str, home: list, size: float, clear_z_m: float | None,
                           tcp_x_m: float | None, blocked: str | None, *,
                           actions: dict[str, str], body: tuple[str, ...]) -> tuple[str, str, int, float | None, dict | None]:
    """Choose unwedge joint and delta; switch or ascend on elbow rather than dipping below clear_z_m."""
    from cell_recovery_plan import fk_z

    joint = actions[action]
    index = body.index(joint)
    if clear_z_m is not None and action == "pull" and unwedge_pull_dips(
            status["state"], status["target"], home, size, clear_z_m, tcp_x_m):
        if blocked != "lift":
            action = "lift"
            joint = actions[action]
            index = body.index(joint)
        else:
            opp_delta = -max(-size, min(size, home[2] - status["target"][2]))
            probe = list(status["state"])
            probe[2] += opp_delta
            if (abs(opp_delta) > 1e-6 and -100.0 <= status["target"][2] + opp_delta <= 100.0
                    and fk_z(probe, tcp_x_m=tcp_x_m) > fk_z(status["state"], tcp_x_m=tcp_x_m) + 1e-5):
                return action, joint, index, opp_delta, None
            return action, joint, index, None, {"result": "stuck", "error": "pull would dip below clear_z_m while lift is blocked"}
    remaining = home[index] - status["target"][index]
    if remaining * (home[index] - status["state"][index]) <= 0:
        return action, joint, index, None, {"result": "stopped", "error": f"{joint} reached home before clearance"}
    return action, joint, index, max(-size, min(size, remaining)), None


def append_lift_candidates(cur: list[float], home: list[float], plan, *, bounds, tcp_x_m: float | None,
                           clear_z_m: float, situation: str, grip_open: float | None,
                           fk_lift_fn, chunk_jog_fn, interp_fn, step_max: float,
                           elbow_cap: int, raw: list[tuple[str, list[str], list[list[float]]]]) -> None:
    """Append shoulder-first, wide-jaw+elbow-first, and elbow-first vertical clearance candidates."""
    def _plan_lift(**extra):
        return (fk_lift_fn(cur, clear_z_m=clear_z_m + 0.015, bounds=bounds, tcp_x_m=tcp_x_m, home=home, **extra)
                or fk_lift_fn(cur, clear_z_m=clear_z_m, bounds=bounds, tcp_x_m=tcp_x_m, home=home, **extra))

    def _add_group(prefix: str, lift_tuple) -> None:
        if lift_tuple is None:
            return
        l_cmds, l_frames, l_pose = lift_tuple
        raw.append((f"{prefix}_then_park", list(l_cmds), [list(cur), *l_frames[1:], *plan(l_pose)]))
        for d in (10.0, -10.0):
            p_pose = [l_pose[0] + d, *l_pose[1:]]
            cmds = [*l_cmds, *chunk_jog_fn("shoulder_pan.pos", d)]
            frames = [list(cur), *l_frames[1:], *interp_fn(l_pose, p_pose, max_step=step_max), *plan(p_pose)]
            raw.append((f"{prefix}_pan{d:+g}", cmds, frames))

    lift = _plan_lift()
    elbow_axis, elbow_lim = ((2, "elbow_flex.pos"), (1, "shoulder_lift.pos")), {2: elbow_cap}
    elbow_lift = _plan_lift(axis_order=elbow_axis, per_axis_cap=elbow_lim)
    can_open_wider = (situation == "low_open_jaws" and grip_open is not None and not isinstance(grip_open, bool)
                      and math.isfinite(float(grip_open)) and float(grip_open) > cur[5] + 1.0)
    open_elbow = _plan_lift(axis_order=elbow_axis, per_axis_cap=elbow_lim, grip_open=float(grip_open)) if can_open_wider else None

    if situation == "low_open_jaws":
        _add_group("lift", lift)
        _add_group("open_elbow_lift", open_elbow)
        _add_group("elbow_lift", elbow_lift)
        raw.append(("park", [], list(plan(cur))))
    else:
        raw.append(("park", [], list(plan(cur))))
        _add_group("lift", lift)
        _add_group("elbow_lift", elbow_lift)


def rank_candidates(tries: list, *, order, prefer_direct: bool, situation: str) -> list:
    """Sort candidates respecting direct hold, low-open-jaw vertical lift priority, and learned order."""
    rank = (
        {name: i for i, name in enumerate(order([name for name, _, _ in tries]))}
        if (tries and order is not None) else {name: i for i, (name, _, _) in enumerate(tries)}
    )

    def _prio(name: str) -> int:
        if prefer_direct and name == "park":
            return 0
        if situation == "low_open_jaws" and name.startswith("lift_"):
            return 1
        if situation == "low_open_jaws" and name.startswith(("open_elbow_lift_", "elbow_lift_")):
            return 2
        return 3

    return sorted(tries, key=lambda c: (_prio(c[0]), rank.get(c[0], len(rank))))


def attempt_runtime_fallback(cell, fail_reason: str, fail_cand: str, fail_err, *, latched: dict, known: dict,
                             require_empty_gripper: bool, low, note, release, hold, ok_state_fn):
    """Latch human-hold, verify recoverable fault, unlatch, and return refreshed state or fail closed."""
    from chunk_runner_recover import is_recoverable_fault, request_live_unlatch

    cell.act("human-hold")
    fresh = cell.act("state")
    fresh_state = ok_state_fn(fresh)
    recoverable = (
        fresh_state is not None
        and not fresh.get("holding")
        and not (require_empty_gripper and fresh.get("holding") is not False)
        and is_recoverable_fault(fresh.get("fault"))
    )
    if not recoverable:
        return None, hold(fail_reason, candidate=fail_cand, error=fail_err)
    ok_u, ack_u = request_live_unlatch(cell, fresh)
    note({"step": "strategy_fallback", "failed_candidate": fail_cand, "failed_family": candidate_family(fail_cand),
          "reason": fail_reason, "unlatched": ok_u, "error": ack_u.get("error") if not ok_u else None})
    if not ok_u:
        return None, hold(fail_reason, candidate=fail_cand, error=ack_u.get("error") or fail_err)
    release()
    latched["started"], latched["active"] = True, False
    state = known["state"] = ok_state_fn(ack_u) or fresh_state
    raw_t = (ack_u if isinstance(ack_u, dict) else {}).get("target") or fresh.get("target")
    target = list(raw_t[:6]) if isinstance(raw_t, list) and len(raw_t) >= 6 else list(state)
    status = ack_u if isinstance(ack_u, dict) and ack_u.get("state") else fresh
    return (state, target, bool(low(state)), status), None


def try_candidate(cell, name, before, frames, *, state, status, home, held_plan, allow_direct: bool,
                  look, load_check, reserve, release, latched: dict, known: dict, steps: list,
                  note, mark_moved, ok_state_fn, folded_fn, settle_tol: float, sleep, schema: str):
    """Run corridor/load/reservation checks then execute one fold candidate; return None/folded/failed."""
    from cell_pipeline_io import fold_from_hold, park_succeeded
    from cell_recovery_plan import run_detour_jogs
    from chunk_runner_recover import ensure_live_unlatch

    can_fold_direct = allow_direct and not before
    cand_frames = [state, *held_plan(state)] if can_fold_direct else frames
    cand_name = "fold-from-hold" if can_fold_direct else name
    verdict = look(cand_frames)
    note({"step": "check", "candidate": cand_name, "clear": verdict.get("clear"), "low": len(verdict.get("low") or []),
          "high": len(verdict.get("high") or []), "off_map": verdict.get("off_map"), "off_surface": verdict.get("off_surface")})
    if not verdict.get("clear"):
        return None
    if load_check is not None:
        lc = load_check(cand_frames)
        note({"step": "load_check", "candidate": cand_name, "ok": lc.get("ok"), "verdict": lc.get("verdict")})
        if not lc.get("ok"):
            return None
    if not (booked := reserve(cand_frames)).get("ok"):
        note({"step": "reserve", "candidate": cand_name, "refused": booked.get("reason")})
        return None
    if can_fold_direct:
        known["state"] = None
        mark_moved()
        try:
            parked = fold_from_hold(cell, status)
        except Exception as exc:  # noqa: BLE001
            parked = {"ok": False, "error": str(exc)}
        at = known["state"] = ok_state_fn(parked)
        note({"step": "fold_from_hold", "candidate": cand_name, "ok": parked.get("ok"), "settled": parked.get("settled"),
              "error": parked.get("error"), "contact": parked.get("contact")})
        if park_succeeded(parked) and at is not None and folded_fn(at, home):
            release()
            return "folded", {"schema": schema, "result": "folded", "candidate": cand_name, "state": at,
                              "steps": steps, "corridor": verdict, "unlatched_live_hold": True}
        return "failed", "PARK_NOT_HOME", cand_name, parked.get("error")
    ok_u, err_u = ensure_live_unlatch(cell, latched, note)
    if not ok_u:
        release()
        return "failed", "UNLATCH_REFUSED", name, err_u
    known["state"] = None
    mark_moved()
    ok_jog, err_reason, err_ack = run_detour_jogs(cell, list(before), settle_tol=settle_tol, sleep=sleep)
    if not ok_jog:
        return "failed", (err_reason or "DETOUR_REFUSED"), name, (err_ack or {}).get("error")
    parked = cell.act("park-slow" if latched["started"] else "park")
    at = known["state"] = ok_state_fn(parked)
    note({"step": "park", "candidate": name, "ok": parked.get("ok"), "settled": parked.get("settled"),
          "error": parked.get("error"), "contact": parked.get("contact")})
    ok_park = park_succeeded(parked) if latched["started"] else (parked.get("ok") is True and parked.get("settled") is True)
    if ok_park and at is not None and folded_fn(at, home):
        release()
        return "folded", {"schema": schema, "result": "folded", "candidate": name, "state": at, "steps": steps,
                          "corridor": verdict, **({"unlatched_live_hold": True} if latched["started"] else {})}
    return "failed", "PARK_NOT_HOME", name, parked.get("error")
