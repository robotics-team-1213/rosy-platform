"""The Fleet cell-task worker's own principal on the cell job API (owner decision 2026-11-27, amends D-911 section 2).

It is a machine principal with its own token, so the shared cell-job-machine token (AI bridge, Fleet proxy) gains no right.
auto_pick lists it in machine_ids (the D-1079 recover_hold precedent): the job still measures the stop proof and only then
adds --commissioning --person-at-switch. Beyond that, only the narrow free-position pick below is allowed.
"""
from __future__ import annotations

import hmac
import os
import sys
from pathlib import Path

WORKER_ID = "cell-task-worker"
TOKEN_ENV = "ROSY_CELL_JOB_WORKER_TOKEN_FILE"
ALLOWED_KEYS = frozenset({"arm", "config", "catalog", "roi", "source", "dest", "at_px", "map_only", "object", "colour", "verify_zones"})


def read_worker_token(*others: str | None) -> str | None:
    """The worker token, or None (feature off, fail closed) when the file is absent, empty, too short, open to others, or equals another token."""
    path = os.environ.get(TOKEN_ENV)
    if not path or not Path(path).expanduser().exists():
        return None
    from cell_job_guards import read_token_file  # late: cell_job_guards imports this module

    try:
        token = read_token_file(Path(path))
    except (SystemExit, OSError, ValueError) as exc:  # a bad worker file turns only this principal off; it must not stop the human path
        print(f"cell-task-worker principal off: {exc}", file=sys.stderr)
        return None
    if any(o and hmac.compare_digest(token.encode(), o.encode()) for o in others):
        print(f"cell-task-worker principal off: {path}: the worker token must differ from the human and machine tokens", file=sys.stderr)
        return None
    return token


def authenticate_worker(auth_header: str, worker_token: str | None):
    """Constant-time check; -> Principal(machine, WORKER_ID) or None."""
    from cell_job_guards import ROLE_MACHINE, Principal

    if worker_token and hmac.compare_digest((auth_header or "").encode(), f"Bearer {worker_token}".encode()):
        return Principal(ROLE_MACHINE, WORKER_ID)
    return None


def worker_scope_error(job_name: str, params: dict, principal) -> dict | None:
    """403 unless this principal asks for a free-position pick on the measured map alone, with exactly the keys it sends (a strict allowlist)."""
    if principal.principal_id != WORKER_ID:
        return None
    ok = (job_name == "auto_pick" and set(params) <= ALLOWED_KEYS and str(params.get("source", "")).startswith("free:")
          and params.get("map_only") is True and bool(params.get("at_px")) and params.get("verify_zones", True) is True)
    return None if ok else {"code": 403, "error_code": "WORKER_SCOPE_FORBIDDEN",
                            "error": "cell-task-worker may only start auto_pick from free:<site> with map_only, at_px and the keys it sends (verify_zones only true)"}
