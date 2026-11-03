"""라이브 CORE 기능 판정 — 배포된 로봇의 읽기 표면을 그대로 잰다 (D-527 장치 수용).

옵트인: ROSY_LIVE_CORE_URL(로봇 주소)과 읽기 자격(ROSY_LIVE_CORE_TOKEN, 또는
ROSY_LIVE_CORE_TOKEN_FILE 경로)을 환경으로 주면 실물 CORE API에 읽기 요청만 보내
각 기능이 살아 있는지 판정한다. 로봇 인증서가 내부 CA면 ROSY_LIVE_CORE_CA로
그 CA 파일 경로를 준다. 쓰기·명령은 없다 — 명령 거부 경로 검증은 사람이 로봇을
안전 상태로 둔 뒤 별도 수용이 한다. 주소·자격이 없으면 건너뛴다(CI 무해).
test_live_fleet_function.py 와 짝이 되는 로봇 쪽 판정이다.

실행(로봇이 보이는 원격 시험 호스트에서):
    ROSY_TEST_HOSTS=<user@addr> python tools/remote/remote_pytest.py --log-dir "$ROSY_SCRATCH/field" -- \
        ROSY_LIVE_CORE_URL=https://<robot-host> \
        ROSY_LIVE_CORE_TOKEN_FILE=/home/<user>/rosy-test/.live-core-<robot>.token \
        ROSY_LIVE_CORE_CA=/home/<user>/rosy-test/<robot>-ca.crt \
        test/test_live_core_function.py -v

판정 기준은 ROSY API & Protocol Reference 를 따른다:
401(미인증 거부), GET /api/v1/robot/state(스냅숏·채널별 evidence v1.8·seq),
GET /api/v1/safety/state(래치 source, thermal additive).
"""

from __future__ import annotations

import os
import ssl
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx
import pytest

pytestmark = pytest.mark.skipif(
    not (os.environ.get("ROSY_LIVE_CORE_URL")
         and (os.environ.get("ROSY_LIVE_CORE_TOKEN") or os.environ.get("ROSY_LIVE_CORE_TOKEN_FILE"))),
    reason="set ROSY_LIVE_CORE_URL and a token (ROSY_LIVE_CORE_TOKEN or _TOKEN_FILE) to judge a deployed robot",
)

EVIDENCE_STATES = {"fresh", "delayed", "disconnected", "unavailable"}


@pytest.fixture(scope="module")
def site() -> str:
    origin = urlparse(os.environ["ROSY_LIVE_CORE_URL"])
    return f"{origin.scheme}://{origin.netloc}"


@pytest.fixture(scope="module")
def authed(site):
    token = os.environ.get("ROSY_LIVE_CORE_TOKEN")
    if not token:
        token = Path(os.environ["ROSY_LIVE_CORE_TOKEN_FILE"]).read_text(encoding="utf-8").strip()
    headers = {"Authorization": "Bearer " + token}
    with httpx.Client(base_url=site, timeout=15, headers=headers, verify=_verify()) as client:
        yield client


def _verify():
    ca = os.environ.get("ROSY_LIVE_CORE_CA")
    return ssl.create_default_context(cafile=ca) if ca else True


def test_unauthenticated_state_readback_is_refused(site):
    with httpx.Client(base_url=site, timeout=15, verify=_verify()) as client:
        response = client.get("/api/v1/robot/state")
    assert response.status_code == 401, (
        f"미인증 읽기가 {response.status_code}로 돌아왔다 — 배포 인증이 성립하지 않는다")


def test_state_snapshot_reports_channel_evidence(authed):
    response = authed.get("/api/v1/robot/state")
    assert response.status_code == 200, response.text[:200]
    body = response.json()
    assert isinstance(body.get("protocol_version"), str), body.get("protocol_version")
    assert isinstance(body.get("seq"), int), body.get("seq")
    assert body.get("timestamp"), body.get("timestamp")
    evidence = body.get("evidence")
    assert isinstance(evidence, dict) and evidence, "채널별 evidence(v1.8)가 없다"
    for channel, row in evidence.items():
        assert isinstance(row, dict) and row.get("evidence") in EVIDENCE_STATES, (channel, row)
    assert "battery" in evidence, f"배터리 채널이 없다: {sorted(evidence)}"
    assert isinstance(body.get("diagnostics_summary"), dict), body.get("diagnostics_summary")


def test_state_seq_advances_between_reads(authed):
    first = authed.get("/api/v1/robot/state")
    assert first.status_code == 200, first.text[:200]
    seq = first.json()["seq"]
    deadline = time.monotonic() + 3  # 스냅숏 갱신 주기가 느려도 3 s 안에는 한 번은 움직인다
    while time.monotonic() < deadline:
        time.sleep(.2)
        body = authed.get("/api/v1/robot/state").json()
        if body["seq"] > seq:
            return
    assert False, f"seq가 {seq}에서 3 s 동안 움직이지 않는다 — 스냅숏이 얼어 있다"


def test_safety_state_reports_latch_provenance(authed):
    response = authed.get("/api/v1/safety/state")
    assert response.status_code == 200, response.text[:200]
    body = response.json()
    assert isinstance(body.get("source"), str), body.get("source")  # 래치를 건 쪽, 없으면 빈 문자열
    if isinstance(body.get("thermal"), dict):  # additive: 옛 배포에는 없을 수 있다
        for key in ("level", "reasons", "motors"):
            assert key in body["thermal"], (key, body["thermal"])
