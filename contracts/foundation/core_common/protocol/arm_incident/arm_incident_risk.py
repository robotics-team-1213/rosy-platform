"""Deterministic safety-score risk evaluation (0..100, auto-clear >= 95) for OMX arm incidents."""
from __future__ import annotations

import math

from .arm_incident_models import BODY_JOINTS, ArmIncidentRemeasure
from .arm_incidents import (
    REMEASURE_HOME_TOL,
    REMEASURE_MAX_AGE_S,
    REMEASURE_SKEW_S,
    clearable_after_fold,
    held_facts,
    machine_clearable,
    remeasure_kind,
    sag_ok,
    sag_stable,
)

RISK_SCHEMA = "rosy.arm-incident-risk.v1"
AUTO_CLEAR_MIN_SCORE = 95
MAX_RECENT_CLEARS_24H = 3


def _is_num(value) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(float(value))
    except OverflowError:
        return False


def _deduct(deductions: list[dict], code: str, penalty: int, detail: str) -> None:
    deductions.append({"code": code, "penalty": int(penalty), "detail": detail})


def _veto(vetoes: list[dict], code: str, detail: str) -> None:
    vetoes.append({"code": code, "detail": detail})


def _check_camera(camera_check, vetoes: list[dict], deductions: list[dict]) -> bool:
    if camera_check is None:
        return False
    if not isinstance(camera_check, dict):
        _veto(vetoes, "CAMERA_CHECK_INVALID", "camera check payload must be a dict")
        return False
    if camera_check.get("unavailable") or camera_check.get("error"):
        verdict = camera_check.get("verdict") if isinstance(camera_check.get("verdict"), dict) else {}
        if verdict.get("camera_clear") is False:
            worries = verdict.get("worries")
            detail = "; ".join(str(w) for w in worries[:4]) if isinstance(worries, list) and worries else "camera check not clear"
            _veto(vetoes, "CAMERA_CHECK_NOT_CLEAR", detail[:200])
            return False
        err = str(camera_check.get("error") or "camera check unavailable")[:160]
        _deduct(deductions, "CAMERA_CHECK_UNAVAILABLE", 6, err)
        return False
    verdict = camera_check.get("verdict") if isinstance(camera_check.get("verdict"), dict) else camera_check
    if verdict.get("camera_clear") is not True:
        worries = verdict.get("worries")
        detail = "; ".join(str(w) for w in worries[:4]) if isinstance(worries, list) and worries else "camera check not clear"
        _veto(vetoes, "CAMERA_CHECK_NOT_CLEAR", detail[:200])
        return False
    return True


