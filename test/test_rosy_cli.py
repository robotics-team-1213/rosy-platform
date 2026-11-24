"""Tests for `rosy_cli` 1-call composite workflow, local file outputs, CAS wiring, and D-226 hygiene."""
from __future__ import annotations

import ast
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import sys
import threading
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "remote"))

import rosy_cli as cli  # noqa: E402
from secret_scan import scan_files  # noqa: E402


def _serve_mock(routes: dict[tuple[str, str], tuple[int, Any, dict[str, str]]]):
    recorded: list[tuple[str, str, dict | None]] = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_a): pass

        def _handle(self, method: str):
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            body = json.loads(raw.decode("utf-8")) if raw else None
            path = self.path.split("?", 1)[0]
            recorded.append((method, self.path, body))
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


def test_rosy_cli_composite_workflow_and_partial_fault_tolerance(tmp_path: Path, capsys, monkeypatch):
    jpg = b"\xff\xd8\xff\xe0\x00\x10JFIF\xff\xd9"
    bundle = {
        "bundle_id": "20261124T090000Z-arm_b-fault-112233",
        "arm_id": "arm_b",
        "cell_id": "cell_ab",
        "executor_mode": "act_paced",
        "context_sha256": "b" * 64,
        "freshness": {"still_valid_for_action": True},
        "measurement": {
            "attempt_cause": "contact", "stage": "pick", "result": "stopped",
            "trace_ref": {"file": "trace-tail.jsonl"},
        },
        "visual": {"frames": [{"file": "wrist-00.jpg"}, {"file": "top-01.jpg"}]},
        "history_and_constraints": {
            "measured_vetoes": ["ARM_FAULT"],
            "allowed_fallback_menu": [
                {"verb": "escalate_human", "preconditions_met": True},
                {"verb": "propose_ik_fallback_for_policy", "preconditions_met": True},
                {"verb": "home_unwedge", "preconditions_met": False},
            ],
        },
    }
    cell_srv, cell_url, _ = _serve_mock({
        ("GET", "/readiness"): (200, {"cell_state_gen": 12, "allowed_tiers_now": [0, 1], "blocking_refusals": [], "arms": {"arm_b": {"folded": False, "fault": "contact"}}}, {}),
        ("GET", "/queue"): (200, {"active": []}, {}),
        ("GET", "/jobs"): (200, [], {}),
        ("GET", "/failures"): (200, {"bundles": [{"bundle_id": bundle["bundle_id"], "arm_id": "arm_b", "kind": "fault"}]}, {}),
        ("GET", "/failures/latest"): (200, bundle, {}),
        ("GET", f"/failures/{bundle['bundle_id']}/assets/wrist-00.jpg"): (200, jpg, {"Content-Type": "image/jpeg"}),
        ("GET", f"/failures/{bundle['bundle_id']}/assets/top-01.jpg"): (200, jpg, {"Content-Type": "image/jpeg"}),
        ("GET", f"/failures/{bundle['bundle_id']}/assets/trace-tail.jsonl"): (200, b'{"a":1}\n{"b":2}\n', {"Content-Type": "application/x-ndjson"}),
        ("GET", "/frame/top.jpg"): (200, jpg, {"X-Frame-Seq": "77"}),
    })
    fleet_srv, fleet_url, fleet_log = _serve_mock({
        ("GET", "/api/fleet/state"): (200, {"fleet": {"name": "rosy-site", "online": 1, "total": 2}, "robots": [{"robot_id": "rosy_45", "online": True}]}, {}),
        ("GET", "/api/fleet/pipeline/cells/cell_s/readiness"): (200, {"cell_id": "cell_s", "cell_phase": "IDLE", "readiness_digest": "d-s", "authority_epoch": 3, "dispatch_generation": 4, "stop_generation": 1}, {}),
        ("GET", "/api/fleet/pipeline/cells/cell_ab/readiness"): (200, {"cell_id": "cell_ab", "cell_phase": "ABORTED", "readiness_digest": "d-ab", "authority_epoch": 3, "dispatch_generation": 8, "stop_generation": 2}, {}),
        ("POST", "/api/fleet/pipeline/cell-tasks"): (200, {"ok": True, "task": {"task_id": "t-new", "status": "PROPOSED"}}, {}),
    })
    cfg_path = tmp_path / "bridge.json"
    cfg_path.write_text(json.dumps({"cell_url": cell_url, "fleet_url": fleet_url}), encoding="utf-8")
    try:
        # 1. schema
        assert cli.main(["schema"]) == 0
        assert len(json.loads(capsys.readouterr().out)) == 18
        assert cli.main(["schema", "cell_frame"]) == 0
        assert json.loads(capsys.readouterr().out)["name"] == "cell_frame"
        assert cli.main(["schema", "no_such_tool"]) == 1
        capsys.readouterr()

        # 2. snapshot (saves raw file when --out-dir given)
        snap_dir = tmp_path / "snap"
        assert cli.main(["--config", str(cfg_path), "snapshot", "--out-dir", str(snap_dir)]) == 0
        snap = json.loads(capsys.readouterr().out)
        assert snap["ok"] and snap["arm_cell"]["cell_state_gen"] == 12 and (snap_dir / "snapshot.json").is_file()
        assert snap["fleet"]["robots"][0]["robot_id"] == "rosy_45"

        # 3. snapshot partial fault tolerance (Fleet down, Cell still up -> ok=True)
        bad_cfg = tmp_path / "bad_fleet.json"
        bad_cfg.write_text(json.dumps({"cell_url": cell_url, "fleet_url": "http://127.0.0.1:9"}), encoding="utf-8")
        assert cli.main(["--config", str(bad_cfg), "snapshot", "--cell", "cell_s"]) == 0
        part = json.loads(capsys.readouterr().out)
        assert part["ok"] and part["fleet"]["ok"] is False and part["arm_cell"]["ok"] is True

        # 4. frame --out (no image_b64 in stdout, JPEG written to disk)
        frame_out = tmp_path / "frames" / "top.jpg"
        assert cli.main(["--config", str(cfg_path), "frame", "top", "--out", str(frame_out)]) == 0
        fmeta = json.loads(capsys.readouterr().out)
        assert fmeta["ok"] and "image_b64" not in fmeta and frame_out.read_bytes() == jpg

        # 5. diagnose (1-call bundle + assets + live view + cas_context.json)
        diag_dir = tmp_path / "diag"
        assert cli.main(["--config", str(cfg_path), "diagnose", "--arm", "arm_b", "--views", "top", "--out-dir", str(diag_dir)]) == 0
        diag = json.loads(capsys.readouterr().out)
        assert diag["ok"] and diag["bundle_id"] == bundle["bundle_id"]
        assert (diag_dir / "wrist-00.jpg").read_bytes() == jpg
        assert (diag_dir / "live-top.jpg").read_bytes() == jpg
        assert (diag_dir / "trace-tail.jsonl").is_file()
        assert (diag_dir / "cas_context.json").is_file()

        # 6. propose --from (disallowed verb blocked locally, dry-run & live POST carry CAS fields)
        assert cli.main(["--config", str(cfg_path), "propose", "--from", str(diag_dir), "--verb", "home_unwedge"]) == 1
        assert json.loads(capsys.readouterr().out)["error_code"] == "VERB_NOT_ALLOWED"

        assert cli.main(["--config", str(cfg_path), "propose", "--from", str(diag_dir), "--verb", "propose_ik_fallback_for_policy", "--dry-run"]) == 0
        dry = json.loads(capsys.readouterr().out)
        assert dry["dry_run"] and dry["payload"]["expected_readiness_digest"] == "d-ab"
        assert cli.main(["--config", str(cfg_path), "propose", "--from", str(diag_dir), "--verb", "propose_ik_fallback_for_policy", "--tier", "2", "--dry-run"]) == 0
        dry_t2 = json.loads(capsys.readouterr().out)
        assert dry_t2["payload"]["request_key"] != dry["payload"]["request_key"]

        assert cli.main(["--config", str(cfg_path), "propose", "--from", str(diag_dir), "--verb", "propose_ik_fallback_for_policy", "--preset", "s5_tier2_arm_b"]) == 0
        prop = json.loads(capsys.readouterr().out)
        assert prop["ok"]
        sent = fleet_log[-1][2]
        assert sent["propose"] is True and sent["expected_dispatch_generation"] == 8 and sent["expected_context_sha256"] == "b" * 64

        # 6b. diagnose ROSY_SCRATCH fallback & unset fail-closed + unsafe bundle_id guard
        monkeypatch.delenv("ROSY_SCRATCH", raising=False)
        assert cli.main(["--config", str(cfg_path), "diagnose", "--arm", "arm_b"]) == 1
        assert json.loads(capsys.readouterr().out)["error_code"] == "INVALID_ARGS"
        scratch_dir = tmp_path / "scratch"
        monkeypatch.setenv("ROSY_SCRATCH", str(scratch_dir))
        assert cli.main(["--config", str(cfg_path), "diagnose", "--arm", "arm_b"]) == 0
        capsys.readouterr()
        assert (scratch_dir / "rosy-diagnose" / bundle["bundle_id"] / "cas_context.json").is_file()

        bad_srv, bad_url, _ = _serve_mock({("GET", "/failures/latest"): (200, {"bundle_id": "../../evil"}, {})})
        try:
            bad_b_cfg = tmp_path / "bad_bundle.json"
            bad_b_cfg.write_text(json.dumps({"cell_url": bad_url, "fleet_url": fleet_url}), encoding="utf-8")
            assert cli.main(["--config", str(bad_b_cfg), "diagnose"]) == 1
            assert json.loads(capsys.readouterr().out)["error_code"] == "INVALID_UPSTREAM_RESPONSE"
        finally:
            bad_srv.shutdown(); bad_srv.server_close()

        # 7. call passthrough
        assert cli.main(["--config", str(cfg_path), "call", "cell_readiness"]) == 0
        assert json.loads(capsys.readouterr().out)["data"]["cell_state_gen"] == 12
    finally:
        cell_srv.shutdown(); cell_srv.server_close()
        fleet_srv.shutdown(); fleet_srv.server_close()


def test_rosy_cli_is_stdlib_only_no_subprocess_and_d226_clean():
    cli_path = ROOT / "tools/remote/rosy_cli.py"
    tree = ast.parse(cli_path.read_text(encoding="utf-8"))
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split(".")[0])
    assert (imports - {"rosy_agent_bridge"}) <= set(sys.stdlib_module_names)
    assert "subprocess" not in imports
    assert scan_files([cli_path, Path(__file__)], root=ROOT) == []
