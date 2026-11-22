"""PR-7 tests: stdlib-only 12-tool agy bridge across 3 HTTP planes, MCP stdio, 409/403 errors, and D-226 hygiene."""
from __future__ import annotations

import ast
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import sys
import threading
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "remote"))

import rosy_agent_bridge as br  # noqa: E402
from secret_scan import scan_files  # noqa: E402


def _serve_mock(routes: dict[tuple[str, str], tuple[int, Any, dict[str, str]]]):
    recorded: list[tuple[str, str, dict[str, str], dict | None]] = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_a): pass

        def _handle(self, method: str):
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            body = json.loads(raw.decode("utf-8")) if raw else None
            path = self.path.split("?", 1)[0]
            recorded.append((method, self.path, {k.lower(): v for k, v in self.headers.items()}, body))
            status, payload, hdrs = routes.get((method, path), (404, {"code": "NOT_FOUND"}, {}))
            out = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", hdrs.get("Content-Type") or ("image/jpeg" if isinstance(payload, bytes) else "application/json"))
            self.send_header("Content-Length", str(len(out)))
            for k, v in hdrs.items():
                if k.lower() != "content-type":
                    self.send_header(k, v)
            self.end_headers()
            self.wfile.write(out)

        def do_GET(self): self._handle("GET")
        def do_POST(self): self._handle("POST")

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}", recorded


