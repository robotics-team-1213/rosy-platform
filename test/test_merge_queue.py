"""Contract tests for tools/merge_queue.py (#258)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("merge_queue", ROOT / "tools" / "merge_queue.py")
merge_queue = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = merge_queue
SPEC.loader.exec_module(merge_queue)

ENTRY = {
    "position": 2,
    "state": "AWAITING_CHECKS",
    "enqueuedAt": "2026-11-20T01:02:03Z",
    "pullRequest": {"number": 42, "title": "feat: sample", "body": "summary\n\nSession: opencode-1\n"},
}


def fake_run_gh(monkeypatch, data):
    calls = []

    def fake(repo, *args):
        calls.append(args)
        if args[:3] == ("repo", "view", "--json"):
            return "robotics-team-1213/rosy-platform\n"  # real gh -q output ends with a newline
        if args[:2] == ("api", "graphql"):
            return json.dumps({"data": data(args)})
        raise AssertionError(args)

    monkeypatch.setattr(merge_queue, "run_gh", fake)
    return calls


def test_list_prints_queue_fields_and_body_session_line(monkeypatch, capsys):
    calls = fake_run_gh(monkeypatch, lambda args: {
        "repository": {"mergeQueue": {"entries": {"nodes": [
            ENTRY,
            {**ENTRY, "position": 3, "pullRequest": {"number": 43, "title": "fix: no body", "body": None}},
        ]}}},
    })
    assert merge_queue.main(["list"], repo=ROOT) == 0
    out = capsys.readouterr().out
    for piece in ("2 AWAITING_CHECKS PR #42 feat: sample enqueued=2026-11-20T01:02:03Z session=opencode-1",
                  "3 AWAITING_CHECKS PR #43 fix: no body", "session=unknown"):
        assert piece in out
    graphql = calls[-1]
    assert "mergeQueue" in graphql[3] and "owner=robotics-team-1213" in " ".join(graphql)


def test_list_prints_empty_queue(monkeypatch, capsys):
    fake_run_gh(monkeypatch, lambda args: {"repository": {"mergeQueue": {"entries": {"nodes": []}}}})
    assert merge_queue.main(["list"], repo=ROOT) == 0
    assert "empty" in capsys.readouterr().out


def test_dequeue_resolves_pr_id_then_mutates_and_records_audit(monkeypatch, tmp_path):
    calls = fake_run_gh(monkeypatch, lambda args: (
        {"repository": {"pullRequest": {"id": "PR_kwDOABC"}}}
        if "pullRequest(number" in args[3]
        else {"dequeuePullRequest": {"mergeQueueEntry": {"pullRequest": {"number": 42}}}}
    ))
    monkeypatch.setattr(merge_queue, "audit_path", lambda repo: tmp_path / "rosy-queue-audit.jsonl")
    monkeypatch.setenv("ROSY_SESSION_NAME", "opencode-1")

    assert merge_queue.main(["dequeue", "42", "--reason", "stale head"], repo=tmp_path) == 0

    lookup, mutation = calls[-2], calls[-1]
    assert "pullRequest(number" in lookup[3] and "-F" in lookup and "number=42" in lookup
    assert "dequeuePullRequest" in mutation[3] and "id=PR_kwDOABC" in mutation
    record = json.loads((tmp_path / "rosy-queue-audit.jsonl").read_text(encoding="utf-8"))
    assert record == {
        "ts": record["ts"], "action": "dequeue", "pr": 42,
        "reason": "stale head", "session": "opencode-1",
    }


def test_dequeue_refuses_pr_without_id(monkeypatch, tmp_path):
    fake_run_gh(monkeypatch, lambda args: {"repository": {"pullRequest": None}})
    monkeypatch.setattr(merge_queue, "audit_path", lambda repo: tmp_path / "audit.jsonl")
    with pytest.raises(SystemExit, match="not found"):
        merge_queue.main(["dequeue", "42", "--reason", "x"], repo=tmp_path)


def test_dequeue_requires_reason():
    with pytest.raises(SystemExit):
        merge_queue.main(["dequeue", "42"])


def test_session_name_prefers_rosy_then_claude(monkeypatch):
    monkeypatch.setenv("ROSY_SESSION_NAME", "a")
    monkeypatch.setenv("CLAUDE_SESSION_NAME", "b")
    assert merge_queue.session_name() == "a"
    monkeypatch.delenv("ROSY_SESSION_NAME")
    assert merge_queue.session_name() == "b"
    monkeypatch.delenv("CLAUDE_SESSION_NAME")
    assert merge_queue.session_name() == "unknown"
