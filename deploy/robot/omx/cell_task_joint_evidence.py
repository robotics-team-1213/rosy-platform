"""Durable owner command-boundary joint evidence for one supervised OMX attempt."""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re

import cell_attempts


class AttemptJointEvidence:
    def __init__(self, work: Path, task_id: str, run_id: str, lease_id: str, library_sha256: str,
                 *, session_id: str | None = None, owner_io: Path | None = None):
        self.path = work / "joints" / f"{run_id}.jsonl"
        self.owner_trace_path = self.path.with_name(f"{run_id}-owner-trace.jsonl")
        self.binding = {"task_id": task_id, "run_id": run_id,
                        "handoff_lease_id": lease_id, "library_sha256": library_sha256}
        self.session_id, self.owner_io = session_id, Path(owner_io).expanduser() if owner_io else None
        self.stream = None
        self.rows = 0
        self.trace_source, self.trace_end, self.trace_sequence = None, None, None
        self.trace_rows, self.pwm_proxy_rows, self.last_trace_t, self.trace_error = 0, 0, None, False

    def _append(self, row: dict) -> None:
        self.stream.write(json.dumps(row, allow_nan=False) + "\n")
        self.stream.flush()
        os.fsync(self.stream.fileno())  # after a command, never inside the owner's motion tick

    def start(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.owner_trace_path.exists():
            raise FileExistsError("owner trace artifact already exists")
        self.stream = self.path.open("x", encoding="utf-8")
        self._append({"schema": "rosy.omx-command-joints.v1", **self.binding,
                      "source": "owner_command_status", "coverage": "command_boundaries_only",
                      "continuous_trace": "UNKNOWN", "torque_nm": "UNKNOWN"})
        cell_attempts._fsync_directory(self.path.parent)
        return self

    def _segment(self, receipt: dict, command: str, reported_at, *, copy: bool) -> None:
        if not isinstance(receipt, dict) or receipt.get("status") != "ok":
            raise ValueError("owner trace receipt unavailable")
        source, start, end, sequence = (receipt.get(key) for key in ("source", "start", "end", "sequence"))
        if (self.owner_io is None or not isinstance(source, str)
                or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", source)
                or any(type(value) is not int for value in (start, end, sequence))
                or start < 0 or end < start or end - start > 1024 * 1024 or sequence < 1
                or receipt.get("command") != command or receipt.get("session_id") != self.session_id
                or receipt.get("library_sha256") != self.binding["library_sha256"]
                or receipt.get("reported_at") != reported_at):
            raise ValueError("owner trace receipt differs from bound command")
        root = self.owner_io.resolve().parent
        path = (root / source).resolve()
        if path.parent != root or not path.is_file():
            raise ValueError("owner trace source outside owner directory")
        if self.trace_source is None:
            if not command.startswith("load "):
                raise ValueError("owner trace has no load baseline")
        elif source != self.trace_source or start != self.trace_end or sequence != self.trace_sequence + 1:
            raise ValueError("owner trace segment discontinuity")
        with path.open("rb") as stream:
            stream.seek(start)
            data = stream.read(end - start)
        if len(data) != end - start or hashlib.sha256(data).hexdigest() != receipt.get("sha256"):
            raise ValueError("owner trace segment hash mismatch")
        if data and not data.endswith(b"\n"):
            raise ValueError("owner trace segment has partial row")
        rows = [json.loads(line) for line in data.splitlines()]
        for row in rows:
            present = row.get("present") if isinstance(row, dict) else None
            tick_t = row.get("t") if isinstance(row, dict) else None
            sent = row.get("sent") if isinstance(row, dict) else None
            pwm = row.get("pwm") if isinstance(row, dict) else None
            if ((copy and (row.get("owner_session_id") != self.session_id
                           or row.get("library_sha256") != self.binding["library_sha256"]))
                    or not isinstance(present, list) or len(present) != 6
                    or any(type(v) not in (int, float) or not math.isfinite(v) for v in present)
                    or type(tick_t) not in (int, float) or not math.isfinite(tick_t)
                    or (copy and self.last_trace_t is not None and tick_t < self.last_trace_t)
                    or (sent is not None and (not isinstance(sent, list) or len(sent) != 6
                        or any(type(v) not in (int, float) or not math.isfinite(v) for v in sent)))
                    or not isinstance(pwm, dict)
                    or any(type(v) not in (int, float) or not math.isfinite(v) for v in pwm.values())):
                raise ValueError("owner trace joint sample invalid")
            if copy:
                self.last_trace_t = tick_t
        if command.startswith("run ") and not any(isinstance(row.get("sent"), list)
                                                     and len(row["sent"]) == 6 for row in rows):
            raise ValueError("owner trace has no sent joint sample")
        if copy and data:
            created = self.trace_rows == 0
            with self.owner_trace_path.open("xb" if created else "ab") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            if created:
                cell_attempts._fsync_directory(self.owner_trace_path.parent)
            self.trace_rows += len(rows)
            self.pwm_proxy_rows += sum(bool(row.get("pwm")) for row in rows)
        self.trace_source, self.trace_end, self.trace_sequence = source, end, sequence

    def _owner_trace(self, command: str, status: dict) -> str:
        context = status.get("operating_context") or {}
        if context.get("session_id") != self.session_id:
            raise ValueError("owner trace session differs from attempt")
        owner_command = status.get("command", command)
        if owner_command not in (command, "run " + command):
            raise ValueError("owner trace command differs from reviewed command")
        if command.startswith("load "):
            self._segment(status.get("trace_receipt"), owner_command, status.get("t"), copy=False)
            return "baseline"
        pre = status.get("pre_state_trace")
        if not isinstance(pre, dict):
            raise ValueError("owner pre-command trace receipt unavailable")
        self._segment(pre.get("trace_receipt"), "state", pre.get("t"), copy=True)
        self._segment(status.get("trace_receipt"), owner_command, status.get("t"), copy=True)
        return "captured"

    def record(self, command: str, status: dict) -> bool:
        try:
            trace_status = self._owner_trace(command, status)
        except (OSError, TypeError, ValueError):
            self.trace_error = True
            raise
        state = status.get("state")
        valid = (isinstance(state, list) and len(state) == 6
                 and all(type(v) in (int, float) and math.isfinite(v) for v in state))
        health = status.get("health") if isinstance(status.get("health"), dict) else {}
        pwm = health.get("pwm") if isinstance(health.get("pwm"), list) else None
        try:
            self._append({**self.binding, "sequence": self.rows + 1, "command": command,
                          "status_time": status.get("t"), "state": state if valid else None,
                          "target": status.get("target"), "pwm_raw": pwm,
                          "current_ma_raw": health.get("current_ma"), "temp_c": health.get("temp_c"),
                          "health_freshness": "UNKNOWN", "joint_state_valid": valid,
                          "owner_ok": status.get("ok") is True, "owner_fault": status.get("fault"),
                          "owner_trace": trace_status})
        except (OSError, TypeError, ValueError):
            self.trace_error = True
            raise
        self.rows += 1
        return valid

    def stop(self) -> dict:
        if self.stream is not None:
            self.stream.close()
            self.stream = None
        captured = self.trace_source is not None and self.trace_rows > 0 and not self.trace_error
        return {"path": str(self.path), "sha256": hashlib.sha256(self.path.read_bytes()).hexdigest(),
                "rows": self.rows, "coverage": "command_boundaries_only",
                "continuous_trace": "captured" if captured else "UNKNOWN", "torque_nm": "UNKNOWN",
                **({"owner_trace_path": str(self.owner_trace_path),
                    "owner_trace_sha256": hashlib.sha256(self.owner_trace_path.read_bytes()).hexdigest(),
                    "owner_trace_rows": self.trace_rows, "pwm_proxy_rows": self.pwm_proxy_rows,
                    "trace_pwm_semantics": "motion_effort_pwm_proxy"} if captured else {}),
                "status": "stopped"}
