"""core_api_web.api.deps — SEC-101 인증·권한 (정적 토큰 3롤) + 서비스 접근.

토큰은 sha256 다이제스트로만 보관한다. 원문은 인증 요청을 처리하는 동안에만
메모리에 있고 오버레이·응답·이벤트·감사 로그 어디에도 남지 않는다. 토큰을
가리키는 이름은 원문에서 유도하지 않은 불투명 `id` 이며, 그래야 저장된 파일이
새어도 약한 토큰을 확인해 볼 오라클이 되지 않는다.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import Depends, Header, Request

from core_api_web.api.errors import ApiError
from core_common.config import ConfigError, patch_local_config
from typing import Protocol

# --- 라우터용 도메인 타입 (결합도 평가 2026-09-19 §7-5) ----------------------
# v1 라우터는 core_features 를 직접 import 하지 않고 이 면만 본다.
# features 를 재조정할 때 전파 반경이 이 파일에서 멈춘다. 이 규칙은
# core/core/test/test_v1_import_boundary.py 가 고정한다.
from core_features.command.arbitration import Mode
from core_features.diagnostics.collector import worst
from core_features.docking.database import DockError, DockInstance, DockType
from core_features.line_follow import LineFollowMode
from core_features.maps import valid_costmap_scope
from core_features.navigation.manager import NavigationError
from core_features.swarm import SwarmError
from core_features.waypoints.manager import Waypoint
from core_features.vision import VisionFrameAdvanced, VisionPullRateLimited
from core_common.protocol.schemas import VisionPreviewStatus

#: 라우터용 재수출 면. __all__ 선언으로 재수출임을 명시한다(F401 진정).
__all__ = [
    "Mode",
    "NavigationError",
    "DockError",
    "DockInstance",
    "DockType",
    "LineFollowMode",
    "valid_costmap_scope",
    "worst",
    "SwarmError",
    "Waypoint",
    "VisionPreviewStatus",
    "VisionFrameAdvanced",
    "VisionPullRateLimited",
]


class CoreServicesLike(Protocol):
    """Structural port for the DI container (D-126 S5).

    Routers annotate ``svc`` with this instead of importing ``core.services``,
    so the web slice no longer depends on the entry-point package.  Members
    are ``Any`` on purpose: the Protocol pins *which* services a router may
    touch, not their types — behavior is unchanged.
    """

    audit: Any
    battery: Any
    capability: Any
    command: Any
    config: Any
    control_adapter: Any
    docking: Any
    events: Any
    identity: Any
    inventory: Any
    maps: Any
    line_follow: Any
    modes: Any
    nav: Any
    power: Any
    readiness: Any
    runtime_probe: Any
    safety: Any
    started_at: Any
    state: Any
    swarm: Any
    traffic_policy: Any
    vision: Any
    waypoints: Any


ROLE_RANK = {"viewer": 0, "operator": 1, "administrator": 2}

#: 운영자가 직접 고른 토큰의 하한. 생성 토큰은 이보다 훨씬 길다.
MIN_TOKEN_LENGTH = 16
MAX_TOKEN_LENGTH = 128

#: D-193 5. 토큰이 어디서 왔는가. `card` 는 SD 카드 첫 부팅, `manual` 은
#: 설정 화면·API, `pair-*` 는 로그인 코드, `legacy` 는 평문 레거시 항목이다.
TOKEN_SOURCES = frozenset({"card", "manual", "pair-physical", "pair-admin", "legacy"})
PAIRED_SOURCES = frozenset({"pair-physical", "pair-admin"})

#: D-193 7. 장치 모드(`ROSY_DEPLOYMENT=device`)가 거부하는 공용 개발 토큰의
#: 다이제스트. 원문은 `config/rosy_dev_auth.yaml` 에만 있다.
DEV_TOKEN_DIGESTS = frozenset(
    hashlib.sha256(("rosy-dev-" + role).encode("utf-8")).hexdigest()
    for role in ("admin", "operator", "viewer")
)

#: 토큰 id → 마지막 인증 시각. 요청마다 파일을 쓰지 않으려고 메모리에만 둔다.
_LAST_USED: dict[str, str] = {}


def device_mode() -> bool:
    """네이티브 장치 런타임인가 (`rosy-runtime.env` 의 `ROSY_DEPLOYMENT=device`)."""
    return os.environ.get("ROSY_DEPLOYMENT", "").strip() == "device"


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_token() -> str:
    """URL 안전한 32바이트 토큰. 응답에 단 한 번 실린다."""
    return secrets.token_urlsafe(32)


def new_token_id() -> str:
    return secrets.token_hex(6)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def utc_after(seconds: float) -> str:
    """지금부터 `seconds` 뒤의 UTC ISO 시각 (초 단위)."""
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat(timespec="seconds")


def is_expired(record: dict[str, Any], now: Optional[datetime] = None) -> bool:
    """만료 시각이 지났는가. 읽을 수 없는 만료 시각은 만료로 본다 (닫힌 실패)."""
    expires_at = record.get("expires_at")
    if expires_at is None:
        return False
    try:
        moment = datetime.fromisoformat(str(expires_at))
    except ValueError:
        return True
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment <= (now or datetime.now(timezone.utc))


def is_durable_admin(record: dict[str, Any]) -> bool:
    """만료 없는 administrator. 마지막 관리자 규칙(D-193 5)은 이것만 센다."""
    return record.get("role") == "administrator" and record.get("expires_at") is None


def _record(*, id: str, role: str, digest: str, label: str = "",
            created_at: Optional[str] = None, legacy: bool = False,
            expires_at: Optional[str] = None, source: str = "manual",
            paired_via: Optional[str] = None) -> dict[str, Any]:
    return {
        "id": id,
        "role": role if role in ROLE_RANK else "viewer",
        "digest": digest,
        "label": label,
        "created_at": created_at,
        "legacy": legacy,
        "expires_at": str(expires_at) if expires_at is not None else None,
        "source": source if source in TOKEN_SOURCES else "manual",
        "paired_via": str(paired_via) if paired_via is not None else None,
    }


def _from_legacy_plaintext(token: str, role: str) -> dict[str, Any]:
    """패키지 기본값처럼 평문으로 남아 있는 항목. 다음 쓰기에서 해시로 옮겨간다."""
    digest = token_digest(token)
    return _record(id=digest[:12], role=role, digest=digest, label="", legacy=True,
                   source="legacy")


def _configured_records(config: dict) -> list[dict[str, Any]]:
    entries = (config.get("auth") or {}).get("tokens") or []
    if isinstance(entries, dict):
        return [_from_legacy_plaintext(str(k), str(v)) for k, v in entries.items() if k]

    records: list[dict[str, Any]] = []
    for item in entries:
        if not isinstance(item, dict):
            continue
        digest = str(item.get("sha256") or "").strip().lower()
        if digest:
            records.append(_record(
                id=str(item.get("id") or digest[:12]),
                role=str(item.get("role", "viewer")),
                digest=digest,
                label=str(item.get("label") or ""),
                created_at=item.get("created_at"),
                expires_at=item.get("expires_at"),
                source=str(item.get("source") or "manual"),
                paired_via=item.get("paired_via"),
            ))
        elif item.get("token"):
            records.append(_from_legacy_plaintext(
                str(item["token"]), str(item.get("role", "viewer"))))
    return records


def _refused_in_device_mode(record: dict[str, Any]) -> bool:
    return record["legacy"] or record["digest"] in DEV_TOKEN_DIGESTS


def auth_entries(config: dict) -> list[dict[str, Any]]:
    """설정에 담긴 토큰을 내부 레코드로 정규화한다. 원문은 반환하지 않는다.

    장치 모드에서는 평문 레거시 항목과 공용 개발 토큰을 버린다(D-193 7).
    가드 환경 변수 하나가 빠져도 다시 열리지 않도록, 걸러낸 목록이 인증과
    저장 양쪽의 유일한 입력이다.
    """
    records = _configured_records(config)
    if device_mode():
        records = [item for item in records if not _refused_in_device_mode(item)]
    return records


def refused_token_count(config: dict) -> int:
    """장치 모드가 거부한 항목 수. 장치 모드가 아니면 0."""
    if not device_mode():
        return 0
    return sum(1 for item in _configured_records(config) if _refused_in_device_mode(item))


def stored_token_entries(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """오버레이에 쓸 형태. 평문으로 읽힌 항목도 여기서 해시 형태로 옮겨간다."""
    stored = []
    for item in records:
        entry = {
            "id": item["id"],
            "role": item["role"],
            "sha256": item["digest"],
            "label": item["label"],
            "created_at": item["created_at"] or _utc_now(),
            "source": item["source"],
        }
        if item.get("expires_at") is not None:
            entry["expires_at"] = item["expires_at"]
        if item.get("paired_via") is not None:
            entry["paired_via"] = item["paired_via"]
        stored.append(entry)
    return stored


def public_token_records(config: dict, current_id: Optional[str] = None) -> list[dict[str, Any]]:
    """대시보드가 보는 형태. 토큰에서 유도된 값은 하나도 싣지 않는다. 만료된 것은 빠진다."""
    return [
        {
            "id": item["id"],
            "role": item["role"],
            "label": item["label"],
            "created_at": item["created_at"],
            "legacy": item["legacy"],
            "expires_at": item["expires_at"],
            "source": item["source"],
            "current": item["id"] == current_id,
            "last_used_at": _LAST_USED.get(item["id"]),
        }
        for item in auth_entries(config)
        if not is_expired(item)
    ]


def new_token_record(token: str, role: str, label: str = "", *, source: str = "manual",
                     expires_at: Optional[str] = None,
                     paired_via: Optional[str] = None) -> dict[str, Any]:
    return _record(id=new_token_id(), role=role, digest=token_digest(token),
                   label=label, created_at=_utc_now(), source=source,
                   expires_at=expires_at, paired_via=paired_via)


def persist_token_records(svc: "CoreServicesLike", records: list[dict[str, Any]]) -> None:
    """토큰 목록을 오버레이와 메모리 설정에 쓴다. 만료된 레코드는 여기서 지운다."""
    stored = stored_token_entries([item for item in records if not is_expired(item)])
    try:
        patch_local_config({"auth": {"tokens": stored}})
    except (ConfigError, OSError) as exc:
        raise ApiError("INTERNAL_ERROR", 500, f"failed to persist tokens: {exc}")
    svc.config.setdefault("auth", {})["tokens"] = stored


class AuthContext:
    """인증된 호출자. 토큰 원문은 일부러 들고 있지 않는다."""

    def __init__(self, token_id: str, role: str, *, source: str = "manual",
                 expires_at: Optional[str] = None, label: str = "",
                 created_at: Optional[str] = None) -> None:
        self.token_id = token_id
        self.role = role
        self.source = source
        self.expires_at = expires_at
        self.label = label
        self.created_at = created_at

    @property
    def rank(self) -> int:
        return ROLE_RANK.get(self.role, -1)


def get_services(request: Request) -> CoreServicesLike:
    return request.app.state.core


def authenticate(config: dict, bearer: Optional[str], query_token: Optional[str]) -> AuthContext:
    token = bearer.removeprefix("Bearer ").strip() if bearer else (query_token or "").strip()
    if not token:
        raise ApiError("UNAUTHORIZED", 401, "missing or invalid token")
    presented = token_digest(token)
    for item in auth_entries(config):
        if hmac.compare_digest(presented, item["digest"]):
            if is_expired(item):
                break
            _LAST_USED[item["id"]] = _utc_now()
            return AuthContext(token_id=item["id"], role=item["role"], source=item["source"],
                               expires_at=item["expires_at"], label=item["label"],
                               created_at=item["created_at"])
    raise ApiError("UNAUTHORIZED", 401, "missing or invalid token")


def auth_dependency(request: Request,
                    authorization: Optional[str] = Header(default=None)) -> AuthContext:
    return authenticate(request.app.state.core.config, authorization, None)


def require_role(min_role: str):
    def _dep(auth: AuthContext = Depends(auth_dependency)) -> AuthContext:
        if auth.rank < ROLE_RANK[min_role]:
            raise ApiError("FORBIDDEN", 403, f"requires {min_role} role")
        return auth
    return _dep
