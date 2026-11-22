#!/usr/bin/env python3
"""Prepare / record / finish for bench_record.py (W16): the recorder joins Leader and Follower first ("prepare"), then records episodes on request.

Phases shown to the page (status.json "phase"): setup (nothing moves) -> prepare (home, Leader alignment, recorder start, guard alignment; "ready" once the
recorder waits linked, again after every saved episode) -> recording (an episode is being recorded) -> result (finished: restore, seal, upload). The wire to the
recorder is the two files of guarded_native_link (control.json / state.json in <session folder>/link). /start stays the one-shot "prepare and record at once".
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from teleop_speed import valid as valid_teleop_stage

ENDED = ("sealed", "stopped_safe", "stopped_not_sealed", "unsafe_or_failed", "seal_failed", "failed", "leader_manual_check", "restoring", "sealing")
COMMAND_NEEDS = {"record": "waiting", "next": "recording", "rerecord": "recording", "finish": "waiting"}  # the recorder state each request is valid in
WHY = {"record": "연동됨(준비 완료) 상태에서만 녹화를 시작할 수 있습니다", "next": "녹화 중에만 에피소드를 끝낼 수 있습니다",
       "rerecord": "녹화 중에만 다시 녹화할 수 있습니다", "finish": "녹화 중이거나 저장 중에는 연동을 끝낼 수 없습니다 — 에피소드가 끝난 뒤 다시 시도하세요"}


def _leader_mount_path(arm):
    base = Path.home() / ".cache" / "huggingface" / "lerobot" / "calibration" / "teleoperators" / "omx_leader"
    cal = base / f"{arm}_leader.json"
    if arm == "arm_a" and not cal.is_file() and (base / "omx_leader_arm.json").is_file():
        cal = base / "omx_leader_arm.json"
    return cal.with_suffix(".mount.json")


class BenchLinkMixin:
    def _pre_start_home(self, body, replay_path=None):
        """Move a single follower arm home before leader alignment/start when home_before_start is requested."""
        flag = body.get("home_before_start")
        if flag is None or flag is False:
            return False
        if flag is not True:
            raise ValueError("home_before_start는 true 또는 false여야 합니다")
        if body.get("arm") == "arm_ab" or replay_path:
            raise ValueError("시작 전 홈 이동(home_before_start)은 replay 없는 단일 팔 리더 세션만 지원합니다")
        req = {"arm": body["arm"], "include_leader": False}
        if body.get("fold_unfolded") is True:
            req["fold_unfolded"] = True
        self.go_home(req)
        with self.lock:
            if self.abort:
                raise ValueError("정지 요청이 있어 녹화를 시작하지 않습니다")
        return True

    def set_teleop_speed(self, body):
        """Declare the teleop speed stage (None or 30/45/60/90/120 deg/s) for a single arm while idle."""
        if not isinstance(body, dict) or body.get("arm") not in ("arm_a", "arm_b", "arm_s"):
            raise ValueError("속도 단계는 단일 팔(arm_a, arm_b, arm_s)만 설정할 수 있습니다")
        arm, raw_stage = body["arm"], body.get("stage")
        if raw_stage is not None and valid_teleop_stage(raw_stage) is None:
            raise ValueError("지원하지 않는 추종 속도 단계입니다 (기본 null 또는 30, 45, 60, 90, 120, 180, 240)")
        with self.lock:
            if self.state.get("status") in ("handing_over", "homing", "recording", "restoring", "sealing"):
                raise ValueError("세션이나 홈 이동이 진행 중일 때는 속도 단계를 바꿀 수 없습니다")
            path = self.prep / f"teleop-speed-{arm}.json"
            if raw_stage is None:
                path.unlink(missing_ok=True)
            else:
                tmp = path.with_suffix(".json.tmp")
                tmp.write_text(json.dumps({"stage": raw_stage}) + "\n", encoding="utf-8")
                os.replace(tmp, path)
        return self.status()

    def grip_maps(self):
        """Read commissioned gripper mount calibration maps for all single arms."""
        arms = {}
        for arm in ("arm_a", "arm_b", "arm_s"):
            mp = _leader_mount_path(arm)
            grip = None
            if mp.is_file() and not mp.is_symlink():
                try:
                    data = json.loads(mp.read_text(encoding="utf-8"))
                    if isinstance(data, dict) and isinstance(data.get("gripper"), dict):
                        grip = data["gripper"]
                except (OSError, ValueError):
                    pass
            arms[arm] = {"mount_path": str(mp), "exists": mp.is_file(), "gripper": grip}
        return {"arms": arms}

    def save_grip_map(self, body):
        """Update the four gripper endpoints in <leader>.mount.json while preserving mount and floor keys."""
        if not isinstance(body, dict) or body.get("arm") not in ("arm_a", "arm_b", "arm_s"):
            raise ValueError("집게 매핑은 단일 팔(arm_a, arm_b, arm_s)만 저장할 수 있습니다")
        arm = body["arm"]
        clean = {}
        for key in ("leader_closed", "leader_open", "follower_closed", "follower_open"):
            val = body.get(key)
            if isinstance(val, bool) or not isinstance(val, int) or not (0 <= val <= 4095):
                raise ValueError(f"{key} 값은 0~4095 정수여야 합니다")
            clean[key] = val
        if clean["leader_open"] == clean["leader_closed"]:
            raise ValueError("leader_open과 leader_closed는 같을 수 없습니다")
        span = abs(clean["follower_open"] - clean["follower_closed"])
        if span == 0 or span >= 100 * 4096 / 360:
            raise ValueError("팔로워 집게 폭(follower_open - follower_closed)은 1~1137틱(100° 미만)이어야 합니다")
        with self.lock:
            if self.state.get("status") in ("handing_over", "homing", "recording", "restoring", "sealing", "leader_manual_check"):
                raise ValueError("세션이나 홈 이동이 진행 중일 때는 집게 매핑을 바꿀 수 없습니다")
            mp = _leader_mount_path(arm)
            if mp.is_symlink() or mp.parent.is_symlink():
                raise ValueError("심볼릭 링크 mount 파일은 수정할 수 없습니다")
            mp.parent.mkdir(parents=True, exist_ok=True)
            data = {}
            if mp.is_file():
                raw = json.loads(mp.read_text(encoding="utf-8"))
                if not isinstance(raw, dict):
                    raise ValueError(f"손상된 mount 파일: {mp.name}")
                data = raw
            data["gripper"] = clean
            tmp = mp.with_name(mp.name + ".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False) + "\n", encoding="utf-8")
            os.replace(tmp, mp)
        return {"saved": arm, "gripper": clean, **self.grip_maps()}

    def prepare(self, body):
        """Start a linked session: everything /start does up to the guard alignment, then wait ready; nothing is recorded."""
        if body.get("arm") == "arm_ab" or body.get("replay"):
            raise ValueError("연동 준비(/prepare)는 단일 팔 리더 세션만 지원합니다")
        return self.start(dict(body, link_only=True))

    def _link_state(self, state=None):
        """The recorder's own state file of the running linked session (None: not linked, or the recorder has not written it yet)."""
        state = self.state if state is None else state
        if not state.get("link") or not state.get("folder"):
            return None
        try:
            data = json.loads((Path(state["folder"]) / "link" / "state.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    def _link_command(self, cmd, body=None):
        with self.lock:
            state = dict(self.state)
            if state.get("status") != "recording" or not state.get("link") or self.abort:
                raise ValueError("연동 세션이 준비되어 있지 않습니다")
            if isinstance(body, dict) and body.get("arm") and body["arm"] != state.get("arm"):
                raise ValueError(f"진행 중인 연동 세션은 {state.get('arm')}입니다 ({body['arm']} 아님)")
            link = self._link_state(state) or {}
            if link.get("state") != COMMAND_NEEDS[cmd]:
                raise ValueError(WHY[cmd])
            pending = getattr(self, "_link_pending", None)
            if pending is not None and pending[0] == state.get("folder") and isinstance(link.get("seq"), int) and link["seq"] < pending[1]:
                raise ValueError("이전 요청이 아직 처리 중입니다")
            seq = self._link_seq = getattr(self, "_link_seq", 0) + 1  # only a request that is valid takes a number
            self._link_pending = (state.get("folder"), seq)
            directory = Path(state["folder"]) / "link"
            directory.mkdir(parents=True, exist_ok=True)
            tmp = directory / "control.json.tmp"
            payload = {"seq": seq, "cmd": cmd}
            if cmd in ("next", "rerecord") and isinstance(link.get("episode"), int):
                payload["episode"] = link["episode"]
            tmp.write_text(json.dumps(payload), encoding="utf-8")
            os.replace(tmp, directory / "control.json")  # atomic: the recorder never reads half a request
        return self.status()

    def record_episode(self, body=None):
        return self._link_command("record", body)

    def episode_next(self, body=None):
        return self._link_command("next", body)

    def episode_rerecord(self, body=None):
        return self._link_command("rerecord", body)

    def finish(self, body=None):
        """End the link (the page's finish): the recorder leaves its wait and ends cleanly through lerobot's own exit, then restore, seal and the automatic home
        follow as for any session end. Unlike /stop it cancels nothing. Only from the ready state: an episode being recorded or saved is not cut off."""
        return self._link_command("finish", body)

    def link_fields(self, out):
        """phase (setup | prepare | recording | result), prepare {ready, step, link_state, episode} and link for the page."""
        status, link = out.get("status"), self._link_state(out)
        last_cmd = (link or {}).get("last_command")
        extra = {"link_last_command": last_cmd} if isinstance(last_cmd, dict) else {}
        if status in ENDED:
            return {"phase": "result", "prepare": None, "link": bool(out.get("link")), **extra}
        if status in ("handing_over", "homing") or (status == "recording" and out.get("link") and (link or {}).get("state") != "recording"):
            waiting = (link or {}).get("state") == "waiting"
            step = None if waiting else (out.get("starting_step") or (link or {}).get("state"))  # ready: no step left
            return {"phase": "prepare", "link": bool(out.get("link")), **extra,
                    "prepare": {"ready": waiting, "step": step, "link_state": (link or {}).get("state"), "episode": (link or {}).get("episode", 0)}}
        if status == "recording":
            ep_started = (link or {}).get("episode_started") if out.get("link") else None
            if isinstance(ep_started, (int, float)):
                extra["episode_elapsed_s"] = round(max(0.0, self.clock() - ep_started), 1)
            return {"phase": "recording", "prepare": None, "link": bool(out.get("link")), **extra}
        return {"phase": "setup", "prepare": None, "link": False}
