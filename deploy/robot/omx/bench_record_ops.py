#!/usr/bin/env python3
"""Bench hardware operations (caps, home, initial/leader pose) for bench_record.py."""
from __future__ import annotations

import json, math, os, re, signal, subprocess, time, urllib.request
from pathlib import Path

from bench_record_inspect import ARMS, BI_ARM, HERE, active_handover_units
from bench_record_guard import hold_other_arm_locks, release


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


    def go_home(self, body):
        if body.get("at_bench") is not True:
            raise ValueError("작업대 현장 확인(at_bench) 체크 후에만 홈 이동을 실행할 수 있습니다")
        arm = body.get("arm")
        if arm not in (*ARMS, BI_ARM):
            raise ValueError("유효한 팔(arm_a, arm_b, arm_s, arm_ab)을 선택하세요")
        if self.pending.exists():
            raise ValueError("이전 녹화에서 멈춘 유닛이 아직 복원되지 않았습니다. 먼저 복원하세요")
        target_arms = ["arm_a", "arm_b"] if arm == BI_ARM else [arm]
        inc_leader = body.get("include_leader") is True
        if inc_leader and body.get("hands_off_leader") is not True:
            raise ValueError("리더 동시 홈 이동에는 '리더 팔에서 손을 떼었습니다(hands_off_leader)' 확인이 필요합니다")
        arm_plans = []
        for a in target_arms:
            letter = ARMS[a]
            stack = self.prep / f"cell-arm-{letter}-stack.json"
            libs = sorted(self.prep.glob(f"chunks-topdown-guard-arm{letter}*.json"))
            if not stack.is_file() or not libs:
                raise ValueError(f"{a}의 홈 복귀 설정(cell-arm-{letter}-stack.json / chunks-*)을 찾을 수 없습니다")
            rcfg = self.prep / f"record-config-arm-{letter}.json"
            rprof = self.prep / f"arm-{letter}-robot-profile.json"
            caps_cands = [p for p in sorted(self.prep.glob(f"caps-arm-{letter}-*.json")) if "-custom-" not in p.name]
            if not (rcfg.is_file() and rprof.is_file() and caps_cands):
                raise ValueError(f"{a}의 홈 실행용 설정/프로필/caps 파일이 부족합니다")
            self._check_robot(a, rcfg.name, rcfg.read_bytes())
            lpose = self.prep / f"leader-home-{a}.json"
            if inc_leader and not lpose.is_file():
                raise ValueError(f"{a}의 저장된 리더 홈 포즈(leader-home-{a}.json)가 없습니다")
            arm_plans.append((a, letter, stack, libs[-1], rcfg, rprof, caps_cands[-1], lpose))
        with self.lock:
            if self.state["status"] in ("handing_over", "homing", "recording", "restoring", "sealing"):
                raise ValueError("세션이 진행 중일 때는 홈 이동을 실행할 수 없습니다")
            self.state = {"status": "homing", "name": f"home-{arm}"}
        results = []
        env = dict(os.environ)
        adapter_dir = str(HERE.parents[2] / "middleware" / "devices" / "omx" / "adapter")
        py_paths = [adapter_dir, str(HERE)] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else [])
        env["PYTHONPATH"] = os.pathsep.join(py_paths)
        try:
            for a, letter, stack, lib_p, rcfg, rprof, caps_p, lpose in arm_plans:
                io_dir = self.prep / f"chunk-io-{letter}"
                handles = []
                rec_proc = None
                stopped_units = []
                try:
                    handles, busy = hold_other_arm_locks(a, ARMS, self.procs, self.mounts)
                    if busy:
                        raise ValueError(f"{busy} — 점유 세션 종료 후 홈 이동을 실행하세요")
                    for unit in active_handover_units(self.run):
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
                    live_p = io_dir / "live.json"
                    t0 = time.time()
                    rec_proc = self.popen(rec_cmd, cwd=self.prep, env=env)
                    deadline_r = t0 + 20.0
                    ready = False
                    while time.time() < deadline_r:
                        rc = rec_proc.poll()
                        if rc is not None:
                            if rc != 0:
                                raise ValueError(f"{a} 홈용 record_session이 조기 종료되었습니다 (code={rc})")
                            ready = True
                            break
                        if live_p.is_file() and live_p.stat().st_mtime > t0:
                            ready = True
                            break
                        time.sleep(0.3)
                    if not ready:
                        raise ValueError(f"{a} 홈용 record_session 준비 시간 초과 (20s)")
                    time.sleep(1.0)
                    cmd = [self.python, str(HERE / "cell_pipeline.py"), "--config", str(stack),
                           "--stage", "home", "--library", str(lib_p), "--operating-profile", str(rprof), "--person-at-switch"]
                    try:
                        res = subprocess.run(cmd, cwd=self.prep, env=env, capture_output=True, text=True, timeout=60)
                    except subprocess.TimeoutExpired:
                        raise ValueError(f"{a} 홈 이동 시간 초과 (60s)") from None
                    if res.returncode != 0:
                        raise ValueError(f"{a} 홈 이동 실패: {(res.stderr or res.stdout or '').strip()[-240:]}")
                    if inc_leader:
                        lcmd = [self.python, str(HERE / "leader_home.py"), "--config", str(rcfg),
                                "--arm", a, "--pose", str(lpose), "--timeout-s", "35",
                                "--attest", f"hands-off:bench:{int(time.time())}"]
                        try:
                            # leader_home stretches its own deadline to the distance at 1 degree/s; a full turn fits in 420 s
                            lres = subprocess.run(lcmd, cwd=self.prep, env=env, capture_output=True, text=True, timeout=420)
                        except subprocess.TimeoutExpired:
                            raise ValueError(f"{a} 리더 홈 이동 시간 초과 (420s)") from None
                        if lres.returncode != 0:
                            raise ValueError(f"{a} 리더 홈 이동 실패: {(lres.stderr or lres.stdout or '').strip()[-240:]}")
                    results.append(a)
                finally:
                    if rec_proc is not None:
                        try:
                            rec_proc.send_signal(signal.SIGTERM)
                            rec_proc.wait(timeout=15)
                        except subprocess.TimeoutExpired:
                            rec_proc.kill()
                            try:
                                rec_proc.wait(timeout=5)
                            except Exception:
                                pass
                        except Exception:
                            pass
                    if handles:
                        release(handles)
                    if stopped_units:
                        errs, _ = self._start_units(reversed(stopped_units))
                        self._remember(errs)
        finally:
            with self.lock:
                self.state = {"status": "idle"}
        st = self.status()
        st["home_moved"] = results
        return st

    def save_initial_pose(self, body):
        if body.get("at_bench") is not True:
            raise ValueError("작업대 현장 확인(at_bench) 체크 후에만 이니셜 포즈를 저장할 수 있습니다")
        arm = body.get("arm")
        if arm not in (*ARMS, BI_ARM):
            raise ValueError("유효한 팔(arm_a, arm_b, arm_s, arm_ab)을 선택하세요")
        target_arms = ["arm_a", "arm_b"] if arm == BI_ARM else [arm]
        with self.lock:
            if self.state["status"] != "idle":
                raise ValueError(f"작업대 상태가 idle이 아닙니다 ({self.state['status']})")
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
                rcfg = self.prep / f"record-config-arm-{letter}.json"
                if not rcfg.is_file():
                    raise ValueError(f"{a}의 실시간 관절 파일(chunk-io-{letter}/live.json) 또는 설정 파일(record-config-arm-{letter}.json)을 찾을 수 없습니다")
                try:
                    res = subprocess.run([self.python, str(HERE / "leader_home.py"), "--config", str(rcfg), "--arm", a, "--read-follower-pose"],
                                         cwd=self.prep, env=env, capture_output=True, text=True, timeout=15)
                except subprocess.TimeoutExpired:
                    raise ValueError(f"{a} 팔로워 현재 위치 읽기 시간 초과 (15s)") from None
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
        if body.get("at_bench") is not True:
            raise ValueError("작업대 현장 확인(at_bench) 체크 후에만 리더 포즈를 저장할 수 있습니다")
        arm = body.get("arm")
        if arm not in (*ARMS, BI_ARM):
            raise ValueError("유효한 팔(arm_a, arm_b, arm_s, arm_ab)을 선택하세요")
        with self.lock:
            if self.state["status"] != "idle":
                raise ValueError(f"작업대 상태가 idle이 아닙니다 ({self.state['status']})")
        target_arms = ["arm_a", "arm_b"] if arm == BI_ARM else [arm]
        cfgs = {}
        for a in target_arms:
            letter = ARMS[a]
            rcfg = self.prep / f"record-config-arm-{letter}.json"
            if not rcfg.is_file():
                raise ValueError(f"{a}의 설정 파일(record-config-arm-{letter}.json)을 찾을 수 없습니다")
            cfgs[a] = rcfg
        env = dict(os.environ)
        adapter_dir = str(HERE.parents[2] / "middleware" / "devices" / "omx" / "adapter")
        py_paths = [adapter_dir, str(HERE)] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else [])
        env["PYTHONPATH"] = os.pathsep.join(py_paths)
        read_ticks = {}
        for a, rcfg in cfgs.items():
            try:
                res = subprocess.run([self.python, str(HERE / "leader_home.py"), "--config", str(rcfg), "--arm", a, "--read-pose"],
                                     cwd=self.prep, env=env, capture_output=True, text=True, timeout=15)
            except subprocess.TimeoutExpired:
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
        if body.get("at_bench") is not True:
            raise ValueError("작업대 현장 확인(at_bench) 체크 후에만 기준 카메라를 저장할 수 있습니다")
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

