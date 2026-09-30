"""D-391 1 and 4.1: site-link records, failure classes and device kinds follow the shared vectors."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core_common.protocol import device_kind, failure_class, site_link

FIXTURES = Path(__file__).resolve().parents[4] / "test/fixtures/protocol"
FAILURES = json.loads((FIXTURES / "failure-classes.v1.json").read_text(encoding="utf-8"))
SITE_LINK = json.loads((FIXTURES / "site-link.v1.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", FAILURES["cases"], ids=lambda case: case["id"])
def test_failure_class_matches_vector(case):
    assert failure_class.classify(**case["input"]) == case["expect"]


def test_failure_class_vocabulary_is_the_vector_vocabulary():
    assert tuple(FAILURES["classes"]) == failure_class.CLASSES


def test_4400_retry_reasons_are_the_vector_list():
    assert tuple(FAILURES["close_4400_retry_reasons"]) == failure_class.CLOSE_4400_RETRY_REASONS


def test_4400_retry_reasons_match_the_ingest_protocol_vector():
    ingest = json.loads((FIXTURES / "overhead-ingest.v1.json").read_text(encoding="utf-8"))
    assert list(FAILURES["close_4400_retry_reasons"]) == ingest["close_4400_reasons"]["retry"]


@pytest.mark.parametrize("kwargs", [
    {},
    {"ws_close": 4401, "http_status": 401},
    {"http_status": 401, "reason": "x"},
    {"transport": "carrier_pigeon"},
    {"discovery": "maybe"},
])
def test_classify_rejects_ambiguous_or_unknown_input(kwargs):
    with pytest.raises(ValueError):
        failure_class.classify(**kwargs)


@pytest.mark.parametrize("case", SITE_LINK["cases"], ids=lambda case: case["id"])
def test_site_link_validation_matches_vector(case):
    expect = case["expect"]
    assert site_link.validate(case["record"]) == (None if expect["valid"] else expect["reason"])


def test_site_link_reason_vocabulary_is_the_vector_vocabulary():
    assert tuple(SITE_LINK["reasons"]) == site_link.REASONS


def test_site_link_roles_are_the_device_kinds():
    assert tuple(SITE_LINK["roles"]) == device_kind.ALL


def test_non_object_record_is_rejected():
    assert site_link.validate(["not", "a", "record"]) == "bad_value"


def test_device_kind_values():
    assert device_kind.OVERHEAD_CAMERA == "overhead-camera"
    assert device_kind.ROBOT == "robot"
    assert device_kind.ALL == (device_kind.OVERHEAD_CAMERA, device_kind.ROBOT)
