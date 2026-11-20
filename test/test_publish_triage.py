"""publish_main --merge-when-green on a red ci-result: classify, rerun only infra, show log links (2026-11-19)."""

from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

from test_ci_triage import FakeGh, RUN, SHA, _shards

ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location("publish_main_triage", ROOT / "tools" / "publish_main.py")
tool = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = tool
_SPEC.loader.exec_module(tool)
NOW = datetime(2026, 11, 19, 12, tzinfo=timezone.utc)


@pytest.fixture
def local(tmp_path):
    subprocess.run(["git", "init", "-q", "-b", "main", str(tmp_path)], check=True)
    return tmp_path


def _wire(monkeypatch, gh: FakeGh, view: dict | None = None):
    def run_gh(repo, *args):
        if view is not None and args[:2] == ("pr", "view"):
            return json.dumps(view)
        return gh(*args)
    monkeypatch.setattr(tool, "run_gh", run_gh)


def _red_view() -> dict:
    return {"state": "OPEN", "headRefName": "publish/main-20261119-11", "headRefOid": SHA, "mergeable": "MERGEABLE",
            "mergeStateStatus": "CLEAN",
            "statusCheckRollup": [{"name": "ci-result", "status": "COMPLETED", "conclusion": "FAILURE"}]}


def test_infra_only_red_reruns_once_and_asks_to_retry_later(local, monkeypatch):
    gh = FakeGh(_shards("apt_install", 4))
    _wire(monkeypatch, gh, _red_view())
    with pytest.raises(tool.Stop) as stop:
        tool.merge_when_green(local, "247", True, NOW, via_ci=True)
    assert stop.value.code == 5 and "retry later" in str(stop.value) and "infra" in str(stop.value)
    assert len(gh.reruns()) == 1
    ledger = (local / ".git" / "rosy-ci-triage.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(ledger) == 4 and json.loads(ledger[0])["action"] == "rerun"


def test_a_test_failure_stays_red_with_its_classification_and_log_link(local, monkeypatch):
    from test_ci_triage import FX
    job = dict(FX["assertion_test"]["job"], html_url="https://github.com/o/r/actions/runs/1/job/2")
    gh = FakeGh([(job, FX["assertion_test"]["log"])], attempt=3)
    _wire(monkeypatch, gh, _red_view())
    with pytest.raises(tool.Stop) as stop:
        tool.merge_when_green(local, "247", True, NOW, via_ci=True)
    text = str(stop.value)
    assert stop.value.code == 1 and "not merging" in text and "real_failure" in text
    assert "test_omx_cell_frame" in text and "actions/runs/1/job/2" in text and gh.reruns() == []


def test_a_triage_failure_keeps_the_plain_refusal(local, monkeypatch):
    def broken(repo, *args):
        if args[:2] == ("pr", "view"):
            return json.dumps(_red_view())
        raise tool.Stop(1, "gh exploded")
    monkeypatch.setattr(tool, "run_gh", broken)
    with pytest.raises(tool.Stop) as stop:
        tool.merge_when_green(local, "247", True, NOW, via_ci=True)
    assert stop.value.code == 1 and str(stop.value) == "ci-result FAILURE on PR 247; not merging"