def _check_motor_health(motor_health, since, now, vetoes: list[dict], deductions: list[dict]) -> bool:
    if motor_health is None:
        return False
    if not isinstance(motor_health, dict):
        _veto(vetoes, "MOTOR_HEALTH_INVALID", "motor health payload must be a dict")
        return False
    motors = motor_health.get("motors")
    if motors is None:
        motors = []
    if not isinstance(motors, list):
        _veto(vetoes, "MOTOR_HEALTH_INVALID", "motor health motors field must be a list")
        return False
    raw_reasons = motor_health.get("stop_reasons")
    if raw_reasons is not None and not isinstance(raw_reasons, (list, tuple)):
        _veto(vetoes, "MOTOR_HEALTH_INVALID", "motor health stop_reasons must be a list")
        stop_reasons = []
    else:
        stop_reasons = [
            str(r).strip() for r in (raw_reasons or ())
            if str(r).strip() and str(r).strip() != "session ended"
        ]
    if motor_health.get("status") == "fault" and stop_reasons:
        _veto(vetoes, "MOTOR_HEALTH_STOP_REASON", "; ".join(stop_reasons[:3])[:200])

    max_temp: float | None = None
    has_warnings = False
    for motor in motors:
        if not isinstance(motor, dict):
            _veto(vetoes, "MOTOR_HEALTH_INVALID", "motor entry must be a dict")
            continue
        label = str(motor.get("joint") or motor.get("id") or "motor")
        hw_err = motor.get("hardware_error")
        if hw_err is True or (
            isinstance(hw_err, int) and not isinstance(hw_err, bool) and hw_err != 0
        ) or (
            isinstance(hw_err, float) and (not math.isfinite(hw_err) or hw_err != 0.0)
        ) or (bool(hw_err) and not isinstance(hw_err, (int, float, bool))):
            _veto(vetoes, "MOTOR_HEALTH_HW_ERROR", f"{label} hardware_error={hw_err}")
        torque = motor.get("torque_enabled")
        if torque is True or (
            isinstance(torque, (int, float)) and not isinstance(torque, bool) and (not _is_num(torque) or torque != 0)
        ) or (
            isinstance(torque, str) and torque.strip().lower() not in ("", "0", "false", "off")
        ) or (bool(torque) and not isinstance(torque, (bool, int, float, str))):
            _veto(vetoes, "MOTOR_HEALTH_TORQUE_ON", f"{label} torque_enabled={torque}")
        if motor.get("fault"):
            _veto(vetoes, "MOTOR_HEALTH_STOP_REASON", f"{label} fault={motor.get('fault')}"[:160])
        temp = motor.get("temperature_c")
        t_limit = motor.get("temperature_limit_c")
        if temp is not None and not _is_num(temp):
            _veto(vetoes, "MOTOR_HEALTH_INVALID", f"{label} invalid temperature_c")
        elif temp is not None:
            t_val = float(temp)
            max_temp = t_val if max_temp is None else max(max_temp, t_val)
            if t_limit is not None and not _is_num(t_limit):
                _veto(vetoes, "MOTOR_HEALTH_INVALID", f"{label} invalid temperature_limit_c")
            else:
                limit = float(t_limit) if t_limit is not None else 65.0
                if t_val >= limit or t_val >= 65.0:
                    _veto(vetoes, "MOTOR_HEALTH_OVERTEMP", f"{label} temperature {t_val:.1f}C >= {min(limit, 65.0):.1f}C")
        volt, v_min, v_max = motor.get("voltage_v"), motor.get("min_voltage_v"), motor.get("max_voltage_v")
        if any(v is not None and not _is_num(v) for v in (volt, v_min, v_max)):
            _veto(vetoes, "MOTOR_HEALTH_INVALID", f"{label} invalid voltage field")
        elif _is_num(volt) and _is_num(v_min) and _is_num(v_max):
            if not (float(v_min) <= float(volt) <= float(v_max)):
                _veto(vetoes, "MOTOR_HEALTH_VOLTAGE_OUT_OF_RANGE",
                      f"{label} voltage {float(volt):.2f}V outside {float(v_min):.1f}..{float(v_max):.1f}V")
        if motor.get("warnings"):
            has_warnings = True

    if max_temp is not None:
        if max_temp >= 55.0:
            _deduct(deductions, "MOTOR_TEMP_HIGH", 6, f"max motor temp {max_temp:.1f}C >= 55C")
        elif max_temp >= 50.0:
            _deduct(deductions, "MOTOR_TEMP_ELEVATED", 3, f"max motor temp {max_temp:.1f}C >= 50C")
    if has_warnings:
        _deduct(deductions, "MOTOR_HEALTH_WARNINGS", 4, "motor health snapshot contains warnings")
    obs = motor_health.get("observed_at")
    if obs is not None and not _is_num(obs):
        _veto(vetoes, "MOTOR_HEALTH_INVALID", "invalid observed_at")
    elif _is_num(obs):
        obs_f = float(obs)
        if _is_num(since) and obs_f < float(since) - 30.0:
            _deduct(deductions, "MOTOR_HEALTH_STALE", 2, "motor health snapshot predates incident")
        elif _is_num(now) and (float(now) - obs_f) > 1800.0:
            _deduct(deductions, "MOTOR_HEALTH_STALE", 2, "motor health snapshot older than 1800s")
    return True


