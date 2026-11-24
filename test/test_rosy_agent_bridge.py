"""PR-7+ tests: stdlib-only 17-tool bridge across 3 HTTP planes, MCP stdio multimodal, server parity, and D-226 hygiene."""
from __future__ import annotations

import argparse
import ast
import hashlib
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
sys.path.insert(0, str(ROOT / "deploy" / "robot" / "omx"))

import cell_job_spec as cjs  # noqa: E402
import cell_media_job_spec as cmjs  # noqa: E402
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


def test_all_17_tools_mcp_stdio_and_error_handling(tmp_path: Path):
    jpg = b"\xff\xd8\xff\xd9"
    trace_line = '{"event":"start"}\n{"event":"stop"}\n'
    cell_srv, cell_url, cell_log = _serve_mock({
        ("GET", "/readiness"): (200, {"schema": "rosy.cell-readiness.v1", "cell_state_gen": 5}, {"Set-Cookie": "sid=top-secret"}),
        ("GET", "/failures"): (200, {"bundles": [{"bundle_id": "b1"}], "cell_state_gen": 5}, {}),
        ("GET", "/failures/latest"): (200, {"bundle_id": "b1", "context_sha256": "a" * 64}, {}),
        ("GET", "/failures/b1/assets/top-00.jpg"): (200, jpg, {"Content-Type": "image/jpeg", "ETag": '"img-1"'}),
        ("GET", "/failures/b1/assets/trace-tail.jsonl"): (200, trace_line.encode("utf-8"), {"Content-Type": "text/plain; charset=utf-8"}),
        ("GET", "/frame/top.jpg"): (200, jpg, {"X-Frame-Seq": "42", "ETag": '"et42"'}),
        ("GET", "/frame/arm_s_top.jpg"): (200, jpg, {"X-Frame-Seq": "43"}),
        ("GET", "/queue"): (200, {"active": []}, {}),
        ("GET", "/jobs"): (200, [{"id": "j-upkeep", "exit": 0}], {}),
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
        ("GET", "/api/fleet/state"): (200, {"fleet": {"online": 1, "total": 3}, "robots": [{"robot_id": "rosy_45"}]}, {}),
        ("GET", "/api/fleet/pipeline/cells/cell_s/readiness"): (200, {"cell_id": "cell_s", "dispatch_generation": 9}, {}),
        ("GET", "/api/fleet/pipeline/cell-tasks"): (200, {"tasks": [{"task_id": "t1", "status": "PROPOSED"}]}, {}),
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
        ("POST", "/api/fleet/person-requests"): (409, {"detail": {"code": "STALE_FAILURE_CONTEXT", "cookie_leak": "rosy_sess=supersecretcookie99"}}, {}),
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
        img_asset = bridge.call_tool("cell_failure_asset", {"bundle_id": "b1", "filename": "top-00.jpg"})
        assert img_asset["ok"] and img_asset["mime_type"] == "image/jpeg" and img_asset["bytes_len"] == len(jpg)
        txt_asset = bridge.call_tool("cell_failure_asset", {"bundle_id": "b1", "filename": "trace-tail.jsonl"})
        assert txt_asset["ok"] and "stop" in txt_asset["text"] and txt_asset["truncated"] is False
        assert bridge.call_tool("cell_failure_asset", {"bundle_id": "..", "filename": "x"})["error_code"] == "INVALID_ARGS"
        fr = bridge.call_tool("cell_frame", {"view": "top"})
        assert fr["ok"] and fr["mime_type"] == "image/jpeg" and fr["frame_headers"]["X-Frame-Seq"] == "42"
        assert bridge.call_tool("cell_frame", {"view": "arm_s_top"})["ok"]
        q_res = bridge.call_tool("cell_queue", {"include_jobs": True, "include_failures": True, "arm": "arm_s", "limit": 5})
        assert q_res["ok"] and q_res["data"]["queue"] == {"active": []} and len(q_res["data"]["jobs"]) == 1
        assert len(q_res["data"]["failures"]["bundles"]) == 1
        assert bridge.call_tool("cell_upkeep_check", {"manifest": "cell-u.json", "out": "upkeep.json"})["data"]["id"] == "j-upkeep"
        assert bridge.call_tool("cell_dry_run", {
            "config": "c.json", "catalog": "k.json", "roi": [0, 0, 10, 10],
            "source": "inbound", "dest": "outbound", "object": "box", "colour": "orange", "layers_below": 1,
        })["data"]["id"] == "j-dry"
        assert bridge.call_tool("fleet_state")["data"]["robots"][0]["robot_id"] == "rosy_45"
        assert bridge.call_tool("fleet_cell_readiness", {"cell_id": "cell_s"})["data"]["dispatch_generation"] == 9
        assert bridge.call_tool("fleet_cell_tasks", {"cell_id": "cell_s", "status": "PROPOSED"})["data"]["tasks"][0]["task_id"] == "t1"
        prop = bridge.call_tool("fleet_propose_cell_task", {
            "cell_id": "cell_s", "preset": "s3_act_policy", "robot_id": "rosy_45",
            "tier": 1, "execution_mode": "act_policy", "max_chunks": 4, "request_key": "rk-9",
        })
        assert prop["ok"] and fleet_log[-1][3]["propose"] is True and fleet_log[-1][2]["idempotency-key"] == "rk-9"
        assert bridge.call_tool("job_status", {"job_id": "j-upkeep", "plane": "cell"})["data"]["exit"] == 0
        assert bridge.call_tool("job_status", {"job_id": "run-1", "plane": "learning"})["data"]["status"] == "succeeded"
        assert bridge.call_tool("cell_open_human_request", {"kind": "clear_area", "text": "inspect", "why": "stall"})["data"]["id"] == "req-1"
        assert bridge.call_tool("cell_capture_clip", {"view": "top", "duration_s": 5, "fps": 10, "out_dir": "clips"})["data"]["id"] == "j-clip"
        assert bridge.call_tool("cell_dataset_pipeline", {"stage": "convert", "episodes": "e", "fps": 15, "outcome": "success"})["data"]["id"] == "j-conv"
        assert bridge.call_tool("cell_dataset_pipeline", {"stage": "transfer", "collection": "c"})["data"]["id"] == "j-xfer"
        assert bridge.call_tool("learning_run_job", {"kind": "collect_dart", "arm_id": "arm_a", "request_id": "req-learn-1"})["data"]["id"] == "run-1"
        assert bridge.call_tool("learning_stage_bundle", {"run_id": "run-1", "target_dir": "models/s"})["data"]["id"] == "j-stage"
        stage_req = next(b for m, p, _, b in cell_log if m == "POST" and p == "/jobs/stage_policy_bundle")
        exp_mf_sha = hashlib.sha256(json.dumps({"schema": "rosy.canonical-bundle-manifest.v1", "files": []}).encode("utf-8")).hexdigest()
        assert stage_req == {"run_id": "run-1", "target_dir": "models/s", "expected_manifest_sha256": exp_mf_sha}
        assert any(path == "/api/learning/canonical/runs/run-1/bundle-manifest" for _, path, _, _ in learn_log)

        # Schema & safety hardening through call_tool().
        assert bridge.call_tool("cell_upkeep_check", {})["error_code"] == "INVALID_ARGS"
        assert bridge.call_tool("cell_capture_clip", {"view": "top"})["error_code"] == "INVALID_ARGS"
        assert bridge.call_tool("cell_capture_clip", {"view": "top", "duration_s": 5.5})["error_code"] == "INVALID_ARGS"
        assert bridge.call_tool("learning_run_job", {"kind": "collect_dart", "arm_id": "arm_a"})["error_code"] == "INVALID_ARGS"
        assert bridge.call_tool("cell_dry_run", {"config": "c.json", "catalog": "k.json", "roi": [0], "source": "a", "dest": "b", "person_at_switch": True})["error_code"] == "INVALID_ARGS"
        assert bridge.call_tool("fleet_propose_cell_task", {"cell_id": "cell_s", "propose": False})["error_code"] == "INVALID_ARGS"
        assert bridge.call_tool("job_status", {"job_id": "j-nonjson"})["error_code"] == "INVALID_UPSTREAM_RESPONSE"
        assert bridge.call_tool("job_status", {"job_id": "j-redir"})["status"] == 302
        assert bridge._http("GET", (ROOT / "LICENSE").as_uri())["error_code"] == "INVALID_URL_SCHEME"

        # Cookie auth: Origin on POST and full redaction of cookie value in error payloads.
        cookie_bridge = br.RosyAgentBridge(br.BridgeConfig(
            cell_url=cell_url, fleet_url=queued_url, fleet_cookie="rosy_sess=supersecretcookie99; path=/", learning_url=learn_url,
        ))
        assert cookie_bridge.call_tool("fleet_propose_cell_task", {"cell_id": "cell_s"})["error_code"] == "PROPOSE_NOT_ENFORCED"
        r409 = cookie_bridge.call_tool("cell_open_human_request", {"kind": "other", "text": "x", "why": "y"})
        assert not r409["ok"] and r409["status"] == 409 and r409["error_code"] == "STALE_FAILURE_CONTEXT"
        assert "supersecretcookie99" not in json.dumps(r409)

        cookie_bridge_ok = br.RosyAgentBridge(br.BridgeConfig(cell_url=cell_url, fleet_url=fleet_url, fleet_cookie="rosy_sess=tok123456"))
        assert cookie_bridge_ok.call_tool("fleet_propose_cell_task", {"cell_id": "cell_s"})["ok"]
        assert fleet_log[-1][2]["cookie"] == "rosy_sess=tok123456"
        assert fleet_log[-1][2]["origin"] == fleet_url

        bad_bridge = br.RosyAgentBridge(br.BridgeConfig(cell_url=cell_url, fleet_url=queued_url, fleet_token="f-secret-tok", learning_url=learn_url, learning_token="learn-tok"))
        r403 = bad_bridge.call_tool("job_status", {"job_id": "run-403", "plane": "learning"})
        assert not r403["ok"] and r403["status"] == 403 and "learn-tok" not in json.dumps(r403)

        with pytest.raises(FileNotFoundError):
            br._read_tok(None, tmp_path / "missing.token", "ROSY_CELL_JOB_TOKEN")

        # MCP stdio initialize version negotiation + ping + tools/list + multimodal image blocks + error handling.
        stdin = io.StringIO(
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26"}}) + "\n"
            + json.dumps({"jsonrpc": "2.0", "id": 2, "method": "ping"}) + "\n"
            + json.dumps({"jsonrpc": "2.0", "id": 3, "method": "tools/list"}) + "\n"
            + json.dumps({"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "cell_readiness", "arguments": {}}}) + "\n"
            + json.dumps({"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "cell_frame", "arguments": {"view": "top"}}}) + "\n"
            + json.dumps({"jsonrpc": "2.0", "id": 6, "method": "tools/call", "params": {"name": "cell_failure_asset", "arguments": {"bundle_id": "b1", "filename": "top-00.jpg"}}}) + "\n"
            + "{not-json\n"
            + "[]\n"
            + json.dumps({"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": [1]}) + "\n"
        )
        stdout = io.StringIO()
        assert br.serve_mcp_stdio(bridge, stdin=stdin, stdout=stdout) == 0
        replies = [json.loads(line) for line in stdout.getvalue().splitlines()]
        assert replies[0]["result"]["protocolVersion"] == "2025-03-26"
        assert replies[1]["result"] == {}
        assert len(replies[2]["result"]["tools"]) == 17
        assert json.loads(replies[3]["result"]["content"][0]["text"])["data"]["cell_state_gen"] == 5
        frame_content = replies[4]["result"]["content"]
        assert len(frame_content) == 2 and frame_content[1]["type"] == "image" and frame_content[1]["mimeType"] == "image/jpeg"
        assert "image_b64" not in json.loads(frame_content[0]["text"])
        asset_content = replies[5]["result"]["content"]
        assert len(asset_content) == 2 and asset_content[1]["type"] == "image" and "image_b64" not in json.loads(asset_content[0]["text"])
        assert replies[6]["error"]["code"] == -32700
        assert replies[7]["error"]["code"] == -32600
        assert replies[8]["error"]["code"] == -32602
    finally:
        for s in (cell_srv, fleet_srv, learn_srv, queued_srv):
            s.shutdown(); s.server_close()


def test_config_file_and_cookie_file_loading(tmp_path: Path, monkeypatch):
    (tmp_path / "cell.token").write_text("cell-file-tok\n", encoding="utf-8")
    (tmp_path / "cookie.json").write_text(json.dumps({"cookie": "rosy_sess=from-json"}), encoding="utf-8")
    (tmp_path / "plain.cookie").write_text("Cookie: rosy_sess=from-plain\n", encoding="utf-8")
    cfg_path = tmp_path / "bridge.json"
    cfg_path.write_text(json.dumps({
        "cell_url": "http://127.0.0.1:9781",
        "cell_token_file": "cell.token",
        "fleet_url": "https://127.0.0.1:9443",
        "fleet_cookie_file": "cookie.json",
        "timeout_s": 22.5,
    }), encoding="utf-8")
    for env_k in ("ROSY_AGENT_BRIDGE_CONFIG", "ROSY_CELL_JOB_URL", "ROSY_CELL_JOB_TOKEN", "ROSY_FLEET_URL",
                  "ROSY_FLEET_TOKEN", "ROSY_FLEET_COOKIE", "ROSY_FLEET_COOKIE_FILE", "ROSY_FLEET_CA_FILE",
                  "ROSY_LEARNING_URL", "ROSY_LEARNING_TOKEN"):
        monkeypatch.delenv(env_k, raising=False)
    ns = argparse.Namespace(
        config=cfg_path, cell_url=None, fleet_url=None, learning_url=None,
        cell_token_file=None, fleet_token_file=None, fleet_cookie_file=None,
        fleet_ca_file=None, learning_token_file=None, timeout_s=None,
    )
    cfg = br.build_config(ns)
    assert cfg.cell_url == "http://127.0.0.1:9781"
    assert cfg.cell_token == "cell-file-tok"
    assert cfg.fleet_cookie == "rosy_sess=from-json"
    assert cfg.timeout_s == 22.5
    assert br._read_cookie(None, tmp_path / "plain.cookie", "ROSY_FLEET_COOKIE") == "rosy_sess=from-plain"


def test_bridge_schemas_match_cell_job_specs():
    spec_pairs = [
        ("cell_dry_run", cjs.JOBS["auto_pick_dry_run"]),
        ("cell_upkeep_check", cmjs.MEDIA_JOBS["upkeep_check"]),
        ("cell_capture_clip", cmjs.MEDIA_JOBS["capture_clip"]),
    ]
    for tool_name, job in spec_pairs:
        schema = br.TOOL_MAP[tool_name]["inputSchema"]
        assert set(schema["required"]) == set(job["params"].keys()), tool_name
        assert set(schema["properties"].keys()) == set(job["params"].keys()) | set(job.get("optional", {}).keys()), tool_name

    conv = cmjs.MEDIA_JOBS["convert_episodes"]
    xfer = cmjs.MEDIA_JOBS["transfer_dataset"]
    ds_props = set(br.TOOL_MAP["cell_dataset_pipeline"]["inputSchema"]["properties"].keys())
    assert (set(conv["params"]) | set(conv["optional"]) | set(xfer["params"]) | set(xfer["optional"])) <= ds_props

    stage = cmjs.MEDIA_JOBS["stage_policy_bundle"]
    st_props = set(br.TOOL_MAP["learning_stage_bundle"]["inputSchema"]["properties"].keys())
    assert set(stage["params"]) <= st_props


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
