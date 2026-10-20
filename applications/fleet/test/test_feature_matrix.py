"""Pin the app's HTTP consumers to owned, tested backend contracts."""

import copy
import json
from pathlib import Path
import re

import pytest


ROOT = Path(__file__).resolve().parents[3]
WEB = ROOT / "applications/fleet/web"
MATRIX = Path(__file__).with_name("feature_matrix.json")
HTTP_LITERAL = re.compile(r'''["'`](/api/fleet/[^"'`\n]+)["'`]''')


def load_matrix():
    assert MATRIX.is_file(), "Fleet frontend feature/API matrix is missing"
    return json.loads(MATRIX.read_text(encoding="utf-8"))


def problems(document):
    errors, feature_ids, request_ids, covered = [], set(), set(), set()
    for feature in document["features"]:
        if feature["id"] in feature_ids:
            errors.append("duplicate feature")
        feature_ids.add(feature["id"])
        for path in feature["entrypoints"] + feature["consumers"]:
            if not (ROOT / path).is_file():
                errors.append(f"missing source: {path}")
        for call in feature["calls"]:
            covered.add((call["consumer"], call["expression"]))
            if not call["request_ids"]:
                errors.append("unbound frontend call")
        for request in feature["requests"]:
            if request["id"] in request_ids:
                errors.append("duplicate request")
            request_ids.add(request["id"])
            if request["status"] != "verified":
                errors.append("unverified contract")
            implementation = ROOT / request["implementation"]
            if not implementation.is_file():
                errors.append("missing backend implementation")
            elif request["handler"] not in implementation.read_text(encoding="utf-8"):
                errors.append("missing backend handler")
            if not request["contract_tests"] or any(
                not (ROOT / path).is_file() for path in request["contract_tests"]
            ):
                errors.append("missing backend contract test")
            if not request["expected_statuses"]:
                errors.append("missing response status")
        if not {"happy", "refused", "terminal"}.issubset({flow["kind"] for flow in feature["flows"]}):
            errors.append("missing representative flow")
        for flow in feature["flows"]:
            if not flow["steps"] or not flow["scenario_id"] or not flow["browser_test"]:
                errors.append("missing scenario evidence target")
            if flow["sample_status"] not in {"planned", "verified"}:
                errors.append("invalid sample status")
            if flow["sample_status"] == "verified" and not (ROOT / flow["browser_test"].split("::")[0]).is_file():
                errors.append("missing sample test")
    for feature in document["features"]:
        for call in feature["calls"]:
            if not set(call["request_ids"]).issubset(request_ids):
                errors.append("broken request reference")
    for path in WEB.rglob("*.js"):
        for match in HTTP_LITERAL.finditer(path.read_text(encoding="utf-8")):
            if (path.relative_to(ROOT).as_posix(), match.group(1)) not in covered:
                errors.append(f"unregistered frontend call: {path.name}: {match.group(1)}")
    actual_pages = {path.relative_to(ROOT).as_posix() for path in WEB.rglob("*.html")}
    pages = {path for feature in document["features"] for path in feature["entrypoints"]}
    if pages != actual_pages:
        errors.append("unregistered page")
    return errors


def test_all_supported_features_have_contracts_and_flows():
    assert problems(load_matrix()) == []


@pytest.mark.parametrize("mutation, expected", [
    ("backend", "missing backend implementation"),
    ("verification", "unverified contract"),
    ("flow", "missing representative flow"),
    ("call", "unbound frontend call"),
])
def test_incomplete_or_stale_contracts_are_rejected(mutation, expected):
    matrix = copy.deepcopy(load_matrix())
    feature = next(feature for feature in matrix["features"] if feature["calls"] and feature["requests"])
    if mutation == "backend":
        feature["requests"][0]["implementation"] = "missing/backend.py"
    elif mutation == "verification":
        feature["requests"][0]["status"] = "unverified"
    elif mutation == "flow":
        feature["flows"] = []
    else:
        feature["calls"][0]["request_ids"] = []
    assert expected in problems(matrix)
