"""D-1036 addendum (2026-11-18): app-only deltas publish on their own app's evidence; core, safety and FULL deltas keep FULL."""

import json

import pytest
import yaml

from test_publish_main import _commit, _git, repo, tool  # noqa: F401  (repo is a fixture; puts tools/ on sys.path)
import land_cache
import land_mainred
import publish_evidence

PARTS = {"apps": ["site-fleet", "account", "pinky", "core"], "safety_modules": [], "roots": [
    {"path": "operations/fleet", "app": "site-fleet"},
    {"path": "operations/account", "app": "account"},
    {"path": "middleware/drive", "app": "pinky", "concern": "safety"}]}
PLAN = [["operations/fleet/test"]]


@pytest.fixture
def scoped(repo, monkeypatch):
    local, _ = repo
    _commit(local, tool.publish_scope.PARTS, yaml.safe_dump(PARTS))
    _git(local, "push", "-q", "origin", "main")
    _git(local, "fetch", "-q", "origin")
    calls = []

    def describe(publish, repo_, sha, base, invocations, rows, ancestors=(), scoped=False):
        calls.append(scoped)
        return {"plan": PLAN, "env": "e", "clean": [True] * len(rows), "reach": {},
                "variants": {json.dumps(inv): [[inv]] for inv in PLAN}}

    monkeypatch.setattr(publish_evidence, "describe", describe)
    return local, calls


def _evidence(local, sha):
    log = local / ".git" / "scope.log"
    log.write_text("1 passed in 0.01s\n", encoding="utf-8")
    tree = _git(local, "rev-parse", f"{sha}^{{tree}}")
    land_cache.record(local, sha, tree, "e", PLAN[0], log)


def _red(local, nodeid):
    land_mainred.write(local, "red", id=nodeid, main=_git(local, "rev-parse", "HEAD"), env=[])


def test_app_only_delta_is_proven_by_its_affected_plan_not_a_full_record(scoped):
    local, calls = scoped
    sha = _commit(local, "operations/fleet/fleet/a.py", "1")
    _evidence(local, sha)
    ok, line = tool.publish_scope.check(tool, local, sha)
    assert ok and calls == [True]
    assert line == f"{sha[:10]} apps=site-fleet mode=app required=1 evidenced=1"
    assert tool.publish_sha(local) == sha and tool.SCOPE[sha] == line


def test_app_delta_without_its_clean_rows_is_not_published(scoped):
    local, _ = scoped
    sha = _commit(local, "operations/fleet/fleet/a.py", "1")
    assert not tool.publish_scope.check(tool, local, sha)[0] and tool.publish_sha(local) is None


def test_a_core_delta_keeps_the_full_rule(scoped):
    local, calls = scoped
    sha = _commit(local, "operations/fleet/fleet/a.py", "1")
    sha = _commit(local, "README.md", "core file")  # a path no root covers is core
    ok, line = tool.publish_scope.check(tool, local, sha)
    assert not ok and "mode=full (touches core)" in line and "apps=core,site-fleet" in line and calls == []


def test_a_safety_path_keeps_the_full_rule(scoped):
    local, calls = scoped
    sha = _commit(local, "middleware/drive/x.py", "1")
    ok, line = tool.publish_scope.check(tool, local, sha)
    assert not ok and "mode=full (safety path middleware/drive/x.py)" in line and calls == []


def test_a_selector_escalation_keeps_the_full_rule(scoped, monkeypatch):
    local, _ = scoped
    monkeypatch.setattr(publish_evidence, "describe", lambda *a, **k: {"escalated": ["pytest conftest"]})
    sha = _commit(local, "operations/fleet/fleet/a.py", "1")
    _evidence(local, sha)
    ok, line = tool.publish_scope.check(tool, local, sha)
    assert not ok and line.startswith(f"{sha[:10]} apps=site-fleet mode=full")


def test_a_red_nightly_in_another_app_does_not_block(scoped):
    local, _ = scoped
    sha = _commit(local, "operations/fleet/fleet/a.py", "1")
    _evidence(local, sha)
    _red(local, "operations/account/test/test_a.py::test_x")
    assert tool.publish_scope.check(tool, local, sha)[0]


@pytest.mark.parametrize("nodeid", ["operations/fleet/test/test_b.py::test_y",
                                    "tools/collect_alone.py::test_runs_alone[operations/fleet/test/test_b.py]"])
def test_a_red_nightly_in_a_touched_app_blocks(scoped, nodeid):
    local, calls = scoped
    sha = _commit(local, "operations/fleet/fleet/a.py", "1")
    _evidence(local, sha)
    _red(local, nodeid)
    ok, line = tool.publish_scope.check(tool, local, sha)
    assert not ok and "blocked by red nightly/main-red in a touched app (site-fleet:" in line and calls == []
