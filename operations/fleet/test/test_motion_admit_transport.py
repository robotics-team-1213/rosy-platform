"""D-1079 negotiation, boot binding, generation epoch and total delivery timeout at the HTTP boundary."""
import asyncio
import json

import httpx
import pytest

from fleet.server.goal_lease import GoalLeases
from fleet.swarm.motion_ingress import ADMIT_DEADLINE_PATHS
from fleet.swarm.robots import RobotEndpoint
from fleet.swarm.transport import HttpRobotClient

BOOT = "42ab4cdc-c6d6-4a6f-81ea-25b5714187c1"
OTHER_BOOT = "99ab4cdc-c6d6-4a6f-81ea-25b5714187c9"


@pytest.mark.parametrize("admit, fence", [
    (True, True), (True, False), (False, True), (None, True), (True, None), (1, True), ("true", True),
])
@pytest.mark.parametrize("path", sorted(ADMIT_DEADLINE_PATHS))
def test_only_negotiated_navigation_starts_with_owner_epoch_send_deadline(admit, fence, path):
    async def exercise():
        seen = []

        def handler(request):
            if request.method == "GET":
                if request.url.path == "/api/v1/navigation/state":
                    return httpx.Response(200, json={"owner": {"boot_id": BOOT, "owner_generation": 2}})
                return httpx.Response(200, json={"navigation": {"admit_deadline": admit, "generation_fence": fence}})
            seen.append(json.loads(request.content))
            return httpx.Response(200, json={"accepted": True})

        async with httpx.AsyncClient(base_url="http://robot", transport=httpx.MockTransport(handler)) as http:
            client = HttpRobotClient(RobotEndpoint("r", "http://robot", "test"), http=http)
            await client.capabilities()
            await client._post(path, {})
            await client._post("/api/v1/navigation/bound-plan", {})
            expected = ([{"admit_within_s": 3.0, "expected_boot_id": BOOT, "expected_owner_generation": 2}, {}]
                        if admit is True and fence is True else [{}, {}])
            assert seen == expected

    asyncio.run(exercise())


@pytest.mark.parametrize("error", ["request", "total_timeout", "cancelled", "server"])
def test_failed_request_keeps_original_send_time_and_actual_budget(error):
    async def exercise():
        now = [10.]

        async def handler(request):
            if request.method == "GET":
                if request.url.path == "/api/v1/navigation/state":
                    return httpx.Response(200, json={"owner": {"boot_id": BOOT, "owner_generation": 4}})
                return httpx.Response(200, json={"navigation": {"admit_deadline": True, "generation_fence": True}})
            now[0] += 2.
            if error == "request":
                raise httpx.ReadTimeout("reply lost", request=request)
            if error == "total_timeout":
                raise TimeoutError("total request expired")
            if error == "cancelled":
                raise asyncio.CancelledError()
            return httpx.Response(503, json={"error": {"code": "UNAVAILABLE", "message": "no reply"}})

        async with httpx.AsyncClient(base_url="http://robot", transport=httpx.MockTransport(handler)) as http:
            client = HttpRobotClient(RobotEndpoint("r", "http://robot", "test"), http=http, timeout_s=4.)
            leases = GoalLeases(0., {"r": client}, clock=lambda: now[0])
            client.bind_motion_wire(leases.motion_wire)
            await client.capabilities()
            if error == "server":
                await client._request("POST", "/api/v1/navigation/goal", {})
            else:
                with pytest.raises((httpx.RequestError, TimeoutError, asyncio.CancelledError)):
                    await client._request("POST", "/api/v1/navigation/goal", {})
            marker = leases._uncertain_motion["r"]
            assert marker["sent_at"] == 10. and marker["since"] == 12.
            assert marker["timeout_s"] == 4. and marker["admit_within_s"] == 3.
            assert marker["release_after"] == 17.5
            assert marker["boot_id"] == BOOT and marker["owner_generation"] == 4

    asyncio.run(exercise())


def test_boot_bound_capability_sends_owner_epoch_and_resets_on_boot_change():
    async def exercise():
        boot = [BOOT]
        gen = [7]
        seen = []

        def handler(request):
            if request.url.path == "/api/v1/system/capabilities":
                return httpx.Response(200, json={"navigation": {"admit_deadline": True, "generation_fence": True}})
            if request.url.path == "/api/v1/navigation/state":
                return httpx.Response(200, json={"owner": {"boot_id": boot[0], "owner_generation": gen[0]}})
            seen.append(json.loads(request.content))
            gen[0] += 2
            return httpx.Response(200, json={"accepted": True})

        async with httpx.AsyncClient(base_url="http://robot", transport=httpx.MockTransport(handler)) as http:
            client = HttpRobotClient(RobotEndpoint("r", "http://robot", "test"), http=http)
            await client.capabilities()
            assert client._admit_boot_id == BOOT and client._owner_generation == 7
            await client._post("/api/v1/navigation/goal", {"x": 1., "y": 0.})
            assert seen[-1] == {
                "x": 1., "y": 0., "admit_within_s": 3.0,
                "expected_boot_id": BOOT, "expected_owner_generation": 7,
            }
            # Next start refreshes generation on the same boot; a boot change revokes admit_deadline.
            boot[0] = OTHER_BOOT
            await client._post("/api/v1/navigation/goal", {"x": 2., "y": 0.})
            assert client._admit_deadline is False and client._admit_boot_id is None
            assert seen[-1] == {"x": 2., "y": 0.}

    asyncio.run(exercise())


def test_refresh_failure_omits_deadline_and_keeps_uncertain_marker_unbounded():
    async def exercise():
        now = [10.]
        seen = []
        state_ok = [True]

        def handler(request):
            if request.url.path == "/api/v1/system/capabilities":
                return httpx.Response(200, json={"navigation": {"admit_deadline": True, "generation_fence": True}})
            if request.url.path == "/api/v1/navigation/state":
                if not state_ok[0]:
                    return httpx.Response(503, json={"error": {"code": "UNAVAILABLE", "message": "state down"}})
                return httpx.Response(200, json={"owner": {"boot_id": BOOT, "owner_generation": 9}})
            seen.append(json.loads(request.content))
            if len(seen) == 2:
                raise httpx.ReadTimeout("second start timed out", request=request)
            return httpx.Response(200, json={"accepted": True})

        async with httpx.AsyncClient(base_url="http://robot", transport=httpx.MockTransport(handler)) as http:
            client = HttpRobotClient(RobotEndpoint("r", "http://robot", "test"), http=http)
            leases = GoalLeases(0., {"r": client}, clock=lambda: now[0])
            client.bind_motion_wire(leases.motion_wire)
            await client.capabilities()
            await client._post("/api/v1/navigation/goal", {"x": 1., "y": 0.})
            assert client._owner_generation is None
            state_ok[0] = False
            with pytest.raises(httpx.ReadTimeout):
                await client._post("/api/v1/navigation/goal", {"x": 2., "y": 0.})
            assert seen[-1] == {"x": 2., "y": 0.}
            marker = leases._uncertain_motion["r"]
            assert marker["admit_within_s"] is None and marker["release_after"] is None
            assert marker["boot_id"] is None and marker["owner_generation"] is None

    asyncio.run(exercise())