def _check_remeasured(remeasured, *, since, now, incident_id, binding, vetoes: list[dict]) -> None:
    """Enforce live register/pose/binding/freshness safety whenever a remeasured read is present (any incident kind)."""
    if remeasured is None:
        return
    try:
        read = ArmIncidentRemeasure.model_validate(remeasured)
    except (TypeError, ValueError) as exc:
        _veto(vetoes, "REMEASURE_INVALID", f"invalid remeasure payload: {type(exc).__name__}")
        return
    if any(read.torque_after.values()):
        _veto(vetoes, "REMEASURE_TORQUE_ON", "torque ON at the remeasure")
    if any(read.hardware_error.values()):
        _veto(vetoes, "REMEASURE_HW_ERROR", "hardware error at the remeasure")
    if binding is not None and (read.arm, read.board_serial) != tuple(binding):
        _veto(vetoes, "REMEASURE_BINDING_MISMATCH", "remeasure not of this arm's board")
    if incident_id is not None and read.incident_id != incident_id:
        _veto(vetoes, "REMEASURE_INCIDENT_MISMATCH", "remeasure not of this incident")
    if _is_num(since) and _is_num(now):
        if not float(since) < read.at <= float(now) + REMEASURE_SKEW_S or (float(now) - read.at) > REMEASURE_MAX_AGE_S:
            _veto(vetoes, "REMEASURE_STALE_OR_FUTURE", "remeasure outside valid freshness window")
    if not (read.folded and read.max_home_err <= REMEASURE_HOME_TOL) and not sag_ok(read):
        _veto(vetoes, "REMEASURE_NOT_AT_HOME", f"remeasure not folded at home or quiet sag (err {read.max_home_err:.2f})")


def _deduct_kind_and_pose(facts: dict, clear_path: str, policy_reason: str, remeasured, recovery, deductions: list[dict]) -> None:
    if clear_path == "clearable_after_fold":
        _deduct(deductions, "KIND_AUTO_FOLD", 3, "incident cleared via autonomous fold")
        state, home = recovery["folded_state"], recovery["home"]
        max_fold_err = max(abs(float(a) - float(b)) for a, b in zip(state[:5], home[:5]))
        if max_fold_err > 2.0:
            _deduct(deductions, "POSE_AUTO_FOLD_MARGIN", 3, f"auto-fold max joint error {max_fold_err:.2f} > 2.0")
        return

    if held_facts(facts):
        _deduct(deductions, "KIND_HELD_BOX", 3, "incident involved object held in jaws")
    elif policy_reason.startswith("bus link failure"):
        _deduct(deductions, "KIND_BUS_LINK", 2, "incident involved bus link failure")
    elif policy_reason.startswith("park strain stop"):
        _deduct(deductions, "KIND_PARK_STRAIN", 2, "incident involved park strain stop")
    elif remeasure_kind(facts) is not None:
        _deduct(deductions, "KIND_REMEASURE", 1, "incident required fresh motionless remeasure")

    if remeasured is not None:
        read = ArmIncidentRemeasure.model_validate(remeasured)
        if not read.folded or read.max_home_err > REMEASURE_HOME_TOL:
            _deduct(deductions, "POSE_SAG_ENVELOPE", 4, f"remeasured pose in sag envelope (err {read.max_home_err:.2f})")
        elif read.max_home_err > 2.0 and not sag_stable(read):
            _deduct(deductions, "POSE_NEAR_TOL_UNSTABLE", 5,
                    f"remeasured pose near tolerance ({read.max_home_err:.2f}) without dual-read stability")
        return

    if facts.get("folded") is not True:
        last, home, target = facts.get("last_state"), facts.get("home"), facts.get("last_target")
        if all(isinstance(r, list) and len(r) >= len(BODY_JOINTS) for r in (last, home, target)):
            max_rest_err = max(abs(float(a) - float(b)) for a, b in zip(last[:5], home[:5]))
            max_still_err = max(abs(float(a) - float(b)) for a, b in zip(last[:5], target[:5]))
            if max_rest_err > 6.5:
                _deduct(deductions, "POSE_RESTED_HIGH_DRIFT", 6, f"rested arm drift {max_rest_err:.2f} > 6.5")
            else:
                _deduct(deductions, "POSE_RESTED_NEAR_HOME", 3, f"rested (unfolded) arm near home (err {max_rest_err:.2f})")
            if max_still_err > 1.5:
                _deduct(deductions, "STILL_DRIFT_WARN", 4, f"target drift {max_still_err:.2f} > 1.5")


