"""Freshness guards must include corpus selection rules, not just source bytes."""
import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "tools/graphify_pipeline.py"
sys.path.insert(0, str(SCRIPT.parent))
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


@pytest.fixture
def graphify_commands(monkeypatch):
    commands = []
    original = pipeline.subprocess.check_output
    monkeypatch.setattr(pipeline, "executable", lambda: "graphify-test")
    monkeypatch.setattr(pipeline.subprocess, "check_output", lambda argv, **kw:
                        "graphify 0.9.91" if argv[0] == "graphify-test" else original(argv, **kw))

    def run(binary, argv, folder, name, env):
        commands.append(argv)
        if name == "extract":
            out = folder / "graphify-out"
            (out / "cache").mkdir(parents=True)
            pipeline.save(out / "graph.json", {"nodes": [{"id": "bus", "label": "EventBus"}], "edges": []})
            pipeline.save(out / "cache/stat-index.json", {"guide.md": {}, "bus.py": {}})
            (folder / "extract.log").write_text("warning: one file was partially extracted\n")

    monkeypatch.setattr(pipeline, "run", run)
    return commands


def test_build_supports_external_repository_and_records_warnings(repo, tmp_path, graphify_commands):
    root, _ = repo
    (root / "guide.md").write_text("[Bus](bus.py)\n")
    (root / "bus.py").write_text("class EventBus: pass\n")
    output = tmp_path / "analysis"
    pipeline.build(argparse.Namespace(repository=root, scope=".", output=output, documents=True))
    run, = output.iterdir()
    record = json.loads((run / "provenance.json").read_text())
    coverage = json.loads((run / "coverage.json").read_text())
    assert record["status"] == "verified"
    assert Path(record["repository"]) == root
    assert coverage["document_links"] == 1
    assert "partially extracted" in coverage["extractor_warnings"][0]
    extract, report, *_ = graphify_commands
    assert "--code-only" in extract and "--no-cluster" in extract
    assert "--no-label" in report


@pytest.mark.parametrize("scope", ["..", ".git"])
def test_build_rejects_escaped_or_git_scopes(repo, tmp_path, scope):
    root, _ = repo
    with pytest.raises(ValueError, match="scope"):
        pipeline.build(argparse.Namespace(repository=root, scope=scope, output=tmp_path / "out", documents=False))


def test_external_build_cannot_write_inside_tool_checkout(repo):
    root, _ = repo
    with pytest.raises(ValueError, match="outside the repository"):
        pipeline.build(argparse.Namespace(repository=root, scope=".", output=SCRIPT.parent, documents=False))


def document_helper():
    spec = importlib.util.spec_from_file_location("graphify_documents", SCRIPT.with_name("graphify_documents.py"))
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    return helper


def test_documents_resolve_inline_reference_and_encoded_links(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    (root / "bus.py").write_text("class Bus: pass\n")
    (root / "a b.md").write_text("# Encoded\n")
    (root / "guide.md").write_text(
        '[Bus](bus.py) [Encoded](<a%20b.md>) [Reference][bus]\n'
        '[bus]: bus.py\n'
        '```markdown\n[Not a reference](bus.py)\n```\n'
        '[External](https://example.invalid/x) [Outside](../outside.md) [Missing](missing.md)\n'
    )
    out = tmp_path / "graphify-out"
    (out / "cache").mkdir(parents=True)
    pipeline.save(out / "cache/stat-index.json", {name: {} for name in ("bus.py", "a b.md", "guide.md")})
    graph = {"nodes": [{"id": "symbol", "label": "Bus"},
                       {"id": "bus-file", "label": "bus.py", "source_file": "bus.py", "source_location": "L1"}], "edges": []}
    coverage = document_helper().augment(graph, out, root)
    assert coverage["document_links"] == 3
    assert len(coverage["unresolved_links"]) == 1
    assert coverage["unresolved_links"][0]["target"] == "missing.md"
    assert len(graph["edges"]) == 3
    assert all(edge["confidence"] == "EXTRACTED" for edge in graph["edges"])
    assert sum(node.get("source_file") == "bus.py" for node in graph["nodes"]) == 1
    assert sum(edge["target"] == "bus-file" for edge in graph["edges"]) == 2
    assert {node["source_file"] for node in graph["nodes"] if "source_file" in node} == {
        "guide.md", "bus.py", "a b.md"}


def test_documents_require_corpus_index_and_reject_escaped_paths(tmp_path):
    helper = document_helper()
    with pytest.raises(ValueError, match="corpus index"):
        helper.augment({"nodes": [], "edges": []}, tmp_path, tmp_path)
    (tmp_path / "cache").mkdir()
    pipeline.save(tmp_path / "cache/stat-index.json", {"../outside.md": {}})
    with pytest.raises(ValueError, match="escapes"):
        helper.augment({"nodes": [], "edges": []}, tmp_path, tmp_path)


def test_query_rejects_changed_graph_before_invoking_graphify(repo, tmp_path):
    root, scope = repo
    run = tmp_path / "run"
    (run / "graphify-out").mkdir(parents=True)
    pipeline.save(run / "provenance.json", {"status": "verified", "repository": str(root), "scope": str(scope),
                                          "source": pipeline.snapshot(root, scope), "graph_sha256": "old"})
    (run / "graphify-out/graph.json").write_text("{}")
    with pytest.raises(ValueError, match="Graph hash changed"):
        pipeline.query(argparse.Namespace(run=run, question="EventBus", budget=100))
