"""Static neighbor config and bounded HTTP transport; no device access."""

import asyncio
import json

import httpx
import pytest
import yaml

from test_control_unit_service import MANIFEST


def config_file(tmp_path, **changes):
    (tmp_path / "parent.token").write_text("parent-service-token", encoding="utf-8")
    document = {"unit_id": "A1", "manifest": MANIFEST,
                "peers": {"A": {"url": "http://parent.invalid:8080", "token_file": "parent.token"}}}
    document.update(changes)
    path = tmp_path / "control.yaml"
    path.write_text(yaml.safe_dump(document), encoding="utf-8")
    return path


def test_runtime_config_has_only_direct_neighbors_and_hides_secrets(tmp_path):
    from fleet.server.control_unit_runtime import load_control_unit
    config = load_control_unit(config_file(tmp_path))
    assert config.unit_id == "A1"
    assert set(config.peers) == {"A"}
    assert "parent-service-token" not in repr(config)


@pytest.mark.parametrize("peers", [
    {}, {"R": {"url": "http://root.invalid", "token_file": "parent.token"}},
    {"A": {"url": "http://user:password@parent.invalid", "token_file": "parent.token"}},
    {"A": {"url": "http://parent.invalid/path?token=secret", "token_file": "parent.token"}},
])
def test_rejects_missing_foreign_or_credential_bearing_peer_config(tmp_path, peers):
    from fleet.server.control_unit_runtime import load_control_unit
    with pytest.raises(ValueError):
        load_control_unit(config_file(tmp_path, peers=peers))


def test_peer_transport_uses_scoped_paths_auth_and_bounded_reply(tmp_path):
    from fleet.server.control_unit_runtime import load_control_unit, ControlUnitPeers
    requests = []
    def serve(request):
        requests.append(request)
        return httpx.Response(200, json={"ok": True})
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(serve)) as client:
            peer = ControlUnitPeers(load_control_unit(config_file(tmp_path)), client)
            assert await peer("A", "GET", "R/job-1") == {"ok": True}
            await peer("A", "POST", "inbox", {"origin_id": "R"})
            await peer("A", "POST", "R/job-1", {})
            with pytest.raises(ValueError):
                await peer("R", "GET", "R/job-1")
            with pytest.raises(ValueError):
                await peer("A", "GET", "../secrets")
    asyncio.run(exercise())
    assert [r.url.path for r in requests] == ["/api/fleet/control-unit/delegations/R/job-1",
                                            "/api/fleet/control-unit/inbox",
                                            "/api/fleet/control-unit/delegations/R/job-1/cancel"]
    assert requests[0].headers["Authorization"] == "Bearer parent-service-token"
    assert json.loads(requests[1].content) == {"origin_id": "R"}


@pytest.mark.parametrize("response,error,code", [
    (httpx.Response(302, headers={"Location": "http://other.invalid"}), httpx.HTTPStatusError, None),
    (httpx.Response(200, json={"data": "x" * 131073}), ValueError, "CONTROL_UNIT_PEER_RESPONSE_TOO_LARGE"),
])
def test_peer_transport_refuses_redirects_and_oversized_replies(tmp_path, response, error, code):
    from fleet.server.control_unit_runtime import load_control_unit, ControlUnitPeers
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: response), follow_redirects=True) as client:
            peer = ControlUnitPeers(load_control_unit(config_file(tmp_path)), client)
            with pytest.raises(error, match=code):
                await peer("A", "GET", "R/job-1")
    asyncio.run(exercise())
