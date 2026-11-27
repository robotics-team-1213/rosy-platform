"""D-1082: a Nav2 road trip that stops for a non-hazard reason keeps running and resends from where it stands.

The two reasons are ``stall`` (no progress) and ``navigation`` (Nav2 FAILED, or a CANCELED Fleet did not ask for).
``pose`` is not one: its waits and their bounds belong to transient_loc_hold (#1107 45 s, #1135 120 s standing).
Where ``TripRunner._stop`` would end the trip with one of them, ``recover_instead`` cancels the route (cancel -> ack,
as ``_cancel_active_route``) and records ``detail['recovery']``; ``resume_ready`` waits until the robot is proven
stopped and then lets the existing ``step_nav2_route`` resend from here (``sample_nav2_route(here=)``, the
lane-return route, recentred and from attempt 2 slowed: nav2_recovery_ladder). No new motion writer, no hold, no person. Everything else (E-stop, operator cancel or pause,
off-lane backstop, frame or binding refusals, map change, unconfirmed stops, lease or road-speed ownership) never
reaches here: a reason outside ``RECOVERABLE`` or a detail that marks the off-lane backstop or a link loss ends the
trip as before.

Order with the older paths: an autonomous robot's Nav2 FAILED stays with ``_handle_nav2_failure`` (it never calls
``_stop``); a route D-1080 replaced is ``superseded`` and never reads as aborted, so neither is handled twice.
"""
from __future__ import annotations

import logging

from fleet.server.nav2_recovery_ladder import attempt_entry, exhaust
from fleet.server.trip_halts import _cancel_ack
from fleet.server.trip_nav2_route import NAV2_TRANSIENT_RETRY_S

RECOVERABLE = ("stall", "navigation")
MAX_ATTEMPTS = 3          # recoveries per episode; the next stop ends the trip with its own reason
WINDOW_S = 300.0          # an episode ends this long after its first recovery
WAIT_S = 45.0             # one wait for the cause to clear (as transient_loc_hold's LOC_RECOVERY_WAIT_S)
SETTLE_S = NAV2_TRANSIENT_RETRY_S
#: Progress after a resume that closes the episode (count and window start over). Longer than any lane-return
#: correction, so a robot that keeps failing at one spot spends its budget instead of resetting it.
RESET_M = 1.0
_RUNNING = ("NAVIGATING", "PLANNING")

_LOG = logging.getLogger("fleet.server.trip_runner")


def _in_scope(runner, live, reason, stop_detail, state) -> bool:
    index = live.view["segment_index"]
    stop_detail = stop_detail or {}
    active = runner._store.active()
    topview = getattr(runner, "cell_topview", None)
    return (live.open and live.nav2 and reason in RECOVERABLE
            and "off_lane_m" not in stop_detail and "link_wait" not in stop_detail   # off-lane backstop, no link
            and live.view["state"] != "link_wait" and live.view.get("hold") is None    # pause, replan, nav2_problem
            and not (live.active_route or {}).get("wait_prefix")
            and not live.view["detail"].get("camera_lane_fallback")
            and runner._strict_named_stop(live, index) is None
            and runner._cancel_goal is not None and isinstance(state, dict)
            and (state.get("safety") or {}).get("estop") is False and state.get("mode") not in ("MANUAL", "ESTOP", "DOCKING")
            and live.view["detail"].get("parking_handoff") is None
            and not (topview is not None and topview.covers(live.arc(index).end_place))
            and active is not None and active[0] == live.view["map_version"])


async def _state(runner, robot_id):
    try:
        return await runner._call(runner._robot_state(robot_id)) if runner._robot_state is not None else None
    except Exception:  # noqa: BLE001 - an unread state proves nothing: the trip ends as before
        return None


