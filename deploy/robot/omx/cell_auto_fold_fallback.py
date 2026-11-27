"""Multi-strategy lift candidates, ranking, and guarded execution helpers (D-1048)."""
from __future__ import annotations


def extended_candidate_names() -> list[str]:
    """Return every tier-1 candidate name that `build_candidates(..., extended=True)` may produce."""
    return [
        "park",
        "lift_then_park", "lift_pan+10", "lift_pan-10",
        "elbow_lift_then_park", "elbow_lift_pan+10", "elbow_lift_pan-10",
        "pan+5", "pan-5", "pan+10", "pan-10", "pan+15", "pan-15",
        "elbow_clear_then_park",
    ]


def append_lift_candidates(cur: list[float], home: list[float], plan, *, bounds, tcp_x_m: float | None,
                           clear_z_m: float, situation: str,
                           fk_lift_fn, chunk_jog_fn, interp_fn, step_max: float,
                           elbow_cap: int, raw: list[tuple[str, list[str], list[list[float]]]]) -> None:
    """Append shoulder-first and elbow-first vertical clearance candidates."""
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

    if situation == "low_open_jaws":
        _add_group("lift", lift)
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
        if situation == "low_open_jaws" and name.startswith("elbow_lift_"):
            return 2
        return 3

    return sorted(tries, key=lambda c: (_prio(c[0]), rank.get(c[0], len(rank))))


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
