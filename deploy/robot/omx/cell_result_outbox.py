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
STALE_S = 65  # Fleet takes owner evidence for 60 s after measured_at; measured again only once that has surely passed
WAITING_FOR_PERSON = "BED_CONFIRMATION_INVALID"  # 422 on /complete: the bed confirmation lapsed; a named operator confirms again
WAITING_FOR_AMR = "AMR_BRAKE_BED_VELOCITY_UNMEASURED"  # 422 on /complete: AMR pose/stillness measurement lapsed; wait for measurement
# 422 codes of Fleet's 60 s evidence limit: the result is kept and measured again (no arm motion) once STALE_S has passed
RETRY_LATER = ("OMX_OWNER_EVIDENCE_UNAVAILABLE", "OWNER_EVIDENCE_MEASURED_AT_INVALID")
EVIDENCE_MAX_AGE_S = 60  # Fleet's limit on owner evidence


def refusal_code(exc: HTTPError) -> str:
    """The Fleet error code of a refused request (detail.code), else the HTTP reason text."""
    try:
        return str(json.loads(exc.read())["detail"]["code"])
    except Exception:
        return str(exc.msg)


def abort_reason(hw_tel: dict[str, Any]) -> str:
    """The receipt reason of an aborted run whose placement was not measured: held for review (the runner refused before any
    motion, D-911), preserve explicit fold/displaced failure codes, or fall back to generic missing measurement."""
    if hw_tel.get("review_required"):
        return "REVIEW_REQUIRED"
    err = hw_tel.get("error")
    if err in ("FOLD_READBACK_MISSING", "UNCALIBRATED_DISPLACED_SITE"):
        return str(err)
    return "MEASURED_PLACEMENT_MISSING"


def remeasurer(prep_dir: Path):
    """The re-measure callable for resend_pending (imported lazily: it pulls in the camera and zone code)."""
    def run(task_id: str, entry: dict[str, Any]):
        from cell_remeasure import remeasure

        return remeasure(task_id, entry, prep_dir)

    return run


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




def resend_pending(outbox: Outbox, request_fn: Callable[[str, str, dict[str, Any] | None], dict[str, Any]],
                   remeasure: Callable[[str, dict[str, Any]], tuple[dict[str, Any], dict[str, Any]]] | None = None,
                   now: float | None = None) -> list[dict[str, Any]]:
    """Resend every kept result whose task Fleet still shows RUNNING under the same lease. Returns what was done.

    While Fleet still holds the original owner evidence (60 s) only /complete is retried, with the same body; a 409
    OWNER_EVIDENCE_ALREADY_RECORDED on the evidence means it is already there. Only after it has expired (STALE_S) is the result
    measured again (no arm motion) and replaced. If that fails the entry stays with `last_refusal` and the task stays RUNNING for a
    person to clean up. A 422 BED_CONFIRMATION_INVALID keeps the entry with `last_refusal`: a named operator confirms the bed again.
    """
    import time

    now = time.time() if now is None else now
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
        measured = (entry.get("owner_evidence") or {}).get("measured_at")
        remeasured = False
        if remeasure is not None and isinstance(measured, (int, float)) and now - measured >= STALE_S:
            try:
                entry["owner_evidence"], entry["complete"] = remeasure(task_id, entry)
                entry.pop("last_refusal", None)
                entry["remeasured"] = True
                outbox.put(task_id, entry)
                remeasured = True
            except Exception as exc:  # RemeasureFailed or anything the cameras raise: say why, keep the task for a person
                entry["last_refusal"] = {"reason": f"{type(exc).__name__}: {exc}"[:200], "at": now}
                outbox.put(task_id, entry)
                done.append({"task_id": task_id, "action": "kept", "reason": "re-measurement failed"})
                continue
        if isinstance(measured, (int, float)) and EVIDENCE_MAX_AGE_S <= now - measured < STALE_S:
            done.append({"task_id": task_id, "action": "kept", "reason": "evidence expired, measured again at STALE_S"})
            continue  # Fleet would refuse it now and nothing is lost by waiting
        try:
            if entry.get("owner_evidence") is not None:
                try:
                    request_fn("POST", f"/api/fleet/pipeline/cell-tasks/{task_id}/owner-evidence", entry["owner_evidence"])
                except HTTPError as exc:
                    if exc.code != 409 or refusal_code(exc) != "OWNER_EVIDENCE_ALREADY_RECORDED":
                        raise  # a 409 is only "already recorded": the entry stays and /complete is retried below
                    if remeasured or entry.get("remeasured"):
                        entry["last_refusal"] = {"reason": "OWNER_EVIDENCE_ALREADY_RECORDED", "at": now}
                        outbox.put(task_id, entry)
                        done.append({"task_id": task_id, "action": "kept", "reason": "OWNER_EVIDENCE_ALREADY_RECORDED"})
                        continue
            request_fn("POST", f"/api/fleet/pipeline/cell-tasks/{task_id}/complete", entry["complete"])
        except HTTPError as exc:
            code = refusal_code(exc) if exc.code == 422 else None
            if code in (WAITING_FOR_PERSON, WAITING_FOR_AMR):
                entry["last_refusal"] = {"reason": code, "at": now}
                outbox.put(task_id, entry)
                done.append({"task_id": task_id, "action": "kept",
                             "reason": "waiting for a named operator to confirm the bed" if code == WAITING_FOR_PERSON
                             else "waiting for measured AMR pose/stillness"})
            elif code in RETRY_LATER:
                entry["last_refusal"] = {"reason": code, "at": now}
                outbox.put(task_id, entry)
                done.append({"task_id": task_id, "action": "kept", "reason": code})
            elif exc.code in DROP_CODES:
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
