"""Stdlib-only 12-tool HTTP CLI & MCP stdio bridge across OMX Cell (:8781), Fleet-R, and Learning (:8768)."""
from __future__ import annotations

import argparse
import base64
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import sys
from typing import Any
import urllib.error
import urllib.parse
import urllib.request

MAX_RESPONSE_BYTES = 8 * 1024 * 1024
MAX_ERROR_BYTES = 65_536
_SAFE_RESP_HEADERS = frozenset({
    "x-frame-seq", "x-source-stamp", "etag", "cache-control", "content-type", "content-length",
})


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, "REDIRECT_BLOCKED", headers, fp)


_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirectHandler())


@dataclass(frozen=True)
class BridgeConfig:
    cell_url: str = "http://127.0.0.1:8781"
    cell_token: str = ""
    fleet_url: str = "http://127.0.0.1:8000"
    fleet_token: str = ""
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
        tok = p.read_text(encoding="utf-8").strip()
        if not tok:
            raise ValueError(f"token file is empty: {p}")
        return tok
    return os.environ.get(env_var, "").strip()


def _obj_schema(props: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": required or [], "additionalProperties": False}


TOOL_SPECS: tuple[dict[str, Any], ...] = (
    {"name": "cell_readiness", "description": "Read OMX cell :8781 /readiness state and cell_state_gen.",
     "inputSchema": _obj_schema({})},
    {"name": "cell_failure_context", "description": "Read latest or named CellFailureContext bundle from :8781.",
     "inputSchema": _obj_schema({"bundle_id": {"type": "string"}, "arm": {"type": "string"}, "kind": {"type": "string"}})},
    {"name": "cell_frame", "description": "Fetch live cell frame JPEG from :8781 preserving sequence headers.",
     "inputSchema": _obj_schema({"view": {"type": "string", "enum": ["top", "side", "arm_s_top", "arm_s_wrist", "arm_a_wrist", "arm_b_wrist"]}}, ["view"])},
    {"name": "cell_upkeep_check", "description": "Run non-motion upkeep_check on :8781.",
     "inputSchema": _obj_schema({"manifest": {"type": "string"}})},
    {"name": "cell_dry_run", "description": "Run observe-only auto_pick_dry_run on :8781.",
     "inputSchema": _obj_schema({"config": {"type": "string"}, "catalog": {"type": "string"}, "roi": {"type": "array", "items": {"type": "integer"}}}, ["config", "catalog", "roi"])},
    {"name": "fleet_propose_cell_task", "description": "Propose a Fleet-R cell task (PROPOSED only; carries CAS & request_key).",
     "inputSchema": _obj_schema({
         "cell_id": {"type": "string"}, "arm_id": {"type": "string"}, "src_site": {"type": "string"}, "dst_site": {"type": "string"},
         "task_id": {"type": "string"}, "request_key": {"type": "string"}, "fallback_from_task_id": {"type": "string"},
         "fallback_verb": {"type": "string"}, "failure_bundle_id": {"type": "string"}, "failure_context_sha256": {"type": "string"},
         "expected_context_sha256": {"type": "string"}, "expected_readiness_digest": {"type": "string"},
         "expected_dispatch_generation": {"type": "integer"}, "expected_stop_generation": {"type": "integer"},
     }, ["cell_id"])},
    {"name": "job_status", "description": "Poll cell :8781 job or learning :8768 canonical run status.",
     "inputSchema": _obj_schema({"job_id": {"type": "string"}, "plane": {"type": "string", "enum": ["cell", "learning"]}}, ["job_id"])},
    {"name": "cell_open_human_request", "description": "Open an operator person-request on Fleet-R.",
     "inputSchema": _obj_schema({"robot_id": {"type": "string"}, "kind": {"type": "string", "enum": ["unplug_charger", "plug_charger", "move_robot", "clear_area", "other"]}, "text": {"type": "string"}, "why": {"type": "string"}, "expires_s": {"type": "number"}}, ["kind", "text", "why"])},
    {"name": "cell_capture_clip", "description": "Capture bounded non-motion MP4 clip via :8781.",
     "inputSchema": _obj_schema({"view": {"type": "string"}, "duration_s": {"type": "number"}, "fps": {"type": "number"}}, ["view"])},
    {"name": "cell_dataset_pipeline", "description": "Run convert_episodes or transfer_dataset offline media job via :8781.",
     "inputSchema": _obj_schema({"stage": {"type": "string", "enum": ["convert", "transfer"]}, "episodes": {"type": "string"}, "out": {"type": "string"}, "repo_id": {"type": "string"}, "collection": {"type": "string"}}, ["stage"])},
    {"name": "learning_run_job", "description": "Start a canonical offline learning job on :8768.",
     "inputSchema": _obj_schema({"kind": {"type": "string"}, "arm_id": {"type": "string"}, "request_id": {"type": "string"}, "params": {"type": "object"}}, ["kind", "arm_id"])},
    {"name": "learning_stage_bundle", "description": "Fetch canonical bundle-manifest from :8768 and stage policy bundle onto :8781.",
     "inputSchema": _obj_schema({"run_id": {"type": "string"}, "target_dir": {"type": "string"}}, ["run_id", "target_dir"])},
)
TOOL_MAP = {t["name"]: t for t in TOOL_SPECS}


def _check_type(ps: dict[str, Any], val: Any, key: str) -> str | None:
    t = ps.get("type")
    if t == "string":
        if not isinstance(val, str):
            return f"{key}: expected string"
        if "enum" in ps and val not in ps["enum"]:
            return f"{key}: must be one of {ps['enum']}"
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
    return None


class RosyAgentBridge:
    """Pure stdlib HTTP dispatcher implementing the 12 agy tools across 3 control planes."""

    def __init__(self, cfg: BridgeConfig) -> None:
        self.cfg = cfg

    def _scrub(self, text: str) -> str:
        out = text
        for tok in (self.cfg.cell_token, self.cfg.fleet_token, self.cfg.learning_token):
            if tok:
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
        self, method: str, url: str, *, token: str = "", body: dict | None = None,
        headers: dict[str, str] | None = None, expect_binary: bool = False,
    ) -> dict[str, Any]:
        parts = urllib.parse.urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            return {"ok": False, "status": 400, "error_code": "INVALID_URL_SCHEME", "detail": "only http/https URLs allowed"}
        req_headers = dict(headers or {})
        if token:
            req_headers["Authorization"] = f"Bearer {token}"
        data = None
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            req_headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=req_headers, method=method)
        try:
            with _OPENER.open(req, timeout=self.cfg.timeout_s) as resp:
                raw = resp.read(MAX_RESPONSE_BYTES + 1)
                if len(raw) > MAX_RESPONSE_BYTES:
                    return {"ok": False, "status": 502, "error_code": "RESPONSE_TOO_LARGE", "detail": "upstream response exceeded byte cap"}
                safe_hdrs = {k: str(v) for k, v in resp.headers.items() if k.lower() in _SAFE_RESP_HEADERS}
                ctype = resp.headers.get("Content-Type", "")
                looks_json = "application/json" in ctype or raw.lstrip().startswith((b"{", b"["))
                if expect_binary:
                    if not raw or looks_json:
                        return {"ok": False, "status": 502, "error_code": "INVALID_FRAME_RESPONSE", "detail": "expected non-empty binary image"}
                    return {"ok": True, "status": resp.status, "bytes": raw, "headers": safe_hdrs}
                if not looks_json:
                    return {"ok": False, "status": 502, "error_code": "INVALID_UPSTREAM_RESPONSE", "detail": "expected JSON response"}
                try:
                    parsed = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    return {"ok": False, "status": 502, "error_code": "INVALID_UPSTREAM_JSON", "detail": self._scrub(str(exc))[:200]}
                return {"ok": True, "status": resp.status, "data": parsed, "headers": safe_hdrs}
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

    def call_tool(self, name: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
        if name not in TOOL_MAP:
            return {"ok": False, "status": 400, "error_code": "UNKNOWN_TOOL", "detail": f"unknown tool {name!r}"}
        raw_args = {} if args is None else args
        if err := _validate_args(TOOL_MAP[name], raw_args):
            return {"ok": False, "status": 400, "error_code": "INVALID_ARGS", "detail": err}
        a = dict(raw_args)
        cu, ct = self.cfg.cell_url.rstrip("/"), self.cfg.cell_token
        fu, ft = self.cfg.fleet_url.rstrip("/"), self.cfg.fleet_token
        lu, lt = self.cfg.learning_url.rstrip("/"), self.cfg.learning_token

        if name == "cell_readiness":
            return self._http("GET", f"{cu}/readiness", token=ct)
        if name == "cell_failure_context":
            if bid := a.get("bundle_id"):
                return self._http("GET", f"{cu}/failures/{urllib.parse.quote(str(bid), safe='')}", token=ct)
            q = urllib.parse.urlencode({k: str(a[k]) for k in ("arm", "kind") if a.get(k)})
            return self._http("GET", f"{cu}/failures/latest" + (f"?{q}" if q else ""), token=ct)
        if name == "cell_frame":
            res = self._http("GET", f"{cu}/frame/{urllib.parse.quote(a['view'], safe='')}.jpg", token=ct, expect_binary=True)
            if not res["ok"]:
                return res
            raw = res.pop("bytes", b"")
            hdrs = res.get("headers") or {}
            return {**res, "bytes_len": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
                    "image_b64": base64.b64encode(raw).decode("ascii"),
                    "frame_headers": {k: hdrs[k] for k in ("X-Frame-Seq", "X-Source-Stamp", "ETag", "Cache-Control") if k in hdrs}}
        if name == "cell_upkeep_check":
            return self._http("POST", f"{cu}/jobs/upkeep_check", token=ct, body=a)
        if name == "cell_dry_run":
            return self._http("POST", f"{cu}/jobs/auto_pick_dry_run", token=ct, body=a)
        if name == "fleet_propose_cell_task":
            payload = {**a, "propose": True}
            hdrs = {"Idempotency-Key": str(a["request_key"])} if a.get("request_key") else None
            res = self._http("POST", f"{fu}/api/fleet/pipeline/cell-tasks", token=ft, body=payload, headers=hdrs)
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
            return self._http("POST", f"{fu}/api/fleet/person-requests", token=ft, body=a)
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
            return self._http("POST", f"{cu}/jobs/stage_policy_bundle", token=ct,
                              body={"run_id": a["run_id"], "target_dir": a["target_dir"], "manifest": man["data"]})
        return {"ok": False, "status": 400, "error_code": "UNKNOWN_TOOL", "detail": name}


def _rpc_err(stdout, req_id: Any, code: int, msg: str) -> None:
    stdout.write(json.dumps({"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": msg}}, ensure_ascii=False) + "\n")
    stdout.flush()


