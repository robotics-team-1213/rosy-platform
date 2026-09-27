"""Short-lived source-scoped bearer leases for direct Vision JPEG reads."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import time
from typing import Mapping

_SOURCE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,95}$")
_MAX_TTL_S = 120


class VisionLeaseError(ValueError):
    pass


class VisionLeaseSigner:
    def __init__(self, secret: str | bytes) -> None:
        key = secret.encode("utf-8") if isinstance(secret, str) else secret
        if not isinstance(key, bytes) or len(key) < 32:
            raise ValueError("vision preview secret must contain at least 32 bytes")
        self._key = key

    def issue(self, *, principal_id: str, source_id: str, now: int | None = None,
              ttl_s: int = 60) -> str:
        current = int(time.time()) if now is None else now
        if not isinstance(principal_id, str) or not principal_id or len(principal_id) > 96:
            raise ValueError("invalid preview principal")
        if not isinstance(source_id, str) or not _SOURCE.fullmatch(source_id):
            raise ValueError("invalid preview source")
        if type(ttl_s) is not int or not 1 <= ttl_s <= _MAX_TTL_S:
            raise ValueError("preview lease TTL must be between 1 and 120 seconds")
        payload = {"v": 1, "sub": principal_id, "source": source_id,
                   "scope": "frame:read", "iat": current, "exp": current + ttl_s}
        body = _b64(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
        signature = _b64(hmac.new(self._key, body.encode("ascii"), hashlib.sha256).digest())
        return f"{body}.{signature}"

    def verify(self, token: str, *, source_id: str, now: int | None = None) -> Mapping[str, object]:
        if not isinstance(token, str) or len(token) > 2048 or token.count(".") != 1:
            raise VisionLeaseError("invalid lease")
        body, supplied = token.split(".", 1)
        expected = _b64(hmac.new(self._key, body.encode("ascii", "ignore"), hashlib.sha256).digest())
        if not hmac.compare_digest(supplied, expected):
            raise VisionLeaseError("invalid lease")
        try:
            payload = json.loads(_unb64(body))
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise VisionLeaseError("invalid lease") from exc
        current = int(time.time()) if now is None else now
        if (not isinstance(payload, dict) or payload.get("v") != 1
                or payload.get("scope") != "frame:read"
                or payload.get("source") != source_id
                or not isinstance(payload.get("sub"), str)
                or not isinstance(payload.get("exp"), int)
                or not isinstance(payload.get("iat"), int)
                or payload["iat"] > current or payload["exp"] <= current
                or payload["exp"] - payload["iat"] > _MAX_TTL_S):
            raise VisionLeaseError("expired or out-of-scope lease")
        return payload


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _unb64(value: str) -> bytes:
    if not value or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise ValueError("invalid base64")
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
