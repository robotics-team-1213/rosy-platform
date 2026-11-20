"""D-436 addendum 2026-11-09 ("더 잘게 나누고 정말 필요할때만 하는걸로 결정해"): FULL only for unknown reach.

A safety path and the code that selects or runs tests stay FULL (panel 2026-11-09); another landing tool runs the
selector self-test tier, a foundation or nested conftest its import-graph or folder scope. ``ROSY_FULL_LEGACY=1``
restores FULL for every trigger. The legacy rules themselves stay pinned in test_affected_tests.py.
"""

from __future__ import annotations

import re

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
         "tools/land_room.py": "SLOTS = 2\n",
         "test/test_land_room_flow.py": "import land_room\n\n\ndef test_room():\n    pass\n",
         "test/test_land_sample.py": "def test_land():\n    pass\n",
         "test/test_remote_pytest.py": "def test_remote():\n    pass\n",
         "deploy/requirements.txt": "pyyaml==6.0\n",
         "tools/publish_main.py": "TASK = 'register_publish_merge_task.ps1'\n",
         "tools/register_publish_merge_task.ps1": "Write-Host hi\n",
         "test/test_publish_main_sample.py": "import publish_main\n\n\ndef test_p():\n    pass\n",
         "operations/world/test/test_w.py": "def test_w():\n    pass\n",
         "middleware/media/test/test_m.py": "def test_m():\n    pass\n",
         "contracts/foundation/test/test_f.py": "def test_f():\n    pass\n"}


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
def test_a_safety_path_runs_its_safety_capsule_and_keeps_legacy_escape(sample, monkeypatch, path):
    """D-1052 Zero-FULL: safety paths run full owning+reverse+app capsule by default; ROSY_FULL_LEGACY=1 restores FULL."""
    sel = _select(sample, path)
    assert sel.mode == "affected" and not sel.escalations, sel.escalations
    assert any(e.endswith(affected.SAFETY_TRIGGER) for e in sel.narrowed)
    assert "test/architecture" in sel.reasons
    monkeypatch.setenv("ROSY_FULL_LEGACY", "1")
    legacy = _select(sample, path)
    assert legacy.mode == "full" and any(e.endswith(affected.SAFETY_TRIGGER) for e in legacy.escalations)


@pytest.mark.parametrize("path", ["tools/harness/affected_tests.py", "tools/harness/affected_narrow.py",
                                  "tools/land_selection.py", "test/known_failures.py", "test/browser_scope.py"])
def test_the_code_that_selects_or_judges_tests_runs_harness_capsule(sample, monkeypatch, path):
    """D-1052 Zero-FULL: selector/judge changes run SELF_TEST + test/architecture + CANARY without FULL."""
    sel = _select(sample, path)
    assert sel.mode == "affected" and not sel.escalations, sel.escalations
    assert {"test/test_land_sample.py", "test/architecture", *affected.affected_narrow.CANARY} <= set(sel.reasons)
    monkeypatch.setenv("ROSY_FULL_LEGACY", "1")
    assert _select(sample, path).mode == "full"


@pytest.mark.parametrize("path", ["tools/land_browser.py", "tools/remote/remote_pytest.py", "tools/remote/remote_job.py",
                                  "tools/remote/work_queue.py", "tools/remote/remote_test_tools.py",
                                  "tools/remote/xdist_plan.py"])
def test_a_runner_tool_runs_the_self_test_tier_plus_the_canary(sample, path):
    """2026-11-17 panel: 34 of 55 FULL landings only touched a tool that runs tests."""
    sel = _select(sample, path)
    assert sel.mode == "affected" and not sel.escalations, sel.escalations
    assert {"test/test_land_sample.py", "test/architecture", *affected.affected_narrow.CANARY} <= set(sel.reasons)
    assert "test" not in sel.reasons


def test_a_runner_tool_keeps_the_legacy_escape(sample, monkeypatch):
    monkeypatch.setenv("ROSY_FULL_LEGACY", "1")
    assert _select(sample, "tools/remote/work_queue.py").mode == "full"


def test_a_script_no_test_names_selects_the_tests_of_the_source_naming_it(sample):
    sel = _select(sample, "tools/register_publish_merge_task.ps1")
    assert sel.mode == "affected" and not sel.unmapped, sel.escalations
    assert "test/test_publish_main_sample.py" in sel.reasons
    assert "register_publish_merge_task.ps1" in " ".join(sel.reasons["test/test_publish_main_sample.py"])


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
    assert "contracts/foundation/test" in sel.reasons
    # D-1037 addendum 1: the reverse dependent's suite narrows to the files whose closure reaches the change
    assert "middleware/perception/test/test_battery.py" in sel.reasons, sel.reasons


