"""Short-lived source-scoped bearer leases for direct Vision JPEG reads."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import re
import time
from dataclasses import dataclass
from typing import Mapping

_SOURCE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,95}$")
_MAX_TTL_S = 120


@dataclass(frozen=True)
class PreviewRectification:
    """Bounded, serializable preview-only lens and plane settings."""

    fx: float = 1.0
    fy: float = 1.0
    cx: float = 0.5
    cy: float = 0.5
    k1: float = 0.0
    k2: float = 0.0
    p1: float = 0.0
    p2: float = 0.0
    k3: float = 0.0
    corners: tuple[tuple[float, float], ...] = (
        (0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0),
    )
    output_aspect: float = 0.0

    def __post_init__(self) -> None:
        for name in ("fx", "fy"):
            _bounded(getattr(self, name), name, 0.25, 4.0)
        for name in ("cx", "cy"):
            _bounded(getattr(self, name), name, 0.0, 1.0)
        for name in ("k1", "k2", "k3"):
            _bounded(getattr(self, name), name, -1.0, 1.0)
        for name in ("p1", "p2"):
            _bounded(getattr(self, name), name, -0.5, 0.5)
        if len(self.corners) != 4:
            raise ValueError("rectification needs four source corners")
        for point in self.corners:
            if len(point) != 2:
                raise ValueError("each source corner must be an x/y pair")
            _bounded(point[0], "corner x", 0.0, 1.0)
            _bounded(point[1], "corner y", 0.0, 1.0)
        turns = []
        for index, point in enumerate(self.corners):
            nxt = self.corners[(index + 1) % 4]
            after = self.corners[(index + 2) % 4]
            turns.append((nxt[0] - point[0]) * (after[1] - nxt[1])
                         - (nxt[1] - point[1]) * (after[0] - nxt[0]))
        if any(abs(turn) < 1e-6 for turn in turns) or not all(turn > 0 for turn in turns):
            raise ValueError("source corners must form a clockwise convex quadrilateral")
        _bounded(self.output_aspect, "output aspect", 0.0, 4.0)
        if 0 < self.output_aspect < 0.25:
            raise ValueError("output aspect must be zero (automatic) or at least 0.25")

    @classmethod
    def from_mapping(cls, raw: Mapping[str, object]) -> "PreviewRectification":
        if not isinstance(raw, Mapping):
            raise ValueError("rectification settings must be an object")
        allowed = {"fx", "fy", "cx", "cy", "k1", "k2", "p1", "p2", "k3",
                   "corners", "output_aspect"}
        if raw.keys() - allowed:
            raise ValueError("rectification settings contain unknown fields")
        corners = raw.get("corners", cls.corners)
        if not isinstance(corners, (tuple, list)) or any(
                not isinstance(point, (tuple, list)) for point in corners):
            raise ValueError("source corners must be an array of x/y pairs")
        values = {key: raw[key] for key in raw.keys() & allowed if key != "corners"}
        values["corners"] = tuple(tuple(point) for point in corners)
        return cls(**values)

    def as_dict(self) -> dict:
        return {"fx": self.fx, "fy": self.fy, "cx": self.cx, "cy": self.cy,
                "k1": self.k1, "k2": self.k2, "p1": self.p1, "p2": self.p2,
                "k3": self.k3, "corners": [list(point) for point in self.corners],
                "output_aspect": self.output_aspect}

    @property
    def is_identity(self) -> bool:
        return (self.fx == 1 and self.fy == 1 and self.cx == 0.5 and self.cy == 0.5
                and all(getattr(self, name) == 0 for name in ("k1", "k2", "p1", "p2", "k3"))
                and self.corners == ((0, 0), (1, 0), (1, 1), (0, 1))
                and self.output_aspect == 0)


def _bounded(value: object, name: str, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be numeric")
    number = float(value)
    if not math.isfinite(number) or not low <= number <= high:
        raise ValueError(f"{name} must be finite and between {low} and {high}")
    return number


class VisionLeaseError(ValueError):
    pass


class VisionLeaseSigner:
    def __init__(self, secret: str | bytes) -> None:
        key = secret.encode("utf-8") if isinstance(secret, str) else secret
        if not isinstance(key, bytes) or len(key) < 32:
            raise ValueError("vision preview secret must contain at least 32 bytes")
        self._key = key

    def issue(self, *, principal_id: str, source_id: str, now: int | None = None,
              ttl_s: int = 60,
              rectification: Mapping[str, object] | None = None) -> str:
        current = int(time.time()) if now is None else now
        if not isinstance(principal_id, str) or not principal_id or len(principal_id) > 96:
            raise ValueError("invalid preview principal")
        if not isinstance(source_id, str) or not _SOURCE.fullmatch(source_id):
            raise ValueError("invalid preview source")
        if type(ttl_s) is not int or not 1 <= ttl_s <= _MAX_TTL_S:
            raise ValueError("preview lease TTL must be between 1 and 120 seconds")
        payload = {"v": 1, "sub": principal_id, "source": source_id,
                   "scope": "frame:read", "iat": current, "exp": current + ttl_s}
        if rectification is not None:
            payload["rectification"] = PreviewRectification.from_mapping(rectification).as_dict()
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
        if "rectification" in payload:
            try:
                PreviewRectification.from_mapping(payload["rectification"])
            except (TypeError, ValueError) as exc:
                raise VisionLeaseError("invalid rectification settings") from exc
        return payload


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _unb64(value: str) -> bytes:
    if not value or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise ValueError("invalid base64")
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
