"""사이트 principal — site_users 검증, 인증 Dependants, 자격 분리 검사.

D-276 이름 있는 principal 과 D-361 4의 "등록 키는 남과 다른 비밀" 규칙이 여기 산다.
`create_app` 이 이 모듈로 principal 표를 만들고 라우트 모듈들이 Dependants 를 받는다.
"""

from __future__ import annotations

import hmac
import logging
import sqlite3
from dataclasses import dataclass
from hashlib import sha256
from typing import Mapping, Optional

from fastapi import Depends, Header, HTTPException, Request

_LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class SitePrincipal:
    principal_id: str
    role: str


def parse_site_principals(site_users: Mapping[str, Mapping[str, str]],
                          console) -> dict[str, SitePrincipal]:
    principals: dict[str, SitePrincipal] = {}
    if site_users is None:
        return principals
    seen_principal_ids = set()
    for token, details in site_users.items():
        if not isinstance(token, str) or not isinstance(details, Mapping):
            raise ValueError("site user credential entries must be strings and mappings")
        principal_id = details.get("principal_id", "")
        role = details.get("role", "")
        if not isinstance(principal_id, str) or not isinstance(role, str):
            raise ValueError("site principal_id and role must be strings")
        principal_id = principal_id.strip()
        role = role.strip()
        if (len(token) != 64 or any(char not in "0123456789abcdef" for char in token)
                or not principal_id or len(principal_id) > 96
                or any(ord(char) < 32 for char in principal_id)
                or principal_id in seen_principal_ids
                or role not in {"viewer", "operator", "policy-admin", "service"}):
            raise ValueError("site user credentials require a token, principal_id, and known role")
        principals[token] = SitePrincipal(principal_id, role)
        seen_principal_ids.add(principal_id)
    if not principals:
        raise ValueError("site user credentials cannot be empty")
    if console.user_credential_overlaps_robot_secret(tuple(principals)):
        raise ValueError("site user credentials must differ from robot credentials")
    return principals


def assert_registry_credential_isolated(console_token: Optional[str],
                                        principals: Mapping[str, SitePrincipal]) -> None:
    registry_digest = (sha256(console_token.encode("utf-8")).hexdigest()
                       if console_token is not None else None)
    if (registry_digest is not None
            and any(hmac.compare_digest(registry_digest, digest) for digest in principals)):
        raise ValueError("site user credentials must differ from the CORE registry credential")


def assert_robot_credential_key_isolated(robot_credential_key: str, *,
                                         console_token: Optional[str],
                                         discovery_token: Optional[str],
                                         vision_lease_secret: Optional[str],
                                         console, sightings, policy_evidence,
                                         principals: Mapping[str, SitePrincipal]) -> None:
    # D-361 4: the register key is its own secret, never another site credential.
    key = robot_credential_key.strip()
    key_digest = sha256(key.encode("utf-8")).hexdigest()
    same = lambda other: other is not None and hmac.compare_digest(key, other.strip())  # noqa: E731
    if (same(console_token) or same(discovery_token) or same(vision_lease_secret)
            or console.uses_rest_token(key) or console.uses_agent_pairing_token(key)
            or (sightings is not None and sightings.uses_token(key))
            or (policy_evidence is not None and policy_evidence.uses_token(key))
            or any(hmac.compare_digest(key_digest, digest) for digest in principals)):
        raise ValueError("robot credential key must differ from every other site secret")


def assert_pairing_sync_token_isolated(sync_token: str, *, console_token: Optional[str],
                                       discovery_token: Optional[str],
                                       vision_lease_secret: Optional[str],
                                       robot_credential_key: Optional[str],
                                       console, sightings, policy_evidence,
                                       principals: Mapping[str, SitePrincipal]) -> None:
    # D-341 11, 12 and D-302: Vision's credential-list secret is its own, never another.
    token = sync_token.strip()
    if not token:
        raise ValueError("pairing sync credential must not be empty")
    token_digest = sha256(token.encode("utf-8")).hexdigest()
    same = lambda other: other is not None and hmac.compare_digest(token, other.strip())  # noqa: E731
    if (same(console_token) or same(discovery_token) or same(vision_lease_secret)
            or same(robot_credential_key)
            or console.uses_rest_token(token) or console.uses_agent_pairing_token(token)
            or (sightings is not None and sightings.uses_token(token))
            or (policy_evidence is not None and policy_evidence.uses_token(token))
            or any(hmac.compare_digest(token_digest, digest) for digest in principals)):
        raise ValueError("pairing sync credential must differ from every other site secret")