@pytest.mark.parametrize("path,scope", [("middleware/core/gateway/test/conftest.py", "middleware/core/gateway/test"),
                                        (".github/workflows/ci.yml", None)])
def test_a_nested_conftest_or_workflow_is_narrowed(sample, path, scope):
    sel = _select(sample, path)
    assert sel.mode == "affected" and not sel.unmapped, sel.escalations
    assert scope is None or scope in sel.reasons


@pytest.mark.parametrize("path", ["conftest.py", "deploy/requirements.txt", "tools/mystery/run.sh",
                                  "deploy/site/compose.yaml", "tools/harness/harness.yaml",
                                  "tools/harness/platform_parts.yaml", "tools/mystery/pyproject.toml"])
def test_formerly_full_triggers_run_scoped_capsules_and_keep_legacy_escape(sample, monkeypatch, path):
    sel = _select(sample, path)
    assert sel.mode == "affected" and not sel.escalations, sel.escalations
    assert sel.narrowed
    assert "test/architecture" in sel.reasons and set(affected.affected_narrow.CANARY) <= set(sel.reasons)
    monkeypatch.setenv("ROSY_FULL_LEGACY", "1")
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


GATE_IMPORT = re.compile(r"^\s*(?:import|from)\s+(land\w*|remote_pytest|remote_job|remote_test_tools|work_queue"
                         r"|xdist_plan|host_probe|host_caps|lab_hosts|memory_history|affected_\w+|known_failures"
                         r"|browser_scope|publish_main|publish_evidence|pr_land)\b", re.M)


def test_every_root_test_of_a_gate_tool_is_in_the_self_test_tier():
    """A gate tool's own test whose name the SELF_TEST pattern misses would silently leave the narrowed tier."""
    missed = [t.relative_to(base.ROOT).as_posix() for t in sorted((base.ROOT / "test").glob("test_*.py"))
              if GATE_IMPORT.search(t.read_text(encoding="utf-8", errors="replace"))
              and not affected.affected_narrow.SELF_TEST.match(t.relative_to(base.ROOT).as_posix())]
    assert not missed, missed


def test_pack_splits_large_non_serial_capsules_for_parallel_runners(tmp_path):
    """Capsules above MAX_GROUP_PATHS shard across lab PCs and CI runners instead of one serial queue."""
    import affected_pack

    class FakeRepo:
        root = tmp_path

        @staticmethod
        def test_import_names(path):
            return {path: path}

    cap = affected_pack.MAX_GROUP_PATHS
    groups = affected.pack(FakeRepo(), [f"test/test_cap_{i}.py" for i in range(cap + 5)])
    assert len(groups) == 2
    assert all(len(group) <= cap for group in groups)

def test_a_leaf_gate_tool_runs_its_readers_not_the_whole_self_test_tier(sample):
    """aff-narrow: tools/land_room.py is read by one test; the 85-file land/remote tier stays for unread tools."""
    sel = _select(sample, "tools/land_room.py")
    assert sel.mode == "affected" and not sel.escalations
    assert {"test/test_land_room_flow.py", "test/architecture", "test/test_harness_contracts.py"} <= set(sel.reasons)
    assert not {"test/test_land_sample.py", "test/test_remote_pytest.py"} & set(sel.reasons)


def test_a_leaf_gate_tool_keeps_the_legacy_escape(sample, monkeypatch):
    monkeypatch.setenv("ROSY_FULL_LEGACY", "1")
    assert _select(sample, "tools/land_room.py").mode == "full"


def _jobs(sample, *changed):
    sel = _select(sample, *changed)
    return [e["name"] for e in affected.ci_matrix(affected.Repo.load(sample), sel)["include"]]


def test_a_docs_only_change_skips_build_smoke_but_keeps_the_document_readers(sample):
    sel = _select(sample, "docs/adr/D-1-sample.md")
    assert "build-smoke" not in _jobs(sample, "docs/adr/D-1-sample.md")
    assert "test/test_harness_contracts.py" in sel.reasons and "test/architecture/test_document_placement.py" in sel.reasons


@pytest.mark.parametrize("changed", [["docs/adr/D-1-sample.md", "tools/land_room.py"], ["deploy/requirements.txt"],
                                     ["docs/notes.txt"]])
def test_a_change_with_anything_but_documents_keeps_build_smoke(sample, changed):
    assert "build-smoke" in _jobs(sample, *changed)
