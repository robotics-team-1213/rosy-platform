"""Stdlib-only 12-tool HTTP CLI & MCP stdio bridge across OMX Cell (:8781), Fleet-R, and Learning (:8768)."""
from __future__ import annotations

import argparse
import base64
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any
import urllib.error
import urllib.parse
import urllib.request


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
    if file_path is not None and file_path.is_file():
        return file_path.read_text(encoding="utf-8").strip()
    return os.environ.get(env_var, "").strip()


def _obj_schema(props: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": required or [], "additionalProperties": False}


TOOL_SPECS: tuple[dict[str, Any], ...] = (
    {"name": "cell_readiness", "description": "Read OMX cell :8781 /readiness state and cell_state_gen.",
     "inputSchema": _obj_schema({})},
    {"name": "cell_failure_context", "description": "Read latest or named CellFailureContext bundle from :8781.",
     "inputSchema": _obj_schema({"bundle_id": {"type": "string"}, "arm": {"type": "string"}, "kind": {"type": "string"}})},
    {"name": "cell_frame", "description": "Fetch live cell frame JPEG from :8781 preserving sequence headers.",
     "inputSchema": _obj_schema({"view": {"type": "string", "enum": ["top", "side", "arm_s_wrist", "arm_a_wrist", "arm_b_wrist"]}}, ["view"])},
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
     "inputSchema": _obj_schema({"robot_id": {"type": "string"}, "kind": {"type": "string"}, "text": {"type": "string"}, "why": {"type": "string"}, "expires_s": {"type": "number"}}, ["kind", "text", "why"])},
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


class RosyAgentBridge:
    """Pure stdlib HTTP dispatcher implementing the 12 agy tools across 3 control planes."""

    def __init__(self, cfg: BridgeConfig) -> None:
        self.cfg = cfg

    def _http(self, method: str, url: str, *, token: str = "", body: dict | None = None, headers: dict[str, str] | None = None) -> dict[str, Any]:
        req_headers = dict(headers or {})
        if token:
            req_headers["Authorization"] = f"Bearer {token}"
        data = None
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            req_headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=req_headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.cfg.timeout_s) as resp:
                raw = resp.read()
                resp_hdrs = {k: str(v) for k, v in resp.headers.items()}
                ctype = resp.headers.get("Content-Type", "")
                if "application/json" in ctype or raw.lstrip().startswith((b"{", b"[")):
                    parsed = json.loads(raw.decode("utf-8"))
                    return {"ok": True, "status": resp.status, "data": parsed, "headers": resp_hdrs}
                return {"ok": True, "status": resp.status, "bytes": raw, "headers": resp_hdrs}
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            try:
                err_body = json.loads(raw.decode("utf-8", "replace"))
            except ValueError:
                err_body = {"error": raw.decode("utf-8", "replace")[:200]}
            detail = err_body.get("detail") if isinstance(err_body, dict) else None
            code = (detail.get("code") if isinstance(detail, dict) else None) or (err_body.get("code") if isinstance(err_body, dict) else None) or f"HTTP_{exc.code}"
            return {"ok": False, "status": exc.code, "error_code": str(code), "detail": err_body}
        except (OSError, TimeoutError) as exc:
            return {"ok": False, "status": 503, "error_code": "PLANE_UNREACHABLE", "detail": str(exc)[:200]}

    def call_tool(self, name: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
        if name not in TOOL_MAP:
            return {"ok": False, "status": 400, "error_code": "UNKNOWN_TOOL", "detail": f"unknown tool {name!r}"}
        a = dict(args or {})
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
            res = self._http("GET", f"{cu}/frame/{urllib.parse.quote(str(a['view']), safe='')}.jpg", token=ct)
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
            return self._http("POST", f"{fu}/api/fleet/pipeline/cell-tasks", token=ft, body=payload, headers=hdrs)
        if name == "job_status":
            jid = urllib.parse.quote(str(a["job_id"]), safe="")
            if a.get("plane") == "learning":
                return self._http("GET", f"{lu}/api/learning/canonical/runs/{jid}", token=lt)
            return self._http("GET", f"{cu}/jobs/{jid}", token=ct)
        if name == "cell_open_human_request":
            return self._http("POST", f"{fu}/api/fleet/person-requests", token=ft, body=a)
        if name == "cell_capture_clip":
            return self._http("POST", f"{cu}/jobs/capture_clip", token=ct, body=a)
        if name == "cell_dataset_pipeline":
            stage = a.pop("stage", "")
            job = "convert_episodes" if stage == "convert" else "transfer_dataset" if stage == "transfer" else ""
            if not job:
                return {"ok": False, "status": 400, "error_code": "INVALID_STAGE", "detail": "stage must be 'convert' or 'transfer'"}
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


def serve_mcp_stdio(bridge: RosyAgentBridge, stdin=sys.stdin, stdout=sys.stdout) -> int:
    """Handle line-delimited MCP JSON-RPC requests on stdio."""
    for line in stdin:
        s = line.strip()
        if not s:
            continue
        msg = json.loads(s)
        req_id, method = msg.get("id"), msg.get("method")
        if req_id is None:
            continue
        if method == "initialize":
            result = {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                      "serverInfo": {"name": "rosy-agent-bridge", "version": "1.0.0"}}
        elif method == "tools/list":
            result = {"tools": list(TOOL_SPECS)}
        elif method == "tools/call":
            p = msg.get("params") or {}
            res = bridge.call_tool(str(p.get("name") or ""), p.get("arguments") or {})
            result = {"content": [{"type": "text", "text": json.dumps(res, ensure_ascii=False)}], "isError": not res.get("ok")}
        else:
            stdout.write(json.dumps({"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"unknown method {method}"}}) + "\n")
            stdout.flush()
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
