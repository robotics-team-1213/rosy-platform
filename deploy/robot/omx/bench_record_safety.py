"""Verdict of a recording child that ended without sealing: is the arm's safe end proven by session.json? (U2, 2026-11-21)

The only evidence is what record_session measured and wrote at the end of that session (Session.finish: torque_off_confirmed,
caps_restored, hardware_faults, manual_attention_required, safe_end), plus the local arm incident hold. A child exit code other
than 0 alone (a guard stop at the start of the next episode) does not say the arm is unsafe; a missing or false item does.
"""
from __future__ import annotations

import json
from pathlib import Path

LEFT_KEYS = ("runner_held", "runner_killed", "runner_unconfirmed")  # record_session_helpers.LEFT_KEYS (kept light: no heavy import)
ARM_PAIR = {"arm_ab": ("arm_a", "arm_b")}


def _held_reason(arm):
    from omx_incident_fleet import held  # the local copy of the hold: no network on a status poll

    return held(arm)


def unconfirmed_items(record, arm, held_of=_held_reason):
    """What the session record does not prove, as short Korean items; empty list = safe end proven."""
    if not isinstance(record, dict) or not record:
        return ["session.json 없음 또는 읽을 수 없음"]
    out = []
    if record.get("safe_end") is not True:
        out.append("safe_end 아님")
    if record.get("torque_off_confirmed") is not True:
        out.append("토크 OFF 미확인")
    if record.get("caps_restored") is not True:  # a list means restore failures
        out.append("caps 복원 미확인 또는 실패")
    if record.get("manual_attention_required") is not False:
        out.append("현장 수동 확인 필요")
    if record.get("hardware_faults"):
        out.append("모터 하드웨어 오류 기록")
    if record.get("interrupted") or any(record.get(k) for k in LEFT_KEYS):
        out.append("중단됨 또는 runner가 팔을 잡고 있음")
    arms = ARM_PAIR.get(arm) or ((arm,) if arm else ())
    if not arms:
        out.append("팔 이름 미확인(사고 조회 불가)")
    for a in arms:
        try:
            reason = held_of(a)
        except Exception as exc:  # fail closed: an unreadable hold is not "no incident"
            out.append(f"{a} 사고 조회 실패: {type(exc).__name__}")
            continue
        if reason:
            out.append(f"{a} 사고 열림: {reason}")
    return out


def stop_cause(folder):
    """Last non-empty line of the child's log (the exception or guard message that ended it)."""
    try:
        lines = [x.strip() for x in (Path(folder) / "bench.log").read_text(encoding="utf-8", errors="replace").splitlines() if x.strip()]
    except OSError:
        return ""
    return lines[-1][:300] if lines else ""


def end_verdict(state, held_of=_held_reason):
    """Status fields for a finished session that was not sealed because the child exit was not 0 (or safe_end was not true)."""
    folder = state.get("folder")
    try:
        record = json.loads((Path(folder) / "session.json").read_text()) if folder and (Path(folder) / "session.json").is_file() else {}
    except (OSError, ValueError):
        record = {}
    missing = unconfirmed_items(record, state.get("arm"), held_of)
    if missing:
        return {"status": "unsafe_or_failed", "unconfirmed": missing}
    return {"status": "stopped_safe", "unconfirmed": [], "stop_cause": stop_cause(folder)}
