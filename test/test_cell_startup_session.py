"""Exercise the real UDS server while startup authorizes and settles."""
import json
from datetime import datetime, timezone
import os
from pathlib import Path
import socket
import sys
import threading
import time
from types import SimpleNamespace as NS

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "deploy/robot/omx"))
pytestmark = pytest.mark.skipif(not hasattr(socket, "AF_UNIX"), reason="requires Unix sockets")


def request_identity(path):
    with socket.socket(socket.AF_UNIX) as client:
        client.settimeout(2)
        client.connect(str(path))
        client.sendall(b'{"version":1,"operation":"GetOwnerIdentity"}\n')
        return json.loads(client.recv(65536))


def build(tmp_path):
    from test_platform_cell_owner_assembly import _build
    from test_cell_g2_startup import Fixture
    owner, _ = _build(tmp_path)
    runtime = Fixture()
    runtime.profile.revision = "startup-session-test"
    runtime.owner.config.workcell_id = owner.settings.workcell_id
    runtime.owner.config.instance_id = owner.settings.instance_id
    owner.runtime, owner.profile = runtime, runtime.profile
    owner.uds_server.socket_path.parent.mkdir(parents=True, exist_ok=True)
    owner.stop.rearm(authority_epoch=3, dispatch_generation=8, operator_confirmed=True,
                     fleet_fence_current=lambda epoch, generation: True)
    runtime.cancel = lambda **kwargs: NS(reason="cancel_requested", cancel_outcome="call_returned")
    runtime.action_port = NS(server_is_ready=lambda: True)
    return owner, runtime


@pytest.mark.parametrize("lose_server", [False, True])
def test_uds_is_reachable_before_goal_and_through_startup_settling(tmp_path, lose_server):
    from g2_startup_session import serve_startup, publish_json
    owner, runtime = build(tmp_path)
    run = tmp_path / "evidence"; run.mkdir()
    target = {"joint1": .2, "gripper": 1.}
    original_submit = runtime.submit

    def submit(command):
        assert request_identity(owner.uds_server.socket_path)["status"] == 200
        if lose_server:
            owner.uds_server.stop()
        return original_submit(command)

    runtime.submit = submit

    def sleep(seconds):
        time.sleep(.001)
        if "submit" in runtime.calls:
            runtime.sleep(seconds)
        else:
            runtime.t += seconds
            runtime.latest_joint_state.received_at = runtime.t

    returned, errors = [], []
    def start():
        try:
            returned.append(serve_startup(owner, run, target=target, expected_actor="g2-sim-approver",
                fleet_fence_current=lambda epoch, generation: True,
                wall_clock=runtime.monotonic, sleep=sleep))
        except Exception as error:
            errors.append(error)

    worker = threading.Thread(target=start)
    worker.start()
    try:
        challenge_path = run / "startup-awaiting-authorization.json"
        deadline = time.monotonic()+5
        while not challenge_path.exists() and time.monotonic() < deadline:
            time.sleep(.005)
        challenge = json.loads(challenge_path.read_text())
        assert owner.runner.enabled is False
        assert request_identity(owner.uds_server.socket_path)["status"] == 200
        publish_json(run / "startup-request.json", {**challenge, "actor_id": "g2-sim-approver",
                                                    "authority_epoch": 3, "dispatch_generation": 8})
        worker.join(timeout=5)
        assert not worker.is_alive() and not errors, errors
        if lose_server:
            assert not (run / "startup-home-ready.json").exists()
            assert json.loads((run / "startup-home-failure.json").read_text())["result"] == "HOLD"
            assert owner.runner.enabled is False
        else:
            assert json.loads((run / "startup-home-ready.json").read_text())["result"] == "READY"
            assert owner.runner.enabled is True
            assert request_identity(owner.uds_server.socket_path)["status"] == 200
    finally:
        owner.uds_server.stop()
        worker.join(timeout=5)
        for thread in returned:
            thread.join(timeout=5)


