"""After a real arm_s cell_policy_drive that took one item, ask Fleet R to send the Pinky out (user decision 2026-11-26).

The arm result is never changed: every outcome is returned as a dict for structured_result and audit.jsonl.
Fleet credentials are the cell job API's own --fleet-r-url / --fleet-token-file / --ca-file (same as the safety check).
"""
from __future__ import annotations

import json
import ssl
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from cell_act_verdict import SUCCESS_RESULTS, act_verdict, fold_readback, measured_fold, plan_home, unverified_reason
from cell_job_readiness import parse_structured_result
from cell_policy_entry import FAULT_KEYS

DEPART_PATH = "/api/fleet/pipeline/pinky-tasks"
DEPART_ACTIONS = ("depart_s1",)

def measured_verdict(workdir: Path, params: dict, exit_code: int | None, result: dict) -> dict:
    """The same act_verdict as task_verified: measured live fold, park readback and the destination zone_acceptance (D-1057)."""
    cfg = json.loads((workdir / params["config"]).read_text(encoding="utf-8"))
    handoff = {"cell_id": "cell_s", "tier": params.get("dest_tier"), "src_site": params.get("site")}
    return act_verdict(result, exit_code, handoff, params.get("dest_site") or "", fold_readback_fn=fold_readback,
                       home=plan_home(cfg), live_fold=measured_fold(params["arm"], workdir))


def depart_skip_reason(job: str, params: dict, exit_code: int | None, result: dict | None, verdict: dict | None = None) -> str | None:
    """Why no depart command is sent, or None when the arm really took one item and the shared verdict is verified."""
    if job != "cell_policy_drive" or not params.get("depart_robot"):
        return "depart not requested"
    if params.get("arm") != "arm_s":
        return "depart only for arm_s"
    if params.get("dry_run") is True:
        return "dry_run: arm did not move"
    if exit_code != 0:
        return f"job exit {exit_code}"
    if not isinstance(result, dict):
        return "no structured result"
    if result.get("took_one") is not True:
        return str(result.get("reason") or "took_one not true")
    if result.get("result") not in SUCCESS_RESULTS:
        return f"arm result {result.get('result')!r} is not a success"
    if bad := [k for k in (*FAULT_KEYS, "torque_hold_commanded") if result.get(k)]:
        return f"arm hold/fault/torque hold: {', '.join(bad)}"
    if verdict is None:
        return "measured fold / zone_acceptance not evaluated"
    return unverified_reason(verdict)  # the same judgement as task_verified; Fleet's 409 is not relied on


def post_depart(robot_id: str, action: str, task_id: str, *, fleet_r_url: str | None,
                token_file: Path | None, ca_file: Path | None = None, timeout_s: float = 10.0, urlopen_fn=urlopen) -> dict:
    """POST one pinky-task; never raises. task_id makes a repeat of the same job a 409, not a second departure."""
    out: dict = {"sent": False, "robot_id": robot_id, "action": action, "task_id": task_id}
    if not fleet_r_url or not token_file:
        return out | {"reason": "Fleet R url/token not configured"}
    base = fleet_r_url.rstrip("/")
    parsed = urlsplit(base)
    tpath = Path(token_file).expanduser()
    if parsed.scheme != "https" or not parsed.hostname or not tpath.is_file():
        return out | {"reason": "invalid Fleet HTTPS URL or missing token file"}
    try:
        ctx = ssl.create_default_context(cafile=str(Path(ca_file).expanduser()) if ca_file else None)
        req = Request(
            base + DEPART_PATH, method="POST",
            data=json.dumps({"robot_id": robot_id, "action": action, "task_id": task_id}).encode(),
            headers={"Authorization": "Bearer " + tpath.read_text(encoding="utf-8").strip(),
                     "Content-Type": "application/json", "Origin": base},
        )
        with urlopen_fn(req, context=ctx, timeout=timeout_s) as resp:
            return out | {"sent": True, "accepted": True, "http_status": resp.status,
                          "fleet_response": resp.read(2000).decode("utf-8", "replace")}
    except HTTPError as exc:  # Fleet refused: 403 role, 409 HUMAN_HOLD_ACTIVE / id in use, ...
        try:
            body = exc.read(2000).decode("utf-8", "replace")
        except OSError:
            body = str(exc)
        return out | {"sent": True, "accepted": False, "http_status": exc.code, "reason": body}
    except Exception as exc:  # never raise: the arm result stays as it is
        return out | {"reason": f"Fleet request failed: {exc}"}


def with_depart(result: dict | None, depart: dict | None) -> dict | None:
    return result if depart is None else {**(result or {}), "depart": depart}


def depart_once(runner, jid: str, run: dict) -> dict | None:
    """Decide and send once per run (run["depart"], run["depart_lock"]); every failure is recorded, never raised."""
    if not run["params"].get("depart_robot"):
        return None
    with run["depart_lock"]:
        if run["depart"] is None:
            params = run["params"]
            robot, action = params["depart_robot"], params.get("depart_action", "depart_s1")
            try:
                result = parse_structured_result(run["log"])[0]
                code = run["proc"].poll()
                verdict, err = None, ""
                try:
                    verdict = measured_verdict(runner.workdir, params, code, result) if isinstance(result, dict) else None
                except Exception as exc:  # unreadable config or telemetry: no measured proof, no depart
                    err = f": {exc}"
                why = depart_skip_reason(run["job"], params, code, result, verdict)
                why = why + err if why and verdict is None else why
                run["depart"] = {"sent": False, "robot_id": robot, "action": action, "reason": why} if why else post_depart(
                    robot, action, f"depart-{jid}", fleet_r_url=runner._fleet_r_url, token_file=runner._fleet_token_file, ca_file=runner._ca_file)
                with runner.lock, open(runner.out / "audit.jsonl", "a", encoding="utf-8") as fh:
                    fh.write(json.dumps({"id": jid, "event": "depart", "job": run["job"], "time": time.time(), **run["depart"]}) + "\n")
            except Exception as exc:  # Fleet or audit trouble must not change the job or its audit
                run["depart"] = run["depart"] or {"sent": False, "reason": f"depart error: {exc}"}
        return run["depart"]
