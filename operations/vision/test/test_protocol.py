"""Drive test/fixtures/protocol/overhead-ingest.v1.json against rosy_vision.protocol.

The vectors file is shared with the Kotlin side; do not edit it here (see
the module AGENTS.md). If a vector looks wrong, that is a design question,
not a local fixup.
"""

from __future__ import annotations

import json
import ssl
from pathlib import Path

import pytest

from rosy_vision import protocol

VECTORS = json.loads(
    (Path(__file__).resolve().parents[3] / "test" / "fixtures" / "protocol" / "overhead-ingest.v1.json").read_text(encoding="utf-8")
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


def test_hello_with_lens_passes_and_old_hello_has_no_lens():
    protocol.validate_hello(VECTORS["messages"]["hello_with_lens"])
    assert protocol.parse_hello_lens(VECTORS["messages"]["hello_valid"]) is None
    assert protocol.parse_hello_lens(VECTORS["messages"]["hello_with_lens"]) == {
        "kind": "wide", "focal_mm": 2.2, "hfov_deg": 104.1,
    }


@pytest.mark.parametrize("vector", VECTORS["hello_lens"]["valid"], ids=lambda v: v["lens"]["kind"])
def test_valid_hello_lens_parses(vector):
    hello = {**VECTORS["messages"]["hello_valid"], "lens": vector["lens"]}
    protocol.validate_hello(hello)
    assert protocol.parse_hello_lens(hello) == vector["parsed"]


@pytest.mark.parametrize("vector", VECTORS["hello_lens"]["ignored"], ids=lambda v: v["name"])
def test_malformed_hello_lens_is_ignored_not_rejected(vector):
    hello = {**VECTORS["messages"]["hello_valid"], "lens": vector["lens"]}
    protocol.validate_hello(hello)
    assert protocol.parse_hello_lens(hello) is None


@pytest.mark.parametrize("text", [
    '{"kind": "wide", "focal_mm": Infinity, "hfov_deg": 104.1}',
    '{"kind": "wide", "focal_mm": 2.2, "hfov_deg": NaN}',
    '{"kind": "wide", "focal_mm": 1e400, "hfov_deg": 104.1}',
])
def test_non_finite_hello_lens_is_ignored(text):
    # Python's json accepts these; a stored inf would make json.dumps emit invalid JSON.
    hello = {**VECTORS["messages"]["hello_valid"], "lens": json.loads(text)}
    protocol.validate_hello(hello)
    assert protocol.parse_hello_lens(hello) is None


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
    assert protocol.CLOSE_HELLO_TIMEOUT == VECTORS["close_codes"]["hello_timeout"]
    assert protocol.CLOSE_CREDENTIAL_UNKNOWN == VECTORS["close_codes"]["credential_unknown"] == 4503


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
        vector["host"], vector["port"], vector["token"], vector["source"],
        secure=vector.get("secure", False), pin=vector.get("pin"),
    )
    parsed = protocol.parse_pairing_uri(generated)
    assert parsed["host"] == vector["host"]
    assert parsed["port"] == vector["port"]
    assert parsed["token"] == vector["token"]
    assert parsed["source"] == vector["source"]
    assert parsed["pin"] == vector.get("pin")


@pytest.mark.parametrize("vector", VECTORS["pairing_uris"]["valid"], ids=lambda v: v["uri"])
def test_valid_pairing_uri_carries_its_pin(vector):
    assert protocol.parse_pairing_uri(vector["uri"])["pin"] == vector.get("pin")


def test_pin_pattern_matches_the_vector():
    assert protocol.PIN_PATTERN.pattern == VECTORS["pairing_uris"]["pin_pattern"]


@pytest.mark.parametrize("vector", VECTORS["cert_pins"]["vectors"], ids=lambda v: v["der_utf8"])
def test_cert_pin_matches_the_shared_vector(vector):
    der = vector["der_utf8"].encode("utf-8")
    assert protocol.cert_pin(der) == vector["pin"]
    # PEM_cert_to_DER_cert only strips the armour, so any bytes stand in for a certificate.
    bundle = ssl.DER_cert_to_PEM_cert(b"leaf-stand-in") + ssl.DER_cert_to_PEM_cert(der)
    assert protocol.pem_last_cert_pin(bundle) == vector["pin"]


def test_pem_without_a_certificate_is_rejected():
    with pytest.raises(ValueError, match="no PEM certificate"):
        protocol.pem_last_cert_pin("not a pem")


def test_generator_refuses_a_pin_without_tls():
    pin = VECTORS["cert_pins"]["vectors"][0]["pin"]
    with pytest.raises(protocol.PairingError) as excinfo:
        protocol.pairing_uri("h", 1, "t", "s", secure=False, pin=pin)
    assert excinfo.value.reason == "pin"