async def recover_instead(runner, live, reason: str, stop_detail: dict | None) -> bool:
    """True: the trip stays running in recovery instead of ending with ``reason``."""
    rec = live.view["detail"].get("recovery")
    if rec is not None and rec.get("state") == "exhausted":
        return False
    robot_id = live.view["robot_id"]
    state = await _state(runner, robot_id)
    if not _in_scope(runner, live, reason, stop_detail, state):
        return False
    now = runner._clock()
    if rec is not None and rec["state"] == "waiting":   # the same cause has not cleared yet
        if now - rec["entered_at"] >= WAIT_S or now - rec["since"] >= WINDOW_S:
            exhaust(live, rec, now)
            return False
        rec["checked_at"] = now
        live.progress_at = now
        runner._save(live)
        return True
    attempt = (rec or {}).get("attempt", 0) + 1
    since = (rec or {}).get("since", now)
    if attempt > MAX_ATTEMPTS or now - since >= WINDOW_S:
        if rec is not None:
            exhaust(live, rec, now, reason)
        return False
    nav = state.get("navigation")
    if (live.active_route is not None or nav in _RUNNING) and nav not in ("ARRIVED", "IDLE"):
        try:
            receipt = await runner._call(runner._cancel_goal(robot_id))
        except Exception:  # noqa: BLE001 - an unconfirmed cancel ends the trip (its halt stops the robot)
            return False
        if not _cancel_ack(receipt) or not live.open:
            return False
    live.view["detail"].pop("named_stop_operation", None)
    live.active_route = None
    runner._fence(robot_id)
    live.progress_at = now
    live.view["detail"]["recovery"] = {
        "state": "waiting", "label": "복구 중", "reason": reason, "attempt": attempt, "max_attempts": MAX_ATTEMPTS,
        "since": since, "entered_at": now, "checked_at": now,
        "waiting_for": "robot_stopped", "stop_detail": dict(stop_detail or {}),
        "attempts": [*(rec or {}).get("attempts", []), attempt_entry(live, reason, attempt, now)],
    }
    _LOG.warning("trip %s: %s stop recovered instead (attempt %d/%d)", live.view["trip_id"], reason, attempt, MAX_ATTEMPTS)
    runner._save(live)
    return True


async def resume_ready(runner, live, index: int, s: float) -> bool:
    """True: ``step_nav2_route`` may run this tick (no recovery, or its cause cleared); False: still waiting."""
    from fleet.server.handoff_traffic import _fresh_stopped

    detail = live.view["detail"]
    rec = detail.get("recovery")
    if rec is None or rec.get("state") == "exhausted":
        return True
    now = runner._clock()
    if rec["state"] == "resumed":
        if live.active_route is not None and rec.get("resent_at") is None:
            rec["resent_at"] = now   # the recentred resend went out: later sends are plain
        if live.progress(index, s) >= rec["resumed_progress"] + RESET_M:
            detail["last_recovery"] = {**detail.pop("recovery"), "state": "recovered", "recovered_at": now}
        return True
    state = await _state(runner, live.view["robot_id"])
    readable = isinstance(state, dict)
    end = ("wait_s" if now - rec["entered_at"] >= WAIT_S else "window" if now - rec["since"] >= WINDOW_S
           else "estop" if readable and (state.get("safety") or {}).get("estop") is not False
           else "out_of_scope" if readable and not _in_scope(runner, live, rec["reason"], rec["stop_detail"], state)
           else None)   # MANUAL, DOCKING, a hold or a map change since entry: no resend
    if end is not None:
        exhaust(live, rec, now)
        await runner._stop(live, "stopped", rec["reason"], {**rec["stop_detail"], "recovery_end": end})
        return False
    live.progress_at = now
    rec["checked_at"] = now
    stopped = readable and state.get("navigation") not in _RUNNING and _fresh_stopped(state)
    rec["stopped_samples"] = rec.get("stopped_samples", 0) + 1 if stopped else 0   # two reads on two ticks
    if now - rec["entered_at"] < SETTLE_S or rec["stopped_samples"] < 2:
        runner._save(live)
        return False
    rec.update(state="resumed", waiting_for=None, resumed_at=now, resumed_progress=live.progress(index, s))
    return True
