"""Existing Fleet readback over loopback HTTP; no ROS or physical device ports."""
from contextlib import contextmanager
from datetime import datetime, timezone
from hashlib import sha256
from http.client import HTTPConnection
import json
from pathlib import Path
import socket
import sys
import threading
import time

import pytest
import uvicorn

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/agent/src"))


@pytest.mark.parametrize("url", [
    "http://example.com/api/fleet/dispatch-control", "http://localhost/api/fleet/dispatch-control",
    "http://127.0.0.1/wrong", "http://127.0.0.1/api/fleet/dispatch-control?token=secret",
    "http://user@127.0.0.1/api/fleet/dispatch-control", "https://127.0.0.1/api/fleet/dispatch-control",
    "http://127.0.0.1:0/api/fleet/dispatch-control",
])
def test_fence_configuration_refuses_nonlocal_or_ambiguous_endpoints(url):
    from rosy_agent.fleet_fence import HttpFleetFenceReadback
    with pytest.raises(ValueError):
        HttpFleetFenceReadback(url, "viewer-secret")


def test_configuration_is_required_and_does_not_enable_dispatch(monkeypatch):
    from rosy_agent.fleet_fence import fleet_fence_from_environment
    monkeypatch.delenv("ROSY_FLEET_FENCE_URL", raising=False)
    monkeypatch.delenv("ROSY_FLEET_FENCE_TOKEN", raising=False)
    with pytest.raises(ValueError):
        fleet_fence_from_environment()


