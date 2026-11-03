"""라이브 Fleet 기능 판정 — 배포된 사이트의 읽기 표면을 그대로 잰다 (D-527 현장 수용).

옵트인: ROSY_LIVE_FLEET_URL(사이트 주소)과 ROSY_LIVE_FLEET_TOKEN(읽기 자격)을
환경으로 주면 실물 Fleet API에 읽기 요청만 보내 각 기능이 살아 있는지 판정한다.
쓰기·로봇 명령은 없다. 둘 중 하나라도 없으면 건너뛴다(CI에는 영향 없음).
test_live_surface_gates.py 와 같은 ROSY_LIVE_FLEET_URL 을 쓴다.

실행(원격 시험 PC에서, 현장 사이트가 보이는 망):
    python tools/remote/remote_pytest.py --log-dir "$ROSY_SCRATCH/field" -- \
        ROSY_LIVE_FLEET_URL=https://<site-host> ROSY_LIVE_FLEET_TOKEN=<viewer-token> \
        test/test_live_fleet_function.py -v

판정 기준은 operations/fleet 콘솔 라우트의 실제 응답 계약을 따른다:
401(미인증 거부), /api/fleet/session(자격), /api/fleet/state(로스터 행),
/api/fleet/platoon(활성 지도 고리·속도표·dispatch=False),
/api/fleet/charge-bays(활성 지도 충전 계획).
"""

from __future__ import annotations

import os
from urllib.parse import urlparse

import httpx
import pytest

pytestmark = pytest.mark.skipif(
    not (os.environ.get("ROSY_LIVE_FLEET_URL") and os.environ.get("ROSY_LIVE_FLEET_TOKEN")),
    reason="set ROSY_LIVE_FLEET_URL and ROSY_LIVE_FLEET_TOKEN to judge a deployed site",
)


@pytest.fixture(scope="module")
def site() -> str:
    origin = urlparse(os.environ["ROSY_LIVE_FLEET_URL"])
    return f"{origin.scheme}://{origin.netloc}"


@pytest.fixture(scope="module")
def authed(site):
    headers = {"Authorization": "Bearer " + os.environ["ROSY_LIVE_FLEET_TOKEN"]}
    with httpx.Client(base_url=site, timeout=15, headers=headers) as client:
        yield client


def test_unauthenticated_readback_is_refused(site):
    with httpx.Client(base_url=site, timeout=15) as client:
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
