from types import SimpleNamespace
import time

from fastapi import FastAPI
from fastapi.testclient import TestClient

from fleet.routing.graph import build_graph
from fleet.server.pipeline_routes import install_pipeline_routes
from fleet.site_map import SiteMap


def _map():
    return SiteMap(map_id="pipeline-test", places=[
        {"id": "C1", "name": "C1", "x": 0, "y": 0, "kind": "charge"},
        {"id": "C2", "name": "C2", "x": 1, "y": 0, "kind": "charge"},
        {"id": "C3", "name": "C3", "x": 2, "y": 0, "kind": "charge"},
        {"id": "S1", "name": "S1", "x": 3, "y": 0, "kind": "junction"},
    ], edges=[
        {"id": f"e{i}", "from": p1, "to": p2, "direction": "two_way",
         "width_m": 0.5, "speed_cap_mps": 0.15, "polyline": [[i - 1, 0], [i, 0]]}
        for i, (p1, p2) in enumerate((("C1", "C2"), ("C2", "C3"), ("C3", "S1")), 1)
    ])


def test_fleet_estop_and_restart_revoke_staged_omx_homing_fence(tmp_path, monkeypatch):
    site_map = _map()
    graph = build_graph(site_map)
    maps = SimpleNamespace(active=lambda: (1, site_map, graph, None),
                           rules=SimpleNamespace(active_rules=lambda: None))
    app = FastAPI()
    ctrl = {"dispatch_enabled": True, "generation": 1, "authority_epoch": 1}

    def _trip_latch(**_k):
        ctrl["dispatch_enabled"] = False
        ctrl["generation"] += 1
        return dict(ctrl)

    app.state.task_service = SimpleNamespace(store=SimpleNamespace(
        dispatch_control=lambda: dict(ctrl),
        trip_stop_latch=_trip_latch,
    ))
    install_pipeline_routes(app, site_maps=maps)
    client = TestClient(app)

    t_res = client.post("/api/fleet/pipeline/cell-tasks", json={"task_id": "fold-abort-1", "cell_id": "cell_s"}).json()
    tid = t_res["task"]["task_id"]
    app.state.omx_cell_tasks[tid]["status"] = "ABORTED"
    app.state.omx_cell_tasks[tid]["reason"] = "FOLD_READBACK_MISSING"
    app.state.arm_live_states["arm_s"]["folded"] = False
    now = time.time()
    app.state.arm_live_states["arm_s"]["updated_at"] = now
    app.state.cell_camera_quality.update({
        "arm_s_top": {"fresh": True, "sequence": 10, "recorded_at": now, "receipt_age_s": 0.1},
        "arm_s_wrist": {"fresh": True, "sequence": 11, "recorded_at": now, "receipt_age_s": 0.1},
    })

    ctx_row = client.get("/api/fleet/pipeline/recovery-tools").json()["active_failures"][0]
    inv = client.post("/api/fleet/pipeline/recovery-tools/invoke", json={
        "tool_name": "safe_fold_home",
        "arguments": {"arm_id": "arm_s", "strategy": "release_and_lift"},
        "caller_kind": "llm_agent",
        "request_id": "req-fence-1",
        "root_task_id": ctx_row["root_task_id"],
        "expected_context_sha256": ctx_row["context_sha256"],
        "rationale": "stage release and lift before park",
    })
    assert inv.status_code == 200
    q1 = client.post("/api/fleet/pipeline/cell-quality", json={"schema": "rosy.pipeline.cell-quality.v1", "cameras": {}}).json()
    assert q1["human_hold"] is False and "arm_s" in q1["pending_safe_home_arms"]
    gen_before = q1["safety_stop_generation"]
    assert type(gen_before) is int

    # Trip Fleet-wide E-stop latch WITHOUT calling pipeline human stop.
    _trip_latch()
    q2 = client.post("/api/fleet/pipeline/cell-quality", json={"schema": "rosy.pipeline.cell-quality.v1", "cameras": {}}).json()
    assert q2["human_hold"] is True
    assert q2["pending_safe_home_arms"] == {}
    assert type(q2["safety_stop_generation"]) is int and q2["safety_stop_generation"] > gen_before
    assert app.state.pipeline_homing_sessions[ctx_row["root_task_id"]]["stage"] == "SKIPPED"

    # Unreadable dispatch authority fails closed with safety_stop_generation=None and refuses safe_fold_home.
    ctrl["dispatch_enabled"] = True
    app.state.task_service = SimpleNamespace(store=SimpleNamespace(
        dispatch_control=lambda: (_ for _ in ()).throw(RuntimeError("sqlite down")),
    ))
    q3 = client.post("/api/fleet/pipeline/cell-quality", json={"schema": "rosy.pipeline.cell-quality.v1", "cameras": {}}).json()
    assert q3["human_hold"] is True and q3["safety_stop_generation"] is None and q3["pending_safe_home_arms"] == {}
    ctx_unreadable = client.get("/api/fleet/pipeline/recovery-tools").json()["active_failures"][0]
    inv_bad = client.post("/api/fleet/pipeline/recovery-tools/invoke", json={
        "tool_name": "safe_fold_home",
        "arguments": {"arm_id": "arm_s", "strategy": "release_and_lift"},
        "caller_kind": "llm_agent",
        "request_id": "req-fence-2",
        "root_task_id": ctx_row["root_task_id"],
        "expected_context_sha256": ctx_unreadable["context_sha256"],
        "rationale": "should refuse without stop authority",
    })
    assert inv_bad.status_code == 409 and inv_bad.json()["detail"]["code"] == "STOP_AUTHORITY_UNAVAILABLE"

    # Failed Fleet E-stop latch write (while old dispatch row still reads dispatch_enabled=True) closes fence anyway.
    import asyncio
    from fleet.server.ledger.task_dispatch_routes import install_task_dispatch_routes
    from rosy_account.principal import SitePrincipal

    app_latch = FastAPI()
    ctrl_latch = {"dispatch_enabled": True, "generation": 1, "authority_epoch": 1}
    allow_latch = [False]

    def _maybe_latch(**_k):
        if not allow_latch[0]:
            raise RuntimeError("sqlite busy")
        ctrl_latch["dispatch_enabled"] = False
        ctrl_latch["generation"] += 1
        return dict(ctrl_latch)

    def _rearm_dispatch(**_k):
        ctrl_latch["dispatch_enabled"] = True
        ctrl_latch["generation"] += 1
        return {"dispatch_enabled": True, "generation": ctrl_latch["generation"], "authority_epoch": 1}

    fake_store = SimpleNamespace(
        dispatch_control=lambda: dict(ctrl_latch),
        trip_stop_latch=_maybe_latch,
        rearm_dispatch=_rearm_dispatch,
    )
    fake_svc = SimpleNamespace(store=fake_store, cancel_all_queued=lambda **_k: [])
    fake_console = SimpleNamespace(
        estop_all=lambda: asyncio.sleep(0, result={"robots": []}),
        discard_task_queue_entries=lambda _s: None,
    )
    op_principal = SitePrincipal(principal_id="op1", role="operator")
    # While dispatch_rearm awaits OMX rearm, trigger an E-stop whose latch write fails -> must supersede rearm.
    app_rearm = FastAPI()

    class _SlowStopTransport:
        def stop(self, **_k):
            return {"state": "LOCAL_LATCHED"}

        def rearm(self, **_k):
            app_rearm.state.safety_stop_generation = int(getattr(app_rearm.state, "safety_stop_generation", 0)) + 1
            app_rearm.state._fleet_estop_latch_unresolved = True
            return {"state": "OPEN"}

    install_task_dispatch_routes(
        app_rearm, console=fake_console, task_service=fake_svc,
        configured_omx={"cell_s": "omx1"}, stop_transport=_SlowStopTransport(),
        require_viewer=lambda: op_principal, require_operator=lambda: op_principal,
        require_named_operator=lambda: op_principal, read_guard=(), operator_guard=(),
        authorize=lambda: op_principal,
    )
    r_sup = TestClient(app_rearm).post("/api/fleet/dispatch/rearm", json={"expected_generation": 1})
    assert r_sup.status_code == 409 and r_sup.json()["detail"]["code"] == "DISPATCH_REARM_SUPERSEDED"
    assert app_rearm.state._fleet_estop_latch_unresolved is True

    install_task_dispatch_routes(
        app_latch, console=fake_console, task_service=fake_svc, configured_omx={}, stop_transport=None,
        require_viewer=lambda: op_principal, require_operator=lambda: op_principal,
        require_named_operator=lambda: op_principal, read_guard=(), operator_guard=(), authorize=lambda: op_principal,
    )
    app_latch.state.task_service = fake_svc
    install_pipeline_routes(app_latch, site_maps=maps)
    c_latch = TestClient(app_latch)
    t_l = c_latch.post("/api/fleet/pipeline/cell-tasks", json={"task_id": "fold-abort-latch", "cell_id": "cell_s"}).json()
    app_latch.state.omx_cell_tasks[t_l["task"]["task_id"]]["status"] = "ABORTED"
    app_latch.state.omx_cell_tasks[t_l["task"]["task_id"]]["reason"] = "FOLD_READBACK_MISSING"
    app_latch.state.arm_live_states["arm_s"].update(folded=False, updated_at=now)
    app_latch.state.cell_camera_quality.update({
        "arm_s_top": {"fresh": True, "sequence": 10, "recorded_at": now, "receipt_age_s": 0.1},
        "arm_s_wrist": {"fresh": True, "sequence": 11, "recorded_at": now, "receipt_age_s": 0.1},
    })
    stale_pre_stop = c_latch.get("/api/fleet/pipeline/recovery-tools").json()["active_failures"][0]
    assert c_latch.post("/api/fleet/estop").status_code == 200
    assert app_latch.state._fleet_estop_latch_unresolved is True
    q_latch = c_latch.post("/api/fleet/pipeline/cell-quality", json={"schema": "rosy.pipeline.cell-quality.v1", "cameras": {}}).json()
    assert q_latch["human_hold"] is True and q_latch["safety_stop_generation"] is None and q_latch["pending_safe_home_arms"] == {}
    # Must refuse STOP_AUTHORITY_UNAVAILABLE even when caller holds pre-E-stop context digest.
    inv_latch = c_latch.post("/api/fleet/pipeline/recovery-tools/invoke", json={
        "tool_name": "safe_fold_home",
        "arguments": {"arm_id": "arm_s", "strategy": "release_and_lift"},
        "caller_kind": "llm_agent",
        "request_id": "req-latch-fail",
        "root_task_id": stale_pre_stop["root_task_id"],
        "expected_context_sha256": stale_pre_stop["context_sha256"],
        "rationale": "must fail closed after latch write failure",
    })
    assert inv_latch.status_code == 409 and inv_latch.json()["detail"]["code"] == "STOP_AUTHORITY_UNAVAILABLE"

    # Restarting with a persisted pending_safe_home_arms entry from a previous authority epoch prunes it.
    from fleet.server import pipeline_routes as pr

    monkeypatch.setattr(pr, "_storage_dir", lambda: tmp_path)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    gov_db = tmp_path / "rosy-pipeline-governance.sqlite3"
    from fleet.server.sitemap.pipeline_ledger import write_ledger
    app_r1 = FastAPI()
    app_r1.state.pipeline_governance_db_path = gov_db
    pr.install_pipeline_routes(app_r1, site_maps=maps)
    payload = {
        "omx_cell_states": app_r1.state.omx_cell_states, "omx_cell_tasks": app_r1.state.omx_cell_tasks,
        "pinky_tasks": app_r1.state.pinky_tasks, "unload_releases": {}, "cell_auto_events": [],
        "repark_requests": {}, "repark_done": [], "pipeline_decisions": [],
        "pipeline_homing_sessions": {"t1": {"root_task_id": "t1", "arm_id": "arm_s", "stage": "EXECUTING_RELEASE_AND_LIFT"}},
        "pending_safe_home_arms": {"arm_s": {"request_id": "old", "root_task_id": "t1", "arm_id": "arm_s", "stop_generation": 1_000_000}},
        "detected_displaced_site": None, "cable_tangled": True, "human_detected": app_r1.state.human_detected,
        "_gov_managed": True,
    }
    write_ledger(tmp_path / "rosy-pipeline-ledger.json", payload)
    app_r1.state.pipeline_governance.commit_enqueue(bump_dispatch=False, ledger_snapshot=payload)

    app_r2 = FastAPI()
    app_r2.state.pipeline_governance_db_path = gov_db
    pr.install_pipeline_routes(app_r2, site_maps=maps)
    assert app_r2.state.pending_safe_home_arms == {}
    assert app_r2.state.pipeline_homing_sessions["t1"]["stage"] == "SKIPPED"