@contextmanager
def _serve(app):
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="critical", access_log=False, lifespan="off"))
    thread = threading.Thread(target=lambda: server.run(sockets=[listener]), daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 5
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(.01)
        assert server.started, "loopback Fleet test server did not start"
        yield port
    finally:
        server.should_exit = True
        thread.join(5)
        listener.close()
        assert not thread.is_alive()


def _post(port, token, path, body):
    connection = HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        connection.request("POST", path, json.dumps(body), headers={
            "Authorization": "Bearer " + token, "Content-Type": "application/json"})
        response = connection.getresponse()
        return response.status, json.loads(response.read())
    finally:
        connection.close()


def test_real_fleet_reverse_readback_during_owner_rearm_does_not_deadlock(tmp_path):
    from rosy_agent.fleet_fence import HttpFleetFenceReadback
    from test_platform_cell_owner_assembly import _build
    from fleet.server.app import create_app
    from fleet.server.console import FleetConsole
    from fleet.server.task_store import FleetTaskStore
    from fleet.server.task_service import FleetTaskService
    store = FleetTaskStore(tmp_path / "fleet.sqlite3")
    holder = {}
    class OwnerTransport:
        def rearm(self, **identity):
            response = holder["owner"].action_api.dispatch(
                {"version": 1, "operation": "RearmLocal", **identity}, peer_uid=1001)
            return {"state": response.get("snapshot", {}).get("state", "UNKNOWN")}
        def stop(self, **identity):
            response = holder["owner"].action_api.dispatch({
                "version": 1, "operation": "StopLocal", **identity,
                "requested_at": datetime.now(timezone.utc).isoformat()}, peer_uid=1001)
            return {"state": response.get("snapshot", {}).get("state", "UNKNOWN")}
    app = create_app(FleetConsole([], []), task_service=FleetTaskService(store, robot_ids=set()),
        start_task_dispatcher=False, omx_instances={"omx_cell_sim": "omx_cell_sim_01"},
        omx_stop_transport=OwnerTransport(), deployment_profile="simulation", site_users={
            sha256(b"private-viewer").hexdigest(): {"principal_id": "cell-fence-reader", "role": "viewer"},
            sha256(b"named-operator").hexdigest(): {"principal_id": "operator-1", "role": "operator"}})
    with _serve(app) as port:
        url = f"http://127.0.0.1:{port}/api/fleet/dispatch-control"
        fence = HttpFleetFenceReadback(url, "private-viewer", timeout_s=.5)
        owner, _ = _build(tmp_path / "owner", fleet_fence_current=fence)
        holder["owner"] = owner
        assert not fence(0, 0)
        rearm = {"expected_generation": store.dispatch_control()["generation"]}
        assert _post(port, "private-viewer", "/api/fleet/dispatch/rearm", rearm)[0] == 403
        status, control = _post(port, "named-operator", "/api/fleet/dispatch/rearm", rearm)
        assert status == 200, control
        epoch, generation = control["authority_epoch"], control["generation"]
        assert fence(epoch, generation)
        assert not fence(epoch, generation + 1)
        assert owner.stop.is_open(authority_epoch=epoch, dispatch_generation=generation)
        assert not HttpFleetFenceReadback(url, "wrong-credential")(epoch, generation)
        status, stopped = _post(port, "named-operator", "/api/fleet/estop", {})
        assert status == 200 and stopped["omx_local_stop"]["state"] == "LOCAL_LATCHED"
        assert not fence(epoch, generation)
        assert not owner.stop.is_open(authority_epoch=epoch, dispatch_generation=generation)
        store.close_dispatch_for_startup()
        assert not fence(epoch, generation)
    assert not fence(epoch, generation)


@pytest.mark.parametrize("document", [
    {"authority_epoch": True, "generation": 1, "dispatch_enabled": True},
    {"authority_epoch": 0, "generation": 1.0, "dispatch_enabled": True},
    {"authority_epoch": 0, "generation": 1, "dispatch_enabled": 1},
    {}, [], {"authority_epoch": 0, "generation": 1, "dispatch_enabled": True, "junk": "x" * 9000},
    {"authority_epoch": 0, "generation": 1, "dispatch_enabled": True, "junk": float("nan")},
])
def test_malformed_or_oversized_readback_cannot_open_fence(document):
    from rosy_agent.fleet_fence import HttpFleetFenceReadback
    from fastapi import FastAPI
    from fastapi.responses import Response
    app = FastAPI()
    @app.get("/api/fleet/dispatch-control")
    def readback():
        return Response(json.dumps(document), media_type="application/json")
    with _serve(app) as port:
        assert not HttpFleetFenceReadback(
            f"http://127.0.0.1:{port}/api/fleet/dispatch-control", "private-viewer")(0, 1)


def test_redirect_and_slow_response_refuse_without_following_or_caching():
    from rosy_agent.fleet_fence import HttpFleetFenceReadback
    from fastapi import FastAPI
    from fastapi.responses import RedirectResponse
    app = FastAPI()
    mode = {"value": "redirect", "target_reads": 0}
    @app.get("/api/fleet/dispatch-control")
    def readback():
        if mode["value"] == "redirect":
            return RedirectResponse("/target")
        time.sleep(.15)
        return {"authority_epoch": 0, "generation": 1, "dispatch_enabled": True}
    @app.get("/target")
    def target():
        mode["target_reads"] += 1
        return {"authority_epoch": 0, "generation": 1, "dispatch_enabled": True}
    with _serve(app) as port:
        fence = HttpFleetFenceReadback(f"http://127.0.0.1:{port}/api/fleet/dispatch-control",
                                      "private-viewer", timeout_s=.02)
        assert not fence(0, 1) and mode["target_reads"] == 0
        mode["value"] = "slow"
        started = time.monotonic()
        assert not fence(0, 1)
        assert time.monotonic() - started < 1


def test_owner_entrypoint_requires_fleet_readback_before_loading_ros(monkeypatch):
    import importlib.util
    import builtins
    original_import = builtins.__import__
    def refuse_ros_import(name, *args, **kwargs):
        assert name != "rclpy", "invalid Fleet configuration reached ROS initialization"
        return original_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", refuse_ros_import)
    monkeypatch.syspath_prepend(str(ROOT / "deploy/robot/omx"))
    monkeypatch.setenv("ROSY_SIM_REPO", str(ROOT))
    monkeypatch.setenv("ROS_AUTOMATIC_DISCOVERY_RANGE", "LOCALHOST")
    monkeypatch.setenv("ROSY_FLEET_PEER_UID", "1001")
    monkeypatch.delenv("ROSY_FLEET_FENCE_URL", raising=False)
    monkeypatch.delenv("ROSY_FLEET_FENCE_TOKEN", raising=False)
    spec = importlib.util.spec_from_file_location("cell_owner_entrypoint", ROOT / "deploy/robot/omx/run_cell_owner.py")
    entrypoint = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(entrypoint)
    with pytest.raises(ValueError, match="Fleet fence"):
        entrypoint.main()
