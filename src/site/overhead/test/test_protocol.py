"""Drive src/site/overhead/protocol/vectors.json against overhead.protocol.

The vectors file is shared with the Kotlin side; do not edit it here (see
the module AGENTS.md). If a vector looks wrong, that is a design question,
not a local fixup.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from overhead import protocol

VECTORS = json.loads(
    (Path(__file__).resolve().parents[1] / "protocol" / "vectors.json").read_text(encoding="utf-8")
)


def test_vectors_proto_and_ws_path_match_the_module():
    assert VECTORS["proto"] == protocol.PROTO
    assert VECTORS["ws_path"] == protocol.WS_PATH
    assert VECTORS["header_size"] == protocol.HEADER_SIZE
    assert tuple(VECTORS["rotation_values"]) == protocol.VALID_ROTATIONS


@pytest.mark.parametrize("vector", VECTORS["frame_headers"]["valid"], ids=lambda v: v["name"])
def test_valid_header_parses(vector):
    data = bytes.fromhex(vector["hex"])
    header = protocol.parse_header(data)
    assert header.seq == vector["seq"]
    assert header.age_ms == vector["age_ms"]
    assert header.width == vector["width"]
    assert header.height == vector["height"]
    assert header.rotation_deg == vector["rotation_deg"]


@pytest.mark.parametrize("vector", VECTORS["frame_headers"]["valid"], ids=lambda v: v["name"])
def test_valid_header_round_trips_through_pack(vector):
    data = bytes.fromhex(vector["hex"])
    header = protocol.parse_header(data)
    assert protocol.pack_header(header) == data


@pytest.mark.parametrize("vector", VECTORS["frame_headers"]["invalid"], ids=lambda v: v["name"])
def test_invalid_header_reports_the_vector_reason(vector):
    data = bytes.fromhex(vector["hex"])
    with pytest.raises(protocol.HeaderError) as excinfo:
        protocol.parse_header(data)
    assert excinfo.value.reason == vector["reason"]


def test_hello_valid_passes():
    protocol.validate_hello(VECTORS["messages"]["hello_valid"])


def test_hello_bad_proto_is_rejected():
    with pytest.raises(protocol.HelloError) as excinfo:
        protocol.validate_hello(VECTORS["messages"]["hello_bad_proto"])
    assert excinfo.value.reason == "proto"


def test_make_config_matches_the_default_vector():
    assert protocol.make_config() == VECTORS["messages"]["config_default"]


def test_close_codes_match_the_vector():
    assert protocol.CLOSE_BAD_PROTO == VECTORS["close_codes"]["bad_proto"]
    assert protocol.CLOSE_UNAUTHORIZED == VECTORS["close_codes"]["unauthorized_source"]
    assert protocol.CLOSE_REPLACED == VECTORS["close_codes"]["replaced_by_same_source"]


@pytest.mark.parametrize("vector", VECTORS["pairing_uris"]["valid"], ids=lambda v: v["uri"])
def test_valid_pairing_uri_parses(vector):
    parsed = protocol.parse_pairing_uri(vector["uri"])
    assert parsed["host"] == vector["host"]
    assert parsed["port"] == vector["port"]
    assert parsed["token"] == vector["token"]
    assert parsed["source"] == vector["source"]
    assert parsed["ws_url"] == vector["ws_url"]


@pytest.mark.parametrize("vector", VECTORS["pairing_uris"]["invalid"], ids=lambda v: v["uri"])
def test_invalid_pairing_uri_reports_the_vector_reason(vector):
    with pytest.raises(protocol.PairingError) as excinfo:
        protocol.parse_pairing_uri(vector["uri"])
    assert excinfo.value.reason == vector["reason"]


def test_source_pattern_matches_the_vector():
    assert protocol.SOURCE_PATTERN.pattern == VECTORS["pairing_uris"]["source_pattern"]


@pytest.mark.parametrize("vector", VECTORS["pairing_uris"]["valid"], ids=lambda v: v["uri"])
def test_generated_pairing_uri_round_trips(vector):
    generated = protocol.pairing_uri(
        vector["host"], vector["port"], vector["token"], vector["source"]
    )
    parsed = protocol.parse_pairing_uri(generated)
    assert parsed["host"] == vector["host"]
    assert parsed["port"] == vector["port"]
    assert parsed["token"] == vector["token"]
    assert parsed["source"] == vector["source"]
