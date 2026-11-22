"""Scoped offline bearer-token auth for Learning Center (:8768) agent/automation clients."""
from __future__ import annotations

import hashlib
import hmac
import json
import re
from pathlib import Path
from typing import Any

SERVICE_SCOPE = "service_offline_job"
_ALLOWED_SCOPES = frozenset({SERVICE_SCOPE})
_UUID_OR_ID = r"[A-Za-z0-9_][A-Za-z0-9._-]{0,63}"

_DENIED_PREFIXES = (
    "/api/frames/",
    "/api/masks/",
    "/api/mask-preview/",
    "/api/prepare",
    "/api/import",
    "/api/cad",
    "/api/catalog/",
    "/api/classes/",
    "/api/accounts/",
    "/api/learning/register",
    "/api/learning/remove",
    "/api/learning/control",
    "/api/learning/imports/",
    "/api/review-ai/",
    "/api/review-ai-cancel/",
    "/api/learning/vlm/",
)
_DENIED_POST_EXACT = frozenset({
    "/api/learning/ladder/decision",
    "/api/learning/promotion-requests",
    "/api/learning/omx/center/hub-upload",
    "/api/learning/omx/center/cuda-run",
})
_ALLOWED_GET_EXACT = frozenset({
    "/api/learning",
    "/api/learning/canonical",
    "/api/learning/omx/center",
    "/api/learning/storage",
    "/api/learning/control",
    "/api/learning/promotion-requests",
})
_ALLOWED_GET_PREFIXES = (
    "/api/learning/canonical/",
    "/api/learning/omx/center/",
    "/api/learning/ladder/",
)
_ALLOWED_POST_EXACT = frozenset({
    "/api/learning/canonical/jobs",
    "/api/learning/omx/center/run",
    "/api/learning/omx/center/stop",
    "/api/learning/omx/center/lerobot-run",
    "/api/learning/ladder/start",
    "/api/learning/ladder/two-arm",
    "/api/learning/ladder/two-arm-compare",
    "/api/learning/storage/preflight",
})
_CANCEL_JOB_RE = re.compile(rf"/api/learning/canonical/jobs/{_UUID_OR_ID}/cancel")


class ServiceTokens:
    """Constant-time bearer-token verifier mapped to `service_offline_job` principals."""

    def __init__(self, spec: dict[str, Any]) -> None:
        if not isinstance(spec, dict) or not isinstance(spec.get("tokens"), list):
            raise ValueError("service tokens config must contain a 'tokens' list")
        self._records: list[dict[str, str]] = []
        for idx, row in enumerate(spec["tokens"]):
            if not isinstance(row, dict):
                raise ValueError("service token entry must be an object")
            tid = str(row.get("id") or f"svc-{idx}").strip()
            scope = str(row.get("scope") or "").strip()
            if not tid or scope not in _ALLOWED_SCOPES:
                raise ValueError(f"invalid service token scope {scope!r}")
            digest = row.get("token_sha256")
            if digest is None:
                raw = row.get("token")
                if not isinstance(raw, str) or len(raw.strip()) < 16:
                    raise ValueError("raw service token must be >= 16 characters")
                digest = hashlib.sha256(raw.strip().encode("utf-8")).hexdigest()
            elif not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest.strip()):
                raise ValueError("token_sha256 must be a 64-char lowercase hex SHA-256")
            self._records.append({"id": tid, "scope": scope, "digest": digest.strip().lower()})

    def verify(self, header_value: str | None) -> dict[str, Any] | None:
        if not isinstance(header_value, str) or not header_value.startswith("Bearer "):
            return None
        candidate = header_value[7:].strip()
        if not candidate:
            raise PermissionError("empty service bearer token")
        cand_hex = hashlib.sha256(candidate.encode("utf-8")).hexdigest()
        for rec in self._records:
            if hmac.compare_digest(cand_hex, rec["digest"]):
                return {
                    "principal_id": rec["id"],
                    "user_id": f"svc:{rec['id']}",
                    "scope": rec["scope"],
                    "capabilities": ("view", rec["scope"]),
                }
        raise PermissionError("invalid service bearer token")


def load(path: Path | None, parser=None) -> ServiceTokens | None:
    if path is None:
        return None
    try:
        return ServiceTokens(json.loads(Path(path).read_text(encoding="utf-8")))
    except (OSError, ValueError) as exc:
        if parser is not None:
            parser.error(f"--service-tokens: {exc}")
        raise


def authorize(method: str, path: str, principal: dict[str, Any]) -> None:
    """Default-DENY route check for scoped offline learning service principals."""
    if principal.get("scope") != SERVICE_SCOPE:
        raise PermissionError("unsupported service token scope")
    if any(path == p.rstrip("/") or path.startswith(p) for p in _DENIED_PREFIXES):
        raise PermissionError("service token forbidden on UI/frame/mutation route")
    if method == "GET":
        if path in _ALLOWED_GET_EXACT or path.startswith(_ALLOWED_GET_PREFIXES):
            return
        raise PermissionError("service token GET path outside allowlist")
    if method == "POST":
        if path in _DENIED_POST_EXACT:
            raise PermissionError("service token forbidden on approval/upload/cuda route")
        if path in _ALLOWED_POST_EXACT or _CANCEL_JOB_RE.fullmatch(path):
            return
        raise PermissionError("service token POST path outside allowlist")
    raise PermissionError(f"unsupported HTTP method {method!r}")


def check_get(handler, path: str, tokens: ServiceTokens | None) -> bool:
    """Authenticate + authorize Bearer GET if present; returns True if an HTTP error response was sent."""
    if tokens is None:
        return False
    auth = handler.headers.get("Authorization")
    if not auth or not auth.startswith("Bearer "):
        return False
    try:
        principal = tokens.verify(auth)
        assert principal is not None
        authorize("GET", path, principal)
        handler.service_principal = principal
        return False
    except PermissionError as exc:
        handler.send({"error": str(exc)}, 403)
        return True


def handle_post(handler, path: str, tokens: ServiceTokens | None, deny_fn) -> bool | None:
    """Handle Bearer POST auth before CSRF: returns True if rejected, False if authorized, None if not Bearer."""
    if tokens is None:
        return None
    auth = handler.headers.get("Authorization")
    if not auth or not auth.startswith("Bearer "):
        return None
    if not handler.allowed_host():
        deny_fn()
        return True
    try:
        principal = tokens.verify(auth)
        assert principal is not None
        authorize("POST", path, principal)
        handler.service_principal = principal
        return False
    except PermissionError as exc:
        handler.send({"error": str(exc)}, 403)
        return True
