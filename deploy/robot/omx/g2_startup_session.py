"""Keep canonical UDS stop/readback serving while a simulation startup is authorized."""
import json
import os
from pathlib import Path
import threading
import time

from g2_ports import write_json
from g2_startup import hold_startup, prepare_home
from g2_startup_gate import StartupCommandGate


def publish_json(path, value):
    """Publish a complete, fsynced handshake once; never overwrite an earlier request."""
    path = Path(path)
    pending = path.with_name(path.name + ".pending")
    write_json(pending, value)
    os.link(pending, path)
    pending.unlink()
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def serve_startup(owner, run, *, target, expected_actor, fleet_fence_current,
                  timeout_s=300, wall_clock=time.monotonic, sleep=time.sleep):
    run = Path(run)
    hold_startup(owner)
    gate = StartupCommandGate(owner, target=target, expected_actor=expected_actor,
        fleet_fence_current=lambda epoch, generation: (
            owner.uds_server.is_serving and fleet_fence_current(epoch, generation)),
        record=lambda name, value: write_json(run / (name + ".json"), value))
    server = threading.Thread(target=owner.uds_server.serve_forever, daemon=True)
    server.start()
    deadline = wall_clock() + timeout_s

    def wait_until(condition):
        while True:
            if not server.is_alive() or wall_clock() >= deadline:
                raise RuntimeError("explicit SIM startup authorization/readiness timed out")
            if condition():
                return
            sleep(.05)

    try:
        # Do not publish the challenge until the StopLocal server is listening.
        wait_until(lambda: owner.uds_server.is_serving)
        publish_json(run / "startup-awaiting-authorization.json", gate.challenge)
        request = run / "startup-request.json"
        wait_until(request.exists)
        if request.stat().st_size > 4096:
            raise ValueError("startup authorization exceeds bounded frame")
        gate.authorize(json.loads(request.read_text()))

        def fresh_ready():
            gate.assert_current()
            sample = owner.runtime.latest_joint_state
            return (sample is not None and owner.runtime.owner.state == "ready"
                    and owner.runtime.action_port.server_is_ready() is True
                    and 0 <= owner.runtime.monotonic()-sample.received_at <= owner.profile.max_joint_state_age_s)

        wait_until(fresh_ready)
        receipt = prepare_home(owner.runtime, owner.profile, target, startup_gate=gate,
                               wall_clock=wall_clock, sleep=sleep)
        gate.complete(lambda: setattr(owner.runner, "enabled", True))
        publish_json(run / "startup-home-ready.json", receipt)
    except Exception as error:
        owner.runner.enabled = False
        try:
            gate.cancel()
        finally:
            publish_json(run / "startup-home-failure.json", {
                "fixture": "SIM_STARTUP_HOME", "result": "HOLD",
                "reason": type(error).__name__ + ": " + str(error)})
    return server
