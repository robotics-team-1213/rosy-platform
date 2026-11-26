"""Fleet proxy to an arm cell's job API (:8781) for the ARM-CELL run/recover panel.

Only three POST jobs and three reads pass. The job API keeps every guard (session locks, incident holds, peer fold,
Fleet safety stop, D-1024 proposer check); Fleet adds the named operator as `operator` (an Account person's login,
never the opaque Account ID), refuses a proposer equal to that name, display name or ID, and returns the job API's refusal status and body unchanged. Cell URL, token file, per-arm files and the
model list come from the JSON file named by ROSY_FLEET_CELL_JOBS on the Fleet host, never from the browser.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from fastapi import Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt

from fleet.server.account_receiver import COOKIE as ACCOUNT_COOKIE

CONFIG_ENV = "ROSY_FLEET_CELL_JOBS"
POST_JOBS = ("cell_policy_drive", "recover_hold", "safe_home")
_JOB_ID = re.compile(r"[\w-]{1,64}")
# Run settings a model needs on the cell (backend, calibration, goal, step budget); host config only, never the browser.
MODEL_PARAMS = ("act_backend", "endpoint_url", "token_file", "model_calibration", "cell_calibration", "goal_slot",
                "goal_site", "n_action", "max_obs_age_s")
_ARM_FILES = {"cell_policy_drive": ("config", "library"), "recover_hold": ("config", "library", "site", "roi"),
              "safe_home": ("config", "library", "site", "roi")}


class CellJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    arm: str = Field(min_length=1, max_length=16)
    proposer: str = Field(min_length=1, max_length=64)
    mode: str | None = Field(default=None, pattern=r"^(act|hybrid|taught)$")
    model: str | None = Field(default=None, max_length=64)
    max_chunks: StrictInt | None = Field(default=None, ge=1, le=60)
    paced_chunks: StrictBool | None = None
    dry_run: StrictBool | None = None


def load_config(environ=os.environ) -> dict:
    """{"cells": {cell: {url, token_file, arms: {arm: {config, library, site, roi}}, models: [{id, label,
    policy_root, policy_revision}]}}}; no file configured means no cell."""
    path = environ.get(CONFIG_ENV)
    if not path:
        return {}
    cells = json.loads(Path(path).read_text(encoding="utf-8")).get("cells") or {}
    return cells if isinstance(cells, dict) else {}


def http_request(method: str, url: str, token: str, body: dict | None = None, timeout: float = 10.0):
    """(status, json body); an HTTP refusal returns its own status and body."""
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Authorization": f"Bearer {token}", **({"Content-Type": "application/json"} if data else {})}
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            return exc.code, json.loads(raw)
        except ValueError:
            return exc.code, {"error": raw[:400]}


def _reply(status: int, body) -> JSONResponse:
    """The job API's body unchanged; a refusal also gets Fleet's detail shape so the console client reads it."""
    if status >= 400 and isinstance(body, dict):
        body = {**body, "detail": {"code": body.get("error_code") or f"CELL_JOB_API_{status}",
                                   "message": str(body.get("error") or f"HTTP {status}")}}
    return JSONResponse(status_code=status, content=body)


def _refuse(status: int, code: str, message: str) -> JSONResponse:
    return _reply(status, {"error_code": code, "error": message})


class CellJobProxy:
    def __init__(self, cells: dict, request_fn=http_request):
        self.cells, self.request_fn = cells, request_fn

    def _send(self, cell: str, method: str, path: str, body: dict | None = None) -> JSONResponse:
        conf = self.cells.get(cell)
        if not isinstance(conf, dict) or not conf.get("url"):
            return _refuse(404, "CELL_JOBS_NOT_CONFIGURED", f"no cell job API configured for {cell}")
        try:
            token = Path(conf["token_file"]).read_text(encoding="utf-8").strip()
            status, out = self.request_fn(method, str(conf["url"]).rstrip("/") + path, token, body)
        except (OSError, KeyError, ValueError) as exc:
            return _refuse(502, "CELL_JOB_API_UNREACHABLE", f"cell job API unreachable: {type(exc).__name__}")
        return _reply(status, out)

    def options(self, cell: str):
        conf = self.cells.get(cell)
        if not isinstance(conf, dict):
            return _refuse(404, "CELL_JOBS_NOT_CONFIGURED", f"no cell job API configured for {cell}")
        models = [{k: m.get(k) for k in ("id", "label", "policy_revision")}
                  for m in conf.get("models") or () if isinstance(m, dict) and m.get("id")]
        return {"cell": cell, "arms": sorted((conf.get("arms") or {})), "models": models}

    def start(self, cell: str, job: str, req: CellJobRequest, operator: str, aliases: tuple = ()) -> JSONResponse:
        if job not in POST_JOBS:
            return _refuse(404, "CELL_JOB_NOT_ALLOWED", f"{job} is not a Fleet cell job")
        if _fold(req.proposer) in {_fold(name) for name in (operator, *aliases) if name}:
            return _refuse(400, "PROPOSER_IS_OPERATOR", "operator must differ from proposer (D-1024)")
        conf = self.cells.get(cell) if isinstance(self.cells.get(cell), dict) else {}
        arm_files = (conf.get("arms") or {}).get(req.arm)
        if not isinstance(arm_files, dict):
            return _refuse(400, "ARM_NOT_CONFIGURED", f"{req.arm} is not configured for {cell}")
        params = {"arm": req.arm, "operator": operator, "proposer": req.proposer.strip()}
        params.update({k: arm_files[k] for k in _ARM_FILES[job] if k in arm_files})
        if job == "cell_policy_drive":
            params["max_chunks"] = req.max_chunks or 1
            params["dry_run"] = True if req.dry_run is None else req.dry_run
            if req.mode:
                params["mode"] = req.mode
            if req.paced_chunks is not None:
                params["paced_chunks"] = req.paced_chunks
            if req.model:
                model = next((m for m in conf.get("models") or () if isinstance(m, dict) and m.get("id") == req.model), None)
                if model is None:
                    return _refuse(400, "MODEL_NOT_CONFIGURED", f"model {req.model} is not in the Fleet list")
                params.update({k: model[k] for k in ("policy_root", "policy_revision") if model.get(k)})
                params.update({k: v for k, v in (model.get("params") or {}).items() if k in MODEL_PARAMS})
        return self._send(cell, "POST", f"/jobs/{job}", params)


def _fold(name: str) -> str:
    return "".join(name.split()).casefold()


def operator_identity(request, principal) -> tuple[str, tuple] | None:
    """(name sent as operator, other names the proposer must not equal); None when an Account person has no readable login.

    A site-users or password-login principal_id is the configured operator name. An Account principal_id is an opaque
    ID (2026-11-27: proposer "agent-operator" passed D-1024 against it), so the login comes from Account userinfo.
    """
    if not principal.account_id:
        return principal.principal_id, ()
    client = getattr(request.app.state, "account_client", None)
    cookie = request.cookies.get(ACCOUNT_COOKIE)
    profile = client.profile(cookie) if client is not None and cookie else None
    if not profile or not profile.get("login"):
        return None
    return profile["login"], (profile.get("display_name") or "", principal.principal_id)


def install_cell_job_proxy_routes(app, *, require_viewer, require_named_operator, environ=os.environ):
    app.state.cell_job_proxy = CellJobProxy(load_config(environ))
    base = "/api/fleet/cells/{cell}/jobs"

    def proxy() -> CellJobProxy:
        return app.state.cell_job_proxy

    @app.get(base + "/options", tags=["fleet"])
    def cell_job_options(cell: str, principal=Depends(require_viewer)):
        return proxy().options(cell)

    @app.get(base + "/readiness", tags=["fleet"])
    def cell_job_readiness(cell: str, principal=Depends(require_viewer)):
        return proxy()._send(cell, "GET", "/readiness?" + urllib.parse.urlencode({"cell": cell}))

    @app.get(base + "/queue", tags=["fleet"])
    def cell_job_queue(cell: str, principal=Depends(require_viewer)):
        return proxy()._send(cell, "GET", "/queue")

    @app.get(base + "/{job_id}", tags=["fleet"])
    def cell_job_status(cell: str, job_id: str, principal=Depends(require_viewer)):
        if not _JOB_ID.fullmatch(job_id):
            return _refuse(400, "INVALID_JOB_ID", "invalid job id")
        return proxy()._send(cell, "GET", f"/jobs/{job_id}")

    @app.post(base + "/{job}", tags=["fleet"])
    def cell_job_start(cell: str, job: str, body: CellJobRequest, request: Request,
                       principal=Depends(require_named_operator)):
        identity = operator_identity(request, principal)
        if identity is None:
            return _refuse(403, "OPERATOR_NAME_REQUIRED", "an Account operator needs a console login with a readable name")
        return proxy().start(cell, job, body, *identity)
