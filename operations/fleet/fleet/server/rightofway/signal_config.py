"""Signal endpoint configuration and YAML persistence."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import yaml

#: 장치 램프 이름 → 관측 색상군 기대치. 노란 램프는 관측에서 orange 군으로, 청록
#: 계열 녹색은 green/blue 경계로 온다 — 3자 교차 검증(관측 설계 §3)의 대조표다.
EXPECTED_GROUPS: dict[str, tuple[str, ...]] = {
    "red": ("red",),
    "yellow": ("orange",),
    "green": ("green", "blue"),
}


class SignalsFileError(ValueError):
    """signals.yaml 을 읽을 수 없다."""


@dataclass(frozen=True)
class SignalEndpoint:
    signal_id: str
    base_url: str   # 끝 슬래시 없음
    token: str
    #: 관측 서비스의 `/observed` — 없으면 3자 교차 검증은 꺼진다(verify=absent).
    observer_url: Optional[str] = None
    #: 장치 램프 이름 → 관측 ROI 이름. B0 사이클 지도(운영자)가 채운다.
    observer_map: Optional[dict] = None


_REQUIRED = ("signal_id", "base_url", "token")


def _endpoint(signal_id, base_url, token, where: str, *,
              observer_url: Optional[str] = None,
              observer_map: Optional[dict] = None) -> SignalEndpoint:
    """`swarm.robots._endpoint` 와 같은 규칙 — 두 로더가 갈라지면 배포가 갈라진다.

    토큰은 따옴표 문자열이어야 한다(YAML 1.1 이 `01234567` 을 8진으로, `yes` 를
    불로 읽는 문제는 robots.yaml 쪽에서 이미 겪은 것이다). 스킴이 없으면 URL 이
    조용히 깨진다 — 연결 시점이 아니라 여기서 거절한다.
    """
    if not signal_id or not base_url or not token:
        raise SignalsFileError(f"{where}: signal_id, base_url and token are all required")
    for key, value in (("base_url", base_url), ("token", token)):
        if not isinstance(value, str):
            raise SignalsFileError(f"{where}: '{key}' must be a quoted string, not {type(value).__name__}")
    base_url = base_url.rstrip("/")
    if not base_url.lower().startswith(("http://", "https://")):
        raise SignalsFileError(f"{where}: base_url needs an http:// or https:// scheme")
    if observer_url is not None:
        if not isinstance(observer_url, str) or not observer_url.lower().startswith(
                ("http://", "https://")):
            raise SignalsFileError(f"{where}: observer_url needs an http(s) scheme")
        observer_url = observer_url.rstrip("/")
    if observer_map is not None:
        if not isinstance(observer_map, dict) or not observer_map:
            raise SignalsFileError(f"{where}: observer_map must be a non-empty mapping")
        bad_keys = [k for k in observer_map if k not in EXPECTED_GROUPS]
        bad_vals = [v for v in observer_map.values()
                    if not isinstance(v, str) or not v]
        if bad_keys or bad_vals:
            raise SignalsFileError(
                f"{where}: observer_map maps device lamps red/yellow/green to ROI names")
        observer_map = dict(observer_map)
    return SignalEndpoint(str(signal_id), base_url, token, observer_url, observer_map)


def load_signals(path: Path) -> list[SignalEndpoint]:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise SignalsFileError(f"{path}: cannot read signals file: {exc}") from exc
    try:
        data = yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        raise SignalsFileError(f"{path}: not valid YAML: {exc}") from exc
    rows = data.get("signals") if isinstance(data, dict) else None
    if not isinstance(rows, list) or not rows:
        raise SignalsFileError(f"{path}: needs a non-empty 'signals' list")
    seen: set[str] = set()
    out: list[SignalEndpoint] = []
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            raise SignalsFileError(f"{path}: signals[{i}] is not a mapping")
        for key in _REQUIRED:
            if not row.get(key):
                raise SignalsFileError(f"{path}: signals[{i}] is missing '{key}'")
        endpoint = _endpoint(row["signal_id"], row["base_url"], row["token"],
                             f"{path}: signals[{i}]",
                             observer_url=row.get("observer_url"),
                             observer_map=row.get("observer_map"))
        if endpoint.signal_id in seen:
            raise SignalsFileError(f"{path}: duplicate signal_id {endpoint.signal_id!r}")
        seen.add(endpoint.signal_id)
        out.append(endpoint)
    return out


def write_signals(path: Path, signals: list[SignalEndpoint]) -> None:
    """로더가 받아들이는 signals.yaml 을 쓴다. 쓰기 전에 로더 규칙을 통과시킨다."""
    if not signals:
        raise SignalsFileError("every signal needs signal_id, base_url and token")
    normalized = [_endpoint(s.signal_id, s.base_url, s.token, f"signals[{i}]",
                            observer_url=s.observer_url, observer_map=s.observer_map)
                  for i, s in enumerate(signals)]
    ids = [s.signal_id for s in normalized]
    if len(set(ids)) != len(ids):
        raise SignalsFileError(f"duplicate signal_id in {ids}")
    rows: list[dict[str, Any]] = []
    for s in normalized:
        row: dict[str, Any] = {"signal_id": s.signal_id, "base_url": s.base_url,
                               "token": s.token}
        if s.observer_url is not None:
            row["observer_url"] = s.observer_url
        if s.observer_map is not None:
            row["observer_map"] = dict(s.observer_map)
        rows.append(row)
    target = Path(path)
    text = yaml.safe_dump({"signals": rows}, sort_keys=False)
    # robots.yaml 과 같은 등급의 비밀 파일이다 — 소유자만 읽게 연다(POSIX).
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    try:
        os.chmod(target, 0o600)
    except OSError:
        pass  # Windows 는 chmod 를 무시한다 — robots.py 와 같은 태도다
