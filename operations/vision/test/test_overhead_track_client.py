"""D-457 4: Vision writes detections and reads its own config with the source token only."""

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from core_common.protocol.overhead_detections import OverheadDetectionsPayload
from rosy_vision.track.fleet_client import TrackClient, TrackPublishError

FIXTURE = json.loads((Path(__file__).resolve().parents[3]
                      / "test/fixtures/protocol/overhead-detections.v1.json").read_text(encoding="utf-8"))
CASES = {case["id"]: case for case in FIXTURE["cases"]}
CONFIG = FIXTURE["config_example"]


def _run(handler, call):
    async def run():
        async with TrackClient("http://127.0.0.1:8090", "source-secret",
                               transport=httpx.MockTransport(handler)) as client:
            return await call(client)
    return asyncio.run(run())


def test_publish_posts_the_payload_with_the_source_token_header_only():
    observed = []

    def handler(request):
        observed.append(request)
        return httpx.Response(200, json={"accepted": True, "source_id": "ceiling_north", "seq": 41,
                                         "status": "OK"})

    payload = OverheadDetectionsPayload.model_validate(CASES["ok_two_detections"]["payload"])
    assert _run(handler, lambda client: client.publish(payload))["accepted"] is True
    request = observed[0]
    assert (request.method, request.url.path, request.url.query) == ("POST", "/api/fleet/detections", b"")
    assert request.headers["authorization"] == "Bearer source-secret"
    assert json.loads(request.content) == CASES["ok_two_detections"]["payload"]
    assert b"source-secret" not in request.content


def test_rejection_carries_the_fleet_code():
    def handler(_request):
        return httpx.Response(409, json={"detail": {"code": "CALIBRATION_MISMATCH", "message": "no"}})

    payload = OverheadDetectionsPayload.model_validate(CASES["ok_empty"]["payload"])
    with pytest.raises(TrackPublishError) as err:
        _run(handler, lambda client: client.publish(payload))
    assert (err.value.status_code, err.value.code) == (409, "CALIBRATION_MISMATCH")


def test_rejection_without_a_fleet_code_gets_a_generic_one():
    payload = OverheadDetectionsPayload.model_validate(CASES["ok_empty"]["payload"])
    with pytest.raises(TrackPublishError) as err:
        _run(lambda _request: httpx.Response(502, text="bad gateway"), lambda client: client.publish(payload))
    assert (err.value.status_code, err.value.code) == (502, "DETECTION_HTTP_ERROR")


def test_config_read_returns_the_source_config():
    observed = []

    def handler(request):
        observed.append(request)
        return httpx.Response(200, json=CONFIG)

    assert _run(handler, lambda client: client.fetch_config()) == CONFIG
    assert (observed[0].method, observed[0].url.path) == ("GET", "/api/fleet/detections/config")
    assert observed[0].headers["authorization"] == "Bearer source-secret"


@pytest.mark.parametrize("body", [[], {"source_id": "ceiling_north"},
                                  {**CONFIG, "relearn_seq": "1"}, {**CONFIG, "calibration": []}])
def test_malformed_config_is_an_error(body):
    with pytest.raises(TrackPublishError) as err:
        _run(lambda _request: httpx.Response(200, json=body), lambda client: client.fetch_config())
    assert err.value.code == "CONFIG_BAD_RESPONSE"


@pytest.mark.parametrize("url,token", [("ftp://fleet", "t"), ("https://u:p@fleet", "t"),
                                       ("https://fleet?x=1", "t"), ("https://fleet", "")])
def test_base_url_must_be_a_plain_origin_and_token_present(url, token):
    with pytest.raises(ValueError):
        TrackClient(url, token)
