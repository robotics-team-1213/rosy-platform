"""D-1057: keep a finished cell task's result until Fleet has it, and resend the same result without moving the arm.

The arm ran and measured; if sending the owner evidence or `/complete` then fails (a 403 for an unregistered principal, a network
break), the task stays RUNNING in Fleet. The result is kept in a state file and resent on the next polls, but only while Fleet
shows the task RUNNING under the same lease. A changed lease, a finished task or a task Fleet no longer knows drops the entry:
that result belongs to a handoff that is over. Resending never runs the arm.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError

DROP_CODES = (409, 422)  # Fleet refused this exact body on its merits (another record, stale or invalid): not retried


def abort_reason(hw_tel: dict[str, Any]) -> str:
    """The receipt reason of an aborted run whose placement was not measured: held for review (the runner refused before any
    motion, D-911) or the generic missing measurement."""
    return "REVIEW_REQUIRED" if hw_tel.get("review_required") else "MEASURED_PLACEMENT_MISSING"


def result_bodies(handoff, phase, digest, receipt, stage_result, hw_tel) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """(owner-evidence body or None, /complete body). Fleet compares /complete with the stored owner record, so for a
    released task the first is sent first and both are kept together."""
    owner = ({"handoff_lease_id": handoff.get("handoff_lease_id"), "measured_at": hw_tel["measured_at"], "receipt": receipt,
              "stage_result": stage_result, "hardware_telemetry": hw_tel} if phase == "RELEASED" else None)
    return owner, {"phase": phase, "goal_evidence_digest": digest, "reason": receipt["reason"], "receipt": receipt,
                   "stage_result": stage_result, "hardware_telemetry": hw_tel}


class Outbox:
    def __init__(self, path: Path | None) -> None:
        self.path = None if path is None else Path(path)  # no path (no work directory): nothing is kept

    def _read(self) -> dict[str, Any]:
        if self.path is None:
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _write(self, data: dict[str, Any]) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, default=str), encoding="utf-8")
        os.replace(tmp, self.path)  # a crash leaves the old file or the new one, never half of one

    def put(self, task_id: str, entry: dict[str, Any]) -> None:
        data = self._read()
        data[task_id] = entry
        self._write(data)

    def drop(self, task_id: str) -> None:
        data = self._read()
        if data.pop(task_id, None) is not None:
            self._write(data)

    def items(self) -> dict[str, Any]:
        return self._read()


def resend_pending(outbox: Outbox, request_fn: Callable[[str, str, dict[str, Any] | None], dict[str, Any]]) -> list[dict[str, Any]]:
    """Resend every kept result whose task Fleet still shows RUNNING under the same lease. Returns what was done."""
    done: list[dict[str, Any]] = []
    entries = outbox.items()
    if not entries:
        return done
    try:
        running = {t.get("task_id"): t for t in (request_fn("GET", "/api/fleet/pipeline/cell-tasks?status=RUNNING", None) or {}).get("tasks") or []}
    except Exception:  # Fleet unreachable: keep everything for the next poll
        return done
    for task_id, entry in entries.items():
        task = running.get(task_id)
        if task is None or task.get("handoff_lease_id") != entry.get("lease"):
            outbox.drop(task_id)
            done.append({"task_id": task_id, "action": "dropped", "reason": "not RUNNING under the same lease"})
            continue
        try:
            if entry.get("owner_evidence") is not None:
                request_fn("POST", f"/api/fleet/pipeline/cell-tasks/{task_id}/owner-evidence", entry["owner_evidence"])
            request_fn("POST", f"/api/fleet/pipeline/cell-tasks/{task_id}/complete", entry["complete"])
        except HTTPError as exc:
            if exc.code in DROP_CODES:
                outbox.drop(task_id)
                done.append({"task_id": task_id, "action": "dropped", "reason": f"Fleet refused the result ({exc.code})"})
            else:  # 403 until the principal is registered, 5xx, ...: try again next poll
                done.append({"task_id": task_id, "action": "kept", "reason": f"HTTP {exc.code}"})
            continue
        except Exception as exc:  # network break
            done.append({"task_id": task_id, "action": "kept", "reason": type(exc).__name__})
            continue
        outbox.drop(task_id)
        done.append({"task_id": task_id, "action": "resent"})
    return done
