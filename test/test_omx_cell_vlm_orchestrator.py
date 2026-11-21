from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
import sys
import threading
import time
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy" / "robot" / "omx"))
import cell_job_api as api  # noqa: E402
from cell_job_client import CellJobClient, CellJobError  # noqa: E402
import cell_vlm_orchestrator as orch  # noqa: E402


def _make_workdir(tmp_path: Path) -> Path:
    for name in ("cell-a.json", "cell-b.json", "catalog-ab.json", "chunks-a.json", "chunks-b.json"):
        (tmp_path / name).write_text("{}", encoding="utf-8")
    (tmp_path / "tools-env-current.sh").write_text("export OMX=~/rosy-test/omx-tools-abc1234/deploy/robot/omx\n", encoding="utf-8")
    return tmp_path


def _start_fake_viewer(available_views=("/frame/top.jpg", "/frame/side.jpg", "/frame/arm_a_wrist.jpg"), empty_views=()):
    allowed = set(available_views)
    empty = set(empty_views)

    class ViewerHandler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass

        def do_GET(self):
            if self.path in allowed or self.path in empty:
                raw = b"" if self.path in empty else b"JPEG:" + self.path.encode("ascii")
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
                return
            self.send_response(404)
            self.end_headers()

    srv = ThreadingHTTPServer(("127.0.0.1", 0), ViewerHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def _arm_configs():
    sha = "a" * 64
    return {
        "arm_a": {
            "config": "cell-a.json",
            "library": "chunks-a.json",
            "catalog": "catalog-ab.json",
            "roi": [10, 20, 100, 120],
            "source": "pallet",
            "dest": "temp_plate_a",
            "operating_profile": "profile-a.json",
            "policy_root": "~/rosy-models/ab_act_3cam",
            "policy_revision": sha,
            "cell_calibration": "cal-a.json",
            "model_calibration": "model-cal-a.json",
            "max_chunks": 3,
        },
        "arm_b": {
            "config": "cell-b.json",
            "library": "chunks-b.json",
            "catalog": "catalog-ab.json",
            "roi": [10, 20, 100, 120],
            "source": "beltend",
            "dest": "pallet",
            "operating_profile": "profile-b.json",
            "mode": "hybrid",
            "policy_root": "~/rosy-models/h1-goal-b-mixed",
            "policy_revision": sha,
            "cell_calibration": "cal-b.json",
            "max_chunks": 3,
        },
    }


def _install_fake_popen(monkeypatch, *, incidents=None, dry_pick=None, live_outputs=None):
    incidents = incidents or {
        "arm_a": {"arm": "arm_a", "local_held": False, "fleet_held": False, "unsent_outbox": 0},
        "arm_b": {"arm": "arm_b", "local_held": False, "fleet_held": False, "unsent_outbox": 0},
    }
    dry_pick = dry_pick or {
        "cell-a.json": (0, {"result": "planned", "attempts": [{"observed": 1, "refused": [], "chosen": {"object": "box"}}]}),
        "cell-b.json": (0, {"result": "planned", "attempts": [{"observed": 2, "refused": [], "chosen": {"object": "box"}}]}),
    }
    live_outputs = live_outputs or {}
    motion_procs = []

    def fake_popen(argv, **kwargs):
        p = Mock()
        p.argv = argv
        fh = kwargs.get("stdout")
        script = argv[3] if len(argv) > 3 and argv[0] == "bash" else ""
        if script == "omx_incident.py":
            arm = argv[argv.index("--arm") + 1]
            payload = incidents[arm]
            if fh is not None:
                fh.write((json.dumps(payload) + "\n").encode("utf-8"))
                fh.flush()
            p._code = 0
        elif script == "cell_auto_pick.py" and "--dry-run" in argv:
            cfg = argv[argv.index("--config") + 1]
            code, payload = dry_pick[cfg]
            if fh is not None:
                fh.write(("choice log line\n" + json.dumps(payload, indent=1) + "\n").encode("utf-8"))
                fh.flush()
            p._code = code
        else:
            p._code = None
            out_row = live_outputs.get(argv[4] if len(argv) > 4 else "")
            if out_row and fh is not None:
                fh.write(("session up\n" + json.dumps(out_row, indent=1) + "\n").encode("utf-8"))
                fh.flush()
            motion_procs.append(p)
        p.poll.side_effect = lambda: p._code
        return p

    monkeypatch.setattr(api.subprocess, "Popen", fake_popen)
    return motion_procs


def test_select_vision_backend_rejects_text_only_and_non_vision_specs():
    for bad in (
        {"provider": "opencode", "model": "zai-coding-plan/glm-5.3-flash"},
        {"provider": "zai", "model": "glm-5.3", "vision": False},
        {"provider": "zai", "model": "glm-5.3"},
        "opencode:zai-coding-plan/glm-5.3-flash",
        "codex:gpt-5-codex",
        ["ollama:qwen3-vl:8b-instruct", "opencode:glm-5.3-flash"],
        {"models": ["ollama:qwen3-vl:8b-instruct"], "arbiter": "claude:sonnet"},
        None,
    ):
        with pytest.raises(ValueError):
            orch.select_vision_backend(bad)
    ok = orch.select_vision_backend({"provider": "ollama", "model": "qwen3-vl:8b-instruct"})
    assert callable(ok)


def test_orchestrator_fails_closed_on_zero_or_empty_frames_and_unreachable_viewer(tmp_path, monkeypatch):
    wd = _make_workdir(tmp_path)
    _install_fake_popen(monkeypatch)
    runner = api.Runner(wd, lock_dir=wd)
    viewer = _start_fake_viewer(available_views=(), empty_views=("/frame/top.jpg",))
    token = "t" * 32
    server = api.make_server("127.0.0.1", 0, token, runner, viewer=f"http://127.0.0.1:{viewer.server_port}")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        client = CellJobClient(f"http://127.0.0.1:{server.server_port}", token=token)
        called = False

        def fail_if_called(*args):
            nonlocal called
            called = True
            return {}

        res = orch.run_once(
            client, fail_if_called, _arm_configs(),
            operator="human_op", execute=True, person_at_switch=True, approve=lambda _: True, poll_s=0.01,
        )
        assert res["status"] == "idle"
        assert res["proposal"]["reason"] == "no camera frames available"
        assert called is False
    finally:
        server.shutdown()
        server.server_close()
        viewer.shutdown()
        viewer.server_close()

    bad_server = api.make_server("127.0.0.1", 0, token, runner, viewer=f"http://127.0.0.1:{viewer.server_port}")
    threading.Thread(target=bad_server.serve_forever, daemon=True).start()
    try:
        bad_client = CellJobClient(f"http://127.0.0.1:{bad_server.server_port}", token=token)
        with pytest.raises(CellJobError) as exc_info:
            orch.propose_next(bad_client, lambda *a: {})
        assert exc_info.value.status_code == 502
    finally:
        bad_server.shutdown()
        bad_server.server_close()


def test_measured_facts_hold_vetoes_and_dry_pick_zero_veto(tmp_path, monkeypatch):
    wd = _make_workdir(tmp_path)
    runner = api.Runner(wd, lock_dir=wd)
    viewer = _start_fake_viewer()
    token = "t" * 32
    server = api.make_server("127.0.0.1", 0, token, runner, viewer=f"http://127.0.0.1:{viewer.server_port}")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        client = CellJobClient(f"http://127.0.0.1:{server.server_port}", token=token)

        # 1. Both arms held -> returns idle without invoking VLM
        _install_fake_popen(
            monkeypatch,
            incidents={
                "arm_a": {"arm": "arm_a", "local_held": True, "local_reason": "torque hold"},
                "arm_b": {"arm": "arm_b", "local_held": False, "fleet_held": True, "fleet_reason": "incident open"},
            },
        )
        vlm_calls = 0

        def fail_vlm(*args):
            nonlocal vlm_calls
            vlm_calls += 1
            return {}

        both_held = orch.run_once(client, fail_vlm, _arm_configs(), operator="human_op", poll_s=0.01)
        assert both_held["status"] == "idle"
        assert "held" in both_held["proposal"]["reason"]
        assert vlm_calls == 0

        # 2. Only arm_a held -> schema restricts arm enum to ["arm_b"]; buggy VLM picking arm_a raises ValueError
        _install_fake_popen(
            monkeypatch,
            incidents={
                "arm_a": {"arm": "arm_a", "local_held": True, "local_reason": "hold"},
                "arm_b": {"arm": "arm_b", "local_held": False, "fleet_held": False, "unsent_outbox": 0},
            },
        )
        seen_schemas = []

        def bad_arm_vlm(prompt, images, schema):
            seen_schemas.append(schema)
            return {"action": "home", "arm": "arm_a", "site": "", "reason": "wrong arm"}

        with pytest.raises(ValueError, match="invalid VLM proposal"):
            orch.run_once(client, bad_arm_vlm, _arm_configs(), operator="human_op", poll_s=0.01)
        assert seen_schemas[0]["properties"]["arm"]["enum"] == ["arm_b"]

        # 3. auto_pick_dry_run exit 1 with observed == 0 injects facts into prompt and vetoes auto_pick -> idle
        _install_fake_popen(
            monkeypatch,
            dry_pick={
                "cell-a.json": (1, {"result": "stopped: empty", "attempts": [{"observed": 0, "refused": []}]}),
                "cell-b.json": (0, {"result": "planned", "attempts": [{"observed": 1, "refused": []}]}),
            },
        )
        seen_prompts = []

        def pick_empty_vlm(prompt, images, schema):
            seen_prompts.append(prompt)
            return {"action": "auto_pick", "arm": "arm_a", "site": "pallet", "reason": "try pick"}

        vetoed = orch.run_once(client, pick_empty_vlm, _arm_configs(), operator="human_op", poll_s=0.01)
        assert "Measured cell facts" in seen_prompts[0]
        assert vetoed["status"] == "idle"
        assert "vetoed auto_pick" in vetoed["proposal"]["reason"]
        assert vetoed["proposal"]["facts"]["dry_pick"]["arm_a"]["observed"] == 0
    finally:
        server.shutdown()
        server.server_close()
        viewer.shutdown()
        viewer.server_close()


def test_client_and_orchestrator_end_to_end(tmp_path, monkeypatch):
    wd = _make_workdir(tmp_path)
    procs = _install_fake_popen(
        monkeypatch,
        live_outputs={"cell_policy_drive.py": {"result": "released", "took_one": True}},
    )
    runner = api.Runner(wd, lock_dir=wd)
    viewer = _start_fake_viewer()
    token = "t" * 32
    server = api.make_server("127.0.0.1", 0, token, runner, viewer=f"http://127.0.0.1:{viewer.server_port}")
    threading.Thread(target=server.serve_forever, daemon=True).start()

    try:
        client = CellJobClient(f"http://127.0.0.1:{server.server_port}", token=token)
        assert client.health() == {"ok": True}

        bad_client = CellJobClient(f"http://127.0.0.1:{server.server_port}", token="wrong" * 8)
        with pytest.raises(CellJobError) as exc_info:
            bad_client.queue()
        assert exc_info.value.status_code == 401

        seen_images = []
        next_proposal = {"action": "cell_policy_drive", "arm": "arm_b", "site": "yard:r3-s2-t1", "reason": "box ready"}

        def fake_vlm(prompt, images, schema):
            seen_images.append(len(images))
            return dict(next_proposal)

        # 1. Propose-only captures 3 views + measured facts and submits no motion job
        proposed = orch.run_once(client, fake_vlm, _arm_configs(), operator="human_op", execute=False, poll_s=0.01)
        assert proposed["status"] == "proposed"
        assert proposed["proposal"]["facts"]["dry_pick"]["arm_b"]["observed"] == 2
        assert seen_images == [3]
        assert procs == []

        # 2. Dry-run cell_policy_drive works without person_at_switch or approve callback
        dry_policy = orch.run_once(
            client, fake_vlm, _arm_configs(),
            operator="human_op", execute=True, dry_run=True, wait=False, poll_s=0.01,
        )
        assert dry_policy["status"] == "submitted" and dry_policy["job"] == "cell_policy_drive"
        dry_argv = procs[-1].argv
        assert dry_argv[0] == "bash" and "--dry-run" in dry_argv
        assert dry_argv[dry_argv.index("--mode") + 1] == "hybrid"
        assert dry_argv[dry_argv.index("--goal-site") + 1] == "yard:r3-s2-t1"
        assert "--model-calibration" not in dry_argv
        procs[-1]._code = 0

        # 3. Dry-run auto_pick routes to auto_pick_dry_run; dry-run home skips safely
        next_proposal = {"action": "auto_pick", "arm": "arm_a", "site": "pallet", "reason": "pick test"}
        dry_pick = orch.run_once(
            client, fake_vlm, _arm_configs(),
            operator="human_op", execute=True, dry_run=True, wait=False, poll_s=0.01,
        )
        assert dry_pick["job"] == "auto_pick_dry_run"
        assert runner.runs[dry_pick["id"]]["argv"][0] == "bash"

        next_proposal = {"action": "home", "arm": "arm_a", "site": "", "reason": "fold home"}
        dry_home = orch.run_once(
            client, fake_vlm, _arm_configs(),
            operator="human_op", execute=True, dry_run=True, wait=False, poll_s=0.01,
        )
        assert dry_home["status"] == "dry_run_skipped"
        assert len(procs) == 1

        # 4. proposer == operator fails BEFORE approve callback is prompted
        next_proposal = {"action": "cell_policy_drive", "arm": "arm_b", "site": "yard:r3-s2-t1", "reason": "live run"}
        approve_called = False

        def track_approve(p):
            nonlocal approve_called
            approve_called = True
            return True

        with pytest.raises(ValueError, match="D-1024"):
            orch.run_once(
                client, fake_vlm, _arm_configs(),
                operator="vlm_orchestrator", proposer="vlm_orchestrator",
                execute=True, person_at_switch=True, approve=track_approve, poll_s=0.01,
            )
        assert approve_called is False

        with pytest.raises(ValueError, match="person_at_switch"):
            orch.run_once(
                client, fake_vlm, _arm_configs(),
                operator="human_op", execute=True, person_at_switch=False, approve=lambda _: True, poll_s=0.01,
            )
        with pytest.raises(ValueError, match="approve callback"):
            orch.run_once(
                client, fake_vlm, _arm_configs(),
                operator="human_op", execute=True, person_at_switch=True, poll_s=0.01,
            )

        rejected = orch.run_once(
            client, fake_vlm, _arm_configs(),
            operator="human_op", execute=True, person_at_switch=True, approve=lambda _: False, poll_s=0.01,
        )
        assert rejected["status"] == "rejected" and len(procs) == 1

        # 5. Live home and live auto_pick wrap through SESSION[arm]
        next_proposal = {"action": "home", "arm": "arm_a", "site": "", "reason": "fold home"}
        live_home = orch.run_once(
            client, fake_vlm, _arm_configs(),
            operator="human_op", execute=True, person_at_switch=True, wait=False, approve=lambda _: True, poll_s=0.01,
        )
        assert live_home["job"] == "home" and procs[-1].argv[0] == "./with-session-arm-a-par.sh"
        procs[-1]._code = 0

        next_proposal = {"action": "auto_pick", "arm": "arm_a", "site": "pallet", "reason": "pick box"}
        live_pick = orch.run_once(
            client, fake_vlm, _arm_configs(),
            operator="human_op", execute=True, person_at_switch=True, wait=False, approve=lambda _: True, poll_s=0.01,
        )
        assert live_pick["job"] == "auto_pick" and procs[-1].argv[0] == "./with-session-arm-a-par.sh"
        procs[-1]._code = 0

        # 6. Live execute with wait=True populates read-only verification without touching choices.json
        next_proposal = {"action": "cell_policy_drive", "arm": "arm_b", "site": "yard:r3-s2-t1", "reason": "live run"}

        def finish_async_and_approve(p):
            before = len(procs)

            def _complete_spawned():
                deadline = time.monotonic() + 2.0
                while len(procs) == before and time.monotonic() < deadline:
                    time.sleep(0.01)
                if len(procs) > before:
                    time.sleep(0.02)
                    procs[-1]._code = 0

            threading.Thread(target=_complete_spawned, daemon=True).start()
            return p["arm"] == "arm_b"

        done_run = orch.run_once(
            client, fake_vlm, _arm_configs(),
            operator="human_op", execute=True, person_at_switch=True, wait=True,
            approve=finish_async_and_approve, poll_s=0.01,
        )
        assert done_run["status"] == "completed"
        assert done_run["verification"]["job_summary"] == {"result": "released", "took_one": True}
        assert done_run["verification"]["post_incident"]["held"] is False
        assert not (wd / "choices.json").exists()

        # 7. While arm_b holds A/B space, propose_next short-circuits to idle without calling VLM
        submitted = orch.run_once(
            client, fake_vlm, _arm_configs(),
            operator="human_op", execute=True, person_at_switch=True, wait=False,
            approve=lambda _: True, poll_s=0.01,
        )
        assert submitted["status"] == "submitted"
        calls_before_busy = len(seen_images)
        busy = orch.run_once(
            client, fake_vlm, _arm_configs(),
            operator="human_op", execute=True, person_at_switch=True, approve=lambda _: True, poll_s=0.01,
        )
        assert busy["status"] == "idle"
        assert "queue busy" in busy["proposal"]["reason"]
        assert len(seen_images) == calls_before_busy
        procs[-1]._code = 0
    finally:
        server.shutdown()
        server.server_close()
        viewer.shutdown()
        viewer.server_close()


def test_orchestrator_cli_requires_interactive_confirmation_for_live_exec(tmp_path, monkeypatch):
    wd = _make_workdir(tmp_path)
    cfg_path = wd / "arm-configs.json"
    cfg_path.write_text(json.dumps(_arm_configs()), encoding="utf-8")
    _install_fake_popen(monkeypatch)
    runner = api.Runner(wd, lock_dir=wd)
    viewer = _start_fake_viewer()
    token = "t" * 32
    server = api.make_server("127.0.0.1", 0, token, runner, viewer=f"http://127.0.0.1:{viewer.server_port}")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setenv("ROSY_CELL_JOB_TOKEN", token)
    monkeypatch.setattr(
        orch.judge_seat,
        "from_config",
        lambda spec: (lambda *a: {"action": "home", "arm": "arm_a", "site": "", "reason": "cli check"}),
    )
    try:
        monkeypatch.setattr(sys, "stdin", io.StringIO("n\n"))
        rc = orch.main([
            "--url", f"http://127.0.0.1:{server.server_port}",
            "--arm-configs", str(cfg_path),
            "--operator", "human_op",
            "--execute",
            "--person-at-switch",
        ])
        assert rc == 1
    finally:
        server.shutdown()
        server.server_close()
        viewer.shutdown()
        viewer.server_close()


def test_multiline_last_json_parser_and_unsent_outbox_hold(tmp_path, monkeypatch):
    parsed = orch._parse_last_json(
        'session up\n{"old": 1}\n' + json.dumps({"result": "placed", "attempts": [{"observed": 2}]}, indent=1)
    )
    assert parsed == {"result": "placed", "attempts": [{"observed": 2}]}

    wd = _make_workdir(tmp_path)
    _install_fake_popen(
        monkeypatch,
        incidents={
            "arm_a": {"arm": "arm_a", "local_held": False, "fleet_held": False, "unsent_outbox": 1},
            "arm_b": {"arm": "arm_b", "local_held": False, "fleet_held": False, "unsent_outbox": 0},
        },
    )
    runner = api.Runner(wd, lock_dir=wd)
    viewer = _start_fake_viewer()
    token = "t" * 32
    server = api.make_server("127.0.0.1", 0, token, runner, viewer=f"http://127.0.0.1:{viewer.server_port}")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        client = CellJobClient(f"http://127.0.0.1:{server.server_port}", token=token)
        facts = orch.collect_measured_facts(client, _arm_configs(), run_dry_pick=False, poll_s=0.01)
        assert facts["incidents"]["arm_a"]["held"] is True
        assert facts["incidents"]["arm_b"]["held"] is False
        assert facts["available_arms"] == ["arm_b"]
    finally:
        server.shutdown()
        server.server_close()
        viewer.shutdown()
        viewer.server_close()


def test_propose_next_vetoes_auto_pick_on_nonzero_dry_pick_with_observed_boxes(tmp_path, monkeypatch):
    wd = _make_workdir(tmp_path)
    _install_fake_popen(
        monkeypatch,
        dry_pick={
            "cell-a.json": (1, {"result": "stopped: no usable object (neighbour clearance)", "attempts": [{"observed": 8, "chosen": None, "refused": [{"id": "b1"}]}]}),
            "cell-b.json": (0, {"result": "planned", "attempts": [{"observed": 1, "chosen": {"object": "box"}, "refused": []}]}),
        },
    )
    runner = api.Runner(wd, lock_dir=wd)
    viewer = _start_fake_viewer()
    token = "t" * 32
    server = api.make_server("127.0.0.1", 0, token, runner, viewer=f"http://127.0.0.1:{viewer.server_port}")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        client = CellJobClient(f"http://127.0.0.1:{server.server_port}", token=token)
        proposal = orch.propose_next(
            client,
            lambda *a: {"action": "auto_pick", "arm": "arm_a", "site": "pallet", "reason": "pick box"},
            arm_configs=_arm_configs(),
            collect_facts=True,
            poll_s=0.01,
        )
        assert proposal["action"] == "idle"
        assert "neighbour clearance" in proposal["reason"]
    finally:
        server.shutdown()
        server.server_close()
        viewer.shutdown()
        viewer.server_close()
