#!/usr/bin/env python3
"""Leader alignment and the stoppable leader_home child process for bench_record.py."""
from __future__ import annotations

import json, math, os, re, signal, subprocess, threading, time
from pathlib import Path

from bench_live_preview import camera_labels
from bench_record_inspect import ARMS, BI_ARM, HERE, arm_connectivity
from bench_record_guard import FOLLOWER_TORQUE_ON, follower_torque_on, hold_other_arm_locks, recorder_running, release, resolve_record_config
from camera_roles import disabled_roles, load_registry, resolve_record_cameras, source_role

BUSY = ("handing_over", "recording", "homing", "restoring", "sealing", "leader_manual_check")  # the recorder or a child owns the devices
HOME_LEADER_RATE_DEG_S = 20


def library_home_ticks(lib_p):
    """Last home pose in `lib_p` (`chunks.home[-1][:5]`) mapped from [-100, 100] to raw Follower ticks, or None."""
    try:
        data = json.loads(Path(lib_p).read_text(encoding="utf-8"))
        chunks = data.get("chunks") if isinstance(data, dict) else None
        home = chunks.get("home") if isinstance(chunks, dict) else None
        if not isinstance(home, list) or not home or not isinstance(home[-1], list) or len(home[-1]) < 5:
            return None
        ticks = []
        for val in home[-1][:5]:
            if isinstance(val, bool) or not isinstance(val, (int, float)) or not math.isfinite(val):
                return None
            tick = round((float(val) + 100.0) / 200.0 * 4095.0)
            if not 0 <= tick <= 4095:
                return None
            ticks.append(tick)
        return ticks
    except (OSError, ValueError, TypeError, AttributeError):
        return None