def serve_mcp_stdio(bridge: RosyAgentBridge, stdin=sys.stdin, stdout=sys.stdout) -> int:
    """Handle line-delimited MCP JSON-RPC requests on stdio."""
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
            result = {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                      "serverInfo": {"name": "rosy-agent-bridge", "version": "1.0.0"}}
        elif method == "tools/list":
            result = {"tools": list(TOOL_SPECS)}
        elif method == "tools/call":
            p = msg.get("params")
            if not isinstance(p, dict) or not isinstance(p.get("name"), str) or not (p.get("arguments") is None or isinstance(p.get("arguments"), dict)):
                _rpc_err(stdout, req_id, -32602, "Invalid params")
                continue
            res = bridge.call_tool(p["name"], p.get("arguments") or {})
            result = {"content": [{"type": "text", "text": json.dumps(res, ensure_ascii=False)}], "isError": not res.get("ok")}
        else:
            _rpc_err(stdout, req_id, -32601, f"unknown method {method}")
            continue
        stdout.write(json.dumps({"jsonrpc": "2.0", "id": req_id, "result": result}, ensure_ascii=False) + "\n")
        stdout.flush()
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--cell-url", default=os.environ.get("ROSY_CELL_JOB_URL", "http://127.0.0.1:8781"))
    ap.add_argument("--fleet-url", default=os.environ.get("ROSY_FLEET_URL", "http://127.0.0.1:8000"))
    ap.add_argument("--learning-url", default=os.environ.get("ROSY_LEARNING_URL", "http://127.0.0.1:8768"))
    ap.add_argument("--cell-token-file", type=Path)
    ap.add_argument("--fleet-token-file", type=Path)
    ap.add_argument("--learning-token-file", type=Path)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list-tools")
    p_call = sub.add_parser("call")
    p_call.add_argument("tool")
    p_call.add_argument("--args-json", default="{}")
    sub.add_parser("mcp-stdio")
    args = ap.parse_args(argv)
    cfg = BridgeConfig(
        cell_url=args.cell_url, fleet_url=args.fleet_url, learning_url=args.learning_url,
        cell_token=_read_tok(None, args.cell_token_file, "ROSY_CELL_JOB_TOKEN"),
        fleet_token=_read_tok(None, args.fleet_token_file, "ROSY_FLEET_TOKEN"),
        learning_token=_read_tok(None, args.learning_token_file, "ROSY_LEARNING_TOKEN"),
    )
    bridge = RosyAgentBridge(cfg)
    if args.cmd == "list-tools":
        print(json.dumps(list(TOOL_SPECS), indent=2, ensure_ascii=False))
        return 0
    if args.cmd == "mcp-stdio":
        return serve_mcp_stdio(bridge)
    res = bridge.call_tool(args.tool, json.loads(args.args_json))
    print(json.dumps(res, ensure_ascii=False))
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
