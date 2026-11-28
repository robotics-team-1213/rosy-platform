"""Fleet cell-task motions on the arm cell: a free-position pick runs through the cell job API (:8781).

The worker is its own machine principal there ("cell-task-worker", own token file). It never sends operator, proposer,
reviewed_auto or person_at_switch, and never falls back to another token or URL (it passes both to the client itself, so
ROSY_CELL_JOB_TOKEN / ROSY_CELL_JOB_URL cannot override them; the URL is ROSY_CELL_JOB_WORKER_URL): the cell's Gate, contact/torque guards, finger room, depth
bounds, incident holds and stop proof (measured before --commissioning is added) stay the one place that decides.
A lost or timed-out job is asked once to stop (client.cancel: a park at its next guarded step, best effort, errors swallowed) and is still reported as CELL_JOB_LOST with its id.
A push (owner decision 2026-11-28) runs the same way and completes only on the job's own measured evidence (push_evidence_ok), never on its exit code. The push job is not cancellable (cell_push does not use Guarded.act): the cancel request is refused 409 and ignored.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import re
import time
from types import SimpleNamespace
from typing import Any

from cell_act_verdict import fold_readback, measured_fold, plan_home
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
    """-> (job, params) for the cell's `push` job (5..20 mm), run as cell-task-worker; completion needs the measured displacement (D-1083)."""
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


# Measured completion of a push. Mirrored by fleet.pipeline.cell_motion.push_completion_verified (a test pins both to the same numbers).
PUSH_ALONG_MIN_FRAC = 0.5  # the object must move along the commanded direction by at least this share of the commanded mm
PUSH_ALONG_MAX_EXTRA_MM = 3.0  # and by at most 1.5 x the commanded mm plus this (a drag far past the plan is not a clean push)
PUSH_LATERAL_MAX_MM = 6.0  # sideways drift beyond this is a failure
PUSH_EVIDENCE_KEYS = frozenset({"result", "site", "measured", "commanded_mm", "moved_mm", "along_dir_mm", "lateral_mm"})


def _finite(*values) -> bool:
    return all(type(v) in (int, float) and math.isfinite(v) for v in values)


def push_evidence_ok(motion: dict[str, Any], ev: Any) -> bool:
    """True only for the cell job's own measured displacement of the commanded push: exact shape, the commanded distance, along
    the direction by roughly that distance, little lateral drift, a self-consistent total. No boolean is trusted."""
    if not isinstance(ev, dict) or set(ev) != PUSH_EVIDENCE_KEYS or ev["result"] != "pushed" or ev["measured"] is not True:
        return False
    mm, moved, along, lateral = (ev[k] for k in ("commanded_mm", "moved_mm", "along_dir_mm", "lateral_mm"))
    if not _finite(mm, moved, along, lateral) or not isinstance(ev["site"], str) or not ev["site"] or mm != motion.get("mm") or lateral < 0:
        return False
    return (PUSH_ALONG_MIN_FRAC * mm <= along <= 1.5 * mm + PUSH_ALONG_MAX_EXTRA_MM and lateral <= PUSH_LATERAL_MAX_MM
            and abs(moved - math.hypot(along, lateral)) <= 0.5)


def run_push(handoff: dict[str, Any], motion: dict[str, Any], *, arm_id: str, cfg: Path, cfg_data: dict, cat: Path, roi, site: str,
             prep_dir: Path, client: CellJobClient | None = None) -> dict[str, Any]:
    """Run the push through the cell job API as cell-task-worker; -> the worker's result dict (stage_result, stop_event, error)."""
    stage = {"directive_id": handoff.get("task_id"), "arm_id": arm_id, "task_verified": False}
    refused = {"command": "stop", "ok": False, "folded": False}
    proc, refusal = run_job(handoff, *push_request({**motion, "site": site}, arm_id=arm_id, config=cfg.name, catalog=cat.name, roi=roi), client=client)
    if refusal:
        return {"arm": arm_id, "error": refusal, "stage_result": stage, "stop_event": refused}
    parsed = json.loads(proc.stdout)
    parsed = parsed if isinstance(parsed, dict) else {}
    measured_at = time.time()  # the readbacks below existed by now
    disp = parsed.get("displacement") if isinstance(parsed.get("displacement"), dict) else {}
    ev = {"result": parsed.get("result"), "site": parsed.get("site"), "measured": disp.get("measured"), "commanded_mm": disp.get("commanded_mm"),
          "moved_mm": disp.get("moved_mm"), "along_dir_mm": disp.get("along_dir_mm"), "lateral_mm": disp.get("lateral_mm")}
    verified = proc.returncode == 0 and push_evidence_ok(motion, ev)
    fold = fold_readback({"transfer": {"steps": [parsed.get("park") or {}]}}, plan_home(cfg_data))
    live = measured_fold(arm_id, prep_dir)
    folded = bool(verified and fold["folded"] and live["folded"])
    return {"arm": arm_id, "measured_at": measured_at, "events_count": 1,
            "stage_result": {"handoff_lease_id": handoff.get("handoff_lease_id"), "directive_id": handoff.get("task_id"), "arm_id": arm_id,
                             "task_verified": verified, "push": ev, "raw": parsed},
            "stop_event": {"command": "stop", "ok": folded, "folded": folded, "readback": fold, "live": live,
                           **({"state": fold["state"]} if fold["state"] else {})},
            "commissioning": False,
            **({"error": "PUSH_NOT_VERIFIED:" + str(parsed.get("result") or f"exit_{proc.returncode}")} if not verified else
               {} if folded else {"error": "FOLD_READBACK_MISSING"})}
