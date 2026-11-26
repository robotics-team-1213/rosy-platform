"""Linked wait for the one-arm Leader recorder (W16): the Leader and Follower stay joined and the guard keeps running, nothing is recorded.

The bench starts the recorder with ROSY_LINK_DIR=<session folder>/link. Two small files carry the whole protocol (there is no other control path to the
recorder: next episode / re-record / stop used to be keyboard events or SIGTERM only):
  control.json  written by the bench, atomically: {"seq": n, "cmd": "record" | "next" | "rerecord" | "finish"}; seq grows with every request.
  state.json    written by the recorder, atomically: {"state": "aligning" | "waiting" | "recording" | "saving", "episode": n, "seq": last consumed, "t": time}.
"waiting" is the ready state: a record loop WITHOUT dataset (the pre-roll mechanism: same guard, same send_action, same pause watch around it) that ends
on a "record" command; on "finish", lerobot's stop event or IDLE_LIMIT_S without input it ends the session CLEANLY: the episode call returns without a frame and
sets stop_recording together with rerecord_episode, so lerobot clears the empty buffer instead of saving it, leaves its loop and finalizes the dataset (exit 0:
the bench then seals and homes as after any session; a SIGTERM would mark the session interrupted and unsealed). During an episode the same file carries
"next" (end the episode now = lerobot's right arrow) and "rerecord" (drop it and record again = the left arrow). /stop stays SIGTERM from the bench.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import time

ENV = "ROSY_LINK_DIR"
COMMANDS = ("record", "next", "rerecord", "finish")
IDLE_LIMIT_S = 180.0


class LinkChannel:
    def __init__(self, directory):
        self.dir, self.seq_seen, self._signature, self.episode, self.frames = Path(directory), 0, None, 0, 0
        self.last_state, self.episode_started, self.last_command, self.last_cmd_episode = None, None, None, None

    def poll(self):
        """The next command not yet seen (control.json changed and its seq is higher), else None. An unreadable or half-written file is read again next time."""
        path = self.dir / "control.json"
        try:
            stat = path.stat()
        except OSError:
            return None
        signature = (stat.st_mtime_ns, stat.st_size, stat.st_ino)  # the bench replaces the file atomically: a new inode every request
        if signature == self._signature:
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        self._signature = signature
        seq, cmd = data.get("seq") if isinstance(data, dict) else None, data.get("cmd") if isinstance(data, dict) else None
        if type(seq) is int and seq > self.seq_seen and cmd in COMMANDS:
            self.seq_seen = seq
            ep = data.get("episode") if isinstance(data, dict) else None
            self.last_cmd_episode = ep if type(ep) is int else None
            return cmd
        return None

    def note_command(self, cmd, applied, reason=None):
        self.last_command = {"seq": self.seq_seen, "cmd": cmd, "applied": bool(applied), **({"reason": reason} if reason else {})}

    def sync_state(self, state):
        if state != self.last_state:
            self.publish(state)

    def publish(self, state):
        self.dir.mkdir(parents=True, exist_ok=True)
        now = time.time()
        if state == "recording":
            if self.last_state != "recording" or self.episode_started is None:
                self.episode_started = now
        else:
            self.episode_started = None
        self.last_state = state
        tmp = self.dir / "state.json.tmp"
        payload = {"state": state, "episode": self.episode, "seq": self.seq_seen, "pid": os.getpid(), "t": now,
                   "episode_started": self.episode_started, "last_command": self.last_command}
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        os.replace(tmp, self.dir / "state.json")


class LinkEvents:
    """lerobot's events dict seen through the channel. waiting=True: exit_early is true once "record" arrived while aligned; False (an episode): "next" and
    "rerecord" set lerobot's own events. Everything else, and every write, goes to the real dict (stop_recording from the pause watch included)."""

    def __init__(self, events, channel, waiting, *, require_frame=False, is_ready=None):
        self.events, self.channel, self.waiting, self.started, self.finished = events, channel, waiting, False, False
        self.require_frame, self.pending_next, self.is_ready = require_frame, False, is_ready

    def _poll(self, *, final=False):
        cmd = self.channel.poll()
        if cmd is None:
            return
        if self.waiting:
            if cmd in ("record", "finish"):
                self.started, self.finished = self.started or cmd == "record", self.finished or cmd == "finish"
                self.channel.note_command(cmd, True)
            else:
                self.channel.note_command(cmd, False, f"에피소드가 이미 끝나 요청({cmd})이 적용되지 않았습니다")
                self.channel.publish(self.channel.last_state or "waiting")
            return
        ep = self.channel.last_cmd_episode
        if ep is not None and ep != self.channel.episode:
            self.channel.note_command(cmd, False, f"에피소드 번호 불일치(요청 {ep}, 현재 {self.channel.episode})로 적용되지 않았습니다")
            if not final:
                self.channel.publish(self.channel.last_state or "recording")
            return
        if cmd == "next":
            if not final:
                if self.require_frame and self.channel.frames == 0:
                    self.pending_next = True
                else:
                    self.events["exit_early"] = True
            self.channel.note_command(cmd, True)
        elif cmd == "rerecord":
            self.events["rerecord_episode"] = True
            if not final:
                self.events["exit_early"] = True
            self.channel.note_command(cmd, True)
        else:
            self.channel.note_command(cmd, False, f"녹화 중에는 {cmd} 요청을 적용할 수 없습니다")
            if not final:
                self.channel.publish(self.channel.last_state or "recording")

    def poll_final(self):
        self._poll(final=True)

    def __getitem__(self, key):
        if self.waiting:
            ready = True if self.is_ready is None else bool(self.is_ready())
            if self.is_ready is not None:
                self.channel.sync_state("waiting" if ready else "aligning")
            if ready:
                self._poll()
            return (self.started or self.finished or self.events[key]) if key == "exit_early" else self.events[key]
        self._poll()
        if self.pending_next and self.channel.frames > 0:
            self.pending_next = False
            self.events["exit_early"] = True
        return self.events[key]

    def __setitem__(self, key, value):
        self.events[key] = value
