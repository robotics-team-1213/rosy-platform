"""D-370 5.1: the TXT vectors and the human profile table say the same thing."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VECTORS = ROOT / "test/fixtures/protocol/discovery-txt.v1.json"
PROFILE = ROOT / "docs/reference/site-lan-discovery-profile.md"
COMMON_KEYS = ("product", "role", "proto", "tls")


def _profile_table() -> dict[str, dict[str, str]]:
    """Return {column header: {key: value}} from the TXT key table."""
    lines = PROFILE.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("| 키 |"))
    # Headers read "로봇 값", "Fleet 값", ...; the vectors name the column without "값".
    header = [cell.strip().removesuffix(" 값") for cell in lines[start].strip("|").split("|")]
    table: dict[str, dict[str, str]] = {name: {} for name in header[2:]}
    for line in lines[start + 2:]:
        if not line.startswith("|"):
            break
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        key = cells[0].strip("`")
        for name, cell in zip(header[2:], cells[2:]):
            token = re.match(r"`([^`]+)`", cell)
            table[name][key] = token.group(1) if token else ""
    return table


def test_every_service_type_matches_the_profile_column():
    vectors = json.loads(VECTORS.read_text(encoding="utf-8"))
    table = _profile_table()
    assert len(vectors["profile"]) == 5
    for service_type, profile in vectors["profile"].items():
        column = table[profile["role_column"]]
        assert {key: column[key] for key in COMMON_KEYS} == profile["required"], service_type
        assert f"`{service_type}.local`" in PROFILE.read_text(encoding="utf-8")


def test_vectors_cover_every_reason_and_every_service_type():
    vectors = json.loads(VECTORS.read_text(encoding="utf-8"))
    seen_reasons = {case["expect"].get("reason") for case in vectors["cases"]} - {None}
    assert seen_reasons == set(vectors["reasons"])
    accepted_types = {case["service_type"] for case in vectors["cases"]
                      if case["expect"]["accepted"]}
    assert accepted_types == set(vectors["profile"])
    assert any(case["expect"].get("legacy") for case in vectors["cases"])
    ids = [case["id"] for case in vectors["cases"]]
    assert len(ids) == len(set(ids))
