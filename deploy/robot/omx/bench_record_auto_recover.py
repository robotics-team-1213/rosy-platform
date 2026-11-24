#!/usr/bin/env python3
"""Strictly safety-gated automatic recovery for folded-at-home HOLDs, dead leases, stopped units, and baseline caps."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time

from bench_record_guard import recorder_running
from bench_record_handoff import load_json_value
from bench_record_inspect import ARMS, HERE

SAFE_FOLD_TOL = 3.0
SAFE_LIFT_MAX = -50.0
SAFE_ELBOW_MIN = 45.0
SAFE_PWM_MAX = 120.0
LIVE_MAX_AGE_S = 10.0


def _home_failure_guidance(arm: str, err: str) -> str:
    low = str(err or "").lower()
    if any(tok in low for tok in ("경로 차단", "corridor", "장애물")):
        return "상단 카메라 작업 경로의 장애물·그리퍼 간섭을 치운 뒤 '홈으로 이동'을 다시 실행하세요."
    if any(tok in low for tok in ("hold", "토크 유지", "manual")):
        return "팔을 손으로 받친 상태에서 '토크 해제(SIGUSR2)' 후 접고 다시 확인하세요."
    if any(tok in low for tok in ("연결되어 있지 않", "port", "serial")):
        return f"{arm} USB·전원 연결을 점검하고 '연결 재확인' 후 홈 복귀를 다시 시도하세요."
    if any(tok in low for tok in ("incident", "fleet", "보류")):
        return "Fleet 사고 보류가 남아 있습니다. 물리 상태(집게·충돌·과부하)를 확인한 뒤 보류를 해제하세요."
    return "팔 주변 간섭과 집게 상태를 확인한 뒤, 팔을 받치고 토크 OFF 상태에서 접어 다시 시도하세요."


def _ensure_foundation_path() -> None:
    extra = HERE.parents[3] / "contracts" / "foundation"
    if extra.is_dir() and str(extra) not in sys.path:
        sys.path.insert(0, str(extra))


def _latest_local_incident(prep: Path, arm: str) -> dict | None:
    import omx_incident_fleet

    roots = [prep / "incidents"]
    inc_root = omx_incident_fleet.incidents_dir()
    if inc_root not in roots:
        roots.append(inc_root)
    files = [p for root in roots if root.is_dir() for p in root.glob(f"*-{arm}/incident.json")]
    if not files:
        return None
    doc = load_json_value(max(files, key=lambda p: p.parent.name), None)
    return doc if isinstance(doc, dict) else None


def _incident_reassess_config(prep: Path, arm: str) -> Path | None:
    letter = ARMS.get(arm)
    if not letter:
        return None
    for name in (f"cell-arm-{letter}-stack.json", f"cell-arm-{letter}-policy.json", f"cell-arm-{letter}.json"):
        cand = prep / name
        doc = load_json_value(cand, None) if cand.is_file() else None
        if isinstance(doc, dict) and doc.get("arm_id") == arm:
            return cand
    return None


def _assess_incident_holds(prep: Path, inc_holds: dict) -> tuple[list[dict], str | None]:
    """Judge every active Fleet/local incident hold through core_common's machine_clearable contract (fail closed)."""
    if not inc_holds:
        return [], None
    _ensure_foundation_path()
    try:
        from core_common.protocol.arm_incident.arm_incidents import machine_clearable, remeasure_kind
    except ImportError as exc:
        return [], f"Fleet 사고 판정 규칙(core_common)을 불러올 수 없습니다: {exc}"
    import omx_incident_auto

    token = omx_incident_auto.assessor_token_file()
    plans = []
    for arm, info in inc_holds.items():
        if arm not in ARMS:
            return [], f"{arm}: 알 수 없는 팔의 Fleet 보류는 자동 복구할 수 없습니다"
        if isinstance(info, dict) and (info.get("outbox") or 0) > 0:
            return [], f"{arm}: 미전송 사고 리포트({info['outbox']}건)가 남아 있어 먼저 전송/확인이 필요합니다"
        inc = _latest_local_incident(prep, arm)
        facts = inc.get("facts") if isinstance(inc, dict) else None
        if not isinstance(facts, dict):
            return [], f"{arm}: 로컬 사고 기록(incident.json)이 없어 자동 복구할 수 없습니다"
        ok_direct, why = machine_clearable(facts)
        rk = remeasure_kind(facts)
        if ok_direct:
            mode, cfg = "direct", None
        elif rk is not None and why == f"{rk}: no valid remeasure":
            mode, cfg = "reassess", _incident_reassess_config(prep, arm)
            if cfg is None:
                return [], f"{arm}: D-1040 재측정용 셀 설정(cell-arm-{ARMS[arm]}-*.json)이 없습니다"
        else:
            return [], f"{arm} Fleet 사고 보류 자동 해제 불가 ({why}) — 사람이 팔 상태를 확인하세요"
        if token is None:
            return [], f"{arm}: AI Assessor 토큰(*-ai-assessor.token)이 없어 자동 해제할 수 없습니다"
        plans.append({"arm": arm, "mode": mode, "why": why, "token": token, "config": cfg})
    return plans, None


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
        st.get("arm") if st.get("arm") in ARMS else (
            dead_leases[0] if len(dead_leases) == 1 and dead_leases[0] in ARMS else (
                next(iter(inc_holds)) if len(inc_holds) == 1 and next(iter(inc_holds)) in ARMS else None
            )
        )
    )
    if st.get("status") in ("handing_over", "recording", "restoring", "sealing"):
        return {"eligible": False, "reason": "세션 진행 중에는 자동 복구할 수 없습니다", "steps": [], "arm": target_arm}
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
    inc_plans, inc_why = _assess_incident_holds(bench.prep, inc_holds)
    if inc_why:
        return {"eligible": False, "reason": inc_why, "steps": [], "arm": target_arm}
    if not mh and (dead_leases or inc_plans):
        if recorder_running(bench.procs):
            return {"eligible": False, "reason": "녹화/러너 프로세스가 실행 중입니다", "steps": [], "arm": target_arm}
    if not mh and dead_leases:
        steps.append("clear_dead_lease")
    if pending:
        steps.append("restore_units")
    if inc_plans:
        steps.append("clear_fleet_incident")
    if baseline_needed and target_arm in ARMS:
        steps.append("restore_baseline")
    if can_ack:
        steps.append("ack_error")
    if not steps:
        return {"eligible": False, "reason": "자동 복구 대상이 없습니다", "steps": [], "arm": target_arm}
    return {"eligible": True, "reason": "안전 확인됨 — 접힌 홈 HOLD·보류·유닛·기준 캡·Fleet 보류 자동 복구 가능", "steps": steps, "arm": target_arm}


