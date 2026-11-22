"""D-358 external egress policy & D-878 strict JSON schema chat adapter for Argon/external VLM calls."""
from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import json
import math
import re
from typing import Any
from urllib.parse import urlparse

from rosy.decision.structured_output import ollama_chat, ollama_reply, openai_chat, openai_reply

_SECRET_KEY_RE = re.compile(r"(?:token|secret|password|api[-_]?key|apikey|authorization|cookie|bearer)", re.I)
_TOKEN_COUNT_KEYS = frozenset({
    "max_tokens", "max_completion_tokens", "prompt_tokens", "completion_tokens",
    "input_tokens", "output_tokens", "total_tokens", "token_count", "tokens",
})
_TOKEN_RE = re.compile(
    r"(?i:\bBearer\s+[A-Za-z0-9._\-+/=]{8,})|sk-[A-Za-z0-9._\-]{12,}|(?:sk|hf|ghp|xoxb|rosy|svc)_[A-Za-z0-9._\-]{8,}|AIza[A-Za-z0-9_\-]{20,}"
)
_IPV4_RE = re.compile(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b")
_IPV6_RE = re.compile(r"\b(?:f[cd][0-9a-f]{2}|fe80):[0-9a-f:]+\b", re.I)
_POSIX_PATH_RE = re.compile(r"/(?:home|Users|var|etc|tmp|opt|mnt|root|srv|usr|private)/[A-Za-z0-9._/\-]+")
_WIN_PATH_RE = re.compile(r"""(?<![A-Za-z0-9_])[A-Za-z]:(?:\\|/(?!/))(?:[^\s"'`]+)""")
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
_INTERNAL_SUFFIXES = (".localhost", ".local", ".internal", ".ts.net")
_TAILNET_NET = ipaddress.ip_network("100.64.0.0/10")
_PROVIDERS = frozenset({"ollama", "openai"})


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
    if not ip.is_global or ip.is_private or ip in _TAILNET_NET or ip.is_link_local:
        return "[REDACTED_IP]"
    return raw


def _redact_str(text: str) -> str:
    out = _TOKEN_RE.sub("[REDACTED_SECRET]", text)
    out = _IPV4_RE.sub(_mask_ipv4, out)
    out = _IPV6_RE.sub("[REDACTED_IP]", out)
    out = _POSIX_PATH_RE.sub("[REDACTED_PATH]", out)
    return _WIN_PATH_RE.sub("[REDACTED_PATH]", out)


def _is_secret_key(key: str) -> bool:
    kl = key.lower()
    if kl in _TOKEN_COUNT_KEYS or kl.endswith(("_tokens", "_token_count", "_token_limit")):
        return False
    return bool(_SECRET_KEY_RE.search(kl))


def _redact_obj(value: Any) -> Any:
    if isinstance(value, str):
        return _redact_str(value)
    if isinstance(value, list):
        return [_redact_obj(v) for v in value]
    if isinstance(value, dict):
        return {
            k: ("[REDACTED_SECRET]" if _is_secret_key(str(k)) else _redact_obj(v))
            for k, v in value.items()
        }
    return value


def _messages_have_images(value: Any) -> bool:
    if isinstance(value, str):
        return "data:image/" in value.lower()
    if isinstance(value, list):
        return any(_messages_have_images(v) for v in value)
    if isinstance(value, dict):
        for k, v in value.items():
            kl = str(k).lower()
            if kl in ("images", "image_url") and v:
                return True
            if _messages_have_images(v):
                return True
    return False


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
        if not parts.scheme or not host or parts.username is not None or parts.password is not None:
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
        except ValueError:
            ip = None
        if ip is not None:
            if (
                not ip.is_global
                or ip.is_multicast
                or ip.is_link_local
                or ip.is_loopback
                or ip.is_private
                or (ip.version == 4 and ip in _TAILNET_NET)
            ):
                raise EgressDeniedError("SSRF_BLOCKED", f"SSRF-protected address {host!r}")
        elif host == "localhost" or host.endswith(_INTERNAL_SUFFIXES):
            raise EgressDeniedError("SSRF_BLOCKED", f"SSRF-protected internal host {host!r}")
        if host not in {h.lower() for h in self.allowed_hosts}:
            raise EgressDeniedError("HOST_NOT_ALLOWED", f"host {host!r} not in allowed_hosts")

    def sanitize_payload(self, payload: Any) -> Any:
        cleaned = _redact_obj(payload)
        encoded = json.dumps(cleaned, ensure_ascii=False, allow_nan=False).encode("utf-8")
        if len(encoded) > self.max_payload_bytes:
            raise EgressDeniedError("PAYLOAD_TOO_LARGE", f"payload {len(encoded)} bytes > {self.max_payload_bytes}")
        return cleaned


def normalize_strict_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Enforce D-878 closed object schemas (`additionalProperties: False`, full `required`, non-empty enum)."""
    if not isinstance(schema, dict):
        raise ValueError("SCHEMA_NOT_STRICT")
    out = dict(schema)
    if "enum" in out and (not isinstance(out["enum"], list) or not out["enum"]):
        raise ValueError("SCHEMA_NOT_STRICT")
    if out.get("type") == "object" or "properties" in out:
        props = out.get("properties")
        if not isinstance(props, dict) or out.get("additionalProperties") not in (None, False):
            raise ValueError("SCHEMA_NOT_STRICT")
        if any(not isinstance(v, dict) for v in props.values()):
            raise ValueError("SCHEMA_NOT_STRICT")
        out["type"] = "object"
        out["properties"] = {k: normalize_strict_schema(v) for k, v in props.items()}
        out["required"] = sorted(props.keys())
        out["additionalProperties"] = False
    elif out.get("type") == "array":
        if "items" in out:
            if not isinstance(out["items"], dict):
                raise ValueError("SCHEMA_NOT_STRICT")
            out["items"] = normalize_strict_schema(out["items"])
    return out


def _exact_eq(a: Any, b: Any) -> bool:
    return (type(a) is bool) == (type(b) is bool) and a == b


def _check_single_type(val: Any, typ: str, spec: dict[str, Any], error: str) -> bool:
    if typ == "null":
        return val is None
    if typ == "boolean":
        return isinstance(val, bool)
    if typ == "integer":
        return type(val) is int
    if typ == "number":
        return isinstance(val, (int, float)) and not isinstance(val, bool) and math.isfinite(float(val))
    if typ == "string":
        return isinstance(val, str)
    if typ == "array":
        if not isinstance(val, list):
            return False
        if isinstance(spec.get("items"), dict):
            for item in val:
                _validate_value(item, spec["items"], error)
        return True
    if typ == "object":
        if not isinstance(val, dict):
            return False
        props = spec.get("properties") or {}
        if set(val.keys()) != set(props.keys()):
            raise ValueError(error)
        for k, sub in props.items():
            _validate_value(val[k], sub, error)
        return True
    return False


def _validate_value(val: Any, spec: dict[str, Any], error: str) -> None:
    if "const" in spec and not _exact_eq(val, spec["const"]):
        raise ValueError(error)
    if "enum" in spec and not any(_exact_eq(val, opt) for opt in spec["enum"]):
        raise ValueError(error)
    t = spec.get("type")
    if t is None:
        return
    if isinstance(t, list):
        for branch in t:
            try:
                if _check_single_type(val, branch, spec, error):
                    return
            except ValueError:
                continue
        raise ValueError(error)
    if not _check_single_type(val, t, spec, error):
        raise ValueError(error)


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
    prov = provider.lower()
    if prov not in _PROVIDERS:
        raise ValueError(f"UNSUPPORTED_PROVIDER: {provider!r}")
    pol = policy or EgressPolicy()
    pol.check_destination(url, tier=tier, has_images=has_images or _messages_have_images(messages))
    strict_schema = normalize_strict_schema(schema)
    clean_msgs = pol.sanitize_payload(messages)
    body = ollama_chat(model, clean_msgs, strict_schema, num_predict=max_tokens) if prov == "ollama" else openai_chat(model, clean_msgs, strict_schema, name=name, max_tokens=max_tokens)
    encoded = json.dumps(body, ensure_ascii=False, allow_nan=False).encode("utf-8")
    if len(encoded) > pol.max_payload_bytes:
        raise EgressDeniedError("PAYLOAD_TOO_LARGE", f"payload {len(encoded)} bytes > {pol.max_payload_bytes}")
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
    prov = provider.lower()
    if prov not in _PROVIDERS:
        raise ValueError(f"UNSUPPORTED_PROVIDER: {provider!r}")
    strict = normalize_strict_schema(schema)
    if prov == "ollama":
        payload, _ = ollama_reply(response, model, error)
    else:
        payload = openai_reply(response, model, error)
    _validate_value(payload, strict, error)
    return payload
