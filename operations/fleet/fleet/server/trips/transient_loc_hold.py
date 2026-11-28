"""Transient onboard CANDIDATES/SUSPECT hold helpers extracted from trip_steps (D-766 size cap)."""

from __future__ import annotations

import asyncio

import httpx

from fleet.server.named_stop_map_pose import read_precision_pose_status
from fleet.server.trip_halts import error_code, pre_dispatch_wait
from fleet.server.trip_ports import pose_diagnostics

# The robot stands still (goal canceled) while it waits. One onboard recovery on rosy_45 took about
# 20 s on 2026-11-27 (fit drop, node restart, 3 s search, initialpose, 3 s check); two fit in 45 s.
LOC_RECOVERY_WAIT_S = 45.0
# A robot standing in a traffic hold can lose its camera sighting for minutes (13:05-13:13Z, rosy_46 behind
# rosy_42: pose DEGRADED, trip stopped/pose). It cannot drift while standing, so wait for a re-sighting.
POSE_WAIT_S = 120.0  # shortcut: fixed bound, not tied to the traffic hold (the hold is not re-read while pose-less)
UNREACHABLE_GAP_S = 5.0  # failures further apart than this are separate outages
# 2026-11-28 user: a lost robot recovers on its own (camera cue + the rotate rung, which starts 10 s into the
# localization ladder and runs up to 30 s), so the standing trip waits past one full rotate before it ends.
LOC_LADDER_WAIT_S = 60.0


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
    if now - wait["since"] >= LOC_LADDER_WAIT_S:
        return False
    runner._save(live)
    return True


async def auto_rebind_before_dispatch(runner, live, robot_id: str) -> None:
    """D-1022: one auto-rebind attempt (map_binding_auto) for a robot whose map was redrawn in the same frame,
    before this trip has sent anything; the robot stands then. A mid-goal grid change still stops the trip."""
    rebind = getattr(runner, "auto_rebind", None)
    if (rebind is None or not runner.config.map_auto_rebind or runner._robot_state is None
            or live.last_goal is not None or live.active_route is not None or live.sent is not None
            or any(live.view["detail"].get(k) for k in ("goal_frame", "nav2_route"))):
        return
    try:  # the grid read is large: its own bound, not the 1.5 s port timeout
        state = await runner._call(runner._robot_state(robot_id))
        await asyncio.wait_for(rebind(robot_id, state or {}), 8.0)
    except Exception:  # noqa: BLE001 - no proof, no rebind: the trip stops as before
        pass


def hold_own_untrusted_goal(runner, live, robot_id: str, reply: dict, state) -> bool:
    """CORE's admission refused this robot's own goal for LOCALIZATION_UNTRUSTED before anything was sent: wait
    for the localization recovery (same bound as hold_transient_localization) and resend, instead of failing."""
    safety = (state or {}).get("safety") or {}
    if not (live.open and live.nav2 and reply.get("reason") == "LOCALIZATION_UNTRUSTED"
            and reply.get("blocked_by") == robot_id
            and (reply.get("dispatch_attempted") is False or reply.get("cancel_confirmed") is True)
            and safety.get("estop") is not True and (state or {}).get("mode") not in ("MANUAL", "ESTOP")):
        return False
    now = runner._clock()
    detail = live.view["detail"]
    wait = detail.get("localization_wait")
    if not isinstance(wait, dict):
        wait = detail["localization_wait"] = {"since": now}
    wait.update({"updated_at": now, "loc_state": ((state or {}).get("localization") or {}).get("state"),
                 "loc_reason": "goal_admission"})
    if now - wait["since"] >= LOC_LADDER_WAIT_S:
        return False
    detail["goal_admission"] = {"blocked_by": reply.get("blocked_by"), "waiting_on": list(reply.get("waiting_on") or ()),
                                "dispatch_attempted": bool(reply.get("dispatch_attempted")),
                                "cancel_confirmed": bool(reply.get("cancel_confirmed"))}
    live.active_route, live.progress_at = None, now
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


def _standing(state) -> bool:
    """Fresh zero velocity, no goal running, no estop: only then can an unusable pose not hide a moving robot."""
    state = state if isinstance(state, dict) else {}
    vel = state.get("velocity") or {}
    fresh = ((state.get("evidence") or {}).get("velocity") or {}).get("evidence") == "fresh"
    return (fresh and not (state.get("safety") or {}).get("estop")
            and state.get("navigation") not in ("NAVIGATING", "PLANNING", None)
            and state.get("mode") not in ("MANUAL", "ESTOP")
            and all(type(vel.get(k)) in (int, float) for k in ("linear", "angular"))
            and abs(vel["linear"]) < 0.01 and abs(vel["angular"]) <= 0.02)


async def hold_unusable_pose(runner, live, robot_id: str, pose) -> bool:
    """Keep a Nav2 trip up to POSE_WAIT_S while the map pose is DEGRADED/UNKNOWN (stale camera) and Fleet proves
    the robot stands. Nothing new is sent while it waits; a moving robot is stopped as before."""
    if not (live.nav2 and live.open and pose is not None and pose.state in ("DEGRADED", "UNKNOWN")
            and runner._robot_state is not None):
        return False
    try:
        state = await runner._call(runner._robot_state(robot_id))
    except Exception:
        return False
    if not _standing(state):
        return False
    detail, now = live.view["detail"], runner._clock()
    wait = detail.get("pose_wait")
    if not isinstance(wait, dict) or now - wait["updated_at"] > UNREACHABLE_GAP_S:  # a flapping pose keeps one budget
        wait = detail["pose_wait"] = {"since": now}
        live.active_route = None  # whatever was sent is void: cancel it, the route goes out again after the wait
        if runner._cancel_goal is not None:
            try:
                await runner._call(runner._cancel_goal(robot_id))
            except Exception:
                pass
    wait.update(updated_at=now, pose_state=pose.state)
    if now - wait["since"] >= POSE_WAIT_S:
        return False
    live.progress_at = now
    runner._save(live)
    return True


async def handle_unlocalized_pose(runner, live, robot_id: str, pose) -> None:
    """Hold transient unlocalized Nav2 poses if recoverable, else stop with structured diagnostics."""
    detail = live.view["detail"]
    if await hold_unusable_pose(runner, live, robot_id, pose):
        return
    detail.pop("pose_wait", None)
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
