"""D-341 19: rosy-pair/1 code, fingerprint and JSON shapes follow the shared vector."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from core_common.protocol import discovery_txt, pairing

FIXTURES = Path(__file__).resolve().parents[4] / "test/fixtures/protocol"
VECTOR = json.loads((FIXTURES / "pairing.v1.json").read_text(encoding="utf-8"))
CODE_CASES = {case["id"]: case for case in VECTOR["code_cases"]}


def test_vector_constants_are_the_module_constants():
    assert VECTOR["proto"] == pairing.PROTO
    assert VECTOR["role"] == pairing.ROLE
    assert VECTOR["max_request_bytes"] == pairing.MAX_REQUEST_BYTES
    assert tuple(VECTOR["request_reasons"]) == pairing.REQUEST_REASONS
    assert tuple(VECTOR["result_reasons"]) == pairing.RESULT_REASONS
    added = tuple(VECTOR["pairable_reasons_added"])
    assert pairing.PAIRABLE_REASONS == discovery_txt.REASONS + added


@pytest.mark.parametrize("case", VECTOR["code_cases"], ids=lambda case: case["id"])
def test_confirmation_code_matches_vector(case):
    assert pairing.confirmation_code(
        role=case["role"], request_id=case["request_id"],
        leaf_cert_sha256=case["leaf_cert_sha256"], client_nonce=case["client_nonce"],
        server_nonce=case["server_nonce"]) == case["code"]
    assert pairing.commit(case["client_nonce"]) == case["client_commit"]


@pytest.mark.parametrize("pair", VECTOR["code_pairs_differing_only_in_leaf"])
def test_a_relayed_leaf_changes_the_code(pair):
    first, second = (CODE_CASES[name] for name in pair)
    differing = {key for key in first if first[key] != second[key]} - {"id", "code"}
    assert differing == {"leaf_cert_sha256"}
    assert first["code"] != second["code"]


def test_a_tampered_vector_fails():
    case = dict(VECTOR["code_cases"][0])
    case["server_nonce"] = case["server_nonce"][:-1] + "y"
    assert pairing.confirmation_code(
        role=case["role"], request_id=case["request_id"],
        leaf_cert_sha256=case["leaf_cert_sha256"], client_nonce=case["client_nonce"],
        server_nonce=case["server_nonce"]) != case["code"]


@pytest.mark.parametrize("case", VECTOR["fingerprint_cases"], ids=lambda case: case["id"])
def test_fingerprint_matches_vector(case):
    assert pairing.fingerprint_from_sha256(case["der_sha256"]) == case["fingerprint"]
    if "ca_pem" in case:
        assert pairing.der_sha256(case["ca_pem"]) == case["der_sha256"]
        assert pairing.site_fingerprint(case["ca_pem"]) == case["fingerprint"]


def _reason(expect: dict) -> str | None:
    return None if expect["valid"] else expect["reason"]


@pytest.mark.parametrize("case", VECTOR["request_cases"], ids=lambda case: case["id"])
def test_request_validation_matches_vector(case):
    raw = json.dumps(case["body"], ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    assert pairing.validate_request_bytes(raw) == _reason(case["expect"])


@pytest.mark.parametrize("case", VECTOR["reveal_cases"], ids=lambda case: case["id"])
def test_reveal_validation_matches_vector(case):
    raw = json.dumps(case["body"], separators=(",", ":")).encode("utf-8")
    assert pairing.validate_reveal_bytes(raw) == _reason(case["expect"])


@pytest.mark.parametrize("case", VECTOR["result_cases"], ids=lambda case: case["id"])
def test_result_validation_matches_vector(case):
    assert pairing.validate_result(case["result"]) == _reason(case["expect"])


@pytest.mark.parametrize("case", VECTOR["pairable_cases"], ids=lambda case: case["id"])
def test_pairable_matches_vector(case):
    txt = [tuple(item.split("=", 1)) for item in case["txt"]]
    reason = pairing.pairable(case["service_type"], case["host"], case["address"], case["port"], txt)
    expect = case["expect"]
    assert reason == (None if expect["pairable"] else expect["reason"])


def test_request_bytes_that_are_not_json_are_not_an_object():
    assert pairing.validate_request_bytes(b"{not json") == "not_object"
    assert pairing.validate_request_bytes(b"\xff\xfe") == "not_object"


def test_new_secret_is_43_char_base64url_and_commit_is_its_digest():
    nonce = pairing.new_secret()
    assert pairing.SECRET_PATTERN.fullmatch(nonce)
    assert pairing.commit(nonce) == hashlib.sha256(nonce.encode("ascii")).hexdigest()


def test_leaf_sha256_of_the_first_pem_block():
    ca = VECTOR["fingerprint_cases"][0]
    assert pairing.der_sha256(ca["ca_pem"] + ca["ca_pem"]) == ca["der_sha256"]
    with pytest.raises(ValueError):
        pairing.der_sha256("no certificate here")
