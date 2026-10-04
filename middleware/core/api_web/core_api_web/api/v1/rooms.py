"""D-343 1단계 잔여 — CORE `GET /api/v1/site/rooms` (Avahi `_rosy._tcp` 탐색).

브라우저는 mDNS 를 못 하므로 각 CORE 가 대신 찾아 준다: 이 기기가 본 이웃 로봇
광고(공개 TXT 만, 발견 규칙 v0.1 + `discovery_txt.classify`)를 방 목록으로 돌려준다.
인증 없이 읽는다 — 행은 공개 정보만 싣는다(토큰·비밀 없음, D-193).
"""

from __future__ import annotations

import subprocess

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from core_common.protocol import discovery_txt

rooms_router = APIRouter(prefix="/api/v1/site", tags=["site"])

#: 브라우저가 방 목록에서 같은 기기를 묶는 데 쓰는 공개 식별만 싣는다.
_ROBOT_SERVICE = discovery_txt.ROBOT


def scan_robots(*, browse=None, timeout_s: float = 4.0) -> list[dict]:
    """이웃 로봇 광고를 Avahi 로 탐색해 방 행으로 반환한다 (D-343 2.2-1).

    ``browse`` 주입은 시험·Windows 호스트용: Avahi 호출을 대체한다.
    """
    if browse is None:
        browse = _avahi_browse_robot
    return sorted(
        (row for row in browse(timeout_s=timeout_s)),
        key=lambda row: row["hostname"],
    )


def _avahi_browse_robot(*, timeout_s: float) -> list[dict]:
    try:
        completed = subprocess.run(
            ["avahi-browse", "-r", "-t", "-p", "-k", _ROBOT_SERVICE],
            capture_output=True, text=True, timeout=timeout_s, check=False)
    except (FileNotFoundError, subprocess.SubprocessError) as exc:
        raise _Unavailable(f"avahi-browse is unavailable: {exc}") from exc
    if completed.returncode not in (0,):
        raise _Unavailable(f"avahi-browse exited {completed.returncode}")
    rows = []
    for line in completed.stdout.splitlines():
        columns = line.split(";", 9)
        if len(columns) != 10 or columns[0] != "=":
            continue
        verdict = discovery_txt.classify(
            _ROBOT_SERVICE, columns[6], columns[7],
            _port(columns[8]), discovery_txt.parse_txt_pairs(columns[9]))
        if verdict.__class__.__name__ != "Accepted":
            continue
        rows.append({
            "hostname": verdict.host,
            "address": columns[7],
            "port": int(columns[8]),
            "kind": "robot",
            "url": f"http://{verdict.host}.local:{columns[8]}/pilot/#join",
        })
    return rows


class _Unavailable(Exception):
    """Avahi 가 없어 탐색을 못 한 경우 — 503 (D-432 손실 안내 계약과 같은 문화)."""


def _port(text: str):
    try:
        return int(text)
    except ValueError:
        return text


@rooms_router.get("/rooms")
def site_rooms():
    try:
        rows = scan_robots(timeout_s=4.0)
    except _Unavailable as exc:
        return JSONResponse(status_code=503, content={"code": "DISCOVERY_UNAVAILABLE",
                                                      "message": str(exc)})
    return JSONResponse(headers={"Cache-Control": "no-store"}, content={"rooms": rows})
