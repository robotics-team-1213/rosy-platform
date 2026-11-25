"""Stdlib-only 18-tool HTTP CLI & MCP stdio bridge across OMX Cell (:8781), Fleet-R, and Learning (:8768)."""
from __future__ import annotations

import argparse
import base64
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import ssl
import sys
from typing import Any
import urllib.error
import urllib.parse
import urllib.request

from rosy_agent_proposal_context import check_proposal_context, validate_proposal_args

MAX_RESPONSE_BYTES = 8 * 1024 * 1024
MAX_ERROR_BYTES = 65_536
MAX_TEXT_ASSET_CHARS = 65_536
SUPPORTED_MCP_PROTOCOLS = ("2024-11-05", "2025-03-26", "2025-06-18")
_SAFE_RESP_HEADERS = frozenset({
    "x-frame-seq", "x-source-stamp", "etag", "cache-control", "content-type", "content-length",
})
_VIEWS = ["top", "side", "arm_s_top", "arm_s_wrist", "arm_a_wrist", "arm_b_wrist"]
_CELLS = ["cell_s", "cell_ab"]


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, "REDIRECT_BLOCKED", headers, fp)


def _build_opener(ca_file: str = "") -> urllib.request.OpenerDirector:
    handlers: list[Any] = [urllib.request.ProxyHandler({})]
    if ca_file:
        ctx = ssl.create_default_context(cafile=str(Path(ca_file).expanduser()))
        handlers.append(urllib.request.HTTPSHandler(context=ctx))
    handlers.append(_NoRedirectHandler())
    return urllib.request.build_opener(*handlers)


_OPENER = _build_opener()


@dataclass(frozen=True)
class BridgeConfig:
    cell_url: str = "http://127.0.0.1:8781"
    cell_token: str = ""
    fleet_url: str = "http://127.0.0.1:8000"
    fleet_token: str = ""
    fleet_cookie: str = ""
    fleet_ca_file: str = ""
    learning_url: str = "http://127.0.0.1:8768"
    learning_token: str = ""
    timeout_s: float = 15.0


def _read_tok(explicit: str | None, file_path: Path | None, env_var: str) -> str:
    if explicit:
        return explicit.strip()
    if file_path is not None:
        p = Path(file_path).expanduser()
        if not p.is_file():
            raise FileNotFoundError(f"token file not found: {p}")
        tok = p.read_text(encoding="utf-8-sig").strip()
        if not tok:
            raise ValueError(f"token file is empty: {p}")
        return tok
    return os.environ.get(env_var, "").strip()


def _strip_cookie_prefix(raw: str) -> str:
    val = raw.strip()
    return val.split(":", 1)[1].strip() if val.lower().startswith("cookie:") else val


def _read_cookie(explicit: str | None, file_path: Path | None, env_var: str) -> str:
    if explicit:
        return _strip_cookie_prefix(explicit)
    if file_path is not None:
        p = Path(file_path).expanduser()
        if not p.is_file():
            raise FileNotFoundError(f"cookie file not found: {p}")
        raw = p.read_text(encoding="utf-8-sig").strip()
        if not raw:
            raise ValueError(f"cookie file is empty: {p}")
        if p.suffix.lower() == ".json" or raw.startswith("{"):
            parsed = json.loads(raw)
            if not isinstance(parsed, dict) or not isinstance(parsed.get("cookie"), str) or not parsed["cookie"].strip():
                raise ValueError(f"cookie JSON must contain non-empty string 'cookie': {p}")
            return _strip_cookie_prefix(parsed["cookie"])
        line = next((ln.strip() for ln in raw.splitlines() if ln.strip()), "")
        if not line:
            raise ValueError(f"cookie file is empty: {p}")
        return _strip_cookie_prefix(line)
    return _strip_cookie_prefix(os.environ.get(env_var, ""))


