"""Standalone behavior of the selector leaf and its legacy gateway seams."""

from __future__ import annotations

import importlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load_selection():
    path = ROOT / "tools/land_selection.py"
    assert path.is_file(), "selection must have a standalone owner outside the near-limit gateway"
    spec = importlib.util.spec_from_file_location("standalone_land_selection", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def caller(tmp_path):
    marker = tmp_path / "tools/harness/affected_tests.py"
    marker.parent.mkdir(parents=True)
    marker.touch()

    class Stop(Exception):
        pass

    calls = []
    payload = dict(mode="affected", escalations=[], invocations=[["selected/test"]],
                   local_invocations=[["guard/test"]], full_invocations=[["test"], ["module/test"]])

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")

    land = SimpleNamespace(Stop=Stop, HARNESS="tools/harness/rosy_harness.py",
                           HARNESS_TRIGGER=": harness configuration or the selector itself",
                           ENV={"PYTHONUTF8": "1", "CALLER_ENV": "retained"},
                           subprocess=SimpleNamespace(run=run),
                           browser_tier=lambda *args: [["ROSY_RUN_BROWSER_TESTS=1", "browser/test"]])
    return land, payload, calls


def test_affected_selection_keeps_candidate_subprocess_and_env(caller, tmp_path):
    selection = load_selection()
    land, _, calls = caller
    invocations, note = selection.select(land, tmp_path, "base", "python", head="candidate")
    assert invocations == [["selected/test"], ["ROSY_RUN_BROWSER_TESTS=1", "browser/test"]]
    assert note is None
    assert calls == [(["python", land.HARNESS, "affected", "--base", "base", "--head", "candidate", "--json"],
                      dict(cwd=tmp_path, capture_output=True, text=True, encoding="utf-8", env=land.ENV))]
    assert calls[0][1]["env"] is land.ENV


def test_full_selection_keeps_full_plan_and_reason(caller, tmp_path):
    selection = load_selection()
    land, payload, _ = caller
    payload.update(mode="full", escalations=["safety", "foundation"])
    invocations, note = selection.select(land, tmp_path, "base", "python")
    assert invocations == [["test"], ["module/test"], ["ROSY_RUN_BROWSER_TESTS=1", "browser/test"]]
    assert note == "selector escalated to FULL (safety; foundation): full tier on the lab PCs"


def test_landed_harness_delta_keeps_local_selection(caller, tmp_path):
    selection = load_selection()
    land, payload, _ = caller
    payload.update(mode="full", escalations=["tools/harness/x.py" + land.HARNESS_TRIGGER])
    assert selection.select(land, tmp_path, "base", "python", head="main", landed=True) == (
        [["guard/test"], ["ROSY_RUN_BROWSER_TESTS=1", "browser/test"]], None)
    payload["escalations"].append("production: safety")
    assert selection.select(land, tmp_path, "base", "python", landed=True)[0][:2] == [
        ["test"], ["module/test"]]


def test_landed_full_delta_runs_both_changes_own_suites_unless_safety(caller, tmp_path):
    selection = load_selection()
    land, _, calls = caller
    delta = dict(mode="full", escalations=["conftest.py: pytest conftest"], local_invocations=[["guard/test"]],
                 full_invocations=[["test"]])
    mine = dict(mode="affected", escalations=[], invocations=[["mine/test"], ["guard/test"]])
    answers = [delta, mine]
    land.subprocess = SimpleNamespace(run=lambda command, **kw: calls.append(command) or SimpleNamespace(
        returncode=0, stdout=json.dumps(answers.pop(0)), stderr=""))
    assert selection.select(land, tmp_path, "base", "python", head="main", landed=True) == (
        [["guard/test"], ["mine/test"], ["ROSY_RUN_BROWSER_TESTS=1", "browser/test"]], None)
    assert calls[-1] == ["python", land.HARNESS, "affected", "--base", "main", "--json"]  # this branch on the merge
    answers[:] = [delta, dict(mine, escalations=["safe/x.py" + selection.SAFETY_TRIGGER])]
    assert selection.select(land, tmp_path, "base", "python", head="main", landed=True)[1] is not None


def test_safety_trigger_is_the_selectors_text():
    selection = load_selection()
    text = (ROOT / "tools/harness/affected_tests.py").read_text(encoding="utf-8")
    assert f'SAFETY_TRIGGER = "{selection.SAFETY_TRIGGER[2:]}"' in text


def test_failed_selector_raises_callers_stop(caller, tmp_path):
    selection = load_selection()
    land, _, _ = caller
    land.subprocess.run = lambda *a, **k: SimpleNamespace(returncode=7, stdout="out", stderr="error")
    with pytest.raises(land.Stop, match=r"affected selector failed \(exit 7\)") as exc:
        selection.select(land, tmp_path, "base", "python")
    assert type(exc.value) is land.Stop
    assert str(exc.value).endswith("outerror")


@pytest.mark.parametrize("payload", ["{", "null", '{}', '{"mode":"full"}'])
def test_unusable_selector_raises_callers_stop(caller, tmp_path, payload):
    selection = load_selection()
    land, _, _ = caller
    land.subprocess.run = lambda *a, **k: SimpleNamespace(returncode=0, stdout=payload, stderr="")
    with pytest.raises(land.Stop, match="unusable JSON") as exc:
        selection.select(land, tmp_path, "base", "python")
    assert type(exc.value) is land.Stop
    assert exc.value.__cause__ is not None


def test_fallback_preserves_callers_path_mapping_and_packing(tmp_path):
    selection = load_selection()
    calls = []
    changed, targets = ["package/code.py"], ["package/test"]
    def lines(*args):
        calls.append(args)
        return changed
    def fallback(wt, paths):
        assert wt == tmp_path and paths is changed
        return targets
    def pack(wt, paths):
        assert wt == tmp_path and paths is targets
        return [["package/test"]]
    land = SimpleNamespace(lines=lines, fallback_targets=fallback, pack=pack,
                           browser_tier=lambda *a: [["ROSY_RUN_BROWSER_TESTS=1", "browser/test"]])
    assert selection.select(land, tmp_path, "base", "python", head="candidate") == (
        [["package/test"], ["ROSY_RUN_BROWSER_TESTS=1", "browser/test"]], None)
    assert calls == [(tmp_path, "diff", "--name-only", "base...candidate")]


def test_browser_tier_preserves_target_pack_chunk_order(tmp_path):
    selection = load_selection()
    calls = []
    def lines(*args):
        calls.append(args)
        return ["web/app.js"]
    def targets(paths):
        assert paths == ["web/app.js"]
        return ["a/test.py", "b/test.py"]
    def pack(wt, paths):
        assert wt == tmp_path and paths == ["a/test.py", "b/test.py"]
        return [["a/test.py"], ["b/test.py"]]
    def chunks(wt, group):
        assert wt == tmp_path
        return [["ROSY_RUN_BROWSER_TESTS=1", *group], ["ROSY_RUN_BROWSER_TESTS=1", "ROSY_BROWSER_ALONE=1", *group]]
    land = SimpleNamespace(lines=lines, pack=pack, browser_scope=SimpleNamespace(targets=targets),
                           land_browser=SimpleNamespace(chunks=chunks))
    assert selection.browser_tier(land, tmp_path, "base") == [
        ["ROSY_RUN_BROWSER_TESTS=1", "a/test.py"],
        ["ROSY_RUN_BROWSER_TESTS=1", "ROSY_BROWSER_ALONE=1", "a/test.py"],
        ["ROSY_RUN_BROWSER_TESTS=1", "b/test.py"],
        ["ROSY_RUN_BROWSER_TESTS=1", "ROSY_BROWSER_ALONE=1", "b/test.py"]]
    assert calls == [(tmp_path, "diff", "--name-only", "base...HEAD")]


def test_legacy_gateway_delegates_with_same_module_and_signatures(monkeypatch, tmp_path):
    selection = load_selection()
    monkeypatch.syspath_prepend(str(ROOT / "tools"))
    land = importlib.import_module("land")
    calls = []
    def choose(*args):
        calls.append(args)
        return [["selected"]], "note"
    def browsers(*args):
        calls.append(args)
        return [["browser"]]
    monkeypatch.setattr(land.land_selection, "select", choose)
    monkeypatch.setattr(land.land_selection, "browser_tier", browsers)
    assert land.select(tmp_path, "base", "python") == ([["selected"]], "note")
    assert calls.pop() == (land, tmp_path, "base", "python", None, False)
    assert land.select(tmp_path, "base", "python", head="candidate", landed=True) == ([["selected"]], "note")
    assert calls.pop() == (land, tmp_path, "base", "python", "candidate", True)
    assert land.browser_tier(tmp_path, "base") == [["browser"]]
    assert calls.pop() == (land, tmp_path, "base", None)
