import asyncio
import json
from types import SimpleNamespace as NS

import httpx
import pytest
from fastapi import FastAPI, Header, HTTPException

from fleet.server.console import FleetConsole
from fleet.server.ledger.named_stop_store import NamedStopStore
from fleet.server.named_stop_motion import NamedStopMotion
from fleet.server.trips.precision_correction_routes import install_precision_correction_routes
from fleet.swarm.robots import RobotEndpoint
from fleet.swarm.transport import HttpRobotClient
from test_named_stop_motion import BOOT, RUN


@pytest.mark.parametrize("case", ["valid", "untrusted_operator", "no_clearance", "wrong_run", "wrong_endpoint",
                                  "changed_after_handover", "lost_reply"])
def test_approved_trip_dispatches_at_most_one_exact_repark(tmp_path, case):
    async def run():
        journal = NamedStopStore(tmp_path / "site.db")
        claim = NamedStopMotion("pinky", BOOT, "approach", RUN, precision_required=True)
        assert journal.claim(claim) and journal.bind_run(claim)
        operation = dict(kind="navigate", boot_id=BOOT, run_id=RUN, correlation_id="approach", phase="TERMINAL",
                         result="SUCCEEDED")
        owner = dict(boot_id=BOOT, owner_generation=8, owner_run_id=None)
        grid, sha = "occupancy:0123456789ab", "a" * 64
        posts, audit = [], []
        handover_done = False

        async def robot(req):
            nonlocal handover_done
            path = req.url.path
            if req.method == "POST":
                posts.append(path)
                body = json.loads(req.content)
                if path == "/api/v1/navigation/handover":
                    assert body["run_id"] == RUN and body["expected_map_grid_id"] == grid
                    handover_done = True
                    return httpx.Response(200, json=dict(accepted=True, mode="IDLE", run_id=RUN, boot_id=BOOT,
                                                         owner_generation=8, map_grid_id=grid, idle_mode_epoch=11))
                assert path == "/api/v1/motion/repark/run" and audit
                assert body["forward_m"] == .04 and body["left_m"] == 0. and body["expected_idle_epoch"] == 11
                assert body["expected_nav_run_id"] == RUN and body["expected_boot_id"] == BOOT
                assert body["expected_owner_generation"] == 3 and body["operator_name"] == "alice"
                assert journal.current().repark_correlation_id == body["correlation_id"]
                if case == "lost_reply":
                    raise httpx.ReadTimeout("lost reply", request=req)
                return httpx.Response(202, json={"accepted": True})
            if path == "/api/v1/motion/repark/run":
                return httpx.Response(200, json={"owner": {"boot_id": BOOT, "owner_generation": 3}})
            assert path == "/api/v1/navigation/state" and req.url.params["run_id"] == RUN
            proof = dict(**owner, requested_run_id=RUN, transport_generation=4, quiescent=True,
                         observed_at="2026-11-20T01:00:00+00:00", admitting=False, pending_submission=False,
                         actuating_callback=False, lease_active=False)
            return httpx.Response(200, json=dict(operation=operation, owner=owner, quiescence=proof, lookup="FOUND"))

        async def preview(*_):
            change = case == "changed_after_handover" and handover_done
            return {"forward_m": .03 if change else .04, "site_end": [.745, -.207]}

        evidence = dict(map_sha256=sha, place="S3", map_grid_id=grid, binding_id="binding")
        live = NS(open=True, view={"robot_id": "pinky", "detail": {"named_stop_dispatch": evidence,
                                                                  "named_stop_operation": operation}})
        scope = NS(_find=lambda trip_id: live if trip_id == "trip" else None, check_named_correction=preview)
        maps = NS(active_view=lambda: {"sha256": sha, "map": {"places": [{"id": "S3", "precision_stop": {}}]}},
                  map_bindings=NS(active=lambda robot: {"binding_id": "binding"}), record_event=lambda *entry: audit.append(entry))
        endpoint = RobotEndpoint("pinky", "http://pinky", "operator")
        async with httpx.AsyncClient(transport=httpx.MockTransport(robot), base_url="http://pinky") as link:
            console = FleetConsole([endpoint], [HttpRobotClient(endpoint, http=link)])
            console.goal_leases.restore_named_stop(journal)
            console._named_stop_site_maps = maps
            app = FastAPI()

            async def authenticate(x_actor: str | None = Header(None)):
                if x_actor != "alice":
                    raise HTTPException(403)
                return NS(principal_id=x_actor)

            install_precision_correction_routes(app, console=console, runner=scope,
                                                require_named_operator=authenticate, cable_inhibited=lambda _: False)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://fleet") as fleet:
                checked = dict(nav_run_id=BOOT if case == "wrong_run" else RUN, map_sha256=sha, forward_m=.04,
                               site_end=[.75, -.207] if case == "wrong_endpoint" else [.745, -.207],
                               cable_and_path_clear=case != "no_clearance")
                header = {} if case == "untrusted_operator" else {"X-Actor": "alice"}
                path = "/api/fleet/trips/trip/correction-clearance"
                response = await fleet.post(path, json=checked, headers=header)
                expected = {"valid": 202, "untrusted_operator": 403, "lost_reply": 503}.get(case, 409)
                assert response.status_code == expected, response.text
                if case in ("valid", "lost_reply"):
                    assert (await fleet.post(path, json=checked, headers=header)).status_code == 409
                    assert posts.count("/api/v1/motion/repark/run") == 1
                    assert journal.current().repark_correlation_id
                else:
                    assert posts == (["/api/v1/navigation/handover"] if case == "changed_after_handover" else [])
                    assert journal.current().repark_correlation_id is None

    asyncio.run(run())
