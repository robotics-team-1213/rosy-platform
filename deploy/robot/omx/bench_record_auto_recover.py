#!/usr/bin/env python3
"""Strictly safety-gated automatic recovery for folded-at-home HOLDs, dead leases, stopped units, and baseline caps."""
from __future__ import annotations

import json
import math
from pathlib import Path
import time

from bench_record_guard import recorder_running
from bench_record_handoff import load_json_value
from bench_record_inspect import ARMS

SAFE_FOLD_TOL = 3.0
SAFE_LIFT_MAX = -50.0
SAFE_ELBOW_MIN = 45.0
SAFE_PWM_MAX = 120.0
LIVE_MAX_AGE_S = 10.0


def library_home_pose(prep: Path, arm: str) -> list[float] | None:
    letter = ARMS.get(arm)
    if not letter:
        return None
    libs = sorted(prep.glob(f"chunks-arm-{letter}-inplace-live.json" if arm == "arm_s" else f"chunks-topdown-guard-arm{letter}*.json"))
    if not libs:
        return None
    doc = load_json_value(libs[-1], {})
    home_seq = (doc.get("chunks") or {}).get("home") if isinstance(doc, dict) else None
    if not isinstance(home_seq, list) or not home_seq:
        return None
    last = home_seq[-1]
    if not isinstance(last, list) or len(last) < 5 or any(type(x) not in (int, float) or not math.isfinite(x) for x in last[:5]):
        return None
    return [float(x) for x in last[:6]]


def safe_folded_hold(prep: Path, arm: str | None, mh: dict | None, now=time.time) -> tuple[bool, str]:
    """Allow automatic SIGUSR2 runner release ONLY when fresh live telemetry proves the arm is folded safely at home."""
    if arm not in ARMS or not isinstance(mh, dict) or mh.get("runner_alive") is not True:
        return False, "실행 중인 단일 팔 HOLD 러너가 아닙니다"
    pid = mh.get("runner_pid")
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 1:
        return False, "유효한 러너 PID를 확인할 수 없습니다"
    from bench_record_recover import _pid_is_chunk_runner
    if not _pid_is_chunk_runner(pid):
        return False, f"PID {pid}가 chunk_runner가 아닙니다"
    io_dir = prep / f"chunk-io-{ARMS[arm]}"
    live_p, hold_p = io_dir / "live.json", io_dir / "hold.json"
    if not live_p.is_file():
        return False, "실시간 관절 좌표(live.json)가 없어 접힘 여부를 확인할 수 없습니다"
    try:
        age = float(now()) - live_p.stat().st_mtime
    except OSError:
        return False, "실시간 관절 좌표 시각을 확인할 수 없습니다"
    if not 0 <= age <= LIVE_MAX_AGE_S:
        return False, f"실시간 관절 좌표가 오래되었습니다 ({age:.1f}s) — 사람이 팔 상태를 확인하세요"
    hold_doc = load_json_value(hold_p, {})
    if isinstance(hold_doc, dict):
        if hold_doc.get("label") == "PARTIAL_GUARD_STOP":
            return False, "부분 가드 정지(PARTIAL_GUARD_STOP) 상태는 사람이 직접 확인해야 합니다"
        err_low = str(hold_doc.get("error") or "").lower()
        if any(tok in err_low for tok in ("hardware", "overload", "unfolded")):
            return False, f"하드웨어/과부하 HOLD({hold_doc.get('error')})는 자동 해제하지 않습니다"
    live_doc = load_json_value(live_p, {})
    if not isinstance(live_doc, dict) or live_doc.get("pid") != pid:
        return False, "live.json의 PID가 실행 중인 러너와 일치하지 않습니다"
    if live_doc.get("holding") is not False:
        return False, "그리퍼 파지 중(holding=true) 상태는 자동 토크 해제를 금지합니다"
    if live_doc.get("fault"):
        return False, f"런타임 fault({live_doc.get('fault')}) 상태는 수동 확인이 필요합니다"
    state = live_doc.get("state")
    if not isinstance(state, list) or len(state) < 5 or any(type(x) not in (int, float) or not math.isfinite(x) for x in state[:5]):
        return False, "live.json 관절 좌표가 유효하지 않습니다"
    home = library_home_pose(prep, arm)
    if home is None:
        return False, f"{arm} 기준 홈 라이브러리(chunks-*.json)를 찾을 수 없어 안전 확인이 불가합니다"
    diffs = [abs(float(a) - float(b)) for a, b in zip(state[:5], home[:5])]
    if max(diffs) > SAFE_FOLD_TOL:
        return False, f"팔이 홈 자세에서 벗어나 있어(최대 {max(diffs):.1f} > {SAFE_FOLD_TOL}) 사람이 받친 뒤 해제해야 합니다"
    if float(state[1]) > SAFE_LIFT_MAX or float(state[2]) < SAFE_ELBOW_MIN:
        return False, f"어깨/팔꿈치가 완전히 접히지 않아(lift={state[1]:.1f}, elbow={state[2]:.1f}) 자동 토크 해제를 거부합니다"
    pwm = (live_doc.get("health") or {}).get("pwm") if isinstance(live_doc.get("health"), dict) else None
    if isinstance(pwm, list) and len(pwm) >= 5 and all(type(x) in (int, float) and math.isfinite(x) for x in pwm[:5]):
        if abs(float(pwm[1])) > SAFE_PWM_MAX or abs(float(pwm[2])) > SAFE_PWM_MAX:
            return False, f"접힌 상태 부하 PWM이 높아({pwm[1]:.0f}, {pwm[2]:.0f}) 사람이 직접 확인해야 합니다"
    return True, "팔이 홈에 완전히 접혀 있어 안전 자동 복구 가능"


