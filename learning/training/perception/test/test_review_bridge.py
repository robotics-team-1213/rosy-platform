"""Review-to-model-PC handoff without approvals or duplicate publication."""
from pathlib import Path
import shutil
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "training"))
import review_bridge
from test_learning_cycle import make_review


def test_verified_export_published_once_and_incomplete_ignored(tmp_path):
    source = tmp_path / "incoming"
    source.mkdir()
    make_review(source)
    (source / "incomplete").mkdir()
    shutil.copytree(source / "export", source / ".partial-export")
    cfg = {"source": str(source), "peer": "approved-model-peer", "remote_reviews": "/srv/reviews",
           "interval_s": 3, "max_attempts": 2}
    calls = []
    fn = lambda *args: calls.append(args[1]) or {"training_dataset_qualified": False}
    review_bridge.run_once(cfg, tmp_path / "state", publisher=fn)
    shutil.copytree(source / "export", source / "duplicate")
    state = review_bridge.run_once(cfg, tmp_path / "state", publisher=fn)
    assert len(calls) == 1 and len(state["steps"]) == 1


def test_untrusted_bytes_never_reach_remote(tmp_path):
    source = tmp_path / "incoming"
    source.mkdir()
    export = make_review(source)
    (export / "inputs/images/000000.jpg").write_bytes(b"tampered")
    cfg = {"source": str(source), "peer": "approved-model-peer", "remote_reviews": "/srv/reviews",
           "interval_s": 3, "max_attempts": 2}
    state = review_bridge.run_once(cfg, tmp_path / "state",
                                  publisher=lambda *args: pytest.fail("do not publish"))
    assert not state["steps"] and state["errors"]


def test_network_failure_retries_then_stops_without_blocking_other_exports(tmp_path):
    source = tmp_path / "incoming"
    source.mkdir()
    make_review(source)
    cfg = {"source": str(source), "peer": "approved-model-peer", "remote_reviews": "/srv/reviews",
           "interval_s": 3, "max_attempts": 2}
    calls = []
    def fail(*args):
        calls.append(args)
        raise OSError("offline")
    for _ in range(3):
        state = review_bridge.run_once(cfg, tmp_path / "state", publisher=fail)
    assert len(calls) == 2
    assert next(iter(state["steps"].values()))["status"] == "failed"
