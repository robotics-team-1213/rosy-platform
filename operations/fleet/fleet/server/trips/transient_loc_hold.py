"""Transient onboard CANDIDATES/SUSPECT hold helpers extracted from trip_steps (D-766 size cap)."""

from __future__ import annotations

import httpx

from fleet.server.named_stop_map_pose import read_precision_pose_status
from fleet.server.trip_halts import error_code, pre_dispatch_wait
from fleet.server.trip_ports import pose_diagnostics

# The robot stands still (goal canceled) while it waits. One onboard recovery on rosy_45 took about
# 20 s on 2026-11-27 (fit drop, node restart, 3 s search, initialpose, 3 s check); two fit in 45 s.
LOC_RECOVERY_WAIT_S = 45.0
UNREACHABLE_GAP_S = 5.0  # failures further apart than this are separate outages


def loc_diag_from_state(
    state: dict | None,
    active_binding: dict | None,
    *,
    reason: str = "ROBOT_NOT_LOCALIZED",
) -> dict:
    """Extract bounded onboard localization diagnostics for transient holds."""
    loc = (state or {}).get("localization") or {}
    safety = (state or {}).get("safety") or {}
    return {
        "pose_reason": reason,
        "loc_state": loc.get("state"),
        "loc_reason": loc.get("reason"),
        "robot_grid_id": (state or {}).get("map_grid_id"),
        "binding_grid_id": (active_binding or {}).get("robot_grid_id"),
        "navigation": (state or {}).get("navigation"),
        "mode": (state or {}).get("mode"),
        "estop": bool(safety.get("estop")),
    }


async def hold_transient_localization(runner, live, robot_id: str, diag: dict) -> bool:
    """Hold a Nav2 trip up to LOC_RECOVERY_WAIT_S while onboard localization recovers (UNKNOWN: its node restarts)."""
    detail = live.view["detail"]
    recoverable = (
        live.nav2
        and live.open
        and diag.get("pose_reason") == "ROBOT_NOT_LOCALIZED"
        and diag.get("loc_state") in ("SUSPECT", "CANDIDATES", "UNKNOWN")
        and diag.get("robot_grid_id") is not None
        and diag.get("robot_grid_id") == diag.get("binding_grid_id")
        and not diag.get("estop")
        and diag.get("mode") not in ("MANUAL", "ESTOP")
    )
    if not recoverable:
        return False
    live.active_route = None
    if diag.get("navigation") in ("NAVIGATING", "PLANNING") and runner._cancel_goal is not None:
        try:
            await runner._call(runner._cancel_goal(robot_id))
        except Exception:
            pass
    now = runner._clock()
    live.progress_at = now
    wait = detail.get("localization_wait")
    if not isinstance(wait, dict):
        wait = {"since": now}
        detail["localization_wait"] = wait
    wait.update({"updated_at": now, "loc_state": diag.get("loc_state"), "loc_reason": diag.get("loc_reason")})
    if now - wait["since"] >= LOC_RECOVERY_WAIT_S:
        return False
    runner._save(live)
    return True


async def hold_unreachable_pre_dispatch(runner, live, exc) -> bool:
    """A robot that gave no answer (CORE restart, ~16 s on 2026-11-27) while the trip waits before any goal went
    out has no motion of ours to lose: keep the trip up to LOC_RECOVERY_WAIT_S. A moving robot never gets this."""
    # Only a connection that never opened proves nothing of ours reached the robot; a timeout may follow a
    # delivered request (D-760 4 HIGH-1), and a stale peer_wait must not vouch for a goal sent since.
    never_connected = (isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout, OSError))
                       and not isinstance(exc, TimeoutError))
    if not (live.open and never_connected and live.active_route is None and live.last_goal is None
            and pre_dispatch_wait(live.view)):
        return False
    now = runner._clock()
    wait = live.view["detail"].get("unreachable_wait")
    if not isinstance(wait, dict) or now - wait["updated_at"] > UNREACHABLE_GAP_S:
        wait = live.view["detail"]["unreachable_wait"] = {"since": now}  # an earlier outage that ended
    wait.update(updated_at=now, kind=error_code(exc))
    if now - wait["since"] >= LOC_RECOVERY_WAIT_S:
        return False
    live.at, live.at_stamp, live.progress_at = None, None, now
    runner._save(live)
    return True


async def handle_unlocalized_pose(runner, live, robot_id: str, pose) -> None:
    """Hold transient unlocalized Nav2 poses if recoverable, else stop with structured diagnostics."""
    detail = live.view["detail"]
    binding_id = detail.get("precision_binding_id") or detail.get("nav2_binding_id")
    pose_diag: dict = {}
    if pose is None and binding_id is not None:
        _, pose_diag = await read_precision_pose_status(runner, robot_id, live.view["map_version"], binding_id)
        if await hold_transient_localization(runner, live, robot_id, pose_diag):
            return
    detail.pop("localization_wait", None)
    await runner._stop(
        live,
        "stopped",
        "pose",
        {"pose_state": pose.state if pose else None, **pose_diagnostics(pose), **pose_diag},
        halt_free=(
            binding_id is not None
            or runner._auto_locate_on(robot_id)
            or runner._named_stop_handoff(live, live.view["segment_index"])
        ),
    )


def consume_transient_wait(runner, live, prev_loc_wait_at) -> bool:
    """Save and return True if transient localization hold updated this tick; otherwise clear wait marker."""
    cur_loc_wait = live.view["detail"].get("localization_wait")
    if isinstance(cur_loc_wait, dict) and cur_loc_wait.get("updated_at") != prev_loc_wait_at:
        runner._save(live)
        return True
    live.view["detail"].pop("localization_wait", None)
    return False


async def recheck_binding(runner, live, active) -> None:
    """Stop (or briefly hold transient CANDIDATES/SUSPECT) if bound grid/localization changed mid-goal."""
    robot_id = live.view["robot_id"]
    state = await runner._call(runner._robot_state(robot_id)) if runner._robot_state is not None else None
    _, reason = runner._store.map_bindings.matching_fit(robot_id, state or {}, (active[1].map_id, active[0]))
    active_binding = runner._store.map_bindings.active(robot_id) or {}
    sent = (live.view["detail"].get("goal_frame") or {}).get("binding_id")
    if not reason and sent != active_binding.get("binding_id"):
        reason = "MAP_BINDING_CHANGED"
    if reason == "ROBOT_NOT_LOCALIZED" and sent == active_binding.get("binding_id"):
        diag = loc_diag_from_state(state, active_binding, reason=reason)
        if await hold_transient_localization(runner, live, robot_id, diag):
            return
    if reason:
        await runner._stop(live, "stopped", "map_frame", {"map_id": active[1].map_id, "binding": reason})
