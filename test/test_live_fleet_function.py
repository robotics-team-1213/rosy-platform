"""라이브 Fleet 기능 판정 — 배포된 사이트의 읽기 표면을 그대로 잰다 (D-527 현장 수용).

옵트인: ROSY_LIVE_FLEET_URL(사이트 주소)과 읽기 자격(ROSY_LIVE_FLEET_TOKEN, 또는
ROSY_LIVE_FLEET_TOKEN_FILE 경로)을 환경으로 주면 실물 Fleet API에 읽기 요청만 보내
각 기능이 살아 있는지 판정한다. 사이트 인증서가 내부 CA면 ROSY_LIVE_FLEET_CA로
그 CA 파일 경로를 준다. 쓰기·로봇 명령은 없다. 주소·자격이 없으면 건너뛴다
(CI에는 영향 없음). test_live_surface_gates.py 와 같은 ROSY_LIVE_FLEET_URL 을 쓴다.

실행(사이트 PC를 시험 호스트로 — 자격 파일과 CA가 거기에 있다):
    ROSY_TEST_HOSTS=robttt python tools/remote/remote_pytest.py --log-dir "$ROSY_SCRATCH/field" -- \
        ROSY_LIVE_FLEET_URL=https://<site-host>:8443 \
        ROSY_LIVE_FLEET_TOKEN_FILE=/etc/rosy/site/secrets/site-update-viewer.token \
        ROSY_LIVE_FLEET_CA=/etc/rosy/site/secrets/site-ca.crt \
        test/test_live_fleet_function.py -v

판정 기준은 operations/fleet 콘솔 라우트의 실제 응답 계약을 따른다:
401(미인증 거부), /api/fleet/session(자격), /api/fleet/state(로스터 행),
/api/fleet/platoon(활성 지도 고리·속도표·dispatch=False),
/api/fleet/charge-bays(활성 지도 충전 계획).
"""

from __future__ import annotations

import os
import ssl
from urllib.parse import urlparse

import httpx
import pytest
from pathlib import Path

pytestmark = pytest.mark.skipif(
    not (os.environ.get("ROSY_LIVE_FLEET_URL")
         and (os.environ.get("ROSY_LIVE_FLEET_TOKEN") or os.environ.get("ROSY_LIVE_FLEET_TOKEN_FILE"))),
    reason="set ROSY_LIVE_FLEET_URL and a token (ROSY_LIVE_FLEET_TOKEN or _TOKEN_FILE) to judge a deployed site",
)


@pytest.fixture(scope="module")
def site() -> str:
    origin = urlparse(os.environ["ROSY_LIVE_FLEET_URL"])
    return f"{origin.scheme}://{origin.netloc}"


@pytest.fixture(scope="module")
def authed(site):
    token = os.environ.get("ROSY_LIVE_FLEET_TOKEN")
    if not token:
        token = Path(os.environ["ROSY_LIVE_FLEET_TOKEN_FILE"]).read_text(encoding="utf-8").strip()
    headers = {"Authorization": "Bearer " + token}
    with httpx.Client(base_url=site, timeout=15, headers=headers, verify=_verify()) as client:
        yield client


def _verify():
    ca = os.environ.get("ROSY_LIVE_FLEET_CA")
    return ssl.create_default_context(cafile=ca) if ca else True


def test_unauthenticated_readback_is_refused(site):
    with httpx.Client(base_url=site, timeout=15, verify=_verify()) as client:
        response = client.get("/api/fleet/platoon")
    assert response.status_code == 401, (
        f"미인증 읽기가 {response.status_code}로 돌아왔다 — 배포 인증이 성립하지 않는다")


def test_session_names_the_principal(authed):
    response = authed.get("/api/fleet/session")
    assert response.status_code == 200, response.text[:200]
    body = response.json()
    assert body.get("principal_id"), body
    assert body.get("role"), body


def test_state_reports_the_roster(authed):
    response = authed.get("/api/fleet/state")
    assert response.status_code == 200, response.text[:200]
    rows = response.json()["robots"]
    assert rows, "roster가 비었다 — 등록된 로봇이 없다"
    for row in rows:
        assert row.get("robot_id"), row
        assert isinstance(row.get("online"), bool), row


def test_platoon_serves_the_active_loop_readonly(authed):
    response = authed.get("/api/fleet/platoon")
    assert response.status_code == 200, (
        f"platoon 판독 실패 {response.status_code}: {response.text[:200]} — "
        "활성 지도/고리가 없으면 NO_ACTIVE_MAP/NO_LOOP 로 돌아온다")
    body = response.json()
    assert body["dispatch"] is False, "D-941 platoon 뷰는 읽기 전용이어야 한다"
    assert body["loop"]["perimeter_m"] > 0, body["loop"]
    assert isinstance(body["robots"], list)
    assert body["speed"], "속도표가 비었다"


def test_charge_bays_serves_the_active_map_plan(authed):
    response = authed.get("/api/fleet/charge-bays")
    assert response.status_code == 200, (
        f"charge-bays 판독 실패 {response.status_code}: {response.text[:200]}")
    body = response.json()
    assert body.get("map_version"), body
    assert body["dispatch"] is False, "D-941 충전 계획 뷰는 읽기 전용이어야 한다"
    assert isinstance(body["bays"], list)