def _load_config_file(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    p = Path(path).expanduser()
    if not p.is_file():
        raise FileNotFoundError(f"config file not found: {p}")
    data = json.loads(p.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError(f"config file must contain a JSON object: {p}")
    out = dict(data)
    for k, v in list(out.items()):
        if k.endswith("_file") and isinstance(v, str) and v.strip():
            fp = Path(v.strip()).expanduser()
            out[k] = str(fp if fp.is_absolute() else (p.parent / fp))
    return out


def _obj_schema(props: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": required or [], "additionalProperties": False}


def _safe_segment(val: str) -> bool:
    return bool(val) and val not in (".", "..") and ".." not in val and "/" not in val and "\\" not in val and "\x00" not in val


TOOL_SPECS: tuple[dict[str, Any], ...] = (
    {"name": "cell_readiness", "description": "Read OMX cell :8781 /readiness state and cell_state_gen.",
     "inputSchema": _obj_schema({})},
    {"name": "cell_failure_context", "description": "Read latest or named CellFailureContext bundle from :8781.",
     "inputSchema": _obj_schema({"bundle_id": {"type": "string"}, "arm": {"type": "string"}, "kind": {"type": "string"}})},
    {"name": "cell_failure_asset", "description": "Fetch an image, JSON, or trace-tail asset from a :8781 failure bundle.",
     "inputSchema": _obj_schema({"bundle_id": {"type": "string"}, "filename": {"type": "string"}}, ["bundle_id", "filename"])},
    {"name": "cell_frame", "description": "Fetch live cell frame JPEG from :8781 preserving sequence headers.",
     "inputSchema": _obj_schema({"view": {"type": "string", "enum": _VIEWS}}, ["view"])},
    {"name": "cell_queue", "description": "Read :8781 /queue active jobs, optionally with recent /jobs and /failures.",
     "inputSchema": _obj_schema({"include_jobs": {"type": "boolean"}, "include_failures": {"type": "boolean"},
                                 "arm": {"type": "string"}, "limit": {"type": "integer"}})},
    {"name": "cell_upkeep_check", "description": "Run non-motion upkeep_check on :8781.",
     "inputSchema": _obj_schema({"manifest": {"type": "string"}, "out": {"type": "string"}}, ["manifest"])},
    {"name": "cell_dry_run", "description": "Run observe-only auto_pick_dry_run on :8781.",
     "inputSchema": _obj_schema({
         "config": {"type": "string"}, "catalog": {"type": "string"},
         "roi": {"type": "array", "items": {"type": "integer"}},
         "source": {"type": "string"}, "dest": {"type": "string"},
         "object": {"type": "string"}, "colour": {"type": "string"}, "layers_below": {"type": "integer"},
     }, ["config", "catalog", "roi", "source", "dest"])},
    {"name": "fleet_state", "description": "Read Fleet-R /api/fleet/state (registered robots, online status, scope).",
     "inputSchema": _obj_schema({})},
    {"name": "fleet_cell_readiness", "description": "Read Fleet-R cell readiness, digest, and dispatch_generation.",
     "inputSchema": _obj_schema({"cell_id": {"type": "string", "enum": _CELLS}}, ["cell_id"])},
    {"name": "fleet_cell_tasks", "description": "List Fleet-R /api/fleet/pipeline/cell-tasks and cell safety summary.",
     "inputSchema": _obj_schema({"cell_id": {"type": "string", "enum": _CELLS}, "status": {"type": "string"}})},
    {"name": "fleet_propose_cell_task", "description": "Propose a Fleet-R cell task (PROPOSED only). For fallback, supply the failure bundle ID, context digest, readiness digest, and a stable request_key. For policy fallback, copy correlation.fleet_task_id into fallback_from_task_id.",
     "inputSchema": _obj_schema({
         "cell_id": {"type": "string", "enum": _CELLS}, "arm_id": {"type": "string"}, "src_site": {"type": "string"}, "dst_site": {"type": "string"},
         "preset": {"type": "string"}, "robot_id": {"type": "string"}, "tier": {"type": "integer"},
         "execution_mode": {"type": "string", "enum": ["guarded_pick", "act_policy"]}, "max_chunks": {"type": "integer"},
         "displaced_to": {"type": "string"}, "zone_id": {"type": "string"},
         "task_id": {"type": "string"}, "request_key": {"type": "string"}, "fallback_from_task_id": {"type": "string"},
         "fallback_verb": {"type": "string"}, "failure_bundle_id": {"type": "string"}, "failure_context_sha256": {"type": "string"},
         "expected_context_sha256": {"type": "string"}, "expected_readiness_digest": {"type": "string"},
         "expected_authority_epoch": {"type": "integer"}, "expected_dispatch_generation": {"type": "integer"}, "expected_stop_generation": {"type": "integer"},
     }, ["cell_id"])},
    {"name": "job_status", "description": "Poll cell :8781 job or learning :8768 canonical run status.",
     "inputSchema": _obj_schema({"job_id": {"type": "string"}, "plane": {"type": "string", "enum": ["cell", "learning"]}}, ["job_id"])},
    {"name": "cell_open_human_request", "description": "Open an operator person-request on Fleet-R.",
     "inputSchema": _obj_schema({
         "robot_id": {"type": "string"},
         "kind": {"type": "string", "enum": ["unplug_charger", "plug_charger", "move_robot", "clear_area", "other"]},
         "text": {"type": "string"}, "why": {"type": "string"}, "expires_s": {"type": "number"},
     }, ["kind", "text", "why"])},
    {"name": "cell_capture_clip", "description": "Capture bounded non-motion MP4 clip via :8781.",
     "inputSchema": _obj_schema({
         "view": {"type": "string", "enum": _VIEWS}, "duration_s": {"type": "integer"},
         "fps": {"type": "integer"}, "out_dir": {"type": "string"},
     }, ["view", "duration_s"])},
    {"name": "cell_dataset_pipeline", "description": "Run convert_episodes or transfer_dataset offline media job via :8781.",
     "inputSchema": _obj_schema({
         "stage": {"type": "string", "enum": ["convert", "transfer"]}, "episodes": {"type": "string"},
         "out": {"type": "string"}, "repo_id": {"type": "string"}, "collection": {"type": "string"},
         "fps": {"type": "integer"}, "images": {"type": "string"},
         "outcome": {"type": "string", "enum": ["success", "failed", "failure"]},
     }, ["stage"])},
    {"name": "learning_run_job", "description": "Start a canonical offline learning job on :8768.",
     "inputSchema": _obj_schema({
         "kind": {"type": "string"}, "arm_id": {"type": "string"}, "request_id": {"type": "string"}, "params": {"type": "object"},
     }, ["kind", "arm_id", "request_id", "params"])},
    {"name": "learning_stage_bundle", "description": "Fetch canonical bundle-manifest from :8768 and stage policy bundle onto :8781.",
     "inputSchema": _obj_schema({"run_id": {"type": "string"}, "target_dir": {"type": "string"}}, ["run_id", "target_dir"])},
    {"name": "cell_area_dry_run", "description": "Run observe/IK-plan only area_xyz_pick dry_run on :8781.",
     "inputSchema": _obj_schema({
         "arm": {"type": "string", "enum": ["arm_s", "arm_a", "arm_b"]},
         "config": {"type": "string"},
         "pick_area": {"type": "string"}, "pick_x": {"type": "number"}, "pick_y": {"type": "number"}, "pick_z": {"type": "number"},
         "place_area": {"type": "string"}, "place_x": {"type": "number"}, "place_y": {"type": "number"}, "place_z": {"type": "number"},
         "pick_yaw_deg": {"type": "number"}, "place_yaw_deg": {"type": "number"}, "max_attempts": {"type": "integer"},
         "stay_in_hover": {"type": "boolean"}, "no_vision_refine": {"type": "boolean"},
         "catalog": {"type": "string"}, "object": {"type": "string"},
     }, ["arm", "config", "pick_area", "pick_x", "pick_y", "pick_z", "place_area", "place_x", "place_y", "place_z"])},
)
TOOL_MAP = {t["name"]: t for t in TOOL_SPECS}
OPERATIONS_MCP_TOOLS = frozenset({
    "cell_readiness", "cell_failure_context", "cell_failure_asset", "cell_frame", "cell_queue",
    "fleet_state", "fleet_cell_readiness", "fleet_cell_tasks", "fleet_propose_cell_task",
})


def _check_type(ps: dict[str, Any], val: Any, key: str) -> str | None:
    t = ps.get("type")
    if t == "string":
        if not isinstance(val, str):
            return f"{key}: expected string"
        if "enum" in ps and val not in ps["enum"]:
            return f"{key}: must be one of {ps['enum']}"
    elif t == "boolean":
        if not isinstance(val, bool):
            return f"{key}: expected boolean"
    elif t == "integer":
        if isinstance(val, bool) or not isinstance(val, int):
            return f"{key}: expected integer"
    elif t == "number":
        if isinstance(val, bool) or not isinstance(val, (int, float)) or not math.isfinite(float(val)):
            return f"{key}: expected finite number"
    elif t == "array":
        if not isinstance(val, list):
            return f"{key}: expected array"
        item_t = (ps.get("items") or {}).get("type")
        if item_t == "integer" and any(isinstance(x, bool) or not isinstance(x, int) for x in val):
            return f"{key}: expected array of integers"
    elif t == "object":
        if not isinstance(val, dict):
            return f"{key}: expected object"
    return None


def _validate_args(spec: dict[str, Any], args: Any) -> str | None:
    if not isinstance(args, dict):
        return "arguments must be a JSON object"
    schema = spec["inputSchema"]
    props = schema["properties"]
    if schema.get("additionalProperties") is False:
        unknown = sorted(set(args) - set(props))
        if unknown:
            return f"unexpected arguments: {unknown}"
    missing = [k for k in (schema.get("required") or []) if k not in args]
    if missing:
        return f"missing required arguments: {missing}"
    for k, val in args.items():
        if err := _check_type(props[k], val, k):
            return err
    if spec["name"] == "fleet_propose_cell_task":
        return validate_proposal_args(args)
    return None


class RosyAgentBridge:
    """Pure stdlib HTTP dispatcher implementing the 18 ROSY tools across 3 control planes."""

    def __init__(self, cfg: BridgeConfig) -> None:
        self.cfg = cfg
        self._opener = _build_opener(cfg.fleet_ca_file) if cfg.fleet_ca_file else _OPENER
        secrets = [s for s in (cfg.cell_token, cfg.fleet_token, cfg.learning_token, cfg.fleet_cookie) if s]
        if cfg.fleet_cookie:
            for part in cfg.fleet_cookie.split(";"):
                if "=" in part:
                    val = part.split("=", 1)[1].strip()
                    if len(val) >= 6:
                        secrets.append(val)
        self._secrets = tuple(sorted(set(secrets), key=len, reverse=True))

    def _scrub(self, text: str) -> str:
        out = text
        for tok in self._secrets:
            out = out.replace(tok, "[REDACTED]")
        return out

    def _scrub_obj(self, value: Any) -> Any:
        if isinstance(value, str):
            return self._scrub(value)
        if isinstance(value, list):
            return [self._scrub_obj(x) for x in value]
        if isinstance(value, dict):
            return {k: self._scrub_obj(v) for k, v in value.items()}
        return value

    def _http(
        self, method: str, url: str, *, token: str = "", cookie: str = "", body: dict | None = None,
        headers: dict[str, str] | None = None, expect_binary: bool = False, allow_raw: bool = False,
    ) -> dict[str, Any]:
        parts = urllib.parse.urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            return {"ok": False, "status": 400, "error_code": "INVALID_URL_SCHEME", "detail": "only http/https URLs allowed"}
        req_headers = dict(headers or {})
        if token:
            req_headers["Authorization"] = f"Bearer {token}"
        elif cookie:
            req_headers["Cookie"] = cookie
            if method.upper() not in ("GET", "HEAD") and "origin" not in {k.lower() for k in req_headers}:
                req_headers["Origin"] = f"{parts.scheme}://{parts.netloc}"
        data = None
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            req_headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=req_headers, method=method)
        try:
            with self._opener.open(req, timeout=self.cfg.timeout_s) as resp:
                raw = resp.read(MAX_RESPONSE_BYTES + 1)
                if len(raw) > MAX_RESPONSE_BYTES:
                    return {"ok": False, "status": 502, "error_code": "RESPONSE_TOO_LARGE", "detail": "upstream response exceeded byte cap"}
                safe_hdrs = {k: str(v) for k, v in resp.headers.items() if k.lower() in _SAFE_RESP_HEADERS}
                ctype = resp.headers.get("Content-Type", "")
                mime = ctype.split(";", 1)[0].strip().lower()
                looks_json = "application/json" in mime or (not allow_raw and raw.lstrip().startswith((b"{", b"[")))
                if expect_binary:
                    if not raw or looks_json:
                        return {"ok": False, "status": 502, "error_code": "INVALID_FRAME_RESPONSE", "detail": "expected non-empty binary image"}
                    return {"ok": True, "status": resp.status, "bytes": raw, "mime_type": mime or "image/jpeg", "headers": safe_hdrs}
                if allow_raw and mime.startswith("image/"):
                    return {"ok": True, "status": resp.status, "bytes": raw, "mime_type": mime, "headers": safe_hdrs}
                if looks_json:
                    try:
                        parsed = json.loads(raw.decode("utf-8"))
                    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                        return {"ok": False, "status": 502, "error_code": "INVALID_UPSTREAM_JSON", "detail": self._scrub(str(exc))[:200]}
                    return {"ok": True, "status": resp.status, "data": parsed, "raw_sha256": hashlib.sha256(raw).hexdigest(), "headers": safe_hdrs}
                if allow_raw:
                    txt = raw.decode("utf-8", "replace")
                    return {"ok": True, "status": resp.status, "bytes_len": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
                            "mime_type": mime or "text/plain", "text": txt[:MAX_TEXT_ASSET_CHARS],
                            "truncated": len(txt) > MAX_TEXT_ASSET_CHARS, "headers": safe_hdrs}
                return {"ok": False, "status": 502, "error_code": "INVALID_UPSTREAM_RESPONSE", "detail": "expected JSON response"}
        except urllib.error.HTTPError as exc:
            raw = exc.read(MAX_ERROR_BYTES)
            try:
                err_body = self._scrub_obj(json.loads(raw.decode("utf-8", "replace")))
            except ValueError:
                err_body = {"error": self._scrub(raw.decode("utf-8", "replace")[:200])}
            detail = err_body.get("detail") if isinstance(err_body, dict) else None
            code = (detail.get("code") if isinstance(detail, dict) else None) or (err_body.get("code") if isinstance(err_body, dict) else None) or f"HTTP_{exc.code}"
            return {"ok": False, "status": exc.code, "error_code": self._scrub(str(code)), "detail": err_body}
        except (OSError, TimeoutError, urllib.error.URLError) as exc:
            return {"ok": False, "status": 503, "error_code": "PLANE_UNREACHABLE", "detail": self._scrub(str(exc))[:200]}

    def check_cell_proposal_context(self, proposal: dict[str, Any]) -> dict[str, Any] | None:
        """Recheck the saved failure context with the cell before handing a proposal to Fleet."""
        return check_proposal_context(
            proposal, lambda bundle_id: self.call_tool("cell_failure_context", {"bundle_id": bundle_id}),
        )

    def call_tool(self, name: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
        if name not in TOOL_MAP:
            return {"ok": False, "status": 400, "error_code": "UNKNOWN_TOOL", "detail": f"unknown tool {name!r}"}
        raw_args = {} if args is None else args
        if err := _validate_args(TOOL_MAP[name], raw_args):
            return {"ok": False, "status": 400, "error_code": "INVALID_ARGS", "detail": err}
        a = dict(raw_args)
        cu, ct = self.cfg.cell_url.rstrip("/"), self.cfg.cell_token
        fu, ft, fc = self.cfg.fleet_url.rstrip("/"), self.cfg.fleet_token, self.cfg.fleet_cookie
        lu, lt = self.cfg.learning_url.rstrip("/"), self.cfg.learning_token

        if name == "cell_readiness":
            return self._http("GET", f"{cu}/readiness", token=ct)
        if name == "cell_failure_context":
            if bid := a.get("bundle_id"):
                return self._http("GET", f"{cu}/failures/{urllib.parse.quote(str(bid), safe='')}", token=ct)
            q = urllib.parse.urlencode({k: str(a[k]) for k in ("arm", "kind") if a.get(k)})
            return self._http("GET", f"{cu}/failures/latest" + (f"?{q}" if q else ""), token=ct)
        if name == "cell_failure_asset":
            bid, fn = a["bundle_id"], a["filename"]
            if not (_safe_segment(bid) and _safe_segment(fn)):
                return {"ok": False, "status": 400, "error_code": "INVALID_ARGS", "detail": "bundle_id and filename must be single safe path segments"}
            res = self._http("GET", f"{cu}/failures/{urllib.parse.quote(bid, safe='')}/assets/{urllib.parse.quote(fn, safe='')}", token=ct, allow_raw=True)
            if res.get("ok") and "bytes" in res:
                raw = res.pop("bytes")
                return {**res, "bytes_len": len(raw), "sha256": hashlib.sha256(raw).hexdigest(), "image_b64": base64.b64encode(raw).decode("ascii")}
            return res
        if name == "cell_frame":
            res = self._http("GET", f"{cu}/frame/{urllib.parse.quote(a['view'], safe='')}.jpg", token=ct, expect_binary=True)
            if not res["ok"]:
                return res
            raw = res.pop("bytes", b"")
            hdrs = res.get("headers") or {}
            return {**res, "bytes_len": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
                    "image_b64": base64.b64encode(raw).decode("ascii"),
                    "frame_headers": {k: hdrs[k] for k in ("X-Frame-Seq", "X-Source-Stamp", "ETag", "Cache-Control") if k in hdrs}}
        if name == "cell_queue":
            q_res = self._http("GET", f"{cu}/queue", token=ct)
            if not q_res.get("ok"):
                return q_res
            out: dict[str, Any] = {"queue": q_res["data"]}
            if a.get("include_jobs"):
                j_res = self._http("GET", f"{cu}/jobs", token=ct)
                if not j_res.get("ok"):
                    return j_res
                out["jobs"] = j_res["data"]
            if a.get("include_failures"):
                fq = urllib.parse.urlencode({k: str(a[k]) for k in ("arm", "limit") if a.get(k) is not None})
                f_res = self._http("GET", f"{cu}/failures" + (f"?{fq}" if fq else ""), token=ct)
                if not f_res.get("ok"):
                    return f_res
                out["failures"] = f_res["data"]
            return {"ok": True, "status": 200, "data": out}
        if name == "cell_upkeep_check":
            return self._http("POST", f"{cu}/jobs/upkeep_check", token=ct, body=a)
        if name == "cell_dry_run":
            return self._http("POST", f"{cu}/jobs/auto_pick_dry_run", token=ct, body=a)
        if name == "cell_area_dry_run":
            return self._http("POST", f"{cu}/jobs/area_xyz_pick", token=ct, body={**a, "dry_run": True})
        if name == "fleet_state":
            return self._http("GET", f"{fu}/api/fleet/state", token=ft, cookie=fc)
        if name == "fleet_cell_readiness":
            cid = urllib.parse.quote(a["cell_id"], safe="")
            return self._http("GET", f"{fu}/api/fleet/pipeline/cells/{cid}/readiness", token=ft, cookie=fc)
        if name == "fleet_cell_tasks":
            q = urllib.parse.urlencode({k: str(a[k]) for k in ("cell_id", "status") if a.get(k)})
            return self._http("GET", f"{fu}/api/fleet/pipeline/cell-tasks" + (f"?{q}" if q else ""), token=ft, cookie=fc)
        if name == "fleet_propose_cell_task":
            if refusal := self.check_cell_proposal_context(a):
                return refusal
            payload = {**a, "propose": True}
            if a.get("failure_bundle_id"):
                payload["failure_context_sha256"] = a["expected_context_sha256"]
            hdrs = {"Idempotency-Key": str(a["request_key"])} if a.get("request_key") else None
            res = self._http("POST", f"{fu}/api/fleet/pipeline/cell-tasks", token=ft, cookie=fc, body=payload, headers=hdrs)
            if res.get("ok"):
                data = res.get("data")
                task = data.get("task") if isinstance(data, dict) else None
                status = (data.get("status") if isinstance(data, dict) else None) or (task.get("status") if isinstance(task, dict) else None)
                if status != "PROPOSED":
                    return {"ok": False, "status": 502, "error_code": "PROPOSE_NOT_ENFORCED", "detail": f"upstream did not confirm status=PROPOSED (got {status!r})"}
            return res
        if name == "job_status":
            jid = urllib.parse.quote(str(a["job_id"]), safe="")
            if a.get("plane", "cell") == "learning":
                return self._http("GET", f"{lu}/api/learning/canonical/runs/{jid}", token=lt)
            return self._http("GET", f"{cu}/jobs/{jid}", token=ct)
        if name == "cell_open_human_request":
            return self._http("POST", f"{fu}/api/fleet/person-requests", token=ft, cookie=fc, body=a)
        if name == "cell_capture_clip":
            return self._http("POST", f"{cu}/jobs/capture_clip", token=ct, body=a)
        if name == "cell_dataset_pipeline":
            stage = a.pop("stage", "")
            job = "convert_episodes" if stage == "convert" else "transfer_dataset"
            return self._http("POST", f"{cu}/jobs/{job}", token=ct, body=a)
        if name == "learning_run_job":
            return self._http("POST", f"{lu}/api/learning/canonical/jobs", token=lt, body=a)
        if name == "learning_stage_bundle":
            rid = urllib.parse.quote(str(a["run_id"]), safe="")
            man = self._http("GET", f"{lu}/api/learning/canonical/runs/{rid}/bundle-manifest", token=lt)
            if not man["ok"]:
                return man
            return self._http(
                "POST", f"{cu}/jobs/stage_policy_bundle", token=ct,
                body={"run_id": a["run_id"], "target_dir": a["target_dir"], "expected_manifest_sha256": man["raw_sha256"]},
            )
        return {"ok": False, "status": 400, "error_code": "UNKNOWN_TOOL", "detail": name}


def _rpc_err(stdout, req_id: Any, code: int, msg: str) -> None:
    stdout.write(json.dumps({"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": msg}}, ensure_ascii=False) + "\n")
    stdout.flush()


def serve_mcp_stdio(
    bridge: RosyAgentBridge, stdin=sys.stdin, stdout=sys.stdout, *, operations_only: bool = False,
) -> int:
    """Handle line-delimited MCP JSON-RPC requests on stdio."""
    tools = {name: spec for name, spec in TOOL_MAP.items()
             if not operations_only or name in OPERATIONS_MCP_TOOLS}
    for line in stdin:
        s = line.strip()
        if not s:
            continue
        try:
            msg = json.loads(s)
        except json.JSONDecodeError as exc:
            _rpc_err(stdout, None, -32700, f"Parse error: {exc}")
            continue
        if not isinstance(msg, dict):
            _rpc_err(stdout, None, -32600, "Invalid Request: expected object")
            continue
        req_id, method = msg.get("id"), msg.get("method")
        if req_id is None:
            continue
        if method == "initialize":
            req_proto = msg.get("params", {}).get("protocolVersion") if isinstance(msg.get("params"), dict) else None
            proto = req_proto if req_proto in SUPPORTED_MCP_PROTOCOLS else SUPPORTED_MCP_PROTOCOLS[0]
            result: dict[str, Any] = {
                "protocolVersion": proto, "capabilities": {"tools": {}},
                "serverInfo": {"name": "rosy-agent-bridge", "version": "1.1.0"},
            }
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": list(tools.values())}
        elif method == "tools/call":
            p = msg.get("params")
            if not isinstance(p, dict) or not isinstance(p.get("name"), str) or not (p.get("arguments") is None or isinstance(p.get("arguments"), dict)):
                _rpc_err(stdout, req_id, -32602, "Invalid params")
                continue
            if operations_only and p["name"] not in tools:
                _rpc_err(stdout, req_id, -32602, "Tool unavailable in operations scope")
                continue
            res = bridge.call_tool(p["name"], p.get("arguments") or {})
            if res.get("ok") and isinstance(res.get("image_b64"), str):
                meta = {k: v for k, v in res.items() if k != "image_b64"}
                content = [
                    {"type": "text", "text": json.dumps(meta, ensure_ascii=False)},
                    {"type": "image", "data": res["image_b64"], "mimeType": str(res.get("mime_type") or "image/jpeg")},
                ]
            else:
                content = [{"type": "text", "text": json.dumps(res, ensure_ascii=False)}]
            result = {"content": content, "isError": not res.get("ok")}
        else:
            _rpc_err(stdout, req_id, -32601, f"unknown method {method}")
            continue
        stdout.write(json.dumps({"jsonrpc": "2.0", "id": req_id, "result": result}, ensure_ascii=False) + "\n")
        stdout.flush()
    return 0


def _pick_str(cli_val: str | None, env_var: str, cfg_data: dict[str, Any], cfg_key: str, default: str = "") -> str:
    if cli_val is not None:
        return cli_val.strip()
    if env_val := os.environ.get(env_var, "").strip():
        return env_val
    cfg_val = cfg_data.get(cfg_key)
    return cfg_val.strip() if isinstance(cfg_val, str) and cfg_val.strip() else default


def _pick_path(cli_val: Path | None, env_var: str, cfg_data: dict[str, Any], cfg_key: str) -> Path | None:
    if cli_val is not None:
        return cli_val
    if env_val := os.environ.get(env_var, "").strip():
        return Path(env_val)
    cfg_val = cfg_data.get(cfg_key)
    return Path(cfg_val) if isinstance(cfg_val, str) and cfg_val.strip() else None


def build_config(args: argparse.Namespace) -> BridgeConfig:
    cfg_env = os.environ.get("ROSY_AGENT_BRIDGE_CONFIG", "").strip()
    cfg_path = args.config if args.config is not None else (Path(cfg_env) if cfg_env else None)
    cfg_data = _load_config_file(cfg_path)
    raw_timeout = args.timeout_s if args.timeout_s is not None else cfg_data.get("timeout_s")
    timeout_s = 15.0 if raw_timeout is None else float(raw_timeout)
    cookie_path = None if (args.fleet_cookie_file is None and os.environ.get("ROSY_FLEET_COOKIE", "").strip()) else _pick_path(
        args.fleet_cookie_file, "ROSY_FLEET_COOKIE_FILE", cfg_data, "fleet_cookie_file",
    )
    return BridgeConfig(
        cell_url=_pick_str(args.cell_url, "ROSY_CELL_JOB_URL", cfg_data, "cell_url", "http://127.0.0.1:8781"),
        cell_token=_read_tok(None, args.cell_token_file or (None if os.environ.get("ROSY_CELL_JOB_TOKEN", "").strip() else _pick_path(None, "", cfg_data, "cell_token_file")), "ROSY_CELL_JOB_TOKEN"),
        fleet_url=_pick_str(args.fleet_url, "ROSY_FLEET_URL", cfg_data, "fleet_url", "http://127.0.0.1:8000"),
        fleet_token=_read_tok(None, args.fleet_token_file or (None if os.environ.get("ROSY_FLEET_TOKEN", "").strip() else _pick_path(None, "", cfg_data, "fleet_token_file")), "ROSY_FLEET_TOKEN"),
        fleet_cookie=_read_cookie(None, cookie_path, "ROSY_FLEET_COOKIE"),
        fleet_ca_file=_pick_str(args.fleet_ca_file, "ROSY_FLEET_CA_FILE", cfg_data, "fleet_ca_file"),
        learning_url=_pick_str(args.learning_url, "ROSY_LEARNING_URL", cfg_data, "learning_url", "http://127.0.0.1:8768"),
        learning_token=_read_tok(None, args.learning_token_file or (None if os.environ.get("ROSY_LEARNING_TOKEN", "").strip() else _pick_path(None, "", cfg_data, "learning_token_file")), "ROSY_LEARNING_TOKEN"),
        timeout_s=timeout_s,
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--config", type=Path, default=None)
    ap.add_argument("--cell-url", default=None)
    ap.add_argument("--fleet-url", default=None)
    ap.add_argument("--learning-url", default=None)
    ap.add_argument("--cell-token-file", type=Path, default=None)
    ap.add_argument("--fleet-token-file", type=Path, default=None)
    ap.add_argument("--fleet-cookie-file", type=Path, default=None)
    ap.add_argument("--fleet-ca-file", default=None)
    ap.add_argument("--learning-token-file", type=Path, default=None)
    ap.add_argument("--timeout-s", type=float, default=None)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list-tools")
    p_call = sub.add_parser("call")
    p_call.add_argument("tool")
    p_call.add_argument("--args-json", default="{}")
    p_mcp = sub.add_parser("mcp-stdio")
    p_mcp.add_argument("--operations-only", action="store_true",
                       help="expose observation and Fleet proposal tools only")
    args = ap.parse_args(argv)
    bridge = RosyAgentBridge(build_config(args))
    if args.cmd == "list-tools":
        print(json.dumps(list(TOOL_SPECS), indent=2, ensure_ascii=False))
        return 0
    if args.cmd == "mcp-stdio":
        return serve_mcp_stdio(bridge, stdin=sys.stdin, stdout=sys.stdout, operations_only=args.operations_only)
    res = bridge.call_tool(args.tool, json.loads(args.args_json))
    print(json.dumps(res, ensure_ascii=False))
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
