#!/usr/bin/env python3
"""Bench hardware operations (caps, home, initial/leader pose) for bench_record.py."""
from __future__ import annotations

import json, math, os, re, subprocess, time, urllib.request
from pathlib import Path

from bench_record_inspect import ARMS, BI_ARM, HERE, active_handover_units
from bench_record_guard import FOLLOWER_TORQUE_ON, follower_torque_on, hold_other_arm_locks, release, resolve_record_config
from bench_record_leader import library_home_ticks
from bench_record_step import at_home, finish_home_child, resolve_home_failure


HOME_UNFOLDED = "home requires an empty, folded arm"  # cell_unwedge.return_home's refusal, written to the receipt


class BenchOpsMixin:
    def save_caps(self, body):
        if not isinstance(body, dict) or body.get("arm") not in (*ARMS, BI_ARM):
            raise ValueError("유효한 팔을 선택하세요")
        values = body.get("values")
        if not isinstance(values, dict) or not values:
            raise ValueError("caps 값이 필요합니다")
        cleaned = {}
        for mid, fields in values.items():
            if not re.fullmatch(r"1[1-6]", str(mid)) or not isinstance(fields, dict):
                raise ValueError(f"잘못된 모터 ID 또는 값: {mid} (11~16)")
            row = {}
            for k, v in fields.items():
                if k not in ("pwm", "current", "p", "i", "acc", "vel") or isinstance(v, bool) or not isinstance(v, int):
                    raise ValueError(f"모터 {mid}.{k}는 허용된 정수 키(pwm, current, p, i, acc, vel)여야 합니다")
                if k == "pwm" and not (1 <= v <= (600 if str(mid) in ("11", "12", "13") else 400)):
                    raise ValueError(f"모터 {mid}.pwm 범위 초과")
                if k == "current" and (str(mid) not in ("14", "15", "16") or not (1 <= v <= 400)):
                    raise ValueError(f"모터 {mid}.current는 14~16번(1~400)만 지원합니다")
                if k == "p" and not (1 <= v <= 1600):
                    raise ValueError(f"모터 {mid}.p 범위는 1~1600입니다")
                if k == "i" and not (0 <= v <= 1600):
                    raise ValueError(f"모터 {mid}.i 범위는 0~1600입니다")
                if k in ("acc", "vel") and not (0 <= v <= 2000):
                    raise ValueError(f"모터 {mid}.{k} 범위는 0~2000입니다")
                row[k] = v
            if row:
                cleaned[str(mid)] = row
        arm = body["arm"]
        prefix = "caps-bi-custom" if arm == BI_ARM else f"caps-arm-{ARMS[arm]}-custom"
        fname = f"{prefix}-{time.strftime('%Y%m%d-%H%M%S')}.json"
        (self.prep / fname).write_text(json.dumps(cleaned, indent=1) + "\n", encoding="utf-8")
        return {"saved": fname, "choices": self.choices()}


    def _home_files(self, a):
        """(stack, library, record config, robot profile, caps) one arm's home runs on. The stack is the one
        cell_task_exec names for the arm; arm_s's other files carry the -live names of the cell that runs it."""
        from cell_task_exec import _arm_run_spec

        letter, live = ARMS[a], a == "arm_s"
        stack = _arm_run_spec(a, self.prep)[1]
        libs = sorted(self.prep.glob(f"chunks-arm-{letter}-inplace-live.json" if live else f"chunks-topdown-guard-arm{letter}*.json"))
        rcfg = self.prep / f"record-config-arm-{letter}{'-live' if live else ''}.json"
        rprof = self.prep / f"arm-{letter}-robot-profile{'-live' if live else ''}.json"
        caps = [p for p in sorted(self.prep.glob(f"caps-arm-{letter}-*.json")) if "-custom-" not in p.name]
        if not stack.is_file() or not libs:
            raise ValueError(f"{a}의 홈 복귀 설정({stack.name} / chunks-*)을 찾을 수 없습니다")
        if not (rcfg.is_file() and rprof.is_file() and caps):
            raise ValueError(f"{a}의 홈 실행용 설정/프로필/caps 파일이 부족합니다")
        return stack, libs[-1], rcfg, rprof, caps[-1]

    def _pipeline_stage(self, a, cmd, stage, env, *extra):
        try:
            return subprocess.run([*cmd, "--stage", stage, *extra], cwd=self.prep, env=env, capture_output=True, text=True, timeout=60)
        except subprocess.TimeoutExpired:  # subprocess.run killed the stage: the arm may be mid-motion, nothing confirms it
            self._mark_manual(f"{a} {stage} 시간 초과 (60s): 단계를 강제 종료했습니다 — 팔 상태를 확인하세요")
            raise ValueError(f"{a} {stage} 시간 초과 (60s)") from None

    def _check_abort(self, label):
        if self.abort:
            raise ValueError(f"정지 요청이 있어 {label}을 시작하지 않습니다")

    def _home_failure(self, a, res):
        """cell_pipeline prints {"receipt","result"} on stdout; the refusal text is only in the receipt file."""
        try:
            out = json.loads((res.stdout or "").strip().splitlines()[-1])
            result = out["result"]
        except (ValueError, IndexError, KeyError, TypeError):
            return f"{a} 홈 이동 실패: {(res.stderr or res.stdout or '').strip()[-240:]}"
        try:
            error = json.loads(Path(out["receipt"]).read_text(encoding="utf-8")).get("error") or ""
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            error = ""
        hint = (" — 감독 복구(cell_pipeline --stage recover 또는 cell_auto_fold)로 팔을 먼저 접으세요"
                if HOME_UNFOLDED in str(error) else "")
        return f"{a} 홈 이동 실패 (result={result}) {str(error)[-200:]}{hint}"

    def _home_ok(self, res):
        try:
            return res.returncode == 0 and json.loads((res.stdout or "").strip().splitlines()[-1])["result"] == "home"
        except (ValueError, IndexError, KeyError, TypeError):
            return False

    def go_home(self, body):
        self.last_issue, self._home_recovered = None, False
        try:
            return self._go_home(body)
        except ValueError as exc:  # the page tells a refusal, an automatic recovery and a person-needed stop apart (error_kind)
            kind = "needs_person" if self.manual.exists() else "recovered" if self._home_recovered else "refused"
            self.last_issue = {"kind": kind, "message": str(exc)[:300], "arm": (body or {}).get("arm") if isinstance(body, dict) else None}
            raise

    def _go_home(self, body):
        arm = body.get("arm")
        if arm not in (*ARMS, BI_ARM):
            raise ValueError("유효한 팔(arm_a, arm_b, arm_s, arm_ab)을 선택하세요")
        self._check_manual()
        if self.pending.exists():
            raise ValueError("이전 녹화에서 멈춘 유닛이 아직 복원되지 않았습니다. 먼저 복원하세요")
        target_arms = ["arm_a", "arm_b"] if arm == BI_ARM else [arm]
        for a in target_arms:
            self._check_lease(a)  # a held or foreign live lease refuses before any unit stops or bus opens
        inc_leader, fold_unfolded = body.get("include_leader") is True, body.get("fold_unfolded") is True
        arm_plans = []
        for a in target_arms:
            letter = ARMS[a]
            stack, lib, rcfg, rprof, caps = self._home_files(a)
            self._check_robot(a, rcfg.name, rcfg.read_bytes(), rprof)
            port = (json.loads(rcfg.read_text(encoding="utf-8-sig")).get("robot") or {}).get("port")
            if port and str(port).startswith("/dev/serial/by-id/") and not Path(port).exists():  # refuse before any unit stops: nothing was touched, no hold
                raise ValueError(f"{a} 팔로워 보드가 이 PC에 연결되어 있지 않습니다 ({Path(port).name}) — 홈 이동을 시작하지 않았습니다")
            arm_plans.append((a, letter, stack, lib, rcfg, rprof, caps))
        with self.lock:
            if self.state["status"] in ("handing_over", "homing", "recording", "restoring", "sealing", "leader_manual_check"):
                raise ValueError("세션이 진행 중이거나 리더 수동 확인이 필요할 때는 홈 이동을 실행할 수 없습니다")
            claim = self._auto_claim()  # an auto home: only its OWN record, and no request may have taken the bench since its session ended
            if claim is not None:
                record = self._auto_homes.get(claim)
                if record is None or record["cancelled"]:
                    raise ValueError("자동 홈 취소됨 (정지 요청)")
                if getattr(self, "_claims", 0) != claim:
                    raise ValueError("다른 요청이 벤치를 가져갔습니다 — 지난 세션의 자동 홈을 취소합니다")
                record["reserved"] = True  # from here stop() aborts it instead of cancelling it
            self.state, self.abort = {"status": "homing", "name": f"home-{arm}", "step": "follower_home"}, False
            self._person_needed = self._arm_lock = self._home_child = None
            self._claim_bench()
        results, blocked = [], None
        env = dict(os.environ)
        adapter_dir = str(HERE.parents[2] / "middleware" / "devices" / "omx" / "adapter")
        py_paths = [adapter_dir, str(HERE)] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else [])
        env["PYTHONPATH"] = os.pathsep.join(py_paths)
        try:
            for a, letter, stack, lib_p, rcfg, rprof, caps_p in arm_plans:
                self._check_abort(f"{a} 홈 이동")  # a /stop since the last arm: no new arm starts
                self._set(step="follower_home", step_arm=a)
                io_dir = self.prep / f"chunk-io-{letter}"
                handles = []
                rec_proc = None
                clean = True
                stopped_units, fresh, home_ok, stop_flag = [], False, False, [False]
                leader_task = None
                rec_log_p, rec_log = self.prep / ".bench-runs" / f"home-{a}.log", None
                try:
                    handles, busy = hold_other_arm_locks(a, ARMS, self.procs, self.mounts)
                    if busy:
                        raise ValueError(f"{busy} — 점유 세션 종료 후 홈 이동을 실행하세요")
                    home_ticks = library_home_ticks(lib_p) if inc_leader else None
                    if home_ticks is not None:
                        leader_task = self._start_parallel_leader(a, rcfg, home_ticks)
                    for unit in [u for u in active_handover_units(self.run) if u.startswith("rosy-omx-observer@") or u == "rosy-omx-cell-task-worker.service"]:
                        stopped_units.append(unit)
                        self._remember(stopped_units)
                        self.run("stop", unit)
                    cfg_tmp = json.loads(rcfg.read_text(encoding="utf-8-sig"))
                    ds = cfg_tmp.setdefault("dataset", {})
                    ds["root"] = str(self.prep / ".bench-runs" / f"home-{a}-{int(time.time())}")
                    tmp_cfg_p = self.prep / ".bench-runs" / f"home-cfg-{a}.json"
                    tmp_cfg_p.parent.mkdir(parents=True, exist_ok=True)
                    tmp_cfg_p.write_text(json.dumps(cfg_tmp), encoding="utf-8")
                    rec_cmd = [self.python, str(HERE / "record_session.py"),
                               "--config", str(tmp_cfg_p), "--caps", str(caps_p),
                               "--arm", a, "--chunks", str(lib_p),
                               "--io", str(io_dir), "--operating-profile", str(rprof)]
                    if leader_task is not None:
                        rec_cmd.append("--skip-leader-finish")
                    live_p = io_dir / "live.json"
                    for attempt in (0, 1):  # a baseline refusal is restored in place, under this reservation, and retried once
                        t0 = time.time()
                        with self.lock:  # the lock /stop takes: a stop is either seen here or finds the child running
                            self._check_abort(f"{a} 홈 이동")
                            rec_log = rec_log_p.open("wb")  # only now: it truncates the earlier child's log, which the classifier still reads on a stop
                            if getattr(self, "_arm_lock", None) is not None:  # the recovery's lock goes just before the retried recorder's own
                                release([self._arm_lock])
                                self._arm_lock = None
                            rec_proc = self._home_child = self.popen(rec_cmd, cwd=self.prep, env=env, stdout=rec_log, stderr=subprocess.STDOUT)
                        deadline_r = t0 + 20.0
                        ready, refused = False, None
                        while time.time() < deadline_r:
                            rc = rec_proc.poll()
                            if rc is not None:
                                refused, ready = (rc, False) if rc != 0 else (None, True)
                                break
                            if live_p.is_file() and live_p.stat().st_mtime > t0:
                                ready = fresh = True  # written by the recorder this request started
                                break
                            time.sleep(0.3)
                        if refused is None:
                            break
                        rec_log.close()
                        if attempt == 0 and self._baseline_in_place(a, rcfg, refused, rec_log_p):
                            continue
                        raise ValueError(f"{a} 홈용 record_session이 조기 종료되었습니다 (code={refused}){self._child_reason(rec_log_p)}")
                    if not ready:
                        raise ValueError(f"{a} 홈용 record_session 준비 시간 초과 (20s)")
                    time.sleep(1.0)
                    with self.lock:  # /stop also ends the recorder, so a stage started after this check finds no runner (limit: not atomic)
                        self._check_abort(f"{a} 홈 이동")
                    if not (fresh and rec_proc.poll() is None and at_home(live_p, lib_p, t0)):  # its own live pose: no extra bus process
                        cmd = [self.python, str(HERE / "cell_pipeline.py"), "--config", str(stack), "--operating-profile", str(rprof),
                               "--person-at-switch"]
                        res = self._pipeline_stage(a, cmd, "home", env, "--library", str(lib_p))
                        if not self._home_ok(res):
                            resolve_home_failure(self, a, res, stack, lib_p, io_dir, env, fold_unfolded, stop_flag)
                    home_ok = True
                finally:
                    clean = finish_home_child(self, rec_proc, rec_log_p, stop_flag[0])
                    self._home_child = None
                    if rec_log is not None:
                        rec_log.close()
                    if leader_task is not None and leader_task["thread"] is not None and leader_task["thread"].is_alive():
                        self._set(step="leader_align", step_arm=a)
                    leader_err = self._finish_parallel_leader(leader_task)
                    if clean:
                        if getattr(self, "_arm_lock", None) is not None:  # a recovery that ended without handing its lock on
                            release([self._arm_lock])
                            self._arm_lock = None
                        if handles:
                            release(handles)
                        try:  # the Leader reads the Follower here: the observers and previews come back only after that
                            if leader_task is not None:
                                if leader_err is not None and home_ok:
                                    raise leader_err
                            elif inc_leader and home_ok:
                                self._set(step="leader_align", step_arm=a)
                                self._check_abort(f"{a} 리더 정렬")
                                self._match_leader(a, rcfg, "리더 홈 이동", exact=True)
                        finally:
                            if stopped_units:
                                errs, _ = self._start_units(reversed(stopped_units))
                                self._remember(errs)
                    else:  # keep the arm locks, the stopped units listed and the bench busy until a person checks the arm
                        blocked = self._record_home_hold(a, rec_proc, rec_log_p, io_dir)
                        raise ValueError(blocked)
                results.append(a)
        finally:
            with self.lock:
                if blocked:  # record_session did not end cleanly: stay busy until a person checks the arm
                    self.state = {"status": "homing", "name": f"home-{arm}", "error": blocked}
                else:
                    self._idle()
        st = self.status()
        st["home_moved"] = results
        return st

    def save_initial_pose(self, body):
        mine = self._reserve_bench(f"pose-{(body or {}).get('arm')}")
        try:
            return self._save_initial_pose(body)
        finally:
            self._release_bench(mine)

    def _save_initial_pose(self, body):
        arm = body.get("arm")
        if arm not in (*ARMS, BI_ARM):
            raise ValueError("유효한 팔(arm_a, arm_b, arm_s, arm_ab)을 선택하세요")
        target_arms = ["arm_a", "arm_b"] if arm == BI_ARM else [arm]
        poses = {}
        env = dict(os.environ)
        adapter_dir = str(HERE.parents[2] / "middleware" / "devices" / "omx" / "adapter")
        py_paths = [adapter_dir, str(HERE)] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else [])
        env["PYTHONPATH"] = os.pathsep.join(py_paths)
        for a in target_arms:
            letter = ARMS[a]
            live_p = self.prep / f"chunk-io-{letter}" / "live.json"
            state = None
            if live_p.is_file() and (time.time() - live_p.stat().st_mtime) <= 10.0:
                live_d = json.loads(live_p.read_text(encoding="utf-8"))
                state = live_d.get("state")
            else:
                rcfg = resolve_record_config(self.prep, a)
                if not rcfg.is_file():
                    raise ValueError(f"{a}의 실시간 관절 파일(chunk-io-{letter}/live.json) 또는 설정 파일(record-config-arm-{letter}.json)을 찾을 수 없습니다")
                self._check_lease(a)  # the read opens the Follower's bus: lease and incident hold first
                try:
                    res = subprocess.run([self.python, str(HERE / "leader_home.py"), "--config", str(rcfg), "--arm", a, "--read-follower-pose"],
                                         cwd=self.prep, env=env, capture_output=True, text=True, timeout=15)
                except subprocess.TimeoutExpired:  # killed with the Follower torque-OFF write possibly half done
                    self._mark_manual(f"{a} 팔로워 위치 읽기를 강제 종료했습니다 — 팔로워 토크 상태를 확인하세요")
                    raise ValueError(f"{a} 팔로워 현재 위치 읽기 시간 초과 (15s)") from None
                if res.returncode != 0 and follower_torque_on(res.stdout):  # it wrote nothing; a person supports the arm first
                    self._mark_manual(f"{a} {FOLLOWER_TORQUE_ON}")
                    raise ValueError(FOLLOWER_TORQUE_ON)
                if res.returncode != 0:
                    raise ValueError(f"{a} 팔로워 현재 위치 읽기 실패: {(res.stderr or res.stdout or '').strip()[-200:]}")
                data = json.loads(res.stdout)
                state = data.get("state") if isinstance(data, dict) else None
            if not isinstance(state, list) or len(state) < 6 or any(type(x) not in (int, float) or not math.isfinite(x) for x in state[:6]):
                raise ValueError(f"{a}의 현재 관절 좌표(state)가 유효하지 않습니다")
            poses[a] = [round(float(x), 2) for x in state[:6]]
        saved = {}
        for a, pose6 in poses.items():
            pose_file = self.prep / f"initial-pose-{a}.json"
            tmp_p = pose_file.with_suffix(".json.tmp")
            tmp_p.write_text(json.dumps({
                "schema": "rosy.omx-initial-pose.v1",
                "arm": a,
                "state": pose6,
                "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }, indent=2), encoding="utf-8")
            os.replace(tmp_p, pose_file)
            saved[a] = pose6
        st = self.status()
        st["initial_pose_saved"] = saved
        return st

    def save_leader_pose(self, body):
        mine = self._reserve_bench(f"leader-pose-{(body or {}).get('arm')}")
        try:
            return self._save_leader_pose(body)
        finally:
            self._release_bench(mine)

    def _save_leader_pose(self, body):
        arm = body.get("arm")
        if arm not in (*ARMS, BI_ARM):
            raise ValueError("유효한 팔(arm_a, arm_b, arm_s, arm_ab)을 선택하세요")
        target_arms = ["arm_a", "arm_b"] if arm == BI_ARM else [arm]
        cfgs = {}
        for a in target_arms:
            letter = ARMS[a]
            rcfg = resolve_record_config(self.prep, a)
            if not rcfg.is_file():
                raise ValueError(f"{a}의 설정 파일(record-config-arm-{letter}.json)을 찾을 수 없습니다")
            cfgs[a] = rcfg
        env = dict(os.environ)
        adapter_dir = str(HERE.parents[2] / "middleware" / "devices" / "omx" / "adapter")
        py_paths = [adapter_dir, str(HERE)] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else [])
        env["PYTHONPATH"] = os.pathsep.join(py_paths)
        read_ticks = {}
        for a, rcfg in cfgs.items():
            self._check_lease(a)  # the read opens the Leader's bus: lease and incident hold first
            try:
                res = subprocess.run([self.python, str(HERE / "leader_home.py"), "--config", str(rcfg), "--arm", a, "--read-pose"],
                                     cwd=self.prep, env=env, capture_output=True, text=True, timeout=15)
            except subprocess.TimeoutExpired:  # killed on the Leader bus: nothing confirms its state
                self._mark_manual(f"{a} 리더 위치 읽기를 강제 종료했습니다 — 리더 토크 상태를 확인하세요")
                raise ValueError(f"{a} 리더 현재 위치 읽기 시간 초과 (15s)") from None
            if res.returncode != 0:
                raise ValueError(f"{a} 리더 현재 위치 읽기 실패: {(res.stderr or res.stdout or '').strip()[-200:]}")
            data = json.loads(res.stdout)
            ticks = data.get("ticks") if isinstance(data, dict) else None
            if not isinstance(ticks, dict):
                raise ValueError(f"{a} 리더 현재 위치 응답 형식이 올바르지 않습니다")
            read_ticks[a] = ticks
        saved = {}
        for a, ticks in read_ticks.items():
            pose_file = self.prep / f"leader-home-{a}.json"
            tmp_p = pose_file.with_suffix(".json.tmp")
            tmp_p.write_text(json.dumps({"schema": "rosy.omx-leader-pose.v1", "arm": a, "ticks": ticks,
                                         "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S")}, indent=2), encoding="utf-8")
            os.replace(tmp_p, pose_file)
            saved[a] = ticks
        st = self.status()
        st["leader_pose_saved"] = saved
        return st

    def save_camera_baseline(self, body):
        raw_arm = body.get("arm") or "default"
        if raw_arm not in (*ARMS, BI_ARM, "default"):
            raise ValueError("유효한 팔(arm_a, arm_b, arm_s, arm_ab)을 선택하세요")
        raw = json.loads(urllib.request.urlopen("http://127.0.0.1:8767/state.json", timeout=2.0).read())
        bdir = self.prep / "camera-baselines" / raw_arm
        bdir.mkdir(parents=True, exist_ok=True)
        saved = {}
        for lbl, info in raw.items():
            if not re.fullmatch(r"[a-zA-Z0-9_-]+", str(lbl)) or not isinstance(info, dict) or "quality" not in info:
                continue
            saved[lbl] = {"topic": info.get("topic"), "quality": info.get("quality")}
            try:
                jpg = urllib.request.urlopen(f"http://127.0.0.1:8767/frame/{lbl}.jpg", timeout=1.5).read()
                (bdir / f"{lbl}.jpg").write_bytes(jpg)
            except Exception:
                pass
        (bdir / "baseline.json").write_text(json.dumps({"saved_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "cameras": saved}, indent=2), encoding="utf-8")
        return {"ok": True, "arm": raw_arm, "cameras": list(saved)}

