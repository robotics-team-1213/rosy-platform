"""Freshness guards must include corpus selection rules, not just source bytes."""
import argparse
import importlib.util
import json
from pathlib import Path
import subprocess

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "tools/graphify_pipeline.py"
spec = importlib.util.spec_from_file_location("graphify_pipeline", SCRIPT)
pipeline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pipeline)


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    scope = root / "middleware/core/events"
    scope.mkdir(parents=True)
    (scope / "bus.py").write_text("class EventBus: pass\n")
    for args in (("init",), ("add", "."),
                 ("-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                  "commit", "-m", "fixture")):
        subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)
    return root, scope


def test_ancestor_graphifyignore_invalidates_snapshot(repo):
    root, scope = repo
    before = pipeline.snapshot(root, scope)
    (root / ".graphifyignore").write_text("/middleware/core/events/\n")
    after = pipeline.snapshot(root, scope)
    assert before["files"] == after["files"]
    assert before != after


def test_untracked_and_modified_source_change_snapshot(repo):
    root, scope = repo
    before = pipeline.snapshot(root, scope)
    (scope / "bus.py").write_text("class ChangedBus: pass\n")
    changed = pipeline.snapshot(root, scope)
    assert before != changed
    (scope / "new.py").write_text("value = 1\n")
    assert changed != pipeline.snapshot(root, scope)


def test_query_rejects_changed_selection_before_invoking_graphify(repo, tmp_path):
    root, scope = repo
    run = tmp_path / "run"
    run.mkdir()
    (run / "provenance.json").write_text(json.dumps({
        "status": "verified", "repository": str(root), "scope": str(scope),
        "source": pipeline.snapshot(root, scope),
    }))
    (root / ".graphifyignore").write_text("events/\n")
    with pytest.raises(ValueError, match="stale"):
        pipeline.query(argparse.Namespace(run=run, question="EventBus", budget=100))


def test_build_refuses_repository_output_before_resolving_graphify():
    with pytest.raises(ValueError, match="outside the repository"):
        pipeline.build(argparse.Namespace(scope="middleware/core/events", output=SCRIPT.parent))
