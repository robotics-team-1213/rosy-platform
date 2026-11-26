from types import SimpleNamespace as NS

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from fleet.server.work.pipeline_station_stop import assigned_rule, arrived, install, stop_reason, supervise
from test_unload_release import _state, _task


def test_assigned_station_holds_until_matching_named_release_even_after_timeout():
    app = FastAPI()
    task = dict(robot_id="r", trip_id="t", status="SENT", station_operation=assigned_rule(
        NS(stops=[NS(place="S1", role="load", release="external",timeout_s=5)]), "S1", "load"))
    app.state.pinky_tasks={"p":task, "old":{"robot_id":"r", "status":"ARRIVED"}}
    with pytest.raises(Exception, match="STATION_RULE_MISMATCH"):
        assigned_rule(NS(stops=[]),"S1","load")
    changes=[]
    def save():
        changes.append(task["station_operation"]["state"])
    app.state.trip_requester_guards=[lambda _:True]
    @app.middleware("http")
    async def identity(req, call_next):
        if req.headers.get("operator"):
            req.state.site_principal=NS(principal_id="operator")
        return await call_next(req)
    app.state.trip_runner=NS(view=lambda _:{"state":"running"})
    from fleet.server.goal_lease import GoalLeases
    from fleet.swarm.api.ports import RobotApiError
    console=NS(goal_leases=GoalLeases(0., {}))
    install(app, NS(console=console,operator_guard=[],_is_human_detected=lambda:False,_save_ledger=save))
    assert console.station_stop_reason("r") is None
    app.state.trip_runner.view=lambda _:{"state":"arrived"}
    assert stop_reason(app.state,"r")=="STATION_WAITING"
    arrived(task,10.)
    with pytest.raises(OSError):
        supervise(app.state,15.,False,lambda: (_ for _ in ()).throw(OSError()))
    assert stop_reason(app.state,"r")=="STATION_WAITING"
    supervise(app.state,15.,False,save)
    assert stop_reason(app.state,"r")=="STATION_TIMEOUT_HOLD"
    for path in ("/api/v1/navigation/goal", "/api/v1/navigation/bound-goal", "/api/v1/docking/dock"):
        with pytest.raises(RobotApiError, match="external release"):
            with console.goal_leases.motion_wire("r", "POST", path, {}):
                pytest.fail("wire was allowed during external station hold")
    with console.goal_leases.motion_wire("r", "POST", "/api/v1/teleop", {"linear":0., "angular":0.}):
        pass
    with TestClient(app) as client:
        route="/api/fleet/pipeline/pinky-tasks/p/station-release"
        body=dict(robot_id="r",trip_id="t",place_id="S1",role="load")
        assert client.post(route,json=body).status_code==403
        for field in body:
            assert client.post(route,json={**body,field:"other"},headers={"operator":"1"}).status_code==409
        for _ in range(2):
            assert client.post(route,json=body,headers={"operator":"1"}).json()["station_operation"]["state"]=="RELEASED"
    assert stop_reason(app.state,"r") is None and changes==["TIMEOUT_HOLD","RELEASED"]


def test_unload_receipt_requires_the_assigned_trip_and_batch_then_survives_duplicate_ticks():
    from time import time
    state=_state([_task(0)])
    task=dict(robot_id="rosy_46",trip_id="trip",spawned_cell_task_id="u-1",
              station_operation=dict(state="ASSIGNED",role="unload",place_id="S3",timeout_s=60))
    state.pinky_tasks={"load":task}
    arrived(task,time())
    with pytest.raises(OSError):
        supervise(state,time(),False,lambda: (_ for _ in ()).throw(OSError()))
    assert task["station_operation"]["state"]=="WAITING"
    state.omx_cell_states["cell_s"]["stage_id"]="old"
    supervise(state,time(),False,lambda:None)
    assert stop_reason(state,"rosy_46")=="STATION_WAITING"
    state.omx_cell_states["cell_s"]["stage_id"]="u-1"
    for _ in range(2):
        supervise(state,time(),False,lambda:None)
    assert task["station_operation"]["evidence"]=={"batch_id":"u","stage_id":"u-1"}
    assert task["station_operation"]["trip_id"]=="trip" and stop_reason(state,"rosy_46") is None
