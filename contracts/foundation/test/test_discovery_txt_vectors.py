"""D-370 5.1: the canonical Python TXT classifier follows the shared vectors."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core_common.protocol.discovery_txt import (
    REASONS, Accepted, Rejected, classify, parse_txt_pairs,
)

VECTORS = Path(__file__).resolve().parents[3] / "test/fixtures/protocol/discovery-txt.v1.json"
DATA = json.loads(VECTORS.read_text(encoding="utf-8"))


def _pairs(items: list[str]) -> list[tuple[str, str]]:
    return [tuple(item.split("=", 1)) for item in items]


@pytest.mark.parametrize("case", DATA["cases"], ids=lambda case: case["id"])
def test_classification_matches_vector(case):
    result = classify(case["service_type"], case["host"], case["address"], case["port"],
                      _pairs(case["txt"]))
    expect = case["expect"]
    if expect["accepted"]:
        assert isinstance(result, Accepted), result
        assert result.legacy is expect["legacy"]
    else:
        assert result == Rejected(expect["reason"])


def test_reason_vocabulary_is_the_vector_vocabulary():
    assert tuple(DATA["reasons"]) == REASONS


def test_avahi_txt_column_parses_to_ordered_pairs_keeping_duplicates():
    assert parse_txt_pairs('"product=rosy" "role=robot" "role=robot" "flag" "a=b=c"') == [
        ("product", "rosy"), ("role", "robot"), ("role", "robot"), ("a", "b=c"),
    ]
    assert parse_txt_pairs('"unterminated') == []


def test_accepted_record_exposes_txt_and_normalised_service_type():
    result = classify("_rosy-fleet._tcp.local.", "Fleet-A.local.", "192.168.1.20", 8443,
                      [("product", "rosy"), ("role", "fleet"), ("proto", "site-v1"),
                       ("tls", "required"), ("extra", "x")])
    assert result == Accepted(service_type="_rosy-fleet._tcp", host="fleet-a.local",
                              txt={"product": "rosy", "role": "fleet", "proto": "site-v1",
                                   "tls": "required", "extra": "x"}, legacy=False)