def test_absent_authorization_keeps_hold_and_leaves_readback_running(tmp_path):
    from g2_startup_session import serve_startup
    owner, runtime = build(tmp_path)
    run = tmp_path / "evidence"; run.mkdir()
    thread = serve_startup(owner, run, target={"joint1": .2, "gripper": 1.},
        expected_actor="g2-sim-approver", fleet_fence_current=lambda epoch, generation: True,
        timeout_s=.1)
    try:
        assert thread.is_alive() and owner.runner.enabled is False
        assert json.loads((run / "startup-home-failure.json").read_text())["result"] == "HOLD"
        assert request_identity(owner.uds_server.socket_path)["status"] == 200
        assert "submit" not in runtime.calls
    finally:
        owner.uds_server.stop()
        thread.join(timeout=5)


@pytest.mark.parametrize("mode", ["delayed", "never", "stop", "generation", "missing", "exception"])
def test_own_client_readiness_gates_one_startup_goal(tmp_path, monkeypatch, mode):
    import test_platform_cell_owner_assembly as assembly
    from g2_startup_session import serve_startup, publish_json
    # Configure the test Fleet peer to the real socket caller UID; retain SO_PEERCRED checks.
    monkeypatch.setattr(assembly, "FLEET_UID", os.getuid())
    owner, runtime = build(tmp_path)
    run = tmp_path / "evidence"; run.mkdir()
    ready, fence, ticks, premature = [False], [True], [0], []
    runtime.action_port = NS(server_is_ready=lambda: ready[0])
    if mode == "missing":
        runtime.action_port = NS()
    elif mode == "exception":
        def unavailable():
            raise RuntimeError("client discovery unavailable")
        runtime.action_port.server_is_ready = unavailable
    original_submit = runtime.submit
    def submit(command):
        if not ready[0]:
            premature.append(command.command_id)
        return original_submit(command)
    runtime.submit = submit

    def sleep(seconds):
        time.sleep(.002)
        challenge = run / "startup-awaiting-authorization.json"
        if challenge.exists() and not (run / "startup-request.json").exists():
            publish_json(run / "startup-request.json", {**json.loads(challenge.read_text()),
                "actor_id": "g2-sim-approver", "authority_epoch": 3, "dispatch_generation": 8})
        elif (run / "startup-request.json").exists() and "submit" not in runtime.calls:
            ticks[0] += 1
            assert request_identity(owner.uds_server.socket_path)["status"] == 200
            if ticks[0] == 3:
                if mode == "delayed":
                    ready[0] = True
                elif mode == "generation":
                    fence[0] = False
                elif mode == "stop":
                    with socket.socket(socket.AF_UNIX) as client:
                        client.settimeout(2)
                        client.connect(str(owner.uds_server.socket_path))
                        client.sendall(json.dumps({"version": 1, "operation": "StopLocal",
                            "workcell_id": owner.settings.workcell_id,
                            "instance_id": owner.settings.instance_id, "authority_epoch": 3,
                            "dispatch_generation": 8, "requested_at": datetime.now(timezone.utc).isoformat(),
                            "reason": "stop before local client discovery"}).encode()+b"\n")
                        assert json.loads(client.recv(65536))["status"] == 200
        if "submit" in runtime.calls:
            runtime.sleep(seconds)
        else:
            runtime.t += seconds
            runtime.latest_joint_state.received_at = runtime.t

    server = serve_startup(owner, run, target={"joint1": .2, "gripper": 1.},
        expected_actor="g2-sim-approver", fleet_fence_current=lambda *_: fence[0],
        timeout_s=1., wall_clock=runtime.monotonic, sleep=sleep)
    try:
        assert premature == []
        if mode == "delayed":
            assert ticks[0] >= 3 and runtime.calls.count("submit") == 1
            assert json.loads((run / "startup-home-ready.json").read_text())["result"] == "READY"
        else:
            assert "submit" not in runtime.calls
            assert owner.runner.enabled is False
            assert json.loads((run / "startup-home-failure.json").read_text())["result"] == "HOLD"
        assert request_identity(owner.uds_server.socket_path)["status"] == 200
    finally:
        owner.uds_server.stop()
        server.join(timeout=5)
