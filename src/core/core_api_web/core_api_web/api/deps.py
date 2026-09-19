"""core_api_web.api.deps — SEC-101 인증·권한 (정적 토큰 3롤) + 서비스 접근.

토큰은 sha256 다이제스트로만 보관한다. 원문은 인증 요청을 처리하는 동안에만
메모리에 있고 오버레이·응답·이벤트·감사 로그 어디에도 남지 않는다. 토큰을
가리키는 이름은 원문에서 유도하지 않은 불투명 `id` 이며, 그래야 저장된 파일이
새어도 약한 토큰을 확인해 볼 오라클이 되지 않는다.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import Depends, Header, Request

from core_api_web.api.errors import ApiError
from typing import Protocol


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
    modes: Any
    nav: Any
    power: Any
    readiness: Any
    runtime_probe: Any
    safety: Any
    started_at: Any
    state: Any
    swarm: Any
    waypoints: Any

ROLE_RANK = {"viewer": 0, "operator": 1, "administrator": 2}

#: 운영자가 직접 고른 토큰의 하한. 생성 토큰은 이보다 훨씬 길다.
MIN_TOKEN_LENGTH = 16
MAX_TOKEN_LENGTH = 128


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_token() -> str:
    """URL 안전한 32바이트 토큰. 응답에 단 한 번 실린다."""
    return secrets.token_urlsafe(32)


def new_token_id() -> str:
    return secrets.token_hex(6)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _record(*, id: str, role: str, digest: str, label: str = "",
            created_at: Optional[str] = None, legacy: bool = False) -> dict[str, Any]:
    return {
        "id": id,
        "role": role if role in ROLE_RANK else "viewer",
        "digest": digest,
        "label": label,
        "created_at": created_at,
        "legacy": legacy,
    }


def _from_legacy_plaintext(token: str, role: str) -> dict[str, Any]:
    """패키지 기본값처럼 평문으로 남아 있는 항목. 다음 쓰기에서 해시로 옮겨간다."""
    digest = token_digest(token)
    return _record(id=digest[:12], role=role, digest=digest, label="", legacy=True)


def auth_entries(config: dict) -> list[dict[str, Any]]:
    """설정에 담긴 토큰을 내부 레코드로 정규화한다. 원문은 반환하지 않는다."""
    entries = (config.get("auth") or {}).get("tokens", [])
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
            ))
        elif item.get("token"):
            records.append(_from_legacy_plaintext(
                str(item["token"]), str(item.get("role", "viewer"))))
    return records


def stored_token_entries(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """오버레이에 쓸 형태. 평문으로 읽힌 항목도 여기서 해시 형태로 옮겨간다."""
    return [
        {
            "id": item["id"],
            "role": item["role"],
            "sha256": item["digest"],
            "label": item["label"],
            "created_at": item["created_at"] or _utc_now(),
        }
        for item in records
    ]


def public_token_records(config: dict) -> list[dict[str, Any]]:
    """대시보드가 보는 형태. 토큰에서 유도된 값은 하나도 싣지 않는다."""
    return [
        {
            "id": item["id"],
            "role": item["role"],
            "label": item["label"],
            "created_at": item["created_at"],
            "legacy": item["legacy"],
        }
        for item in auth_entries(config)
    ]


def new_token_record(token: str, role: str, label: str = "") -> dict[str, Any]:
    return _record(id=new_token_id(), role=role, digest=token_digest(token),
                   label=label, created_at=_utc_now())


class AuthContext:
    """인증된 호출자. 토큰 원문은 일부러 들고 있지 않는다."""

    def __init__(self, token_id: str, role: str) -> None:
        self.token_id = token_id
        self.role = role

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
            return AuthContext(token_id=item["id"], role=item["role"])
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
