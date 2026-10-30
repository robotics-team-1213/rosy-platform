"""Native cell FIFO/camera transport and stage receipts; never opens the actuator bus."""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np


def case(work: Path, row: dict) -> None:
    """One line per check that did not simply pass, and the outcome that followed: new failure cases to fix
    and turn into tests, and the decision model's training data (it learns before any VLA, D-872)."""
    work.mkdir(parents=True, exist_ok=True)
    with (work / "cases.jsonl").open("a") as f:
        f.write(json.dumps({"t": round(time.time(), 3), **row}, default=str) + "\n")


def write_library(config: dict, pick: dict, place: dict, path: Path) -> Path:
    from grasp_planner import Planner

    library = Planner(dict(config["plan"], pick=pick, place=place, keep_out=config.get("keep_out"))).library()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({k: v for k, v in library.items() if v is not None}))
    return path


class FifoCell:
    """The running chunk_runner (command FIFO + status file) and the read-only camera viewer."""

    def __init__(self, io: Path, cameras: dict, timeout_s: float = 300, *, operating_profile=None):
        self.io, self.cameras, self.timeout_s = io, cameras, timeout_s
        self.operating_profile = operating_profile

    def checked(self, command: str, assessment: dict) -> dict:
        return self.act(f"checked {assessment['session_id']} {assessment['library_sha256']} {command}")

    def act(self, command: str) -> dict:
        if self.operating_profile is not None and command not in ("state", "stop") and not command.startswith("checked "):
            from cell_envelope import _state_current, digest

            state = self.act("state")
            context = state.get("operating_context") or {}
            if not _state_current(state, time.time()) or context.get("operating_profile") != self.operating_profile:
                return {"ok": False, "fault": "profile_mismatch", "error": "live follower differs from selected profile"}
            try:
                revision = (digest(json.loads(Path(command.split(" ", 1)[1]).read_text()))
                            if command.startswith("load ") else state["library_sha256"])
            except (OSError, ValueError, KeyError):
                return {"ok": False, "fault": "profile_library_unavailable", "error": "cannot bind this command library"}
            command = f"checked {context['session_id']} {revision} {command}"
        expected = command.split(" ", 3)[-1] if command.startswith("checked ") else command
        status_path = self.io / "chunk-status.jsonl"
        start = status_path.stat().st_size if status_path.exists() else 0
        try:  # non-blocking: never hand a command to a later runner
            fd = os.open(self.io / "chunk-cmd", os.O_WRONLY | os.O_NONBLOCK)
        except OSError:
            return {"ok": False, "error": "chunk_runner is not running", "fault": "no runner"}
        os.write(fd, (command + "\n").encode())
        os.close(fd)
        deadline = time.monotonic() + self.timeout_s
        while time.monotonic() < deadline:
            with status_path.open() as stream:
                stream.seek(start)
                for line in stream:
                    row = json.loads(line)
                    if row.get("command") in (expected, "run " + expected) or row.get("fault"):
                        return row
            time.sleep(0.1)
        return {"ok": False, "error": f"no status within {self.timeout_s} s"}

    def frame(self, camera: str):
        import urllib.request

        import cv2

        with urllib.request.urlopen(self.cameras[camera]["url"], timeout=10) as reply:
            return cv2.imdecode(np.frombuffer(reply.read(), np.uint8), cv2.IMREAD_COLOR)


def write_receipt(directory: Path, stage: str, payload: dict) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{stage}.json"
    path.write_text(json.dumps({"stage": stage, **payload}, indent=1, default=str))
    return path