def test_unresolved_fleet_estop_latch_blocks_pinky_dispatch_and_runner_start(tmp_path, monkeypatch):
    import asyncio
    import sqlite3
    import pytest
    from fleet.server.ledger.task_dispatch_routes import install_task_dispatch_routes
    from fleet.server.sitemap import pipeline_pinky_dispatch as pd
    from fleet.server.trip_ports import TripError
    from fleet.server.trip_routes import install_trip_routes
    from rosy_account.principal import SitePrincipal
    from test_trip_runner import _plan, _setup

    monkeypatch.setenv(pd.FLAG, "1")
    site_map = _map()
    graph = build_graph(site_map)
    maps = SimpleNamespace(active=lambda: (1, site_map, graph, None),
                           rules=SimpleNamespace(active_rules=lambda: None))
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE fleet_cancel_all (cancel_all_id TEXT, opened_at TEXT)")

    class _Conn:
        def execute(self, *a):
            return db.execute(*a)

        def close(self):
            pass

    store = SimpleNamespace(
        dispatch_control=lambda: {"dispatch_enabled": True, "generation": 1, "authority_epoch": 1},
        trip_stop_latch=lambda **_k: (_ for _ in ()).throw(RuntimeError("sqlite down")),
        _connect=lambda: _Conn(),
    )
    svc = SimpleNamespace(store=store, cancel_all_queued=lambda **_k: [])
    starts = []

    class _FakeRunner:
        def __init__(self):
            self.lease = SimpleNamespace(required=True)
            self.human_hold_fn = None

        def robot_busy(self, _rid):
            return False

        def _start_token(self, _rid):
            return (0, 0)

        async def start(self, plan_id, _pid, start_token=None, start_guard=None):
            if start_guard is not None:
                await start_guard()
            if callable(self.human_hold_fn) and self.human_hold_fn():
                raise TripError(409, "TRIP_START_CANCELED")
            starts.append(plan_id)
            return {"trip_id": plan_id, "robot_id": "rosy_46", "state": "started"}

    fake_console = SimpleNamespace(
        estop_all=lambda: asyncio.sleep(0, result={"robots": []}),
        discard_task_queue_entries=lambda _s: None,
        snapshot=lambda: asyncio.sleep(0, result={
            "robots": [{"robot_id": "rosy_46", "online": True, "state": {"safety": {"estop": False}}}]
        }),
    )
    op = SitePrincipal(principal_id="op1", role="operator")
    app = FastAPI()
    runner = _FakeRunner()
    app.state.trip_runner = runner
    app.state.task_service = svc
    install_task_dispatch_routes(
        app, console=fake_console, task_service=svc, configured_omx={}, stop_transport=None,
        require_viewer=lambda: op, require_operator=lambda: op,
        require_named_operator=lambda: op, read_guard=(), operator_guard=(), authorize=lambda: op,
    )
    install_pipeline_routes(app, site_maps=maps, console=fake_console)

    # 1) /api/fleet/estop latch write fails -> initial dispatch_tick refuses DISPATCH_CLOSED.
    assert TestClient(app).post("/api/fleet/estop").status_code == 200
    assert app.state._fleet_estop_latch_unresolved is True
    assert callable(runner.human_hold_fn) and runner.human_hold_fn() is True

    app.state.pinky_tasks["p1"] = {
        "task_id": "p1", "robot_id": "rosy_46", "action": "dock_s3", "status": "QUEUED",
        "place_id": "S1", "map_version": 1, "requested_by": "op1", "requester_named": True,
        "created_at": time.time(),
    }
    sent = asyncio.run(pd.dispatch_tick(
        app.state, console=fake_console, runner=runner, plan=lambda *_a: asyncio.sleep(0, result={"plan_id": "pl-1"}),
        task_service=svc, active=(1, site_map, graph, None), human_detected=lambda: False,
        save=lambda: None, now=time.time(), trip_request=lambda place: place,
    ))
    assert sent == [] and starts == []
    assert app.state.pinky_tasks["p1"]["status"] == "REFUSED"
    assert app.state.pinky_tasks["p1"]["reason"] == "DISPATCH_CLOSED"

    # 2) Failed latch write during await plan(...) -> start_guard blocks runner.start.
    app.state._fleet_estop_latch_unresolved = False
    app.state.pinky_tasks["p2"] = {
        "task_id": "p2", "robot_id": "rosy_46", "action": "dock_s3", "status": "QUEUED",
        "place_id": "S1", "map_version": 1, "requested_by": "op1", "requester_named": True,
        "created_at": time.time(),
    }

    async def _plan_during_estop(_rid, _req, _pid):
        app.state._fleet_estop_latch_unresolved = True
        return {"plan_id": "pl-2"}

    sent2 = asyncio.run(pd.dispatch_tick(
        app.state, console=fake_console, runner=runner, plan=_plan_during_estop,
        task_service=svc, active=(1, site_map, graph, None), human_detected=lambda: False,
        save=lambda: None, now=time.time(), trip_request=lambda place: place,
    ))
    assert sent2 == [] and starts == []
    assert app.state.pinky_tasks["p2"]["status"] == "FAILED"
    assert app.state.pinky_tasks["p2"]["reason"] == "DISPATCH_CLOSED"

    # 3) Direct POST /api/fleet/trips/{plan_id}/start and fault during lease.open() must also fail closed.
    real_runner, t_store, t_ports = _setup(path=tmp_path / "direct_trip.sqlite3")
    _plan(t_store, t_ports, "ring_s:fwd", 0.1, "NW", plan_id="p-direct")
    direct_ctrl = {"dispatch_enabled": True, "generation": 1, "authority_epoch": 1}
    raise_ctrl = [False]

    def _read_direct_ctrl():
        if raise_ctrl[0]:
            raise RuntimeError("dispatch store unavailable")
        return dict(direct_ctrl)

    direct_app = FastAPI()
    direct_app.state.task_service = SimpleNamespace(store=SimpleNamespace(dispatch_control=_read_direct_ctrl))
    install_trip_routes(
        direct_app, console=fake_console, site_maps=t_store, routing_config=t_store.routing_config,
        require_operator=lambda: op, require_named_operator=lambda: op,
        caps_for=t_ports.caps_for, runner=real_runner, read_guard=(),
    )
    install_pipeline_routes(direct_app, site_maps=maps, console=fake_console)
    c_direct = TestClient(direct_app)

    direct_app.state._pipeline_ledger_fault = True
    r_fault = c_direct.post("/api/fleet/trips/p-direct/start")
    assert r_fault.status_code == 409 and r_fault.json()["detail"]["code"] == "HUMAN_HOLD"

    direct_app.state._pipeline_ledger_fault = False
    raise_ctrl[0] = True
    r_ctrl_err = c_direct.post("/api/fleet/trips/p-direct/start")
    assert r_ctrl_err.status_code == 409 and r_ctrl_err.json()["detail"]["code"] == "HUMAN_HOLD"

    raise_ctrl[0] = False
    direct_app.state._fleet_estop_latch_unresolved = True
    r_latch = c_direct.post("/api/fleet/trips/p-direct/start")
    assert r_latch.status_code == 409 and r_latch.json()["detail"]["code"] == "HUMAN_HOLD"

    direct_app.state._fleet_estop_latch_unresolved = False
    direct_ctrl.clear()
    direct_ctrl.update({"dispatch_enabled": False, "reason": "STARTUP_HOLD", "generation": 1})
    r_startup = c_direct.post("/api/fleet/trips/p-direct/start")
    # The closed dispatch latch alone still refuses, under its own name with the rearm facts (not a human hazard).
    assert r_startup.status_code == 409 and r_startup.json()["detail"]["code"] == "DISPATCH_REARM_REQUIRED"
    assert r_startup.json()["detail"]["detail"]["reason"] == "STARTUP_HOLD"

    direct_ctrl.clear()
    r_missing = c_direct.post("/api/fleet/trips/p-direct/start")
    assert r_missing.status_code == 409 and r_missing.json()["detail"]["code"] == "HUMAN_HOLD"

    direct_ctrl.update({"dispatch_enabled": True, "generation": 1, "authority_epoch": 1})
    released = []

    async def _lease_open_with_fault(robot_id, meta, caps):
        direct_app.state._pipeline_ledger_fault = True
        return {"lease_id": "L-post"}

    async def _lease_release(robot_id, lease_id):
        released.append((robot_id, lease_id))

    real_runner.lease.open = _lease_open_with_fault
    real_runner.lease.release = _lease_release
    with pytest.raises(TripError) as lease_err:
        asyncio.run(real_runner.start("p-direct", "op1", start_guard=lambda: asyncio.sleep(0)))
    assert lease_err.value.code == "HUMAN_HOLD"
    assert released == [("rosy_60", "L-post")] and real_runner.open_trips() == []

    # Real caller start_guard that passes pre-lease and refuses post-lease must also run after lease.open() and release lease.
    direct_app.state._pipeline_ledger_fault = False
    phase = ["pre"]

    async def _lease_open_for_guard(robot_id, meta, caps):
        phase[0] = "post"
        return {"lease_id": "L-guard"}

    async def _post_lease_guard():
        if phase[0] == "post":
            raise TripError(409, "DISPATCH_CLOSED")

    real_runner.lease.open = _lease_open_for_guard
    with pytest.raises(TripError) as guard_err:
        asyncio.run(real_runner.start("p-direct", "op1", start_guard=_post_lease_guard))
    assert guard_err.value.code == "DISPATCH_CLOSED"
    assert ("rosy_60", "L-guard") in released and real_runner.open_trips() == []
