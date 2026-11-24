#!/usr/bin/env python3
"""Guided problem diagnosis and recovery center for stopped units, held runners, leases, baseline caps, and incidents."""
from __future__ import annotations

import json, os, re, signal, subprocess, time
from pathlib import Path

from bench_record_guard import arm_free, hold_arm_lock, recorder_running, release, resolve_record_config
from bench_record_handoff import load_json_value
from bench_record_inspect import ARMS, HERE


def _pid_is_chunk_runner(pid: int | None) -> bool:
    if not pid or pid <= 1:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    proc_cmd = Path(f"/proc/{pid}/cmdline")
    if proc_cmd.is_file():
        try:
            cmd = proc_cmd.read_bytes().replace(b"\0", b" ").decode(errors="replace")
            return "chunk_runner" in cmd
        except OSError:
            return False
    return True


def _pid_alive(pid: int | None) -> bool:
    if not pid or isinstance(pid, bool) or not isinstance(pid, int) or pid <= 1:
        return False
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except OSError:
        return False


def _proof_valid(proof_path: Path, pid, held_at) -> bool:
    ev = load_json_value(proof_path, {})
    if not isinstance(ev, dict) or ev.get("pid") != pid or ev.get("torque_off_confirmed") is not True:
        return False
    return float(ev.get("t") or 0) >= float(held_at or 0)


def _dead_held_leases(prep: Path) -> list[str]:
    import cell_arm_lease
    out = []
    for a, letter in ARMS.items():
        try:
            rec = cell_arm_lease.status(a).get(a)
        except Exception:
            rec = None
        if not rec or not rec.get("hold"):
            continue
        pid = rec.get("pid")
        if pid and _pid_alive(pid):
            continue
        if not _proof_valid(prep / f"chunk-io-{letter}" / "released.json", pid, rec.get("held_at")):
            out.append(a)
    return out