class BenchAutoRecoverMixin:
    def _run_incident_clear(self, cmd, *, cwd, env, timeout=60):
        return subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)

    def _clear_incident_holds(self, inc_holds: dict, steps: list[str]) -> None:
        inc_plans, inc_why = _assess_incident_holds(self.prep, inc_holds)
        if inc_why:
            raise ValueError(inc_why)
        import omx_incident

        env = dict(os.environ)
        found = HERE.parents[3] / "contracts" / "foundation"
        if found.is_dir():
            pp = env.get("PYTHONPATH", "")
            if str(found) not in pp.split(os.pathsep):
                env["PYTHONPATH"] = f"{found}{os.pathsep}{pp}" if pp else str(found)
        py = getattr(self, "python", sys.executable) or sys.executable
        for plan in inc_plans:
            inc_arm = plan["arm"]
            if omx_incident.sync_hold_from_fleet(inc_arm) or not omx_incident.held(inc_arm):
                steps.append(f"incident_synced:{inc_arm}")
                continue
            if plan["mode"] == "direct":
                try:
                    omx_incident.clear(inc_arm, f"bench auto_recover: {plan['why']}", plan["token"],
                                       cause="software_or_config", basis="measured")
                except (SystemExit, Exception) as exc:
                    raise ValueError(f"{inc_arm} Fleet 자동 해제 거절: {str(exc)[:220]}") from exc
            else:
                cmd = [py, str(HERE / "omx_incident.py"), "clear", "--arm", inc_arm, "--reassess",
                       "--config", str(plan["config"]), "--token-file", str(plan["token"]),
                       "--cause", "software_or_config", "--basis", "measured",
                       "--note", f"bench auto_recover (D-1040): {plan['why']}"]
                unit = f"rosy-omx-observer@{inc_arm}.service"
                st_obs = self.run("is-active", unit)
                obs_state = (getattr(st_obs, "stdout", "") or "").strip()
                was_active = (getattr(st_obs, "returncode", 1) == 0 and obs_state in ("", "active")) or obs_state in (
                    "activating", "reloading"
                )
                obs_stopped = False
                try:
                    if was_active:
                        stop_res = self.run("stop", unit)
                        if getattr(stop_res, "returncode", 0) != 0:
                            err = (getattr(stop_res, "stderr", "") or getattr(stop_res, "stdout", "")).strip()
                            raise ValueError(f"{inc_arm} 옵저버({unit}) 중지 실패: {err[:160]}")
                        obs_stopped = True
                    try:
                        done = self._run_incident_clear(cmd, cwd=self.prep, env=env)
                    except (subprocess.TimeoutExpired, OSError) as exc:
                        raise ValueError(f"{inc_arm} Fleet D-1040 재측정 실패: {exc}") from exc
                finally:
                    if obs_stopped:
                        restart_err = None
                        try:
                            start_res = self.run("start", unit)
                            if getattr(start_res, "returncode", 0) != 0:
                                restart_err = "시작 실패"
                        except Exception as exc:
                            restart_err = str(exc)
                        if restart_err is not None:
                            if hasattr(self, "_remember"):
                                cur_p = load_json_value(self.pending, []) if hasattr(self, "pending") and self.pending.is_file() else []
                                self._remember(list(dict.fromkeys([*(u for u in (cur_p if isinstance(cur_p, list) else []) if isinstance(u, str)), unit])))
                            if hasattr(self, "_log_event"):
                                self._log_event("bench", "warn", f"{unit} 재시작 필요 ({restart_err})")
                if getattr(done, "returncode", 1) != 0:
                    msg = (getattr(done, "stderr", "") or getattr(done, "stdout", "")).strip()
                    raise ValueError(f"{inc_arm} Fleet D-1040 자동 복구 거절: {msg[:220]}")
            if omx_incident.held(inc_arm) and not omx_incident.sync_hold_from_fleet(inc_arm):
                raise ValueError(f"{inc_arm} Fleet 사고 보류가 해제되지 않았습니다")
            steps.append(f"incident_cleared:{inc_arm}")

    def _try_return_home(self, arm: str, *, include_leader: bool = True) -> dict:
        if arm not in ARMS or self.manual.exists() or self.pending.exists():
            return {"ok": False, "home_failed": True, "home_error": "보류·유닛 미복원 상태라 홈 복귀를 건너뜁니다",
                    "next_action": "먼저 수동 확인 보류 및 중지 유닛을 정리하세요", "status": self.status()}
        try:
            st = self.go_home({"arm": arm, "include_leader": include_leader, "fold_unfolded": True})
            return {"ok": True, "home_moved": st.get("home_moved") or [arm], "status": st}
        except ValueError as exc:
            cur = self.status()
            err = str(exc)
            if hasattr(self, "_log_event"):
                self._log_event("pose", "warn", f"{arm} 복구 후 홈 복귀 실패: {err}")
            return {"ok": False, "home_failed": True, "home_error": err,
                    "next_action": _home_failure_guidance(arm, err), "status": cur}

    def _return_home_after_clear(self, target_arm: str, *, include_leader: bool = True) -> dict:
        import omx_incident

        held_why = omx_incident.held(target_arm)
        if held_why:
            try:
                self._clear_incident_holds({target_arm: {"reason": held_why, "outbox": len(omx_incident.outbox(target_arm) or [])}}, [])
            except ValueError as exc:
                return {**self.status(), "recovered": True, "home_failed": True,
                        "home_error": str(exc), "next_action": _home_failure_guidance(target_arm, str(exc))}
        hr = self._try_return_home(target_arm, include_leader=include_leader)
        if hr["ok"]:
            return {**hr["status"], "recovered": True, "returned_home": True, "home_moved": hr["home_moved"]}
        return {**hr["status"], "recovered": True, "home_failed": True,
                "home_error": hr["home_error"], "next_action": hr["next_action"]}

    def auto_recover(self, body=None):
        """Safely chain folded-at-home HOLD release -> hold/lease/incident clear -> unit restore -> baseline -> optional home."""
        st = self.status()
        rec = st.get("recovery") if isinstance(st.get("recovery"), dict) else {}
        ar = rec.get("auto_recover") if isinstance(rec.get("auto_recover"), dict) else {}
        mh = st.get("manual_hold") if isinstance(st.get("manual_hold"), dict) and st["manual_hold"].get("active") else None
        if not ar.get("eligible"):
            raise ValueError(ar.get("reason") or "안전 자동 복구 조건을 만족하지 않습니다 — 수동 확인이 필요합니다")
        target_arm = (body or {}).get("arm") if isinstance(body, dict) and (body or {}).get("arm") in ARMS else ar.get("arm")
        return_home = isinstance(body, dict) and body.get("return_home") is True
        include_leader = not (isinstance(body, dict) and body.get("include_leader") is False)
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
        inc_holds = rec.get("incident_holds") if isinstance(rec.get("incident_holds"), dict) else {}
        if inc_holds and not self.manual.exists():
            self._clear_incident_holds(inc_holds, steps)
        if rec.get("baseline_needed") and target_arm in ARMS and not self.manual.exists():
            self.recover_baseline({"arm": target_arm})
            steps.append("baseline_restored")
        cur = self.status()
        cur_rec = cur.get("recovery") if isinstance(cur.get("recovery"), dict) else {}
        if cur_rec.get("can_ack_error"):
            self.ack_bench_error()
            steps.append("error_acked")
            cur = self.status()
        if return_home and target_arm in ARMS:
            hr = self._try_return_home(target_arm, include_leader=include_leader)
            if hr["ok"]:
                steps.append("returned_home")
                cur = hr["status"]
                if hasattr(self, "_log_event"):
                    self._log_event("bench", "good", f"안전 자동 복구 완료 ({' → '.join(steps)})")
                return {"ok": True, "steps": steps, "arm": target_arm, "returned_home": True,
                        "home_moved": hr["home_moved"], "status": cur}
            return {"ok": False, "recovered": True, "home_failed": True, "steps": steps, "arm": target_arm,
                    "home_error": hr["home_error"], "next_action": hr["next_action"], "status": hr["status"]}
        if hasattr(self, "_log_event"):
            self._log_event("bench", "good", f"안전 자동 복구 완료 ({' → '.join(steps) or '확인'})")
        return {"ok": True, "steps": steps, "arm": target_arm, "status": cur}