def test_all_12_tools_mcp_stdio_and_error_handling(tmp_path: Path):
    jpg = b"\xff\xd8\xff\xd9"
    cell_srv, cell_url, _ = _serve_mock({
        ("GET", "/readiness"): (200, {"schema": "rosy.cell-readiness.v1", "cell_state_gen": 5}, {"Set-Cookie": "sid=top-secret"}),
        ("GET", "/failures/latest"): (200, {"bundle_id": "b1", "context_sha256": "a" * 64}, {}),
        ("GET", "/frame/top.jpg"): (200, jpg, {"X-Frame-Seq": "42", "ETag": '"et42"'}),
        ("GET", "/frame/arm_s_top.jpg"): (200, jpg, {"X-Frame-Seq": "43"}),
        ("POST", "/jobs/upkeep_check"): (202, {"id": "j-upkeep"}, {}),
        ("POST", "/jobs/auto_pick_dry_run"): (202, {"id": "j-dry"}, {}),
        ("GET", "/jobs/j-upkeep"): (200, {"id": "j-upkeep", "exit": 0}, {}),
        ("GET", "/jobs/j-nonjson"): (200, b"\x80rawbytes", {"Content-Type": "application/octet-stream"}),
        ("GET", "/jobs/j-redir"): (302, {"ok": True}, {"Location": "http://127.0.0.1:9/leak"}),
        ("POST", "/jobs/capture_clip"): (202, {"id": "j-clip"}, {}),
        ("POST", "/jobs/convert_episodes"): (202, {"id": "j-conv"}, {}),
        ("POST", "/jobs/transfer_dataset"): (202, {"id": "j-xfer"}, {}),
        ("POST", "/jobs/stage_policy_bundle"): (202, {"id": "j-stage"}, {}),
    })
    fleet_srv, fleet_url, fleet_log = _serve_mock({
        ("POST", "/api/fleet/pipeline/cell-tasks"): (200, {"ok": True, "task": {"task_id": "t1", "status": "PROPOSED"}}, {}),
        ("POST", "/api/fleet/person-requests"): (200, {"id": "req-1", "motion": False}, {}),
    })
    learn_srv, learn_url, learn_log = _serve_mock({
        ("POST", "/api/learning/canonical/jobs"): (200, {"id": "run-1", "status": "launching"}, {}),
        ("GET", "/api/learning/canonical/runs/run-1"): (200, {"id": "run-1", "status": "succeeded"}, {}),
        ("GET", "/api/learning/canonical/runs/run-1/bundle-manifest"): (200, {"schema": "rosy.canonical-bundle-manifest.v1", "files": []}, {}),
        ("GET", "/api/learning/canonical/runs/run-403"): (403, {"error": "forbidden fleet-tok learn-tok"}, {}),
    })
    queued_srv, queued_url, _ = _serve_mock({
        ("POST", "/api/fleet/pipeline/cell-tasks"): (200, {"ok": True, "task": {"task_id": "t2", "status": "QUEUED"}}, {}),
        ("POST", "/api/fleet/person-requests"): (409, {"detail": {"code": "STALE_FAILURE_CONTEXT"}}, {}),
    })
    try:
        bridge = br.RosyAgentBridge(br.BridgeConfig(
            cell_url=cell_url, cell_token="cell-tok-012345",
            fleet_url=fleet_url, fleet_token="fleet-tok-012345",
            learning_url=learn_url, learning_token="learn-tok-012345",
        ))
        r_ready = bridge.call_tool("cell_readiness")
        assert r_ready["data"]["cell_state_gen"] == 5 and "Set-Cookie" not in r_ready["headers"]
        assert bridge.call_tool("cell_failure_context", {"arm": "arm_s"})["data"]["bundle_id"] == "b1"
        fr = bridge.call_tool("cell_frame", {"view": "top"})
        assert fr["ok"] and fr["frame_headers"]["X-Frame-Seq"] == "42"
        assert bridge.call_tool("cell_frame", {"view": "arm_s_top"})["ok"]
        assert bridge.call_tool("cell_upkeep_check", {"manifest": "cell-u.json"})["data"]["id"] == "j-upkeep"
        assert bridge.call_tool("cell_dry_run", {"config": "c.json", "catalog": "k.json", "roi": [0, 0, 10, 10]})["data"]["id"] == "j-dry"
        prop = bridge.call_tool("fleet_propose_cell_task", {"cell_id": "cell_s", "request_key": "rk-9"})
        assert prop["ok"] and fleet_log[-1][3]["propose"] is True and fleet_log[-1][2]["idempotency-key"] == "rk-9"
        assert bridge.call_tool("job_status", {"job_id": "j-upkeep", "plane": "cell"})["data"]["exit"] == 0
        assert bridge.call_tool("job_status", {"job_id": "run-1", "plane": "learning"})["data"]["status"] == "succeeded"
        assert bridge.call_tool("cell_open_human_request", {"kind": "clear_area", "text": "inspect", "why": "stall"})["data"]["id"] == "req-1"
        assert bridge.call_tool("cell_capture_clip", {"view": "top"})["data"]["id"] == "j-clip"
        assert bridge.call_tool("cell_dataset_pipeline", {"stage": "convert", "episodes": "e"})["data"]["id"] == "j-conv"
        assert bridge.call_tool("cell_dataset_pipeline", {"stage": "transfer", "collection": "c"})["data"]["id"] == "j-xfer"
        assert bridge.call_tool("learning_run_job", {"kind": "collect_dart", "arm_id": "arm_a"})["data"]["id"] == "run-1"
        assert bridge.call_tool("learning_stage_bundle", {"run_id": "run-1", "target_dir": "models/s"})["data"]["id"] == "j-stage"
        assert any(path == "/api/learning/canonical/runs/run-1/bundle-manifest" for _, path, _, _ in learn_log)

        # Schema & safety hardening through call_tool().
        assert bridge.call_tool("cell_dry_run", {"config": "c.json", "catalog": "k.json", "roi": [0], "person_at_switch": True})["error_code"] == "INVALID_ARGS"
        assert bridge.call_tool("fleet_propose_cell_task", {"cell_id": "cell_s", "propose": False})["error_code"] == "INVALID_ARGS"
        assert bridge.call_tool("job_status", {"job_id": "j-nonjson"})["error_code"] == "INVALID_UPSTREAM_RESPONSE"
        assert bridge.call_tool("job_status", {"job_id": "j-redir"})["status"] == 302
        assert bridge._http("GET", (ROOT / "LICENSE").as_uri())["error_code"] == "INVALID_URL_SCHEME"

        bad_bridge = br.RosyAgentBridge(br.BridgeConfig(cell_url=cell_url, fleet_url=queued_url, fleet_token="f-secret-tok", learning_url=learn_url, learning_token="learn-tok"))
        assert bad_bridge.call_tool("fleet_propose_cell_task", {"cell_id": "cell_s"})["error_code"] == "PROPOSE_NOT_ENFORCED"
        r409 = bad_bridge.call_tool("cell_open_human_request", {"kind": "other", "text": "x", "why": "y"})
        assert not r409["ok"] and r409["status"] == 409 and r409["error_code"] == "STALE_FAILURE_CONTEXT"
        r403 = bad_bridge.call_tool("job_status", {"job_id": "run-403", "plane": "learning"})
        assert not r403["ok"] and r403["status"] == 403 and "learn-tok" not in json.dumps(r403)

        with pytest.raises(FileNotFoundError):
            br._read_tok(None, tmp_path / "missing.token", "ROSY_CELL_JOB_TOKEN")

        # MCP stdio initialize + tools/list + tools/call + error handling (-32700, -32600, -32602).
        stdin = io.StringIO(
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize"}) + "\n"
            + json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}) + "\n"
            + json.dumps({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "cell_readiness", "arguments": {}}}) + "\n"
            + "{not-json\n"
            + "[]\n"
            + json.dumps({"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": [1]}) + "\n"
        )
        stdout = io.StringIO()
        assert br.serve_mcp_stdio(bridge, stdin=stdin, stdout=stdout) == 0
        replies = [json.loads(line) for line in stdout.getvalue().splitlines()]
        assert len(replies[1]["result"]["tools"]) == 12
        assert json.loads(replies[2]["result"]["content"][0]["text"])["data"]["cell_state_gen"] == 5
        assert replies[3]["error"]["code"] == -32700
        assert replies[4]["error"]["code"] == -32600
        assert replies[5]["error"]["code"] == -32602
    finally:
        for s in (cell_srv, fleet_srv, learn_srv, queued_srv):
            s.shutdown(); s.server_close()


def test_bridge_is_stdlib_only_no_subprocess_and_d226_clean():
    bridge_path = ROOT / "tools/remote/rosy_agent_bridge.py"
    tree = ast.parse(bridge_path.read_text(encoding="utf-8"))
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split(".")[0])
    assert imports <= set(sys.stdlib_module_names)
    assert "subprocess" not in imports
    assert scan_files([bridge_path, Path(__file__)], root=ROOT) == []