def build_home_hold_record(arm: str, rc, rec_log_p: Path, io_dir: Path, person_needed=None) -> tuple[str, dict]:
    lines = []
    try:
        lines = [l for l in Path(rec_log_p).read_text(encoding="utf-8", errors="replace").splitlines()
                 if l.strip() and not l.startswith("motor-health follower:")]
    except OSError:
        pass
    hold_doc = load_json_value(io_dir / "hold.json", {})
    if not isinstance(hold_doc, dict):
        hold_doc = {}
    pid, hold_err, worker_hint = hold_doc.get("pid"), str(hold_doc.get("error") or ""), False
    for line in reversed(lines[-60:]):
        if not line.lstrip().startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if ev.get("command") == "human-hold":
            worker_hint = True
        if ev.get("step") == "RUNNER_HELD" and isinstance(ev.get("report"), dict):
            pid = pid or ev["report"].get("pid")
            hold_err = hold_err or str(ev["report"].get("error") or "")
        elif ev.get("hold") and ev.get("error") and not hold_err:
            hold_err = str(ev["error"])
    detail = hold_err or (lines[-1][:180] if lines else (f"exit={rc}" if rc is not None else "no exit"))
    if worker_hint and "human-hold" not in detail:
        detail = f"{detail} (human-hold 수신)"
    if person_needed:
        msg = str(person_needed)
    elif rc == 75 or hold_doc or any("RUNNER_HELD" in l for l in lines[-30:]):
        msg = f"{arm} 홈용 record_session이 HOLD(토크 유지{f', PID {pid}' if pid else ''}) 상태로 보류되었습니다 ({detail}) — 사람이 팔 상태를 확인하세요 (유닛 복원·idle 보류)"
    else:
        msg = f"{arm} 홈용 record_session이 정상 종료되지 않았습니다 ({detail}) — 사람이 팔 상태를 확인하세요 (유닛 복원·idle 보류)"
    meta = {"arm": arm, "kind": "home_hold", "exit_code": rc, "runner_pid": pid if isinstance(pid, int) else None,
            "detail": detail[:240], "log_file": rec_log_p.name, "worker_human_hold": worker_hint,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    return msg, meta


def _live_held_arm(prep: Path) -> str | None:
    import cell_arm_lease
    for candidate, letter in ARMS.items():
        io_dir = prep / f"chunk-io-{letter}"
        hold_doc = load_json_value(io_dir / "hold.json", {})
        live_doc = load_json_value(io_dir / "live.json", {})
        try:
            lease = cell_arm_lease.status(candidate).get(candidate)
        except Exception:
            lease = None
        pid = ((hold_doc.get("pid") if isinstance(hold_doc, dict) else None)
               or (live_doc.get("pid") if isinstance(live_doc, dict) else None)
               or (lease.get("pid") if isinstance(lease, dict) else None))
        if not (isinstance(pid, int) and not isinstance(pid, bool) and _pid_is_chunk_runner(pid)):
            continue
        if ((isinstance(hold_doc, dict) and hold_doc.get("hold"))
                or (isinstance(live_doc, dict) and (live_doc.get("human_hold_latched") or live_doc.get("torque_hold_commanded")))
                or (isinstance(lease, dict) and lease.get("hold"))):
            return candidate
    return None


def diagnose_manual_hold(bench) -> dict:
    doc = load_json_value(bench.manual, {}) if bench.manual.exists() else {}
    if not isinstance(doc, dict):
        doc = {}
    with bench.lock:
        st = dict(bench.state)
    live_arm = _live_held_arm(bench.prep)
    active = (bench.manual.exists() or st.get("status") == "leader_manual_check"
              or (st.get("status") == "homing" and bool(st.get("error"))) or bool(live_arm))
    if not active:
        return {"active": False}
    name_arm = str(st.get("name") or "").removeprefix("home-") if str(st.get("name") or "").startswith("home-") else None
    msg_match = re.search(r"\b(arm_[abs])\b", f"{doc.get('reason') or ''} {st.get('error') or ''}")
    arm = next((cand for cand in (
        doc.get("arm"), live_arm, st.get("step_arm"), name_arm,
        msg_match.group(1) if msg_match else None,
        "arm_a" if st.get("name") == "home-arm_ab" else None,
    ) if cand in ARMS), None)
    letter = ARMS.get(arm)
    io_dir = (bench.prep / f"chunk-io-{letter}") if letter else None
    live_doc = load_json_value(io_dir / "live.json", {}) if io_dir else {}
    hold_doc = load_json_value(io_dir / "hold.json", {}) if io_dir else {}
    import cell_arm_lease
    lease = cell_arm_lease.status(arm).get(arm) if arm else None
    pid = (doc.get("runner_pid") or (hold_doc.get("pid") if isinstance(hold_doc, dict) else None)
           or (live_doc.get("pid") if isinstance(live_doc, dict) else None)
           or (lease.get("pid") if isinstance(lease, dict) else None))
    alive = _pid_is_chunk_runner(pid) if isinstance(pid, int) and not isinstance(pid, bool) else False
    log_name = doc.get("log_file") or (f"home-{arm}.log" if arm else "")
    tail, worker_hint = [], bool(doc.get("worker_human_hold"))
    if log_name and (bench.prep / ".bench-runs" / log_name).is_file():
        try:
            raw = [l for l in (bench.prep / ".bench-runs" / log_name).read_text(encoding="utf-8", errors="replace").splitlines()
                   if l.strip() and not l.startswith("motor-health follower:")]
            tail = raw[-10:]
            worker_hint = worker_hint or any('"command": "human-hold"' in l for l in raw[-60:])
        except OSError:
            pass
    pending = load_json_value(bench.pending, []) if bench.pending.is_file() else []
    pose = live_doc.get("state") if isinstance(live_doc, dict) and isinstance(live_doc.get("state"), list) else None
    dead_leases = _dead_held_leases(bench.prep)
    return {
        "active": True, "arm": arm, "reason": str(doc.get("reason") or st.get("error") or "수동 확인 필요"),
        "detail": str(doc.get("detail") or (hold_doc.get("error") if isinstance(hold_doc, dict) else "") or ""),
        "runner_pid": pid if isinstance(pid, int) else None, "runner_alive": alive,
        "live_pose": [round(float(x), 2) for x in pose[:6]] if pose else None,
        "human_hold_latched": bool(isinstance(live_doc, dict) and live_doc.get("human_hold_latched")),
        "torque_hold_commanded": bool(isinstance(live_doc, dict) and live_doc.get("torque_hold_commanded")),
        "lease_hold": bool(isinstance(lease, dict) and lease.get("hold")), "dead_lease_arms": dead_leases,
        "worker_human_hold": worker_hint, "pending_units": pending if isinstance(pending, list) else [],
        "log_file": log_name, "log_tail": tail, "can_release_runner": bool(alive and arm and pid),
        "can_clear": bool(not alive and not recorder_running(bench.procs)),
    }


class BenchRecoverMixin:
    def _record_home_hold(self, arm, rec_proc, rec_log_p, io_dir):
        rc = getattr(rec_proc, "returncode", None) if rec_proc is not None else None
        msg, meta = build_home_hold_record(arm, rc, Path(rec_log_p), Path(io_dir), getattr(self, "_person_needed", None))
        self._mark_manual(msg, **meta)
        if hasattr(self, "_log_event"):
            self._log_event("pose", "crit", msg)
        return msg

    def manual_hold_info(self):
        return diagnose_manual_hold(self)

    def diagnose_bench_recovery(self, st: dict) -> dict:
        import omx_incident
        mh = st.get("manual_hold") if isinstance(st.get("manual_hold"), dict) and st["manual_hold"].get("active") else None
        pending = load_json_value(self.pending, []) if self.pending.is_file() else []
        if not isinstance(pending, list):
            pending = []
        locks = st.get("active_locks") if isinstance(st.get("active_locks"), list) else []
        dead_leases = (mh.get("dead_lease_arms") if mh else None) or _dead_held_leases(self.prep)
        blob = " ".join([str(st.get("error") or ""), str(st.get("log_tail") or ""), str((mh or {}).get("detail") or "")])
        baseline_needed = ("are not the baseline" in blob or "commissioning_limits" in blob
                           or bool(mh and (mh.get("lease_hold") or "caps" in str(mh.get("detail") or ""))))
        inc_holds = {}
        for a in ARMS:
            try:
                why, ob = omx_incident.held(a), omx_incident.outbox(a)
                if why or ob:
                    inc_holds[a] = {"reason": str(why or "미전송 사고 리포트 대기"), "outbox": len(ob or [])}
            except Exception:
                continue
        code = st.get("status")
        ah = st.get("auto_home") if isinstance(st.get("auto_home"), dict) else {}
        ended_err = code in ("failed", "unsafe_or_failed", "seal_failed") or (code in ("stopped_safe", "stopped_not_sealed") and bool(st.get("error"))) or (ah.get("ok") is False and not ah.get("cancelled"))
        issues = []
        if mh:
            issues.append({"kind": "runner_hold" if mh.get("runner_alive") else "manual_hold", "arm": mh.get("arm"), "label": "토크 ON 러너 정지 필요" if mh.get("runner_alive") else "수동 확인 보류 해제 대기", "detail": mh.get("reason") or ""})
        if locks and code not in ("handing_over", "recording", "restoring", "sealing"):
            issues.append({"kind": "active_locks", "label": f"다른 OMX 세션 락 점유 ({len(locks)}건)", "detail": ", ".join(str(x.get("lock")) for x in locks[:4])})
        if pending:
            issues.append({"kind": "pending_units", "label": f"중지된 유닛 복원 대기 ({len(pending)}개)", "detail": ", ".join(str(u) for u in pending[:4])})
        if baseline_needed:
            issues.append({"kind": "baseline_caps", "arm": (mh or {}).get("arm") or st.get("arm"), "label": "세션 캡 기준값(baseline) 복원 필요", "detail": "torque OFF 상태에서 commissioning_limits --baseline 실행"})
        for a, info in inc_holds.items():
            issues.append({"kind": "incident_hold", "arm": a, "label": f"{a} 사고/Fleet 보류", "detail": info["reason"]})
        if ended_err:
            issues.append({"kind": "ended_error", "arm": st.get("arm"), "label": "이전 세션 오류/중단 상태", "detail": str(st.get("error") or (st.get("auto_home") or {}).get("error") or code)})
        can_ack = bool(ended_err and not self.manual.exists() and not self.pending.exists() and not locks)
        has_any = bool(issues or dead_leases)
        from bench_record_auto_recover import assess_auto_recover
        auto_rec = assess_auto_recover(self, st, mh, pending, locks, dead_leases, inc_holds, baseline_needed, can_ack)
        return {"has_issues": has_any, "issues": issues, "pending_units": pending, "dead_lease_arms": dead_leases,
                "incident_holds": inc_holds, "fleet_clear_available": bool(self._config.get("fleet_console_origin")),
                "baseline_needed": baseline_needed, "can_ack_error": can_ack,
                "can_restore_units": bool(pending and not self.manual.exists()), "auto_recover": auto_rec}

    def release_held_runner(self, body):
        """Send SIGUSR2 to a verified chunk_runner PID after operator confirms physical arm support."""
        if not isinstance(body, dict) or body.get("arm_supported_confirmed") is not True:
            raise ValueError("먼저 사람이 물리적으로 팔을 받쳤는지 확인 체크하세요 (arm_supported_confirmed=true)")
        import cell_arm_lease
        info = self.manual_hold_info()
        arm = body.get("arm") or info.get("arm")
        if arm not in ARMS:
            raise ValueError("해제할 팔(arm_a, arm_b, arm_s)을 확인할 수 없습니다")
        pid = body.get("pid") if body.get("pid") is not None else info.get("runner_pid")
        if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 1:
            raise ValueError("유효한 러너 PID가 없습니다")
        if not _pid_is_chunk_runner(pid):
            raise ValueError(f"PID {pid}가 실행 중인 chunk_runner가 아닙니다 — release_lease/보류 해제를 진행하세요")
        os.kill(pid, signal.SIGUSR2)
        deadline = self.clock() + 6.0
        while self.clock() < deadline and _pid_is_chunk_runner(pid):
            time.sleep(0.2)
        proof = self.prep / f"chunk-io-{ARMS[arm]}" / "released.json"
        ev = load_json_value(proof, {})
        torque_ok = isinstance(ev, dict) and ev.get("pid") == pid and ev.get("torque_off_confirmed") is True
        record = cell_arm_lease.status(arm).get(arm)
        if not _pid_is_chunk_runner(pid) and record and record.get("hold") and torque_ok and cell_arm_lease.release_exact(arm, record):
            proof.unlink(missing_ok=True)
        if hasattr(self, "_log_event"):
            self._log_event("pose", "warn", f"{arm} HOLD 러너(PID {pid}) SIGUSR2 해제 요청 (torque_off={torque_ok})")
        return {"ok": True, "arm": arm, "released_pid": pid, "torque_off_confirmed": torque_ok, "status": self.status()}

    def clear_manual_hold(self, body):
        """Clear .bench-manual-check.json after runner exited safely, restore pending units, and return to idle."""
        if not isinstance(body, dict) or body.get("confirmed") is not True:
            raise ValueError("수동 확인 완료 체크(confirmed=true)가 필요합니다")
        if recorder_running(self.procs):
            raise ValueError("record_session 또는 chunk_runner가 아직 실행 중입니다 — 먼저 팔을 받치고 SIGUSR2 해제 후 다시 시도하세요")
        import cell_arm_lease
        force_dead = body.get("force_dead_lease") is True
        for a, letter in ARMS.items():
            rec = cell_arm_lease.status(a).get(a)
            if not rec or not rec.get("hold"):
                continue
            pid = rec.get("pid")
            if pid and _pid_alive(pid):
                raise ValueError(f"{a} 임대 hold의 러너(PID {pid})가 아직 살아 있습니다 — 먼저 토크 해제를 완료하세요")
            proof = self.prep / f"chunk-io-{letter}" / "released.json"
            if _proof_valid(proof, pid, rec.get("held_at")):
                cell_arm_lease.release_exact(a, rec)
                proof.unlink(missing_ok=True)
            elif force_dead:
                cell_arm_lease.release_exact(a, rec)
            else:
                raise ValueError(f"{a}에 죽은 러너(PID {pid})의 해제되지 않은 임대 hold가 있습니다 — 팔 접힘/토크 OFF 확인 체크 또는 cell_arm_lease.py release-hold 후 진행하세요")
        self.manual.unlink(missing_ok=True)
        self.leader_hold = ""
        self.restore_leftovers()
        with self.lock:
            if self.state.get("status") in ("homing", "leader_manual_check") and (self.state.get("error") or self.state.get("status") == "leader_manual_check"):
                self.state = {"status": "idle"}
            self.last_issue = {"kind": "recovered", "message": "수동 확인 보류 해제 및 대기 복귀", "arm": None}
        if hasattr(self, "_log_event"):
            self._log_event("bench", "good", "수동 확인 보류 해제 · 유닛 복원 및 대기 복귀 완료")
        return self.status()

    def recover_baseline(self, body):
        """Run commissioning_limits.py --baseline (torque OFF, never moves arm) under arm lock and verify clean readback."""
        arm = (body or {}).get("arm") if isinstance(body, dict) else None
        if arm not in ARMS:
            raise ValueError("단일 팔(arm_a, arm_b, arm_s)을 선택하세요")
        if self.manual.exists():
            raise ValueError("먼저 수동 확인 보류를 해제한 뒤 기준 캡 복원을 실행하세요")
        with self.lock:
            st_code = self.state.get("status")
            if st_code in ("handing_over", "recording", "restoring", "sealing", "leader_manual_check") or (st_code == "homing" and not self.state.get("error")):
                raise ValueError(f"작업대 상태({st_code}) 때문에 지금은 기준 캡을 복원할 수 없습니다")
        if recorder_running(self.procs):
            raise ValueError("녹화기/chunk_runner가 실행 중이라 기준 캡을 복원할 수 없습니다")
        refusal = arm_free(arm, self.manual)
        if refusal:
            raise ValueError(refusal)
        rcfg = resolve_record_config(self.prep, arm)
        if not rcfg.is_file():
            raise ValueError(f"{arm} 설정 파일({rcfg.name})이 없습니다")
        port = (json.loads(rcfg.read_text(encoding="utf-8-sig")).get("robot") or {}).get("port")
        if port and str(port).startswith("/dev/serial/by-id/") and not Path(port).exists():
            raise ValueError(f"{arm} 팔로워 보드가 연결되어 있지 않습니다 ({Path(port).name})")
        lock, err = hold_arm_lock(arm)
        if lock is None:
            raise ValueError(err or f"{arm} 세션 락을 잡을 수 없습니다")
        out = self.prep / ".bench-runs" / f"baseline-{arm}-{time.time_ns()}"
        out.parent.mkdir(parents=True, exist_ok=True)
        self._mark_manual(f"{arm} 기준 캡 복원 진행 중 — 중단 시 사람이 캡을 확인하세요", arm=arm, kind="baseline_restore")
        verified, detail = False, ""
        try:
            done = subprocess.run(
                [self.python, str(HERE / "commissioning_limits.py"), "--device", str(port), "--baseline", "--output", str(out)],
                cwd=self.prep, capture_output=True, text=True, timeout=120)
            rep = json.loads((done.stdout or "").strip().splitlines()[-1])
            verified = done.returncode == 0 and rep.get("configuration_verified") is True and rep.get("error") is None
            detail = str(rep.get("error") or "")
        except Exception as exc:
            detail = str(exc)
        finally:
            release([lock])
        if verified:
            self.manual.unlink(missing_ok=True)
            with self.lock:
                if self.state.get("status") in ("homing", "failed", "unsafe_or_failed", "seal_failed"):
                    self.state = {"status": "idle"}
                self.last_issue = {"kind": "recovered", "message": f"{arm} 기준 캡 복원 완료", "arm": arm}
            if hasattr(self, "_log_event"):
                self._log_event("pose", "good", f"{arm} commissioning_limits --baseline 복원 검증 완료")
            return {"ok": True, "arm": arm, "status": self.status()}
        self._mark_manual(f"{arm} 기준 캡 복원 실패 ({detail or '검증 미완료'}) — 보고서: {out}", arm=arm, kind="baseline_restore")
        raise ValueError(f"{arm} 기준 캡 복원에 실패했습니다 ({detail or out})")

    def recover_restore_units(self, body=None):
        if self.manual.exists():
            raise ValueError("수동 확인 보류 중에는 유닛을 복원할 수 없습니다 — 먼저 보류를 해제하세요")
        if recorder_running(self.procs):
            raise ValueError("녹화기/chunk_runner가 실행 중이라 유닛을 복원할 수 없습니다")
        self.restore_leftovers()
        if self.pending.exists():
            raise ValueError(f"유닛 복원이 완료되지 않았습니다 ({self.state.get('error') or self.pending.name})")
        if hasattr(self, "_log_event"):
            self._log_event("bench", "good", "중지된 카메라·옵저버 유닛 복원 완료")
        return self.status()

    def ack_bench_error(self, body=None):
        if self.manual.exists() or self.pending.exists():
            raise ValueError("수동 확인 보류 또는 미복원 유닛이 남아 있어 먼저 해제/복원이 필요합니다")
        with self.lock:
            st_code = self.state.get("status")
            if st_code in ("handing_over", "recording", "restoring", "sealing") or (st_code == "homing" and not self.state.get("error")):
                raise ValueError(f"진행 중인 작업({st_code})은 오류 해제로 초기화할 수 없습니다")
            self.state = {"status": "idle"}
            self.last_issue = None
        if hasattr(self, "_log_event"):
            self._log_event("bench", "info", "이전 세션 오류·중단 표시 확인 후 대기 상태로 복귀")
        return self.status()

    def recover_sync_incident(self, body):
        arm = (body or {}).get("arm") if isinstance(body, dict) else None
        if arm not in ARMS:
            raise ValueError("동기화할 팔(arm_a, arm_b, arm_s)을 선택하세요")
        import omx_incident
        cleared = bool(omx_incident.sync_hold_from_fleet(arm))
        if hasattr(self, "_log_event"):
            self._log_event("bench", "good" if cleared else "warn", f"{arm} Fleet 사고 보류 동기화 ({'해제됨' if cleared else '유지/미연결'})")
        return {"ok": True, "arm": arm, "cleared": cleared, "status": self.status()}