def evaluate_clear_safety(
    facts: dict | None,
    *,
    remeasured: dict | None = None,
    recovery: dict | None = None,
    verdict: dict | None = None,
    stills: set[str] | frozenset[str] | None = None,
    camera_check: dict | None = None,
    motor_health: dict | None = None,
    recent_clears_24h: int = 0,
    since: float | None = None,
    now: float | None = None,
    incident_id: str | None = None,
    binding: tuple[str, str] | None = None,
    min_score: int = AUTO_CLEAR_MIN_SCORE,
) -> dict:
    """Evaluate hard vetoes and deterministic 0..100 safety score (threshold >= 95) before machine auto-clear."""
    if isinstance(min_score, bool) or not isinstance(min_score, int) or not (AUTO_CLEAR_MIN_SCORE <= min_score <= 100):
        raise ValueError("min_score must be an integer in [95, 100]")

    vetoes: list[dict] = []
    deductions: list[dict] = []

    ok, why = machine_clearable(
        facts, remeasured, since=since, now=now, incident_id=incident_id,
        binding=binding, verdict=verdict, stills=stills,
    )
    clear_path = "machine_clearable" if ok else "none"
    if not ok and recovery is not None:
        fold_ok, fold_why = clearable_after_fold(facts, recovery, incident_id, since)
        if fold_ok:
            ok, why, clear_path = True, fold_why, "clearable_after_fold"
        else:
            why = f"{why}; {fold_why}"
    if not ok:
        _veto(vetoes, "POLICY_NOT_CLEARABLE", why)

    if isinstance(recent_clears_24h, bool) or not isinstance(recent_clears_24h, int) or recent_clears_24h < 0:
        _veto(vetoes, "INVALID_REPEAT_COUNT", f"invalid recent_clears_24h={recent_clears_24h!r}")
    elif recent_clears_24h >= MAX_RECENT_CLEARS_24H:
        _veto(vetoes, "REPEAT_LIMIT_EXCEEDED", f"{recent_clears_24h} machine clears in 24h >= {MAX_RECENT_CLEARS_24H}")
    elif recent_clears_24h == 1:
        _deduct(deductions, "REPEAT_RECENT_1", 2, "1 machine clear in the last 24h")
    elif recent_clears_24h == 2:
        _deduct(deductions, "REPEAT_RECENT_2", 4, "2 machine clears in the last 24h")

    camera_checked = _check_camera(camera_check, vetoes, deductions)
    motor_checked = _check_motor_health(motor_health, since, now, vetoes, deductions)
    _check_remeasured(remeasured, since=since, now=now, incident_id=incident_id, binding=binding, vetoes=vetoes)

    if ok and not vetoes and isinstance(facts, dict):
        _deduct_kind_and_pose(facts, clear_path, why, remeasured, recovery, deductions)

    if vetoes:
        safety_score = 0
    else:
        safety_score = max(0, min(100, 100 - sum(int(d["penalty"]) for d in deductions)))
    risk_score = 100 - safety_score
    allowed = (not vetoes) and (safety_score >= min_score)
    decision = "auto_clear" if allowed else "escalate_human"
    return {
        "schema": RISK_SCHEMA,
        "threshold": min_score,
        "safety_score": safety_score,
        "risk_score": risk_score,
        "allowed": allowed,
        "decision": decision,
        "clear_path": clear_path,
        "policy_reason": why,
        "hard_vetoes": vetoes,
        "deductions": deductions,
        "signals": {
            "recent_clears_24h": recent_clears_24h,
            "camera_checked": camera_checked,
            "motor_health_checked": motor_checked,
            "remeasured": remeasured is not None,
            "auto_fold": recovery is not None,
        },
    }
