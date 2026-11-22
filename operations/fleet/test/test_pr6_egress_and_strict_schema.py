"""PR-6 tests: D-358 external egress denial/redaction and D-878 strict JSON schema chat adapter."""
from __future__ import annotations

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

    cleaned = pol.sanitize_payload({
        "token": "raw-secret-1",
        "msg": "host 100.64.10.22 path /home/ai/rosy-test and C:\\Users\\op\\key Bearer sk_test_secretvalue123",
    })
    assert cleaned["token"] == "[REDACTED_SECRET]"
    assert "100.64.10.22" not in cleaned["msg"] and "/home/ai" not in cleaned["msg"]
    assert "C:\\Users\\op" not in cleaned["msg"] and "sk_test_secretvalue123" not in cleaned["msg"]


def test_d878_strict_schema_request_and_fail_closed_parsing():
    with pytest.raises(ValueError, match="SCHEMA_NOT_STRICT"):
        normalize_strict_schema({"type": "object", "properties": {"a": {"type": "string"}}, "additionalProperties": True})

    schema = {"type": "object", "properties": {"verb": {"type": "string", "enum": ["escalate_human", "align_push"]}, "reason": {"type": "string"}}}
    req = build_strict_chat_request("openai", "gpt-4o-mini", [{"role": "user", "content": "host 192.168.1.10 stalled"}], schema, name="fallback_decision")
    assert req["response_format"]["json_schema"]["strict"] is True
    assert req["response_format"]["json_schema"]["schema"]["additionalProperties"] is False
    assert "192.168.1.10" not in req["messages"][0]["content"]

    ok = parse_strict_chat_reply("openai", {
        "model": "gpt-4o-mini",
        "choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": '{"verb":"align_push","reason":"clear"}'}}],
    }, "gpt-4o-mini", schema)
    assert ok == {"verb": "align_push", "reason": "clear"}

    for bad in (
        {"model": "gpt-4o-mini", "choices": [{"finish_reason": "length", "message": {"role": "assistant", "content": '{"verb":"align_push","reason":"x"}'}}]},
        {"model": "gpt-4o-mini", "choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": '{"verb":"invalid","reason":"x"}'}}]},
        {"model": "gpt-4o-mini", "choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": '{"verb":"align_push","reason":"x","extra":1}'}}]},
    ):
        with pytest.raises(ValueError, match="STRICT_OUTPUT_INVALID"):
            parse_strict_chat_reply("openai", bad, "gpt-4o-mini", schema)
