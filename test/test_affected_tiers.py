"""D-436 addendum 2026-11-09 ("더 잘게 나누고 정말 필요할때만 하는걸로 결정해"): FULL only for unknown reach.

A safety path runs the safety tier (every safety-tagged suite plus its own dependents), a landing/selector tool the
selector self-test tier, a foundation or nested conftest its import-graph or folder scope. ``ROSY_FULL_LEGACY=1``
restores FULL for every trigger. The legacy rules themselves stay pinned in test_affected_tests.py.
"""

from __future__ import annotations

import pytest

import affected_tests as affected
import test_affected_tests as base

PARTS = base.PARTS_YAML + """\
  - path: middleware/drive/motion_limits
    concern: safety
safety_modules: [middleware/core/gateway/core/node.py]
"""
FILES = {**base.FILES, "tools/harness/platform_parts.yaml": PARTS,
         "middleware/drive/motion_limits/limits.py": "MAX = 1\n",
         "middleware/drive/motion_limits/test/test_limits.py": "def test_max():\n    pass\n",
         "tools/land_prepare.py": "MAX_PREPARING = 6\n",
         "test/test_land_sample.py": "def test_land():\n    pass\n",
         "test/test_remote_pytest.py": "def test_remote():\n    pass\n",
         "deploy/requirements.txt": "pyyaml==6.0\n"}
SAFETY_SUITES = {"middleware/core/gateway/test", "middleware/drive/motion_limits/test/test_limits.py"}


@pytest.fixture(scope="module")
def sample(tmp_path_factory):
    repo = tmp_path_factory.mktemp("tiers")
    base._git(repo, "init", "-q", "-b", "main")
    base._git(repo, "config", "user.email", "t@example.invalid")
    base._git(repo, "config", "user.name", "t")
    for rel, text in FILES.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text, encoding="utf-8")
    base._git(repo, "add", "-A")
    base._git(repo, "commit", "-q", "-m", "base")
    return repo


@pytest.fixture(autouse=True)
def _new_rule(monkeypatch):
    monkeypatch.delenv("ROSY_FULL_LEGACY", raising=False)


def _select(sample, *changed):
    return affected.select(affected.Repo.load(sample), list(changed))


@pytest.mark.parametrize("path", ["middleware/core/gateway/core/node.py", "middleware/drive/motion_limits/limits.py"])
def test_a_safety_path_runs_every_safety_suite_and_its_dependents_not_full(sample, path, monkeypatch):
    sel = _select(sample, path)
    assert sel.mode == "affected", sel.escalations
    assert any(e.endswith(affected.SAFETY_TRIGGER) for e in sel.escalations), "rollup/speculation keep it apart"
    assert SAFETY_SUITES <= set(sel.reasons), sel.reasons
    assert "test/architecture" in sel.reasons
    if path.endswith("node.py"):  # its own reverse dependent (core_api_web imports core)
        assert "middleware/core/api/test" in sel.reasons
    monkeypatch.setenv("ROSY_FULL_LEGACY", "1")
    assert _select(sample, path).mode == "full", "the revert switch restores FULL"


def test_a_gate_tool_runs_the_selector_self_test_tier(sample):
    sel = _select(sample, "tools/land_prepare.py")
    assert sel.mode == "affected" and not sel.escalations
    assert sel.narrowed == ["tools/land_prepare.py: harness configuration or the selector itself"]
    assert {"test/test_land_sample.py", "test/test_remote_pytest.py", "test/test_harness_contracts.py",
            "test/architecture"} <= set(sel.reasons)
    assert "test/test_unrelated.py" not in sel.reasons and "test" not in sel.reasons


def test_a_docs_only_change_selects_nothing_heavy(sample):
    sel = _select(sample, "docs/adr/D-1-sample.md")
    assert sel.mode == "affected" and not sel.escalations and not sel.narrowed
    heavy = {"test", "middleware/core/gateway/test", "middleware/perception/test", "contracts/foundation/test"}
    assert not heavy & set(sel.reasons), sel.reasons


def test_a_foundation_runtime_change_runs_its_import_graph_dependents(sample):
    sel = _select(sample, "contracts/foundation/core_common/power.py")
    assert sel.mode == "affected", sel.escalations
    assert {"contracts/foundation/test", "middleware/perception/test"} <= set(sel.reasons)


@pytest.mark.parametrize("path,scope", [("middleware/core/gateway/test/conftest.py", "middleware/core/gateway/test"),
                                        (".github/workflows/ci.yml", None)])
def test_a_nested_conftest_or_workflow_is_narrowed(sample, path, scope):
    sel = _select(sample, path)
    assert sel.mode == "affected" and not sel.unmapped, sel.escalations
    assert scope is None or scope in sel.reasons


@pytest.mark.parametrize("path", ["conftest.py", "deploy/requirements.txt", "tools/mystery/run.sh",
                                  "deploy/site/compose.yaml", "tools/harness/harness.yaml",
                                  "tools/harness/platform_parts.yaml", "tools/mystery/pyproject.toml"])
def test_unknown_reach_still_escalates_to_full(sample, path):
    assert _select(sample, path).mode == "full"


def test_the_lab_full_plan_runs_every_path_once():
    """2026-11-09: CI's separate runners put four files a folder invocation also collects into the lab FULL twice."""
    repo = affected.Repo.load(base.ROOT)
    plan = affected.lab_full_invocations(repo)
    plain = [inv for inv in plan if not any(w.startswith("ROSY_") for w in inv)]
    paths = [w for inv in plain for w in inv if not w.startswith("-")]
    assert len(paths) == len(set(paths))
    nested = [(a, b) for a in paths for b in paths if a != b and a.startswith(b.rstrip("/") + "/")
              and not any(f"--ignore={a}" in inv for inv in plain if b in inv)]
    assert not nested, nested
    assert affected.affected_exclusive.canonical_full(plan)