def build_authorize(console_token: Optional[str],
                    principals: Mapping[str, SitePrincipal],
                    task_service):
    def authorize(request: Request,
                  authorization: Optional[str] = Header(default=None)) -> SitePrincipal:
        if principals:
            if not authorization or not authorization.startswith("Bearer "):
                raise HTTPException(status_code=401, detail={"code": "UNAUTHORIZED",
                                                             "message": "valid site credential required"})
            supplied = authorization[len("Bearer "):]
            supplied_digest = sha256(supplied.encode("utf-8")).hexdigest()
            matched = None
            for token_digest, principal in principals.items():
                if hmac.compare_digest(supplied_digest, token_digest):
                    matched = principal
            if matched is None:
                raise HTTPException(status_code=401, detail={"code": "UNAUTHORIZED",
                                                             "message": "valid site credential required"})
            principal = matched
        elif console_token is None:
            principal = SitePrincipal("site-console", "operator")
        else:
            if authorization != f"Bearer {console_token}":
                raise HTTPException(status_code=401, detail={"code": "UNAUTHORIZED",
                                                             "message": "console token required"})
            principal = SitePrincipal("site-console", "operator")
        request.state.site_principal = principal
        if (task_service is not None and request.method == "POST"
                and request.url.path.startswith("/api/fleet/")
                and request.url.path != "/api/fleet/sightings"
                and request.url.path != "/api/fleet/policy-evidence"):
            try:
                request.state.site_api_audit_id = task_service.store.begin_api_audit(
                    principal_id=principal.principal_id, role=principal.role,
                    method=request.method, path=request.url.path,
                )
            except (OSError, sqlite3.Error, ValueError):
                if request.url.path == "/api/fleet/estop":
                    _LOG.exception(
                        "emergency stop audit unavailable; continuing stop request principal=%s",
                        principal.principal_id,
                    )
                    return principal
                raise HTTPException(status_code=503, detail={
                    "code": "AUDIT_STORAGE_UNAVAILABLE",
                    "message": "site command audit is unavailable",
                }) from None
        return principal

    return authorize


def build_role_guards(authorize, principals: Mapping[str, SitePrincipal]):
    def require_viewer(principal: SitePrincipal = Depends(authorize)) -> SitePrincipal:
        return principal

    def require_operator(principal: SitePrincipal = Depends(authorize)) -> SitePrincipal:
        if principal.role != "operator":
            raise HTTPException(status_code=403, detail={"code": "FORBIDDEN",
                                                         "message": "operator role required"})
        return principal

    def require_proposer(principal: SitePrincipal = Depends(authorize)) -> SitePrincipal:
        if principal.role not in {"operator", "service"}:
            raise HTTPException(status_code=403, detail={
                "code": "FORBIDDEN", "message": "operator or service proposal role required",
            })
        return principal

    def require_named_operator(principal: SitePrincipal = Depends(require_operator)) -> SitePrincipal:
        if not principals:
            raise HTTPException(status_code=403, detail={
                "code": "OPERATOR_IDENTITY_REQUIRED",
                "message": "mission admission requires a configured named operator credential",
            })
        return principal

    return require_viewer, require_operator, require_named_operator, require_proposer


def install_mutation_audit(app, task_service):
    """Finish the audit started by authorization after the HTTP outcome is known."""
    @app.middleware("http")
    async def finish_mutation_audit(request: Request, call_next):
        try:
            response = await call_next(request)
        except Exception:
            audit_id = getattr(request.state, "site_api_audit_id", None)
            if audit_id is not None:
                task_service.store.finish_api_audit(audit_id, status_code=500)
            raise
        audit_id = getattr(request.state, "site_api_audit_id", None)
        if audit_id is not None:
            task_service.store.finish_api_audit(audit_id, status_code=response.status_code)
        return response
