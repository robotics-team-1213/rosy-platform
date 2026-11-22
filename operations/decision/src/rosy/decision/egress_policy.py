"""D-358 external egress policy & D-878 strict JSON schema chat adapter for Argon/external VLM calls."""
from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import json
import re
from typing import Any
from urllib.parse import urlparse

from rosy.decision.structured_output import ollama_chat, ollama_reply, openai_chat, openai_reply

_SECRET_KEYS = frozenset({"token", "secret", "password", "api_key", "authorization", "cookie", "bearer"})
_TOKEN_RE = re.compile(r"(?:Bearer\s+[A-Za-z0-9._\-]{8,}|(?:sk|hf|ghp|xoxb|rosy)_[A-Za-z0-9._\-]{8,}|sk-[A-Za-z0-9]{12,})")
_IPV4_RE = re.compile(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b")
_POSIX_PATH_RE = re.compile(r"/(?:home|Users|var|etc|tmp|opt|mnt)/[A-Za-z0-9._/\-]+")
_WIN_PATH_RE = re.compile(r"[A-Za-z]:\\(?:[^\s\"'`]+)")
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
_TAILNET_NET = ipaddress.ip_network("100.64.0.0/10")


class EgressDeniedError(ValueError):
    """Fail-closed D-358 egress or D-878 strict-schema refusal carrying a stable error code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _mask_ipv4(match: re.Match[str]) -> str:
    raw = match.group(1)
    try:
        ip = ipaddress.IPv4Address(raw)
    except ValueError:
        return raw
    if ip.is_private or ip in _TAILNET_NET or ip.is_link_local:
        return "[REDACTED_IP]"
    return raw


def _redact_str(text: str) -> str:
    out = _TOKEN_RE.sub("[REDACTED_SECRET]", text)
    out = _IPV4_RE.sub(_mask_ipv4, out)
    out = _POSIX_PATH_RE.sub("[REDACTED_PATH]", out)
    return _WIN_PATH_RE.sub("[REDACTED_PATH]", out)


def _redact_obj(value: Any) -> Any:
    if isinstance(value, str):
        return _redact_str(value)
    if isinstance(value, list):
        return [_redact_obj(v) for v in value]
    if isinstance(value, dict):
        return {
            k: ("[REDACTED_SECRET]" if str(k).lower() in _SECRET_KEYS else _redact_obj(v))
            for k, v in value.items()
        }
    return value


@dataclass(frozen=True)
class EgressPolicy:
    """D-358 default-DENY egress policy for local vs external model calls."""

    allow_external: bool = False
    allowed_hosts: frozenset[str] = frozenset()
    allowed_tiers: frozenset[str] = frozenset({"local"})
    allow_images: bool = False
    max_payload_bytes: int = 65_536

    def check_destination(self, url: str, *, tier: str = "local", has_images: bool = False) -> None:
        if has_images and not self.allow_images:
            raise EgressDeniedError("IMAGES_NOT_ALLOWED", "image egress is denied by policy")
        if tier not in self.allowed_tiers:
            if tier != "local" and not self.allow_external:
                raise EgressDeniedError("EXTERNAL_EGRESS_DISABLED", "external model egress is disabled by default")
            raise EgressDeniedError("TIER_NOT_ALLOWED", f"tier {tier!r} is not allowed")
        parts = urlparse(url)
        host = (parts.hostname or "").lower()
        if not parts.scheme or not host or parts.username or parts.password:
            raise EgressDeniedError("INVALID_DESTINATION", "URL missing valid scheme/host or containing credentials")
        if tier == "local":
            if parts.scheme not in ("http", "https") or host not in _LOOPBACK_HOSTS:
                raise EgressDeniedError("HOST_NOT_ALLOWED", f"local tier allows loopback only, got {host!r}")
            return
        if not self.allow_external:
            raise EgressDeniedError("EXTERNAL_EGRESS_DISABLED", "external model egress is disabled by default")
        if parts.scheme != "https":
            raise EgressDeniedError("TLS_REQUIRED", "external tier requires https://")
        try:
            ip = ipaddress.ip_address(host)
            if ip.is_link_local or ip.is_loopback or ip.is_private or ip in _TAILNET_NET:
                raise EgressDeniedError("SSRF_BLOCKED", f"SSRF-protected address {host!r}")
        except ValueError:
            pass
        if host not in {h.lower() for h in self.allowed_hosts}:
            raise EgressDeniedError("HOST_NOT_ALLOWED", f"host {host!r} not in allowed_hosts")

    def sanitize_payload(self, payload: Any) -> Any:
        cleaned = _redact_obj(payload)
        encoded = json.dumps(cleaned, ensure_ascii=False, allow_nan=False).encode("utf-8")
        if len(encoded) > self.max_payload_bytes:
            raise EgressDeniedError("PAYLOAD_TOO_LARGE", f"payload {len(encoded)} bytes > {self.max_payload_bytes}")
        return cleaned


def normalize_strict_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Enforce D-878 closed object schemas (`additionalProperties: False`, full `required`)."""
    if not isinstance(schema, dict):
        raise ValueError("SCHEMA_NOT_STRICT")
    out = dict(schema)
    if out.get("type") == "object" or "properties" in out:
        props = out.get("properties")
        if not isinstance(props, dict) or out.get("additionalProperties") is True:
            raise ValueError("SCHEMA_NOT_STRICT")
        out["type"] = "object"
        out["properties"] = {k: normalize_strict_schema(v) if isinstance(v, dict) else v for k, v in props.items()}
        out["required"] = sorted(props.keys())
        out["additionalProperties"] = False
    elif out.get("type") == "array" and isinstance(out.get("items"), dict):
        out["items"] = normalize_strict_schema(out["items"])
    return out


def build_strict_chat_request(
    provider: str,
    model: str,
    messages: list[dict[str, Any]],
    schema: dict[str, Any],
    *,
    name: str = "decision",
    policy: EgressPolicy | None = None,
    url: str = "http://127.0.0.1:11434",
    tier: str = "local",
    has_images: bool = False,
    max_tokens: int = 1024,
) -> dict[str, Any]:
    """Apply D-358 egress + sanitization and D-878 strict schema wrapping before building provider request."""
    pol = policy or EgressPolicy()
    pol.check_destination(url, tier=tier, has_images=has_images)
    strict_schema = normalize_strict_schema(schema)
    clean_msgs = pol.sanitize_payload(messages)
    prov = provider.lower()
    body = ollama_chat(model, clean_msgs, strict_schema, num_predict=max_tokens) if prov == "ollama" else openai_chat(model, clean_msgs, strict_schema, name=name, max_tokens=max_tokens)
    pol.sanitize_payload(body)
    return body


def parse_strict_chat_reply(
    provider: str,
    response: dict[str, Any],
    model: str,
    schema: dict[str, Any],
    *,
    error: str = "STRICT_OUTPUT_INVALID",
) -> dict[str, Any]:
    """Parse provider envelope and enforce D-878 closed schema fail-closed without JSON repair."""
    strict = normalize_strict_schema(schema)
    if provider.lower() == "ollama":
        payload, _ = ollama_reply(response, model, error)
    else:
        payload = openai_reply(response, model, error)
    if not isinstance(payload, dict):
        raise ValueError(error)
    props = strict.get("properties") or {}
    if set(payload.keys()) != set(props.keys()):
        raise ValueError(error)
    for k, spec in props.items():
        val = payload[k]
        if "enum" in spec and val not in spec["enum"]:
            raise ValueError(error)
        t = spec.get("type")
        if t == "string" and not isinstance(val, str):
            raise ValueError(error)
        if t == "boolean" and not isinstance(val, bool):
            raise ValueError(error)
        if t == "integer" and (type(val) is not int):
            raise ValueError(error)
    return payload
