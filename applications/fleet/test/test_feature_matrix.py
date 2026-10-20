"""Pin the app's HTTP consumers to owned, tested backend contracts."""

import ast
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


def constant_string(node, names):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return names.get(node.id)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = constant_string(node.left, names), constant_string(node.right, names)
        return left + right if left is not None and right is not None else None
    if isinstance(node, ast.JoinedStr):
        parts = [constant_string(item.value if isinstance(item, ast.FormattedValue) else item, names)
                 for item in node.values]
        return "".join(parts) if all(part is not None for part in parts) else None
    return None


def registrations(path):
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    names, found = {}, set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    value = constant_string(node.value, names)
                    if value is not None:
                        names[target.id] = value
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if (isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute)
                    and decorator.func.attr in {"get", "post", "put", "patch", "delete"}
                    and decorator.args):
                path_value = constant_string(decorator.args[0], names)
                if path_value:
                    found.add((decorator.func.attr.upper(), path_value, node.name))
    return found


def problems(document):
    errors, feature_ids, request_ids, covered, registry = [], set(), set(), set(), {}
    evidence = json.loads(MATRIX.with_name('backend_http_evidence.json').read_text(encoding='utf-8'))['requests']
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
            receipt = evidence.get(request['id'])
            if (not receipt or receipt['status'] not in request['expected_statuses']
                    or receipt['test'][0] not in request['contract_tests']
                    or not re.fullmatch('[0-9a-f]{40}', receipt['source_revision'])):
                errors.append('missing HTTP evidence')
            implementation = ROOT / request["implementation"]
            if not implementation.is_file():
                errors.append("missing backend implementation")
            else:
                if implementation not in registry:
                    registry[implementation] = registrations(implementation)
                if (request["method"], request["path"], request["handler"]) not in registry[implementation]:
                    errors.append("unregistered backend route")
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
            if flow["sample_status"] != "verified":
                errors.append("invalid sample status")
            if flow["sample_status"] == "verified" and not (ROOT / flow["browser_test"].split("::")[0]).is_file():
                errors.append("missing sample test")
    for feature in document["features"]:
        for flow in feature['flows']:
            if not set(identifier for step in flow['steps'] for identifier in step['request_ids']).issubset(request_ids):
                errors.append('broken scenario request reference')
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
    ("route", "unregistered backend route"),
    ("receipt", "missing HTTP evidence"),
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
    elif mutation == "route":
        feature["requests"][0]["path"] = "/api/fleet/not-implemented"
    elif mutation == 'receipt':
        feature['requests'][0]['expected_statuses'] = [599]
    else:
        feature["calls"][0]["request_ids"] = []
    assert expected in problems(matrix)
