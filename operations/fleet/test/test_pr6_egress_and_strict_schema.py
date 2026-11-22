"""PR-6 tests: D-358 external egress denial/redaction and D-878 strict JSON schema chat adapter."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "operations" / "decision" / "src"))

from rosy.decision.egress_policy import (  # noqa: E402
    EgressDeniedError,
    EgressPolicy,
    build_strict_chat_request,
    normalize_strict_schema,
    parse_strict_chat_reply,
)


def test_d358_egress_default_deny_ssrf_images_and_redaction():
    pol = EgressPolicy()
    # Local loopback text-only passes.
    pol.check_destination("http://127.0.0.1:11434/api/chat", tier="local", has_images=False)

    # Default DENY blocks external egress, unapproved images, non-loopback local targets.
    with pytest.raises(EgressDeniedError) as e1:
        pol.check_destination("https://api.example.com/v1/chat", tier="external")
    assert e1.value.code == "EXTERNAL_EGRESS_DISABLED"

    with pytest.raises(EgressDeniedError) as e2:
        pol.check_destination("http://127.0.0.1:11434/api/chat", tier="local", has_images=True)
    assert e2.value.code == "IMAGES_NOT_ALLOWED"

    ext = EgressPolicy(allow_external=True, allowed_tiers=frozenset({"local", "external"}),
                       allowed_hosts=frozenset({"llm.example.com"}))
    with pytest.raises(EgressDeniedError) as e3:
        ext.check_destination("http://llm.example.com/v1/chat", tier="external")
    assert e3.value.code == "TLS_REQUIRED"

    with pytest.raises(EgressDeniedError) as e4:
        ext.check_destination("https://169.254.169.254/latest", tier="external")
    assert e4.value.code == "SSRF_BLOCKED"

    with pytest.raises(EgressDeniedError) as e5:
        ext.check_destination("https://other.example.com/v1", tier="external")
    assert e5.value.code == "HOST_NOT_ALLOWED"

    for bad_ssrf in ("https://224.0.0.1/v1", "https://node.ts.net/v1", "https://@llm.example.com/v1"):
        with pytest.raises(EgressDeniedError) as ex:
            ext.check_destination(bad_ssrf, tier="external")
        assert ex.value.code in ("SSRF_BLOCKED", "INVALID_DESTINATION")

    with pytest.raises(EgressDeniedError) as e_img:
        build_strict_chat_request(
            "openai", "gpt-4o-mini",
            [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": "data:image/png;base64,AA"}}]}],
            {"type": "object", "properties": {"a": {"type": "string"}}},
        )
    assert e_img.value.code == "IMAGES_NOT_ALLOWED"

    cleaned = pol.sanitize_payload({
        "token": "raw-secret-1",
        "access_token": "raw-access",
        "openai_api_key": "raw-oak",
        "msg": (
            "host 100.64.10.22 ipv6 fd7a:115c:a1e0::1 path /home/ai/rosy-test and C:\\Users\\op\\key "
            "Bearer sk_test_secretvalue123 bearer lowertok99 "
            "sk-proj-abcdefghijkl1234 sk-ant-api03-abcdefghijkl AIzaSyD1234567890abcdef1234567890 "
            "svc_offline_tok_0123456789abcdef"
        ),
    })
    assert cleaned["token"] == "[REDACTED_SECRET]"
    assert cleaned["access_token"] == "[REDACTED_SECRET]" and cleaned["openai_api_key"] == "[REDACTED_SECRET]"
    for leaked in ("100.64.10.22", "fd7a:115c", "/home/ai", "C:\\Users\\op", "sk_test_secretvalue123",
                   "lowertok99", "sk-proj-abcdefghijkl1234", "sk-ant-api03-abcdefghijkl",
                   "AIzaSyD1234567890abcdef1234567890", "svc_offline_tok_0123456789abcdef"):
        assert leaked not in cleaned["msg"]

    cleaned_meta = pol.sanitize_payload({
        "max_tokens": 512, "prompt_tokens": 99, "access_token": "raw",
        "msg": "see https://example.com/docs and D:/Dev/secret.txt key=sk_live_abcdefgh123456",
    })
    assert cleaned_meta["max_tokens"] == 512 and cleaned_meta["prompt_tokens"] == 99 and cleaned_meta["access_token"] == "[REDACTED_SECRET]"
    assert "https://example.com/docs" in cleaned_meta["msg"]
    assert "D:/Dev/secret.txt" not in cleaned_meta["msg"] and "sk_live_abcdefgh123456" not in cleaned_meta["msg"]


def test_d878_strict_schema_request_and_fail_closed_parsing():
    for bad_schema in (
        {"type": "object", "properties": {"a": {"type": "string"}}, "additionalProperties": True},
        {"type": "object", "properties": {"a": {"type": "string"}}, "additionalProperties": {"type": "string"}},
        {"type": "object", "properties": {"a": {"type": "string", "enum": []}}},
    ):
        with pytest.raises(ValueError, match="SCHEMA_NOT_STRICT"):
            normalize_strict_schema(bad_schema)

    schema = {
        "type": "object",
        "properties": {
            "verb": {"type": "string", "enum": ["escalate_human", "align_push"]},
            "kind": {"const": "fallback"},
            "score": {"type": "number"},
            "steps": {"type": "array", "items": {"type": "integer"}},
            "meta": {"type": "object", "properties": {"ok": {"type": "boolean"}, "note": {"type": ["string", "null"]}}},
        },
    }
    req = build_strict_chat_request("openai", "gpt-4o-mini", [{"role": "user", "content": "host 192.168.1.10 stalled"}], schema, name="fallback_decision")
    assert req["max_tokens"] == 1024
    assert req["response_format"]["json_schema"]["strict"] is True
    assert req["response_format"]["json_schema"]["schema"]["additionalProperties"] is False
    assert req["response_format"]["json_schema"]["schema"]["properties"]["meta"]["additionalProperties"] is False
    assert "192.168.1.10" not in req["messages"][0]["content"]

    with pytest.raises(ValueError, match="UNSUPPORTED_PROVIDER"):
        build_strict_chat_request("anthropic", "claude", [{"role": "user", "content": "hi"}], schema)

    good_reply = json.dumps({"verb": "align_push", "kind": "fallback", "score": 0.85, "steps": [1, 2], "meta": {"ok": True, "note": None}})
    ok = parse_strict_chat_reply("openai", {
        "model": "gpt-4o-mini",
        "choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": good_reply}}],
    }, "gpt-4o-mini", schema)
    assert ok["score"] == 0.85 and ok["meta"]["note"] is None

    for bad_obj in (
        {"verb": "align_push", "kind": "fallback", "score": True, "steps": [1], "meta": {"ok": True, "note": None}},
        {"verb": "align_push", "kind": "wrong", "score": 0.5, "steps": [1], "meta": {"ok": True, "note": None}},
        {"verb": "align_push", "kind": "fallback", "score": 0.5, "steps": ["bad"], "meta": {"ok": True, "note": None}},
        {"verb": "align_push", "kind": "fallback", "score": 0.5, "steps": [1], "meta": {"ok": True, "note": 123}},
        {"verb": "align_push", "kind": "fallback", "score": 0.5, "steps": [1], "meta": {"ok": True, "note": None, "extra": 1}},
    ):
        env = {"model": "gpt-4o-mini", "choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": json.dumps(bad_obj)}}]}
        with pytest.raises(ValueError, match="STRICT_OUTPUT_INVALID"):
            parse_strict_chat_reply("openai", env, "gpt-4o-mini", schema)