class BenchLeaderMixin:
    leader_proc, leader_hold = None, ""

    def _idle(self):
        """Back to idle (caller holds self.lock), unless a Leader child may still hold torque: then new work stays refused."""
        self.state = {"status": "leader_manual_check", "error": self.leader_hold} if self.leader_hold else {"status": "idle"}

    def _reserve_bench(self, name):
        """The bench is not idle while a pose-read child owns a port (like home): a start or home request meanwhile is refused."""
        with self.lock:
            if self.state["status"] != "idle":
                raise ValueError(f"작업대 상태가 idle이 아닙니다 ({self.state['status']})")
            self.state = mine = {"status": "homing", "name": name, "step": "pose_read"}
        return mine

    def _release_bench(self, mine):
        with self.lock:
            if self.state is mine:  # nothing took it over meanwhile
                self._idle()

    def restart_cameras(self, body):
        """Restart the preview camera units of one arm (its record config's cameras, then camera-view) while nothing owns the devices: idle or
        ended bench, no recorder, nothing stopped and waiting to be restored. No arm bus is touched. {ok, arm, units: {unit: {restarted, active}}}."""
        arm = body.get("arm")
        if arm not in (*ARMS, BI_ARM):
            raise ValueError("유효한 팔(arm_a, arm_b, arm_s, arm_ab)을 선택하세요")
        reg = load_registry()
        dis = disabled_roles(reg) if reg is not None else set()
        cameras = []
        for sub in ("arm_a", "arm_b") if arm == BI_ARM else (arm,):
            try:
                cfg = json.loads(resolve_record_config(self.prep, sub).read_text(encoding="utf-8-sig"))
                if reg is not None:
                    cfg, _, _ = resolve_record_cameras(cfg, sub, reg)
                robot = cfg.get("robot") if isinstance(cfg.get("robot"), dict) else {}
                if dis and isinstance(robot.get("cameras"), dict):
                    robot = {**robot, "cameras": {k: v for k, v in robot["cameras"].items() if source_role(k, sub) not in dis}}
                found = camera_labels(robot) if isinstance(robot.get("cameras"), dict) else {}
                if not found:
                    found = {k: v for k, v in (robot.get("cameras") or cfg.get("cameras") or {}).items()
                             if source_role(k, sub) not in dis}
            except (OSError, ValueError, AttributeError):
                found = {}
            cameras += [name for name in found if re.fullmatch(r"[\w-]+", str(name)) and name not in cameras]
        units = [f"rosy-omx-camera@{name}.service" for name in cameras] + ["rosy-omx-camera-view.service"]
        with self.lock:
            if self.state["status"] in BUSY or self.pending.exists():
                raise ValueError("녹화·홈·복원 중이거나 멈춘 유닛이 복원되지 않아 카메라를 재시작할 수 없습니다")
            saved = self.state
            self.state = mine = {"status": "homing", "name": f"cameras-{arm}", "step": "camera_restart"}  # a start or home request meanwhile is refused
        try:
            if recorder_running(self.procs):
                raise ValueError("녹화기가 실행 중이라 카메라를 재시작할 수 없습니다")
            results = {}
            for unit in units:
                done, state = self.run("restart", unit), self.run("is-active", unit)
                results[unit] = {"restarted": done.returncode == 0, "active": (state.stdout or "").strip() == "active"}
            return {"ok": all(r["restarted"] and r["active"] for r in results.values()), "arm": arm, "units": results}
        finally:
            with self.lock:
                if self.state is mine:
                    self.state = saved

    def _run_leader_home(self, cmd, env, label, timeout=420.0):
        """leader_home as a child the bench can stop. /stop and the deadline send SIGTERM, which runs its torque OFF and register
        restore; only a child that ignores that is killed, and then the bench stays in leader_manual_check."""
        with self.lock:
            if self.abort:
                raise ValueError(f"정지 요청이 있어 {label}을 시작하지 않습니다")
            proc = self.leader_proc = self.popen(cmd, cwd=self.prep, env=env, stdout=subprocess.PIPE,
                                                 stderr=subprocess.STDOUT, text=True)
        end, why = time.monotonic() + timeout, ""
        try:
            while True:
                try:
                    out = proc.communicate(timeout=0.5)[0]
                    break
                except subprocess.TimeoutExpired:
                    if self.abort or time.monotonic() > end:
                        why = "정지 요청" if self.abort else f"시간 초과 ({timeout:.0f}s)"
                        proc.send_signal(signal.SIGTERM)
                        try:
                            out = proc.communicate(timeout=20)[0]
                        except subprocess.TimeoutExpired:
                            proc.kill()
                            self.leader_hold = f"{label}: 종료를 확인할 수 없습니다 - 리더 수동 확인 필요: 리더 토크와 자세를 직접 확인한 뒤 작업대 서비스를 재시작하세요"
                            self._mark_manual(self.leader_hold)  # on disk first: a service restart still holds for a person
                            raise ValueError(self.leader_hold) from None
                        break
        finally:
            with self.lock:
                self.leader_proc = None
        if proc.returncode != 0 and follower_torque_on(out):  # it wrote nothing: an arm a dead process left powered, a person supports it first
            self._mark_manual(f"{label}: {FOLLOWER_TORQUE_ON}")
            raise ValueError(FOLLOWER_TORQUE_ON)
        if why or self.abort or proc.returncode != 0:  # anything but a clean success needs leader_home's own torque verdict
            note = self._leader_unconfirmed(proc, out)
            if note:
                self.leader_hold = f"{label}: {note} - 리더 수동 확인 필요: 리더 토크와 자세를 직접 확인한 뒤 작업대 서비스를 재시작하세요"
                self._mark_manual(self.leader_hold)
                raise ValueError(self.leader_hold)
        if why or self.abort:
            raise ValueError(f"{label} 중단: {why or '정지 요청'}")
        if proc.returncode != 0:
            raise ValueError(f"{label} 실패: {(out or '').strip()[-240:]}")

    @staticmethod
    def _leader_unconfirmed(proc, out):
        """Why a failed or stopped leader_home does not prove torque OFF and the restore (empty: it does). Its last line is JSON."""
        if proc.returncode is None or proc.returncode < 0:
            return "신호로 종료되어 토크 OFF를 확인할 수 없습니다"
        try:
            end = json.loads((out or "").strip().splitlines()[-1])
        except (ValueError, IndexError):
            return "종료 결과 줄이 없어 토크 OFF를 확인할 수 없습니다"
        if not isinstance(end, dict) or end.get("torque_off_confirmed") is not True:
            return "토크 OFF를 확인하지 못했습니다"
        return f"복원 실패 {end['restore_failures']}" if end.get("restore_failures") else ""

    def _match_leader(self, arm, config, label="리더 정렬", *, exact=False):
        """leader_home --match-follower: the Leader goes to the Follower's present pose. The arm's own lock is held too: the
        child reads (and torque-OFFs) the Follower, so no other owner may hold it."""
        handles, stopped = [], []
        try:
            self._check_lease(arm)  # lease and incident hold before the child that torque-OFFs the Follower, whoever called (align, home move)
            handles, busy = hold_other_arm_locks(arm, ARMS, self.procs, self.mounts, own=True)
            if busy:
                raise ValueError(f"{busy} — 점유 세션 종료 후 {label}을 실행하세요")
            self._check_lease(arm)  # again with the arm lock held: a session that recorded a hold and released its lock meanwhile is seen
            obs_unit = f"rosy-omx-observer@{arm}.service"
            if (self.run("is-active", obs_unit).stdout or "").strip() == "active":
                stopped.append(obs_unit)
                self._remember(stopped)
                self.run("stop", obs_unit)
            env = dict(os.environ)
            adapter_dir = str(HERE.parents[2] / "middleware" / "devices" / "omx" / "adapter")
            env["PYTHONPATH"] = os.pathsep.join([adapter_dir, str(HERE)] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
            cmd = [self.python, str(HERE / "leader_home.py"), "--config", str(config), "--arm", arm, "--match-follower",
                   *(["--exact"] if exact else []),
                   "--rate-deg-s", str(HOME_LEADER_RATE_DEG_S), "--timeout-s", "35", "--attest", f"hands-off:bench-auto:{int(time.time())}"]
            self._run_leader_home(cmd, env, f"{arm} {label}")
        finally:
            release(handles)
            if stopped and not self.manual.exists():
                errs, _ = self._start_units(reversed(stopped))
                self._remember(errs)

    def _start_parallel_leader(self, arm, config, home_ticks):
        """Start leader_home with known Follower home ticks on its separate Leader USB bus in parallel with Follower homing."""
        if not home_ticks:
            return None
        self._check_lease(arm)
        env = dict(os.environ)
        adapter_dir = str(HERE.parents[2] / "middleware" / "devices" / "omx" / "adapter")
        env["PYTHONPATH"] = os.pathsep.join([adapter_dir, str(HERE)] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
        csv = ",".join(str(int(v)) for v in home_ticks)
        cmd = [self.python, str(HERE / "leader_home.py"), "--config", str(config), "--arm", arm, "--target-follower-ticks", csv,
               "--exact", "--rate-deg-s", str(HOME_LEADER_RATE_DEG_S), "--timeout-s", "35", "--attest", f"hands-off:bench-auto:{int(time.time())}"]
        task = {"arm": arm, "error": None, "thread": None}

        def _worker():
            try:
                self._run_leader_home(cmd, env, f"{arm} 리더 홈 이동")
            except Exception as exc:
                task["error"] = exc

        th = threading.Thread(target=_worker, name=f"leader-home-{arm}", daemon=True)
        task["thread"] = th
        th.start()
        return task

    @staticmethod
    def _finish_parallel_leader(task):
        """Always wait for a parallel Leader child to finish torque-OFF + restore and return any raised error."""
        if task is None:
            return None
        th = task.get("thread")
        if th is not None:
            th.join()
        return task.get("error")

    def align_leader(self, body, config, keep=False):
        """Move the Leader onto the Follower's current pose before a teleop recording starts.
        keep: on success the bench stays claimed (homing) for the caller, who goes on to start the recording or calls _idle."""
        arm = body["arm"]
        if arm == BI_ARM:
            raise ValueError("리더 정렬(align_leader)은 단일 팔(arm_a, arm_b, arm_s)만 지원합니다")
        with self.lock:
            if self.state["status"] != "idle":
                raise ValueError(f"작업대 상태가 idle이 아닙니다 ({self.state['status']})")
            self.state, self.abort = {"status": "homing", "name": f"align-{arm}", "step": "leader_align"}, False
            self._claim_bench()
        ok = False
        try:
            self._match_leader(arm, config)
            ok = True
        finally:
            with self.lock:
                if not (ok and keep):
                    self._idle()

    def check_leader_home_status(self, arm="all"):
        """Passively read Leader distance vs MAX_TRAVEL_DEG without enabling torque (--check-home)."""
        arm = (arm or "all").strip()
        if arm not in ("all", *ARMS, BI_ARM):
            raise ValueError("유효한 팔(all, arm_a, arm_b, arm_s, arm_ab)을 선택하세요")
        targets = list(ARMS) if arm == "all" else (["arm_a", "arm_b"] if arm == BI_ARM else [arm])
        with self.lock:
            busy = self.state.get("status") in BUSY
        if busy or recorder_running(self.procs):
            return {"ok": True, "skipped": True, "reason": "세션 또는 호밍 진행 중", "arms": {}}
        locked = {h.get("lock") for h in self.active_lock_holders() if isinstance(h, dict)}
        env = dict(os.environ)
        adapter_dir = str(HERE.parents[2] / "middleware" / "devices" / "omx" / "adapter")
        env["PYTHONPATH"] = os.pathsep.join([adapter_dir, str(HERE)] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
        results = {}
        for a in targets:
            if f"session-{a}.lock" in locked or (a in ("arm_a", "arm_b") and f"session-{BI_ARM}.lock" in locked):
                results[a] = {"ok": False, "skipped": True, "reason": "세션 락 점유 중"}
                continue
            if arm_connectivity(self.prep, a).get("leader_connected") is False:
                results[a] = {"ok": False, "skipped": True, "reason": "리더 USB 미연결"}
                continue
            try:
                _, lib_p, rcfg, _, _ = self._home_files(a)
            except ValueError as exc:
                results[a] = {"ok": False, "skipped": True, "reason": str(exc)}
                continue
            ticks = library_home_ticks(lib_p)
            pose_p = self.prep / f"leader-home-{a}.json"
            if ticks:
                target_args = ["--target-follower-ticks", ",".join(str(int(v)) for v in ticks)]
            elif pose_p.is_file():
                target_args = ["--pose", str(pose_p)]
            else:
                results[a] = {"ok": False, "skipped": True, "reason": "홈 목표 틱/포즈 없음"}
                continue
            cmd = [self.python, str(HERE / "leader_home.py"), "--config", str(rcfg), "--arm", a,
                   *target_args, "--exact", "--check-home"]
            try:
                res = subprocess.run(cmd, cwd=self.prep, env=env, capture_output=True, text=True, timeout=10)
            except (subprocess.TimeoutExpired, OSError) as exc:
                results[a] = {"ok": False, "error": str(exc)[:200]}
                continue
            lines = [ln for ln in (res.stdout or "").strip().splitlines() if ln.strip()]
            parsed = None
            if lines:
                try:
                    parsed = json.loads(lines[-1])
                except ValueError:
                    parsed = None
            if isinstance(parsed, dict) and res.returncode in (0, 2):
                results[a] = parsed
            else:
                err = parsed.get("error") if isinstance(parsed, dict) and parsed.get("error") else ((res.stderr or res.stdout or "").strip()[-200:] or f"rc={res.returncode}")
                results[a] = {"ok": False, "error": err}
        return {"ok": True, "skipped": False, "checked_at": round(time.time(), 1), "arms": results}
