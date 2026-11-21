from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import threading
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


def _start_fake_viewer(available_views=("/frame/top.jpg", "/frame/side.jpg", "/frame/arm_a_wrist.jpg")):
    allowed = set(available_views)

    class ViewerHandler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass

        def do_GET(self):
            if self.path in allowed:
                raw = b"JPEG:" + self.path.encode("ascii")
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
            "operating_profile": "profile-b.json",
            "mode": "hybrid",
            "policy_root": "~/rosy-models/h1-goal-b-mixed",
            "policy_revision": sha,
            "cell_calibration": "cal-b.json",
            "max_chunks": 3,
        },
    }


def test_select_vision_backend_rejects_text_only_cli():
    with pytest.raises(ValueError, match="text-only CLI"):
        orch.select_vision_backend({"provider": "opencode", "model": "zai-coding-plan/glm-5.3-flash"})
    with pytest.raises(ValueError, match="vision=False"):
        orch.select_vision_backend({"provider": "zai", "model": "glm-5.3", "vision": False})


def test_orchestrator_fails_closed_when_zero_frames_available(tmp_path):
    wd = _make_workdir(tmp_path)
    runner = api.Runner(wd, lock_dir=wd)
    viewer = _start_fake_viewer(available_views=())
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

        res = orch.run_once(client, fail_if_called, _arm_configs(), operator="human_op", execute=True, person_at_switch=True)
        assert res["status"] == "idle"
        assert res["proposal"]["reason"] == "no camera frames available"
        assert called is False
    finally:
        server.shutdown()
        server.server_close()
        viewer.shutdown()
        viewer.server_close()


def test_client_and_orchestrator_end_to_end(tmp_path, monkeypatch):
    wd = _make_workdir(tmp_path)
    procs = []

    def fake_popen(argv, **kwargs):
        p = Mock()
        p.argv = argv
        p._code = None
        p.poll.side_effect = lambda: p._code
        procs.append(p)
        return p

    monkeypatch.setattr(api.subprocess, "Popen", fake_popen)
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

        # 1. Propose-only captures 3 views (clean 404 skip on arm_b_wrist) and submits nothing
        proposed = orch.run_once(client, fake_vlm, _arm_configs(), operator="human_op", execute=False)
        assert proposed["status"] == "proposed"
        assert seen_images == [3]
        assert procs == []

        # 2. Dry-run cell_policy_drive works without person_at_switch and passes h1 goal_site + hybrid mode
        dry_policy = orch.run_once(
            client, fake_vlm, _arm_configs(),
            operator="human_op", execute=True, dry_run=True, wait=False,
        )
        assert dry_policy["status"] == "submitted" and dry_policy["job"] == "cell_policy_drive"
        dry_argv = procs[-1].argv
        assert dry_argv[0] == "bash"
        assert "--dry-run" in dry_argv
        assert dry_argv[dry_argv.index("--mode") + 1] == "hybrid"
        assert dry_argv[dry_argv.index("--goal-site") + 1] == "yard:r3-s2-t1"
        assert "--model-calibration" not in dry_argv
        procs[-1]._code = 0

        # 3. Dry-run auto_pick routes to auto_pick_dry_run without person_at_switch; dry-run home skips safely
        next_proposal = {"action": "auto_pick", "arm": "arm_a", "site": "belt", "reason": "pick test"}
        dry_pick = orch.run_once(
            client, fake_vlm, _arm_configs(),
            operator="human_op", execute=True, dry_run=True, wait=False,
        )
        assert dry_pick["job"] == "auto_pick_dry_run"
        assert procs[-1].argv[0] == "bash"
        procs[-1]._code = 0

        next_proposal = {"action": "home", "arm": "arm_a", "site": "", "reason": "fold home"}
        dry_home = orch.run_once(
            client, fake_vlm, _arm_configs(),
            operator="human_op", execute=True, dry_run=True, wait=False,
        )
        assert dry_home["status"] == "dry_run_skipped"
        assert len(procs) == 2

        # 4. Live execute refuses missing person_at_switch and refuses proposer == operator
        next_proposal = {"action": "cell_policy_drive", "arm": "arm_b", "site": "yard:r3-s2-t1", "reason": "live run"}
        with pytest.raises(ValueError, match="person_at_switch"):
            orch.run_once(client, fake_vlm, _arm_configs(), operator="human_op", execute=True, person_at_switch=False)
        with pytest.raises(ValueError, match="proposer"):
            orch.run_once(
                client, fake_vlm, _arm_configs(),
                operator="vlm_orchestrator", proposer="vlm_orchestrator",
                execute=True, person_at_switch=True,
            )

        # 5. Live execute with approval submits arm_b policy drive through its session wrapper
        submitted = orch.run_once(
            client, fake_vlm, _arm_configs(),
            operator="human_op", execute=True, person_at_switch=True, wait=False,
            approve=lambda p: p["arm"] == "arm_b",
        )
        assert submitted["status"] == "submitted"
        assert submitted["job"] == "cell_policy_drive"
        assert len(procs) == 3
        live_argv = procs[-1].argv
        assert live_argv[0] == "./with-session-arm-b-par.sh"
        assert "--person-at-switch" in live_argv
        assert live_argv[live_argv.index("--goal-site") + 1] == "yard:r3-s2-t1"

        # 6. While arm_b holds A/B space, propose_next short-circuits to idle without calling VLM
        calls_before_busy = len(seen_images)
        busy = orch.run_once(client, fake_vlm, _arm_configs(), operator="human_op", execute=True, person_at_switch=True)
        assert busy["status"] == "idle"
        assert "queue busy" in busy["proposal"]["reason"]
        assert len(seen_images) == calls_before_busy

        procs[-1]._code = 0
        done = client.wait(submitted["id"], poll_s=0.01, timeout_s=2.0)
        assert done["running"] is False and done["exit"] == 0
    finally:
        server.shutdown()
        server.server_close()
        viewer.shutdown()
        viewer.server_close()
