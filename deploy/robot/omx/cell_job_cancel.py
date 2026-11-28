"""Cooperative cancel of a running cell job (D-1081): the API writes a stop marker, the arm script honours it.

No signal and no kill: cell_auto_safety.Guarded.act reads the marker (env ROSY_CELL_JOB_STOP_FILE) before each guarded
command and takes its existing park-and-abort path with torque ON. It is not an emergency stop: the job stops at its next
guarded step, after an in-flight chunk has finished.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from cell_job_guards import ROLE_HUMAN

STOP_FILE_ENV = "ROSY_CELL_JOB_STOP_FILE"  # same string as cell_auto_safety.STOP_FILE_ENV (that module needs numpy, this one must not)


def stop_file(out: Path, jid: str, job: dict, moving: bool) -> Path | None:
    """The marker path for a job whose script honours it (job spec "cancellable") and that moves an arm; else None."""
    return out / f"stop-{jid}" if moving and job.get("cancellable") else None


def clear(run: dict) -> None:
    """Remove the marker when the job is reaped."""
    if run.get("stop_file"):
        try:
            Path(run["stop_file"]).unlink(missing_ok=True)
        except OSError:
            pass


def cancel(runner, jid: str, principal) -> dict:
    """The human principal, or the principal that started the job, may request the stop; idempotent; audited once."""
    with runner.lock:
        run = runner.runs.get(jid)
        if run is None:
            return {"code": 404, "error": f"no job {jid}"}
        if principal.role != ROLE_HUMAN and (principal.role, principal.principal_id) != (run["principal_role"], run["principal_id"]):
            return {"code": 403, "error_code": "CANCEL_FORBIDDEN", "error": "only the human principal or the principal that started the job may cancel it"}
        code = run["proc"].poll()
        if code is not None:
            runner._audit_locked(jid, run, code)  # a finished job: its state, nothing written
        elif not run.get("stop_file"):
            return {"code": 409, "error_code": "JOB_NOT_CANCELLABLE", "error": f"job {run['job']} has no cooperative stop"}
        elif not Path(run["stop_file"]).exists():
            try:
                Path(run["stop_file"]).write_text(f"{principal.role}:{principal.principal_id}\n", encoding="utf-8")
            except OSError as exc:
                return {"code": 500, "error_code": "CANCEL_MARKER_WRITE_FAILED", "error": type(exc).__name__}
            with open(runner.out / "audit.jsonl", "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"event": "cancel_requested", "id": jid, "job": run["job"], "principal_role": principal.role,
                                     "principal_id": principal.principal_id, "at": time.time()}) + "\n")
    return {**runner.get(jid, 0), "code": 200, "cancel_requested": code is None}
