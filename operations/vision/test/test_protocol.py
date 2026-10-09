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

CAMERA_EXAMPLE = VECTORS["messages"]["camera_example"]
STATE_EXAMPLE = VECTORS["messages"]["camera_state_example"]


def _with(message: dict, path: str, value) -> dict:
    """A deep copy of ``message`` with the dotted ``path`` set (or removed for _MISSING)."""
    copy = json.loads(json.dumps(message))
    *parents, key = path.split(".")
    target = copy
    for name in parents:
        target = target[name]
    if value is _MISSING:
        del target[key]
    else:
        target[key] = value
    return copy


_MISSING = object()


def test_camera_example_round_trips_through_make_camera():
    seq, setting = protocol.parse_camera(CAMERA_EXAMPLE)
    assert protocol.make_camera(seq, setting) == CAMERA_EXAMPLE


def test_camera_extra_keys_are_ignored():
    assert protocol.parse_camera({**CAMERA_EXAMPLE, "future": 1}) == protocol.parse_camera(CAMERA_EXAMPLE)


@pytest.mark.parametrize("path,value,reason", [
    ("seq", -1, "seq"), ("seq", True, "seq"), ("ev", 1.5, "ev"), ("ev", "1", "ev"),
    ("ae_lock", 1, "ae_lock"), ("awb_lock", None, "awb_lock"),
    ("max_exposure_us", 0, "max_exposure_us"), ("max_exposure_us", _MISSING, "max_exposure_us"),
    ("antibanding", "50hz", "antibanding"), ("type", "status", "type"),
])
def test_invalid_camera_message_is_rejected(path, value, reason):
    with pytest.raises(protocol.CameraMessageError) as excinfo:
        protocol.parse_camera(_with(CAMERA_EXAMPLE, path, value))
    assert excinfo.value.reason == reason


def test_camera_state_example_parses():
    state = protocol.parse_camera_state(STATE_EXAMPLE)
    assert state.seq == CAMERA_EXAMPLE["seq"]
    assert state.applied == protocol.CameraSetting(-1, True, True, 33333, "60hz")
    assert state.mode == "vision"
    assert (state.ev_min, state.ev_max, state.ev_step) == (-20, 20, 0.1)
    assert (state.exposure_us, state.iso, state.thermal) == (16000, 200, 0)


@pytest.mark.parametrize("path,value", [
    ("applied.mode", "local"), ("applied.mode", "disabled"), ("applied.mode", "thermal_hold"),
    ("thermal", -1), ("exposure_us", None), ("iso", None), ("supported.max_exposure_us", None),
    ("supported.ev_step", 0), ("future", {"x": 1}),
])
def test_camera_state_variants_parse(path, value):
    state = protocol.parse_camera_state(_with(STATE_EXAMPLE, path, value))
    assert state.seq == STATE_EXAMPLE["seq"]


@pytest.mark.parametrize("path,value,reason", [
    ("seq", -1, "seq"), ("applied", _MISSING, "applied"), ("applied.ev", 0.5, "ev"),
    ("applied.mode", "auto", "mode"), ("applied.mode", _MISSING, "mode"),
    ("applied.max_exposure_us", _MISSING, "max_exposure_us"),
    ("supported", _MISSING, "supported"), ("supported.ev_step", -0.1, "supported"),
    ("supported.ev_step", True, "supported"), ("supported.ev_min", 30, "supported"),
    ("supported.antibanding_60hz", 1, "supported"), ("supported.max_exposure_us", 0, "supported"),
    ("exposure_us", _MISSING, "exposure_us"), ("iso", -1, "iso"), ("iso", 1.5, "iso"),
    ("thermal", None, "thermal"), ("thermal", 7, "thermal"), ("thermal", -2, "thermal"),
    ("type", "camera", "type"),
])
def test_invalid_camera_state_is_rejected(path, value, reason):
    with pytest.raises(protocol.CameraMessageError) as excinfo:
        protocol.parse_camera_state(_with(STATE_EXAMPLE, path, value))
    assert excinfo.value.reason == reason


def test_camera_setting_fingerprint_changes_with_every_setting_key():
    base = protocol.CameraSetting(-1, True, True, 33333, "60hz")
    variants = [protocol.CameraSetting(0, True, True, 33333, "60hz"),
                protocol.CameraSetting(-1, False, True, 33333, "60hz"),
                protocol.CameraSetting(-1, True, False, 33333, "60hz"),
                protocol.CameraSetting(-1, True, True, None, "60hz"),
                protocol.CameraSetting(-1, True, True, 33333, "auto")]
    assert len({base.fingerprint(), *(v.fingerprint() for v in variants)}) == 6
