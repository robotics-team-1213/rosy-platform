"""fleet.swarm.robots — 오케스트레이터가 아는 로봇 목록 (robots.yaml).

토큰은 로봇마다 다르다(D-30: 장치 로컬 토큰). 참조 소켓과 swarm/follow 는 operator
이상이어야 한다(D-31) — 파일에 든 토큰은 그 역할이어야 하며 여기서는 형식만 본다.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlencode

import yaml


class RobotsFileError(ValueError):
    """robots.yaml 을 읽을 수 없다."""


@dataclass(frozen=True)
class RobotEndpoint:
    robot_id: str
    base_url: str   # 끝 슬래시 없음
    token: str   # CORE REST operator token
    fleet_pairing_token: str | None = None  # CORE FleetAgent → SiteHub only


_REQUIRED = ("robot_id", "base_url", "token")


def _endpoint(robot_id, base_url, token, where: str,
              fleet_pairing_token=None) -> RobotEndpoint:
    """load_robots 와 write_robots 가 같은 규칙을 통과시킨다."""
    if not robot_id or not base_url or not token:
        raise RobotsFileError(f"{where}: robot_id, base_url and token are all required")
    # 토큰은 바이트 그대로 살아야 하는 비밀이다. YAML 1.1 은 `01234567`(8진), `yes`,
    # `1:23:45` 같은 따옴표 없는 값을 다른 타입으로 읽으므로, str() 로 억지로 바꾸면
    # 다른 문자열이 되어 4401 로 조용히 실패한다. base_url 도 같은 이유로 문자열만 받는다.
    for key, value in (("base_url", base_url), ("token", token)):
        if not isinstance(value, str):
            raise RobotsFileError(f"{where}: '{key}' must be a quoted string, not {type(value).__name__}")
    if fleet_pairing_token is not None:
        if not isinstance(fleet_pairing_token, str) or not fleet_pairing_token:
            raise RobotsFileError(f"{where}: 'fleet_pairing_token' must be a non-empty quoted string")
        if fleet_pairing_token == token:
            raise RobotsFileError(f"{where}: fleet_pairing_token must differ from the REST token")
    base_url = base_url.rstrip("/")
    if not base_url.lower().startswith(("http://", "https://")):
        # 스킴이 없으면 ws_url 이 호스트를 잃고 `ws:///...` 를 만든다 — 연결 시점이 아니라
        # 여기서 거절한다.
        raise RobotsFileError(f"{where}: base_url needs an http:// or https:// scheme")
    return RobotEndpoint(str(robot_id), base_url, token, fleet_pairing_token)


def load_robots(path: Path) -> list[RobotEndpoint]:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        # UnicodeDecodeError 는 ValueError 계열이라 OSError 만 잡으면 새어 나간다.
        raise RobotsFileError(f"{path}: cannot read robots file: {exc}") from exc
    try:
        data = yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        raise RobotsFileError(f"{path}: not valid YAML: {exc}") from exc
    rows = data.get("robots") if isinstance(data, dict) else None
    if not isinstance(rows, list) or not rows:
        raise RobotsFileError(f"{path}: needs a non-empty 'robots' list")
    seen: set[str] = set()
    out: list[RobotEndpoint] = []
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            raise RobotsFileError(f"{path}: robots[{i}] is not a mapping")
        for key in _REQUIRED:
            if not row.get(key):
                raise RobotsFileError(f"{path}: robots[{i}] is missing '{key}'")
        endpoint = _endpoint(row["robot_id"], row["base_url"], row["token"],
                             f"{path}: robots[{i}]", row.get("fleet_pairing_token"))
        if endpoint.robot_id in seen:
            raise RobotsFileError(f"{path}: duplicate robot_id {endpoint.robot_id!r}")
        seen.add(endpoint.robot_id)
        out.append(endpoint)
    return out


def write_robots(path: Path, robots: list[RobotEndpoint]) -> None:
    """로더가 받아들이는 robots.yaml 을 쓰는 기준 구현. 로더의 규칙을 먼저 통과시킨다.

    `gz_multi core:=true` 는 이것을 부르지 않고 같은 모양을 직접 쓴다. 부를 수는 있다 —
    `gz_sim` 은 `fleet` 을 `exec_depend` 로 걸고 있다. 그래도 부르지 않는 것은
    일부러다: launch 파일이 import 하는 순간 `fleet` 이 빌드돼 있지 않은 워크스페이스
    에서는 시뮬 자체가 뜨지 않는다. 그쪽 모양은 `gz_sim` 의 테스트가 못박아 둔다.
    """
    if not robots:
        raise RobotsFileError("every robot needs robot_id, base_url and token")
    normalized = [_endpoint(r.robot_id, r.base_url, r.token, f"robots[{i}]",
                            r.fleet_pairing_token) for i, r in enumerate(robots)]
    ids = [r.robot_id for r in normalized]
    if len(set(ids)) != len(ids):
        raise RobotsFileError(f"duplicate robot_id in {ids}")
    rows = []
    for r in normalized:
        row = {"robot_id": r.robot_id, "base_url": r.base_url, "token": r.token}
        if r.fleet_pairing_token is not None:
            row["fleet_pairing_token"] = r.fleet_pairing_token
        rows.append(row)
    target = Path(path)
    text = yaml.safe_dump({"robots": rows}, sort_keys=False)
    # operator 토큰 N 개가 평문으로 든 파일이다. POSIX 에서는 처음부터 소유자만 읽게 연다;
    # Windows 는 mode 를 무시하므로 open 자체는 그대로 성공해야 한다.
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    # O_CREAT 의 mode 는 파일이 이미 있으면 무시된다 — 예전에 0644 였던 파일은 그대로
    # 세상에 읽힌다. 매번 다시 조인다. Windows 는 chmod 를 무시하므로 실패해도 조용히 넘어간다.
    try:
        os.chmod(target, 0o600)
    except OSError:
        pass


def ws_url(base_url: str, path: str, token: str, **query: str) -> str:
    """REST base_url → 같은 호스트의 WS URL. 토큰은 쿼리로 간다 (API Ref §6)."""
    scheme, _, host = base_url.partition("://")
    scheme = scheme.lower()
    if scheme not in ("http", "https") or not host:
        # 알 수 없는 스킴을 ws 로 떨어뜨리면 https 오타 하나가 토큰을 평문으로 보낸다.
        raise ValueError(f"base_url must be http(s)://host[:port], got {base_url!r}")
    ws_scheme = "wss" if scheme == "https" else "ws"
    params = {"token": token, **query}
    return f"{ws_scheme}://{host}{path}?{urlencode(params)}"
