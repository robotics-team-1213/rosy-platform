#!/usr/bin/env python3
"""Stopped-unit restore list and the persistent "a person must check the arm" marker for bench_record.py."""
from __future__ import annotations

import json
from pathlib import Path
import signal
import subprocess
import threading
import time

from bench_record_guard import arm_free, check_proc_visible, hold_arm_lock, recorder_running, write_restore_list
from teleop_speed import read_stage, summary as speed_summary


BASELINE_REFUSAL = "are not the baseline"  # record_session.check_idle: raised caps an earlier session left; refused before any cap write or torque


_TLS = threading.local()  # this thread's own: the claim its go_home took, the claim its session published, the auto home it is running


class BenchManualMixin:
    def speed_fields(self):
        """W14: the declared teleop speed stage per arm (what the next full-arm Leader session uses); a running session's own is state["teleop_speed"]."""
        return {"teleop_speed_declared": {a: speed_summary(read_stage(self.prep / f"teleop-speed-{a}.json")) for a in ("arm_a", "arm_b", "arm_s")}}

    def _claim_bench(self):
        """Call under self.lock whenever a request takes the bench (start, alignment, home): a per-request number, not a status value."""
        self._claims = getattr(self, "_claims", 0) + 1
        _TLS.home_claim = self._claims
        return self._claims

    def _session_claim(self):
        return self.state.get("claim", getattr(self, "_claims", 0))

    def _publish_end(self, verdict=None, **fields):
        """The session's ended state and ITS OWN pending auto-home record in ONE lock acquisition. Ownership, not a shared "current claim": every
        ended session creates {cancelled, reserved} under its claim in self._auto_homes; the auto home, its finally, stop() and the reservation
        address the record by that claim, and a finally removes only its own. A /stop accepted while this session's recording child had ended but
        the state was not published yet (self._pre_cancel holds the session's claim) starts the record cancelled."""
        with self.lock:
            self.state.update({**(verdict(self.state) if verdict else {}), **fields})  # the verdict is read from the state under the same lock
            claim = self._session_claim()
            cancelled = claim in self._pre_cancel
            self._pre_cancel.discard(claim)
            if self.state.get("status") in ("sealed", "stopped_safe"):
                reason = self._guard_end_reason()
                if reason:  # THE rule: any guard event ends the session without the automatic home (fail-closed pause end, guard fault, exception)
                    _TLS.published_claim = None
                    self.state["auto_home"] = {"ok": False, "skipped": True, "reason": reason, "message": f"skipped: {reason}"}
                    return self.state.get("status")
                self._auto_homes[claim] = {"cancelled": cancelled, "reserved": False}
                _TLS.published_claim = claim  # read by this thread's own _auto_home_after_session
                if cancelled:
                    self.state["auto_home"] = dict(self._CANCELLED)
            return self.state.get("status")

    _CANCELLED = {"ok": False, "cancelled": True, "message": "자동 홈 취소됨"}

    def _guard_end_reason(self):
        """Fail closed: skip auto-home unless guard-end.json is absent AND clean-end.json confirms a clean end."""
        try:
            folder = Path(self.state["folder"])
        except (KeyError, TypeError):
            return ""
        guard = folder / "guard-end.json"
        if guard.exists():
            try:
                return str(json.loads(guard.read_text(encoding="utf-8")).get("reason") or "guard event")
            except (OSError, ValueError, AttributeError):
                return "guard event (end evidence unreadable)"  # fail closed
        clean = folder / "clean-end.json"
        if not clean.exists():
            return "clean-end marker missing"
        try:
            if json.loads(clean.read_text(encoding="utf-8")).get("clean") is not True:
                return "clean-end marker invalid"
        except (OSError, ValueError, AttributeError):
            return "clean-end marker unreadable"
        return ""

    def _stop_plan(self):
        """Call under self.lock: decide, from the state as it is now, what a stop does and RECORD its intent right here (the abort, or the cancel of
        the coming auto home), whatever a child's signal later turns out to reach.
        ("snap", snapshot, home child) | ("child", the recording child, None) | ("none", None, None)."""
        status = self.state["status"]
        pending = [r for r in self._auto_homes.values() if not r["reserved"]]
        for record in pending:
            record["cancelled"] = True  # EVERY auto home that has not reserved yet, whichever session it belongs to; one that reserved is aborted below
        if status in ("handing_over", "homing"):
            self.abort = True  # homing: _run_leader_home sees it, ends its child and start() records nothing
            return "snap", dict(self.state), getattr(self, "_home_child", None) if status == "homing" else None
        if status in ("restoring", "sealing"):
            self._pre_cancel.add(self._session_claim())  # this session's coming auto home: its record is created cancelled
            return "snap", {**self.state, "auto_home": dict(self._CANCELLED)}, None
        if status in ("sealed", "stopped_safe") and pending:
            self.state["auto_home"] = dict(self._CANCELLED)
            return "snap", dict(self.state), None
        if status == "recording" and self.child is not None:
            self._pre_cancel.add(self._session_claim())  # accepted stop = no auto home, even if the child exits normally before the signal lands
            return "child", self.child, None
        if pending:
            return "snap", {**self.state, "auto_home": dict(self._CANCELLED)}, None
        return "none", None, None

    def stop(self):
        """The decision and its record are made under one self.lock acquisition (_stop_plan); the child's poll() and the signal come after
        and only act on it: a child that ended by itself changes nothing about the recorded stop."""
        with self.lock:
            kind, value, home = self._stop_plan()
        if kind == "snap":
            if home is not None and home.poll() is None:
                home.send_signal(signal.SIGTERM)  # the runner's own safe end (park/fold, torque OFF only folded and still, else HOLD)
            return value
        if kind == "none":  # nothing running and nothing pending: a plain 200, not an error the person must close
            return {**self.status(), "stop_result": {"stopped": False, "message": "정지할 것이 없습니다 — 대기 중입니다"}}
        if value.poll() is None:
            value.send_signal(signal.SIGTERM)  # record_session maps it to the same clean ending, and it is not ignored under nohup
            return self.status()
        with self.lock:  # it ended by itself first: the stop is still recorded, the answer says so
            return {**self.state, "auto_home": dict(self._CANCELLED)}

    def _reset_home_claim(self):
        _TLS.home_claim = None

    def _auto_claim(self):
        """The claim of the auto home THIS thread is running (None: an ordinary home); read once by the reservation."""
        claim, _TLS.auto_claim = getattr(_TLS, "auto_claim", None), None
        return claim

    def _home_claim(self):
        return getattr(_TLS, "home_claim", None)

    @property
    def manual(self):
        return self.prep / ".bench-manual-check.json"

    def _mark_manual(self, reason, **meta):
        """A recorder or Leader child ended without proof of a safe end: the marker outlives a service restart."""
        self.manual.write_text(json.dumps({"reason": reason, **meta}, ensure_ascii=False), encoding="utf-8")

    def _record_home_hold(self, arm, rec_proc, rec_log_p, io_dir):
        from bench_record_review import build_home_hold_record
        rc = getattr(rec_proc, "returncode", None) if rec_proc is not None else None
        msg, meta = build_home_hold_record(arm, rc, Path(rec_log_p), Path(io_dir), getattr(self, "_person_needed", None))
        self._mark_manual(msg, **meta)
        if hasattr(self, "_log_event"):
            self._log_event("pose", "crit", msg)
        return msg

    def manual_hold_info(self):
        from bench_record_review import diagnose_manual_hold
        return diagnose_manual_hold(self)

    def release_held_runner(self, body):
        """Send SIGUSR2 to a verified chunk_runner PID after operator confirms physical arm support."""
        if not isinstance(body, dict) or body.get("arm_supported_confirmed") is not True:
            raise ValueError("먼저 사람이 물리적으로 팔을 받쳤는지 확인 체크하세요 (arm_supported_confirmed=true)")
        from bench_record_inspect import ARMS
        from bench_record_review import _pid_is_chunk_runner
        from bench_record_handoff import load_json_value
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
        from bench_record_inspect import ARMS
        from bench_record_handoff import load_json_value
        import cell_arm_lease
        for a, letter in ARMS.items():
            rec = cell_arm_lease.status(a).get(a)
            if not rec or not rec.get("hold"):
                continue
            pid = rec.get("pid")
            if pid and cell_arm_lease._pid_alive(pid):
                raise ValueError(f"{a} 임대 hold의 러너(PID {pid})가 아직 살아 있습니다 — 먼저 토크 해제를 완료하세요")
            proof = self.prep / f"chunk-io-{letter}" / "released.json"
            ev = load_json_value(proof, {})
            if isinstance(ev, dict) and ev.get("pid") == pid and ev.get("torque_off_confirmed") is True and float(ev.get("t") or 0) >= float(rec.get("held_at") or 0):
                cell_arm_lease.release_exact(a, rec)
                proof.unlink(missing_ok=True)
            else:
                raise ValueError(f"{a}에 해제되지 않은 임대 hold가 남아 있습니다 — cell_arm_lease.py release-hold 확인 후 진행하세요")
        self.manual.unlink(missing_ok=True)
        self.restore_leftovers()
        with self.lock:
            if self.state.get("status") in ("homing", "leader_manual_check") and (self.state.get("error") or self.state.get("status") == "leader_manual_check"):
                self.state = {"status": "idle"}
            self.last_issue = {"kind": "recovered", "message": "수동 확인 보류 해제 및 대기 복귀", "arm": None}
        if hasattr(self, "_log_event"):
            self._log_event("bench", "good", "수동 확인 보류 해제 · 유닛 복원 및 대기 복귀 완료")
        return self.status()

    def _check_manual(self):
        if self.manual.exists():
            try:
                reason = json.loads(self.manual.read_text(encoding="utf-8")).get("reason", "")
            except (OSError, ValueError, AttributeError):
                reason = ""
            raise ValueError(f"사람 확인이 필요합니다 ({reason}) — 팔 상태를 직접 확인한 뒤 {self.manual} 파일을 삭제하세요")

    def _remember(self, stopped):
        # A bench restart mid-session must still restore what it stopped (see restore_leftovers).
        write_restore_list(self.pending, stopped)

    def _start_units(self, units):
        """Start units in the given order; returns (failed units, first error text)."""
        failed, detail = [], ""
        for unit in units:
            try:
                done = self.run("start", unit)
                if done.returncode != 0:
                    failed.append(unit)
                    detail = detail or f"{unit}: {(done.stderr or '').strip() or 'exit ' + str(done.returncode)}"
            except Exception as exc:
                failed.append(unit)
                detail = detail or f"{unit}: {type(exc).__name__}: {exc}"
        return failed, detail

    def restore_leftovers(self):
        if self.pending.is_file() and self.manual.exists():  # units stay stopped until a person has checked the arm
            return self._set(error="복원 보류: 사람 확인 표식이 있습니다 - 팔 확인 뒤 " + self.manual.name + " 삭제")
        if self.pending.is_file():
            try:
                check_proc_visible(self.mounts)
            except Exception as exc:  # hidepid or unreadable mounts: a recorder could be invisible, so no restore
                return self._set(error=f"복원 보류: {exc}")
            if recorder_running(self.procs):  # a live recorder owns the bus; retried on the next status poll or restart
                return self._set(error="복원 보류: record_session 또는 chunk_runner가 실행 중이거나 확인할 수 없습니다")
            failed, detail = self._start_units(reversed(json.loads(self.pending.read_text())))
            self._remember(failed)  # failed units stay listed for the next recovery
            self._set(restore_errors=failed, **({"error": f"복원 실패: {detail}"} if failed else {}))
            if not failed:  # the deferred restore worked: an earlier "복원 보류/복원 실패" no longer describes the bench
                with self.lock:
                    if str(self.state.get("error", "")).startswith(("복원 보류", "복원 실패")):
                        self.state.pop("error")
                        self.last_issue = {"kind": "recovered", "message": "유닛 복원 완료", "arm": None}

    # --- what a failed home or start left behind, told from evidence -------------------------------------------------------

    @staticmethod
    def _child_text(log_path):
        try:
            return Path(log_path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""

    def _child_reason(self, log_path):
        """": REFUSED: ..." (the child's own refusal line) or the tail of its log, for the error text."""
        lines = [l for l in self._child_text(log_path).splitlines() if l.strip()]
        refused = [l for l in lines if l.startswith("REFUSED:")]
        return f": {(refused or lines[-1:] or [''])[-1][:240]}" if (refused or lines) else ""

    def _never_powered(self, code, log_path):
        """True only on positive evidence that the child ended before its runner started (so no torque was ever on): a
        non-hold exit, no "step": "run" line, no cap written (or a completed restore), and a refusal line or a traceback. An empty or unreadable log proves nothing."""
        text = self._child_text(log_path)
        caps_clean = '"step": "cap' not in text or '"caps_restored": true' in text  # an attempted (cap_attempt) or written cap must have been restored
        return (code not in (None, 0, 75, 76, 77) and '"step": "run"' not in text and caps_clean
                and ("REFUSED:" in text or "Traceback" in text or BASELINE_REFUSAL in text))

    def issue_fields(self, out):
        """status.json error_kind: needs_person (a marker, a Leader hold or a held home) | refused | recovered | None."""
        last = getattr(self, "last_issue", None)
        person = self.manual.exists() or out.get("status") == "leader_manual_check" or (
            out.get("status") == "homing" and bool(out.get("error")))
        return {"error_kind": "needs_person" if person else last and last["kind"], "last_issue": None if person else last}

    def release_lease(self, body):
        """Clear the arm lease a dead runner left held, only with the proof that a person released that runner (SIGUSR2)."""
        from bench_record_inspect import ARMS
        import cell_arm_lease
        arm = body.get("arm") if isinstance(body, dict) else None
        if arm not in ARMS:
            raise ValueError("유효한 팔(arm_a, arm_b, arm_s)을 선택하세요")
        record = cell_arm_lease.status(arm).get(arm)
        if not record or not record.get("hold"):
            raise ValueError(f"{arm}에는 해제할 임대 hold가 없습니다")
        pid = record.get("pid")
        if pid is None or cell_arm_lease._pid_alive(pid):
            raise ValueError(f"{arm} 임대 hold의 러너가 아직 살아 있거나 알 수 없습니다 — 사람이 팔을 받친 뒤 러너에 SIGUSR2를 보내세요")
        from bench_record_handoff import load_json_value
        evidence = load_json_value(self.prep / f"chunk-io-{ARMS[arm]}" / "released.json", {})
        if not isinstance(evidence, dict) or (evidence.get("pid") != pid or evidence.get("torque_off_confirmed") is not True
                or float(evidence.get("t") or 0) < float(record.get("held_at") or 0)):
            raise ValueError(f"{arm} 임대 hold에 운영자 해제(SIGUSR2) 승인 기록이 없습니다 — 팔을 확인한 뒤 cell_arm_lease.py release-hold")
        if not cell_arm_lease.release_exact(arm, record):  # the very lease validated above, under the lease lock
            raise ValueError(f"{arm} 임대 hold를 해제하지 못했습니다")
        proof.unlink(missing_ok=True)
        return self.status()

    def _check_lease(self, arm):
        """D-1035: a held lease, or a live one of another owner, refuses before the bus is touched (record_session would refuse it later,
        after an alignment child or a torque write already ran)."""
        refusal = arm_free(arm, self.manual)
        if refusal:
            raise ValueError(refusal)

    def _baseline_in_place(self, arm, rcfg, code, log_path):
        """The home child was refused for raised caps before any runner, cap write or torque (_never_powered): run
        commissioning_limits.py --baseline (torque OFF; cell_upkeep --fix runs the same) while the bench stays reserved (state homing, the
        arm's session lock held until the retried child is spawned, observers stopped). Never while a recorder runs or the lease is live.
        A tool that ran but did not verify may have written some caps: that needs a person (marker, observers stay stopped)."""
        import cell_arm_lease
        if BASELINE_REFUSAL not in self._child_text(log_path) or not self._never_powered(code, log_path) or self.abort:
            return False
        lease = cell_arm_lease.status(arm).get(arm)
        if recorder_running(self.procs) or (lease and lease.get("live")) or arm_free(arm, self.manual):
            return False
        lock, _ = hold_arm_lock(arm)
        if lock is None:
            return False
        self._arm_lock = lock
        self._set(step="baseline_restore")
        self._mark_manual(f"{arm} baseline 복구 진행 중 — 도중에 서비스가 멈췄다면 사람이 캡을 확인하세요")  # durable: a restart treats it as a person-check
        try:
            port = (json.loads(rcfg.read_text(encoding="utf-8-sig")).get("robot") or {}).get("port")
            out = self.prep / ".bench-runs" / f"baseline-{arm}-{time.time_ns()}"
            cmd = [self.python, str(Path(__file__).resolve().with_name("commissioning_limits.py")), "--device", str(port), "--baseline",
                   "--output", str(out)]
        except (OSError, ValueError):
            return False
        try:
            done = subprocess.run(cmd, capture_output=True, text=True, timeout=120, cwd=self.prep)
            report = json.loads((done.stdout or "").strip().splitlines()[-1])
            verified = done.returncode == 0 and report.get("configuration_verified") is True and report.get("error") is None
        except FileNotFoundError:
            self.manual.unlink(missing_ok=True)
            return False  # the tool never started: nothing was written
        except (OSError, ValueError, IndexError, subprocess.SubprocessError):
            verified = False  # it ran and the result is unknown
        if verified:
            self.manual.unlink(missing_ok=True)  # only a verified result takes the marker away
        else:
            self._person_needed = f"{arm} baseline 복구가 확인되지 않았습니다 (일부 캡을 썼을 수 있음) — 사람이 캡을 확인하세요 ({out})"
        return verified

    def _auto_home_after_session(self):
        """Move the recorded arm home once after a confirmed safe end (no leader motion, no retry). Works only on THIS session's own record."""
        from bench_record_inspect import ARMS, BI_ARM
        claim = getattr(_TLS, "published_claim", None)
        _TLS.published_claim = None
        with self.lock:
            saved = dict(self.state)
            record = self._auto_homes.get(claim)
        arm = saved.get("arm")
        if record is None or arm not in (*ARMS, BI_ARM) or saved.get("status") not in ("sealed", "stopped_safe") or saved.get("claim", claim) != claim:
            with self.lock:
                self._auto_homes.pop(claim, None)  # only its own
            return
        self._reset_home_claim()
        _TLS.auto_claim = claim
        try:
            # 사용자 결정(녹화 안전 종료 시 자동 홈 복귀)에 따른 내부 호출
            res = self.go_home({"arm": arm, "at_bench": True, "include_leader": False})
            ah = {"ok": True, "arm": arm, "moved": res.get("home_moved", [arm]), "message": "홈 복귀 완료"}
        except Exception as exc:
            ah = {"ok": False, "arm": arm, "error": str(exc), "message": "자동 홈 취소됨" if record["cancelled"] else f"홈 복귀 실패({exc})"}
        finally:
            _TLS.auto_claim = None
            with self.lock:
                self._auto_homes.pop(claim, None)  # a finally removes only its own record
        with self.lock:
            if self.manual.exists():
                self.state["auto_home"] = ah
            elif (getattr(self, "_claims", 0) == (self._home_claim() or claim)  # no request but this home took the bench since the session ended
                  and self.state in (saved, {"status": "idle"})):
                self.state = {**saved, "auto_home": ah}
            else:
                print(f"auto home after the session ({ah['message']}) not shown: another request owns the bench now", flush=True)
