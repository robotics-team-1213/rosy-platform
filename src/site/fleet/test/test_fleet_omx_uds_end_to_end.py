"""Exercise the Fleet grant and OMX local Action API over real Unix IPC."""

from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

import pytest

ADAPTER_ROOT = Path(__file__).resolve().parents[3] / "products" / "omx" / "adapter"
if str(ADAPTER_ROOT) not in sys.path:
    sys.path.insert(0, str(ADAPTER_ROOT))

from omx_adapter.action_api import ActionApi, UnixActionServer  # noqa: E402
from omx_adapter.action_runner import ActionRunner  # noqa: E402
from omx_adapter.action_store import ActionStore  # noqa: E402
from omx_adapter.local_stop import LocalStopController  # noqa: E402

from fleet.server.local_action_transport import UnixLocalActionTransport  # noqa: E402
from fleet.server.mission_dispatcher import MissionDispatcher  # noqa: E402
from test_mission_dispatcher import _ready_mission  # noqa: E402


class _ApproachOnlyPhaseExecution:
    """Record acceptance of one bounded approach phase; never infer grasp/place."""

    def __init__(self, recorder):
        self.recorder = recorder
        self.active_phase_id = None

    def start(self):
        self.active_phase_id = "approach"
        self.recorder.begin_phase(
            phase_id="approach", ordinal=0, command_digest="a" * 64,
        )
        self.recorder.record_first_submission(
            phase_id="approach", accepted=True, driver_goal_id="sim-goal-approach",
        )

    def cancel_current(self):
        self.recorder.request_cancel(phase_id=self.active_phase_id)
        return {"phase_id": self.active_phase_id, "state": "CANCEL_REQUESTED"}


class _RecordingActionApi(ActionApi):
    def __init__(self, runner):
        super().__init__(runner)
        self.responses = []

    def dispatch(self, request, *, peer_uid):
        response = super().dispatch(request, peer_uid=peer_uid)
        self.responses.append(response)
        return response


def test_admitted_fleet_mission_uses_real_uds_and_reconciles_local_phase_receipt(tmp_path):
    pytest.importorskip("fcntl", reason="requires Unix domain socket credentials")
    assert hasattr(__import__("socket"), "SO_PEERCRED")
    peer_uid = os.getuid()

    fleet_store, mission_service, mission, _ = _ready_mission(tmp_path)
    fence = fleet_store.dispatch_control()
    socket_root = tmp_path / "omx"
    instance_dir = socket_root / mission["instance_id"]
    instance_dir.mkdir(parents=True)
    socket_path = instance_dir / "control.sock"

    db = tmp_path / "omx-actions.sqlite3"
    action_store = ActionStore(db)
    stop = LocalStopController(
        db, workcell_id=mission["workcell_id"], instance_id=mission["instance_id"],
    )

    def fleet_fence_current(epoch, generation):
        current = fleet_store.dispatch_control()
        return (epoch == current["authority_epoch"]
                and generation == current["generation"]
                and current["dispatch_enabled"])

    stop.rearm(
        authority_epoch=fence["authority_epoch"],
        dispatch_generation=fence["generation"], operator_confirmed=True,
        fleet_fence_current=fleet_fence_current,
    )
    runner = ActionRunner(
        action_store, object(), workcell_id=mission["workcell_id"],
        instance_id=mission["instance_id"],
        principal_for_peer=lambda uid: "operator-1" if uid == peer_uid else "",
        allowed_peer_uids={peer_uid},
        current_fence=fleet_fence_current,
        capability_current=lambda grant: grant.config_revision == "cfg-1",
        submission_fence=stop, enabled=True,
        phase_runner_factory=lambda grant, recorder: _ApproachOnlyPhaseExecution(recorder),
    )
    api = _RecordingActionApi(runner)
    server = UnixActionServer(api, socket_path)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    deadline = time.monotonic() + 2.0
    while not socket_path.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert socket_path.exists(), "local Action API did not bind its provisioned socket"

    try:
        transport = UnixLocalActionTransport(socket_root, timeout_s=0.5)
        dispatcher = MissionDispatcher(
            mission_service, fleet_store, transport,
            {mission["workcell_id"]: mission["instance_id"]},
        )

        first = dispatcher.dispatch_next()
        reconciled = dispatcher.dispatch_next()
        assert first["state"] == "ACCEPTED", (first, api.responses[0].get("receipt"))
        assert reconciled["state"] == "ACCEPTED"
        assert api.responses[0]["receipt"]["created"] is True
        assert api.responses[1]["receipt"]["created"] is False
        action = action_store.get_action(first["action_id"])
        assert action is not None and action["state"] == "ACCEPTED"
        assert action["principal_id"] == "operator-1"
        phases = action_store.action_phase_receipts(
            first["action_id"], action["attempt_id"],
        )
        assert [(phase["phase_id"], phase["ordinal"], phase["state"])
                for phase in phases] == [("approach", 0, "ACCEPTED")]
        assert mission_service.get(mission["mission_id"])["status"] == "RUNNING"
        assert all(event["state"] != "SUCCEEDED"
                   for event in action_store.history(first["action_id"]))
    finally:
        server.stop()
        server_thread.join(timeout=2.0)
        assert not server_thread.is_alive()