def assess_auto_recover(bench, st: dict, mh: dict | None, pending: list, locks: list, dead_leases: list,
                        inc_holds: dict, baseline_needed: bool, can_ack: bool) -> dict:
    """Determine whether all current bench holds/pending recovery items can be cleared safely without physical touch."""
    target_arm = (mh or {}).get("arm") if (mh and mh.get("arm") in ARMS) else (
        st.get("arm") if st.get("arm") in ARMS else (dead_leases[0] if len(dead_leases) == 1 and dead_leases[0] in ARMS else None)
    )
    if st.get("status") in ("handing_over", "recording", "restoring", "sealing"):
        return {"eligible": False, "reason": "세션 진행 중에는 자동 복구할 수 없습니다", "steps": [], "arm": target_arm}
    if inc_holds:
        return {"eligible": False, "reason": "Fleet 사고 보류는 자동 복구할 수 없습니다", "steps": [], "arm": target_arm}
    own_pid = mh.get("runner_pid") if (mh and mh.get("runner_alive")) else None
    foreign_locks = [lk for lk in locks if not (own_pid and lk.get("pid") == own_pid)]
    if foreign_locks:
        return {"eligible": False, "reason": "다른 OMX 세션 락이 점유 중입니다", "steps": [], "arm": target_arm}
    steps = []
    if mh:
        if mh.get("runner_alive"):
            ok, why = safe_folded_hold(bench.prep, mh.get("arm"), mh, now=bench.clock)
            if not ok:
                return {"eligible": False, "reason": why, "steps": [], "arm": target_arm}
            steps.append("release_folded_runner")
        steps.append("clear_manual_hold")
    elif dead_leases:
        if recorder_running(bench.procs):
            return {"eligible": False, "reason": "녹화/러너 프로세스가 실행 중입니다", "steps": [], "arm": target_arm}
        steps.append("clear_dead_lease")
    if pending:
        steps.append("restore_units")
    if baseline_needed and target_arm in ARMS:
        steps.append("restore_baseline")
    if can_ack:
        steps.append("ack_error")
    if not steps:
        return {"eligible": False, "reason": "자동 복구 대상이 없습니다", "steps": [], "arm": target_arm}
    return {"eligible": True, "reason": "안전 확인됨 — 접힌 홈 HOLD·보류·유닛·기준 캡 자동 복구 가능", "steps": steps, "arm": target_arm}


class BenchAutoRecoverMixin:
    def auto_recover(self, body=None):
        """Safely chain folded-at-home HOLD release -> hold/lease clear -> unit restore -> torque-OFF baseline -> idle."""
        st = self.status()
        rec = st.get("recovery") if isinstance(st.get("recovery"), dict) else {}
        ar = rec.get("auto_recover") if isinstance(rec.get("auto_recover"), dict) else {}
        mh = st.get("manual_hold") if isinstance(st.get("manual_hold"), dict) and st["manual_hold"].get("active") else None
        if not ar.get("eligible"):
            raise ValueError(ar.get("reason") or "안전 자동 복구 조건을 만족하지 않습니다 — 수동 확인이 필요합니다")
        target_arm = (body or {}).get("arm") if isinstance(body, dict) and (body or {}).get("arm") in ARMS else ar.get("arm")
        steps = []
        if mh and mh.get("runner_alive"):
            ok, why = safe_folded_hold(self.prep, mh.get("arm"), mh, now=self.clock)
            if not ok:
                raise ValueError(why)
            rel = self.release_held_runner({"arm": mh["arm"], "pid": mh["runner_pid"], "arm_supported_confirmed": True})
            if rel.get("torque_off_confirmed") is not True:
                raise ValueError("러너 토크 OFF 확인(released.json)이 없어 자동 보류 해제를 중단합니다")
            steps.append("runner_released_folded")
        dead_leases = rec.get("dead_lease_arms") or []
        if mh or self.manual.exists() or dead_leases:
            self.clear_manual_hold({"confirmed": True, "force_dead_lease": True})
            steps.append("manual_hold_cleared")
        if self.pending.exists() and not self.manual.exists():
            self.recover_restore_units()
            steps.append("units_restored")
        if rec.get("baseline_needed") and target_arm in ARMS and not self.manual.exists():
            self.recover_baseline({"arm": target_arm})
            steps.append("baseline_restored")
        cur = self.status()
        cur_rec = cur.get("recovery") if isinstance(cur.get("recovery"), dict) else {}
        if cur_rec.get("can_ack_error"):
            self.ack_bench_error()
            steps.append("error_acked")
            cur = self.status()
        if hasattr(self, "_log_event"):
            self._log_event("bench", "good", f"안전 자동 복구 완료 ({' → '.join(steps) or '확인'})")
        return {"ok": True, "steps": steps, "arm": target_arm, "status": cur}
