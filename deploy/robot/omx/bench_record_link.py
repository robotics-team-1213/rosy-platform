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

ENDED = ("sealed", "stopped_safe", "stopped_not_sealed", "unsafe_or_failed", "seal_failed", "failed", "leader_manual_check", "restoring", "sealing")
COMMAND_NEEDS = {"record": "waiting", "next": "recording", "rerecord": "recording", "finish": "waiting"}  # the recorder state each request is valid in
WHY = {"record": "연동됨(준비 완료) 상태에서만 녹화를 시작할 수 있습니다", "next": "녹화 중에만 에피소드를 끝낼 수 있습니다",
       "rerecord": "녹화 중에만 다시 녹화할 수 있습니다", "finish": "녹화 중이거나 저장 중에는 연동을 끝낼 수 없습니다 — 에피소드가 끝난 뒤 다시 시도하세요"}


class BenchLinkMixin:
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
