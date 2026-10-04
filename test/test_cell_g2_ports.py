"""The simulation aid must neither mint grants nor bypass the owner fence."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import sys
import socket
from datetime import datetime, timedelta, timezone

import pytest


def module():
    path = Path(__file__).parents[1] / "deploy/robot/omx/g2_ports.py"
    spec = importlib.util.spec_from_file_location("g2_ports", path)
    result = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = result
    spec.loader.exec_module(result)
    return result


def test_aid_needs_durable_hold_and_matching_attempt_before_goal():
    calls = []
    port = module().SimAidGoalPort(
        SimpleNamespace(submit=lambda command, **kwargs: calls.append("goal")),
        before=lambda command: (_ for _ in ()).throw(RuntimeError("hold not verified")),
    )
    with pytest.raises(RuntimeError, match="hold"):
        port.submit(object(), on_goal_event=lambda event: True)
    assert calls == []


def test_aid_finishes_before_original_command_is_forwarded_once():
    calls = []
    command, callback = object(), object()
    original = SimpleNamespace(submit=lambda value, **kwargs:
                               calls.append(("goal", value, kwargs["on_goal_event"])) or "receipt")
    port = module().SimAidGoalPort(original, before=lambda value: calls.append(("aid", value)))
    assert port.submit(command, on_goal_event=callback) == "receipt"
    assert calls == [("aid", command), ("goal", command, callback)]


def test_cancel_only_delegates_exact_goal():
    values = []
    port = module().SimAidGoalPort(SimpleNamespace(cancel_goal=lambda value: values.append(value) or None),
                                   before=lambda value: pytest.fail("cancel may not attach"))
    assert port.cancel_goal("actual-goal") is None
    assert values == ["actual-goal"]


def test_used_run_directory_is_refused_without_overwriting_receipts(tmp_path):
    root = tmp_path / "evidence"
    root.mkdir()
    (root / "previous.json").write_text("previous")
    with pytest.raises(ValueError, match="empty"):
        module().fresh_evidence(root)
    assert (root / "previous.json").read_text() == "previous"


def test_fresh_run_provisions_its_instance_socket_before_starting_owner(tmp_path):
    run = module().fresh_evidence(tmp_path / "run")
    assert (run / "uds" / "omx_cell_sim_01").is_dir()


@pytest.mark.skipif(not hasattr(socket, "AF_UNIX"), reason="Unix IPC requires a Linux host")
def test_fresh_run_can_bind_its_instance_socket_before_starting_owner(tmp_path):
    run = module().fresh_evidence(tmp_path / "run")
    socket_path = run / "uds" / "omx_cell_sim_01" / "control.sock"
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
        listener.bind(str(socket_path))
        listener.listen(1)
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.connect(str(socket_path))
            connection, _ = listener.accept()
            with connection:
                client.sendall(b"readiness")
                assert connection.recv(9) == b"readiness"


def grant():
    from core_common.protocol.schemas import FleetCellTransferGrant
    now = datetime.now(timezone.utc)
    pose = {"x": 0., "y": 0.17, "z": 0.015, "yaw": 0.}
    return FleetCellTransferGrant.model_validate({
        "mission_id": "mission", "step_id": "step", "action_id": "action", "attempt_id": "attempt",
        "request_digest": "a"*64, "workcell_id": "omx_cell_sim", "instance_id": "omx_cell_sim_01",
        "action_kind": "CELL_TRANSFER", "capability_revision": "cell-transfer-v1",
        "config_revision": "config", "authority_epoch": 1, "dispatch_generation": 1,
        "issued_at": now, "expires_at": now+timedelta(seconds=15),
        "cell_transfer": {"job_id": "job", "recipe_sha256": "b"*64, "cell_sha256": "c"*64,
                          "step_index": 0, "item": "box", "pallet": "A", "layer": 0, "frame": "robot_base",
                          "home": pose, "pick": pose, "place": pose, "pick_approach_z": 0.045,
                          "place_approach_z": 0.045, "carry_z": 0.1}})


def staging(tmp_path, actual, calls, **kwargs):
    return module().StagingTransport(SimpleNamespace(submit=lambda value: calls.append(value) or "receipt"),
                                     observer=lambda *args, **kw: {"observed_at": actual.issued_at.timestamp()+0.01},
                                     stage=lambda *args: calls.append("stage") or {"ok": True}, directory=tmp_path,
                                     box={"length": .04, "width": .03, "height": .03,
                                          "grasp_depth": .015, "mass_kg": .02},
                                     **kwargs)


def test_typed_real_grant_identity_is_preserved_and_never_replayed(tmp_path):
    actual, calls = grant(), []
    port = staging(tmp_path, actual, calls)
    assert port.submit(actual) == "receipt"
    assert calls == ["stage", actual]
    assert calls[-1] is actual
    with pytest.raises(RuntimeError, match="reconcile"):
        port.submit(actual)
    assert calls == ["stage", actual]


def test_used_action_receipt_blocks_staging_after_process_restart(tmp_path):
    actual, calls = grant(), []
    staging(tmp_path, actual, calls).submit(actual)
    restarted = staging(tmp_path, actual, calls)
    with pytest.raises(RuntimeError, match="reconcile"):
        restarted.submit(actual)
    assert calls == ["stage", actual]


def test_expired_during_staging_never_reaches_uds(tmp_path):
    actual, calls = grant(), []
    times = iter((actual.issued_at, actual.expires_at))
    port = staging(tmp_path, actual, calls, clock=lambda: next(times))
    with pytest.raises(RuntimeError, match="expired"):
        port.submit(actual)
    assert calls == ["stage"]


def test_ambiguous_stage_intent_blocks_restart_replacement(tmp_path):
    actual, calls = grant(), []
    port = staging(tmp_path, actual, calls)
    port.stage = lambda *args: {"ok": False}
    with pytest.raises(RuntimeError, match="uncertain"):
        port.submit(actual)
    restarted = staging(tmp_path, actual, calls)
    with pytest.raises(RuntimeError, match="reconcile"):
        restarted.submit(actual)
    assert calls == []


def test_untyped_grant_is_rejected_before_model_or_uds(tmp_path):
    actual, calls = grant(), []
    port = staging(tmp_path, actual, calls)
    with pytest.raises(ValueError, match="typed"):
        port.submit(actual.model_dump())
    assert calls == []


def observer_module():
    source = Path(__file__).parents[1] / "deploy/robot/omx"
    sys.path.insert(0, str(source))
    import g2_observer
    return g2_observer


def test_observer_requires_measured_model_advancing_clock_and_fresh_open_gripper():
    import time
    state = observer_module().Observations()
    with pytest.raises(RuntimeError, match="clock"):
        state.read("cell_action", require_open=True)
    now = time.time()
    state.clock, state.progress.advances = (now, 3.), 3
    state.progress.last_advance = time.monotonic()
    with pytest.raises(RuntimeError, match="pose"):
        state.read("cell_action", require_open=True)
    state.models["cell_action"] = (now, {"x_m": .12})
    state.gripper = (now, .4)
    with pytest.raises(RuntimeError, match="OPEN"):
        state.read("cell_action", require_open=True)
    state.gripper = (now, 1.)
    result = state.read("cell_action", require_open=True)
    assert result["model_pose_base"] == {"x_m": .12}
    assert result["observed_at"] == now
    state.clock = (now-2, 3.)
    with pytest.raises(RuntimeError, match="clock"):
        state.read("cell_action", require_open=True)


def test_repeated_frozen_clock_publications_do_not_refresh_advancement(monkeypatch):
    module = observer_module()
    current = [100.]
    monkeypatch.setattr(module.time, "monotonic", lambda: current[0])
    state = module.Observations()

    def stamp(sec):
        return SimpleNamespace(clock=SimpleNamespace(sec=sec, nanosec=0))
    for sec in (1, 2, 3):
        state.clocks(stamp(sec))
    state.models["cell_action"] = (module.time.time(), {"x_m": .12})
    state.gripper = (module.time.time(), 1.)
    assert state.read("cell_action", require_open=True)["clock_advances"] == 2
    current[0] = 101.
    state.clocks(stamp(3))
    with pytest.raises(RuntimeError, match="clock"):
        state.read("cell_action", require_open=True)
    state.clocks(stamp(0))
    assert state.progress.last_advance is None
    assert state.progress.advances == 0


def test_box_only_derivation_preserves_original_sheet_contract():
    source = Path(__file__).parents[1] / "deploy/robot/omx"
    sys.path.insert(0, str(source))
    from g2_common import box_only_document
    original = {"name": "original", "slip_sheet": {"thickness": .002},
                "layers": [{"pattern": "grid", "slip_sheet_below": True}]}
    derived = box_only_document(original)
    assert original["layers"][0]["slip_sheet_below"] is True
    assert original["slip_sheet"] == {"thickness": .002}
    assert "slip_sheet" not in derived
    assert "slip_sheet_below" not in derived["layers"][0]


def test_candidate_source_precedes_site_packages(monkeypatch):
    observer_module()
    import g2_common
    monkeypatch.setattr(sys, "path", ["installed-site-packages", str(g2_common.ROOT / g2_common.SOURCE_PATHS[0])])
    g2_common.configure_imports()
    expected = [str(g2_common.ROOT / part) for part in g2_common.SOURCE_PATHS]
    assert sys.path[:len(expected)] == expected
    assert sys.path[-1] == "installed-site-packages"


def test_cached_installed_module_fails_candidate_origin_check(monkeypatch, tmp_path):
    observer_module()
    import g2_common
    monkeypatch.setitem(sys.modules, "g2_fake_shadow", SimpleNamespace(__file__=str(tmp_path / "installed.py")))
    with pytest.raises(RuntimeError, match="origin mismatch"):
        g2_common.verify_module_origins({"g2_fake_shadow": "operations/fleet"})


def test_readiness_clock_gate_rejects_repeated_pause_and_reset():
    observer_module()
    from g2_common import ClockProgress
    now = [10.]
    state = ClockProgress(monotonic=lambda: now[0])
    for stamp in (1., 2., 3.):
        state.observe(stamp)
    assert state.fresh(.5)
    now[0] = 11.
    state.observe(3.)
    assert not state.fresh(.5)
    state.observe(0.)
    assert state.advances == 0
    assert not state.fresh(.5)
    state.observe(1.)
    assert not state.fresh(.5)
    state.observe(2.)
    assert state.fresh(.5)