def test_receiver_hello_timeout_closes_with_try_again_later():
    """D-341 §11: the hello timer closes with 1013, which the phone always retries.

    Pre-1013 receivers closed it with 4400 "no hello"; that reason stays in the retry
    list for one release so older site PCs do not stop the camera for good.

    Transition exception, remove one release after every site runs 1013 receivers (D-341 §11)."""
    source = (Path(protocol.__file__).parent / "ingest.py").read_text(encoding="utf-8")
    assert "protocol.CLOSE_HELLO_TIMEOUT," in source
    assert 'protocol.CLOSE_BAD_PROTO, "no hello"' not in source
    assert protocol.CLOSE_HELLO_TIMEOUT == VECTORS["close_codes"]["try_again_later"] == 1013
    assert VECTORS["close_4400_reasons"]["retry"] == ["", "no hello"]


def test_4400_retry_list_is_exactly_the_transition_exception():
    """A validation message (ingest.py: str(exc)) must never be retryable, whatever words it holds."""
    reasons = VECTORS["close_4400_reasons"]
    assert set(reasons["retry"]).isdisjoint(reasons["fatal"])
    for reason in reasons["fatal"]:
        assert reason.strip().lower() not in ("", "no hello")
    for exc_text in ("receiver busy", "hello timeout", "timed out waiting for hello"):
        assert exc_text not in reasons["retry"]


def test_huge_integer_focal_length_is_ignored_not_raised():
    # Built at runtime: a 400-digit literal in the shared fixture trips the tracked-file secret scan.
    hello = json.loads('{"lens": {"kind": "wide", "focal_mm": 1%s, "hfov_deg": 104.1}}' % ("0" * 400))
    assert protocol.parse_hello_lens(hello) is None


# -- D-589 camera / camera_state ------------------------------------------------------------

CAMERA = VECTORS["camera_tuning"]


def test_camera_tuning_constants_match_the_vectors():
    assert tuple(CAMERA["ev_range"]) == protocol.CAMERA_EV_RANGE
    assert tuple(CAMERA["antibanding"]) == protocol.CAMERA_ANTIBANDING
    assert CAMERA["thermal_severe"] == protocol.THERMAL_SEVERE


def test_camera_example_round_trips_through_make_camera():
    example = VECTORS["messages"]["camera_example"]
    seq, setting = protocol.parse_camera(example)
    assert protocol.make_camera(seq, setting) == example


@pytest.mark.parametrize("vector", CAMERA["camera_valid"], ids=lambda v: v["name"])
def test_valid_camera_message_parses_and_rebuilds(vector):
    seq, setting = protocol.parse_camera(vector["message"])
    assert protocol.make_camera(seq, setting) == vector["message"]


@pytest.mark.parametrize("vector", CAMERA["camera_invalid"], ids=lambda v: v["name"])
def test_invalid_camera_message_is_rejected_with_reason(vector):
    with pytest.raises(protocol.CameraMessageError) as excinfo:
        protocol.parse_camera(vector["message"])
    assert excinfo.value.reason == vector["reason"]


def _parsed(state: protocol.CameraState) -> dict:
    return {"seq": state.seq, "applied": state.applied.as_dict(), "enabled": state.enabled,
            "ev_range": None if state.ev_range is None else list(state.ev_range),
            "exposure_us": state.exposure_us, "iso": state.iso, "thermal": state.thermal}


def test_camera_state_example_parses():
    state = protocol.parse_camera_state(VECTORS["messages"]["camera_state_example"])
    assert state.seq == VECTORS["messages"]["camera_example"]["seq"]
    assert state.applied == protocol.parse_camera(VECTORS["messages"]["camera_example"])[1]
    assert state.enabled is True and state.ev_range == (-6, 3) and state.thermal == 0


@pytest.mark.parametrize("vector", CAMERA["camera_state_valid"], ids=lambda v: v["name"])
def test_valid_camera_state_parses(vector):
    assert _parsed(protocol.parse_camera_state(vector["message"])) == vector["parsed"]


@pytest.mark.parametrize("vector", CAMERA["camera_state_invalid"], ids=lambda v: v["name"])
def test_invalid_camera_state_is_rejected_with_reason(vector):
    with pytest.raises(protocol.CameraMessageError) as excinfo:
        protocol.parse_camera_state(vector["message"])
    assert excinfo.value.reason == vector["reason"]


def test_camera_setting_fingerprint_changes_with_every_setting_key():
    base = protocol.CameraSetting(-1, True, True, 8333, "60hz")
    variants = [protocol.CameraSetting(0, True, True, 8333, "60hz"),
                protocol.CameraSetting(-1, False, True, 8333, "60hz"),
                protocol.CameraSetting(-1, True, False, 8333, "60hz"),
                protocol.CameraSetting(-1, True, True, None, "60hz"),
                protocol.CameraSetting(-1, True, True, 8333, "auto")]
    assert len({base.fingerprint(), *(v.fingerprint() for v in variants)}) == 6
