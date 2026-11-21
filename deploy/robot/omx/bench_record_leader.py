#!/usr/bin/env python3
"""Leader alignment and the stoppable leader_home child process for bench_record.py."""
from __future__ import annotations

import json, os, re, signal, subprocess, time

from bench_record_inspect import ARMS, BI_ARM, HERE
from bench_record_guard import FOLLOWER_TORQUE_ON, follower_torque_on, hold_other_arm_locks, recorder_running, release

BUSY = ("handing_over", "recording", "homing", "restoring", "sealing", "leader_manual_check")  # the recorder or a child owns the devices


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
        cameras = []
        for sub in ("arm_a", "arm_b") if arm == BI_ARM else (arm,):
            try:
                found = json.loads((self.prep / f"record-config-arm-{ARMS[sub]}.json").read_text(encoding="utf-8-sig")).get("cameras") or {}
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

    def _match_leader(self, arm, config, label="리더 정렬"):
        """leader_home --match-follower: the Leader goes to the Follower's present pose. The arm's own lock is held too: the
        child reads (and torque-OFFs) the Follower, so no other owner may hold it."""
        handles = []
        try:
            self._check_lease(arm)  # lease and incident hold before the child that torque-OFFs the Follower, whoever called (align, home move)
            handles, busy = hold_other_arm_locks(arm, ARMS, self.procs, self.mounts, own=True)
            if busy:
                raise ValueError(f"{busy} — 점유 세션 종료 후 {label}을 실행하세요")
            self._check_lease(arm)  # again with the arm lock held: a session that recorded a hold and released its lock meanwhile is seen
            env = dict(os.environ)
            adapter_dir = str(HERE.parents[2] / "middleware" / "devices" / "omx" / "adapter")
            env["PYTHONPATH"] = os.pathsep.join([adapter_dir, str(HERE)] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
            cmd = [self.python, str(HERE / "leader_home.py"), "--config", str(config), "--arm", arm, "--match-follower",
                   "--timeout-s", "35", "--attest", f"hands-off:bench-auto:{int(time.time())}"]  # no person confirms: the bench itself runs it, for align and home alike
            # leader_home stretches its own deadline to the distance at 1 degree/s; a full turn fits in 420 s
            self._run_leader_home(cmd, env, f"{arm} {label}")
        finally:
            release(handles)

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
