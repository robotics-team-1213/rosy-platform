"""Fleet cell-task motions on the arm cell: a free-position pick runs through the cell job API (:8781).

The worker is its own machine principal there ("cell-task-worker", own token file). It never sends operator, proposer,
reviewed_auto or person_at_switch, and never falls back to another token or URL (it passes both to the client itself, so
ROSY_CELL_JOB_TOKEN / ROSY_CELL_JOB_URL cannot override them; the URL is ROSY_CELL_JOB_WORKER_URL): the cell's Gate, contact/torque guards, finger room, depth
bounds, incident holds and stop proof (measured before --commissioning is added) stay the one place that decides.
A lost or timed-out job is asked once to stop (client.cancel: a park at its next guarded step, best effort, errors swallowed) and is still reported as CELL_JOB_LOST with its id. A push is mapped (push_request) but not run: see cell_task_exec.execute_guarded_cell_task.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
from types import SimpleNamespace
from typing import Any

from cell_job_client import CellJobClient, CellJobError

TOKEN_ENV = "ROSY_CELL_JOB_WORKER_TOKEN_FILE"
URL_ENV = "ROSY_CELL_JOB_WORKER_URL"  # worker-only; the shared ROSY_CELL_JOB_URL is never read
LOOPBACK_URL = "http://127.0.0.1:8781"  # default only: the live cell API listens on the host's tailnet address, so the unit sets the env var
WAIT_S = 330.0  # as long as the guarded pick's own subprocess limit plus the API's start-up
CANCEL_TIMEOUT_S = 5.0
_KEY_BAD = re.compile(r"[^A-Za-z0-9_.:-]")


def idempotency_key(handoff: dict[str, Any]) -> str:
    """Task id plus the claim's lease id. The lease id is deterministic per task (not new per claim), so a re-claim sends the same
    key and the cell answers with the earlier job (idempotent replay) instead of starting a second motion; a changed payload is a 409."""
    return _KEY_BAD.sub("_", f"fleet-{handoff.get('task_id')}-{handoff.get('handoff_lease_id')}")[:128]


def free_pick_request(motion: dict[str, Any], *, arm_id: str, config: str, catalog: str, roi, src: str, dst: str) -> tuple[str, dict]:
    """-> (job, params): auto_pick from `free:<anchor>` at the pixel, on the measured map alone (map_only)."""
    params = {"arm": arm_id, "config": config, "catalog": catalog, "roi": [int(v) for v in roi],
              "source": f"free:{src}", "dest": dst, "at_px": "{},{}".format(*motion["at_px"]), "map_only": True,
              "verify_zones": True,  # the API path has no --task-id: this records the zone_verification the measured completion needs
              **{k: motion[k] for k in ("object", "colour") if motion.get(k)}}
    return "auto_pick", params


def push_request(motion: dict[str, Any], *, arm_id: str, config: str, catalog: str, roi) -> tuple[str, dict]:
    """-> (job, params) for the cell's `push` job (5..20 mm). Mapped and tested; not run until push completion is defined."""
    (u, v), (dx, dy) = motion["px"], motion["dir"]
    return "push", {"arm": arm_id, "config": config, "site": motion["site"], "roi": [int(x) for x in roi], "catalog": catalog,
                    "px_x": u, "px_y": v, "dir_x": dx, "dir_y": dy, "mm": motion["mm"]}


def run_job(handoff: dict[str, Any], job: str, params: dict, *, client: CellJobClient | None = None,
            wait_s: float = WAIT_S) -> tuple[SimpleNamespace | None, str | None]:
    """-> (an object with .stdout/.returncode like the subprocess run it replaces, None) or (None, refusal code)."""
    if client is None:
        try:
            token = Path(os.environ[TOKEN_ENV]).read_text(encoding="utf-8").strip()
        except (KeyError, OSError, ValueError):  # ValueError: a non-UTF-8 file
            token = ""
        if not token:
            return None, "CELL_JOB_WORKER_TOKEN_MISSING"  # no fallback to the human or machine token
        client = CellJobClient(os.environ.get(URL_ENV, "").strip() or LOOPBACK_URL, token)
    jid = None
    try:
        jid = client.start(job, params, idempotency_key=idempotency_key(handoff))["id"]
        done = client.wait(jid, timeout_s=wait_s)
    except CellJobError as exc:
        return None, f"CELL_JOB_REFUSED:{exc.status_code}:{exc.detail}"[:200]
    except (OSError, TimeoutError, ValueError, KeyError) as exc:
        if jid:
            try:
                client.cancel(jid, timeout=CANCEL_TIMEOUT_S)
            except Exception:  # noqa: BLE001 - best effort: the job may be done, the link may be down
                pass
        return None, f"CELL_JOB_{'LOST' if jid else 'UNREACHABLE'}:{jid or ''}:{type(exc).__name__}"[:200]
    return SimpleNamespace(stdout=json.dumps(done.get("structured_result") or {}), returncode=done.get("exit")), None
