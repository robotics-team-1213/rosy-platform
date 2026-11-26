"""Paced ACT start check: the arm is stationary at home with a confirmed empty gripper (split from cell_policy_paced)."""
from __future__ import annotations

import time

from cell_policy_entry import PRE_SETTLE_TOL, stationary_idle as _stationary_idle
from cell_policy_timing import (
    ack_status as _ack_status, best_effort_hold as _best_effort_hold, empty_gripper_ok as _empty_gripper_ok,
    library_home as _library_home, max_diff as _max_diff, rest_diagnosis as _rest_diagnosis, send_hold as _send_hold,
)

HOLD_CURRENT_LIMIT_MA = 140.0


def pre_settle_home(cell, library: dict, status: dict, row: dict, log, kin, jaw_spec,
                     *, sleep=time.sleep) -> tuple[dict | None, dict | None]:
    """Fail-closed verification that the arm starts stationary at home with a confirmed empty gripper."""
    from cell_policy_shape import jaw_zone_error

    hold_sent, home = False, None

    def _refuse(cur: dict, reason: str, *, base: dict = row, result: str = "refused", keep_hold: bool = False, **extra):
        nonlocal hold_sent
        diag = _rest_diagnosis(cur, home)
        hold = keep_hold or home is None or not diag["no_hold"]  # no command sent: a clean arm at home or folded ends the session without a hold
        facts = {"reason_code": reason.split(":")[0], "off_home": diag["off_home"], "folded": diag["folded"], "hold_kept": hold,
                 **({"next": "recover_hold"} if hold else {})}  # a kept hold is cleared by the recover_hold job (attach_live_hold)
        rows = [{**base, "refused": reason, **facts, **extra, **(_ack_status(cur) if isinstance(cur, dict) else {})}]
        if hold:
            rows.append({"command": "human-hold", **_ack_status(_send_hold(cell, log=log))})
            hold_sent = True
        for r in rows:
            log(r)
        return None, {"result": result, "at": 0, "reason": reason, "parked": False, **facts}

    try:
        home = _library_home(library)
        if not _empty_gripper_ok(status, HOLD_CURRENT_LIMIT_MA, now=time.time()):
            return _refuse(status, "START_POSE_OFF_HOME: unconfirmed empty gripper",
                           result="fault" if status.get("fault") else "refused")
        if home is None:
            return _refuse(status, "START_POSE_OFF_HOME: library missing home")
        if (off_home := _max_diff([float(v) for v in status["state"]], home, 5)) > PRE_SETTLE_TOL:
            return _refuse(status, "START_POSE_OFF_HOME: arm off home; run home stage first", off_home=round(off_home, 3))
        s2, p2 = _stationary_idle(cell, status, home, check_home_target=True, max_off_home=PRE_SETTLE_TOL, sleep=sleep)
        if not isinstance(s2, dict) or not _empty_gripper_ok(s2, HOLD_CURRENT_LIMIT_MA, now=time.time()):
            return _refuse(s2, "START_POSE_OFF_HOME: unconfirmed empty gripper",
                           result="fault" if isinstance(s2, dict) and s2.get("fault") else "refused")
        if p2 is None:
            return _refuse(s2, "START_POSE_OFF_HOME", keep_hold=True,  # not stationary: something else moves the arm
                           result="fault" if isinstance(s2, dict) and s2.get("fault") else "refused")
        live_poses = [p2, *([s2["target"]] if s2.get("target") is not None else [])]
        if jaw_spec is not None and (jaw_warn := jaw_zone_error(live_poses, kin, jaw_spec)):
            return _refuse(s2, jaw_warn, jaw_warning=jaw_warn)
        return s2, None
    except BaseException as exc:
        hold_row = _best_effort_hold(cell, log=log) if not hold_sent else None
        if not isinstance(exc, Exception) or (not hold_sent and hold_row is None):
            raise
        for entry in ({**row, "refused": "START_POSE_OFF_HOME", "error": str(exc)[:200] or type(exc).__name__},
                      *([hold_row] if hold_row else ())):
            try:
                log(entry)
            except Exception:
                pass
        return None, {"result": "refused", "at": 0, "reason": "START_POSE_OFF_HOME", "parked": False}
