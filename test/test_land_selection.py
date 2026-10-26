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


# Orchestration stays in this small owner; test_land.py is already above its95% size boundary.
import argparse
import sys
from test_land import GREEN, commit, git, land, repos  # noqa: E402,F401

Stop = land.Stop  # land_isolation obtains the caller's exception from run_tests.__globals__.
BROWSER = "ROSY_RUN_BROWSER_TESTS=1"
ALONE = "ROSY_BROWSER_ALONE=1"
NORMAL = [["test"], ["pkg/test"]]
BROWSER_FILES = ["ui/test/test_one_browser.py", "ui/test/test_alone_browser.py"]
CANONICAL = """import json, sys
from pathlib import Path
def generated_targets(repo): return {}
def generate(repo): return []
if __name__ == '__main__' and sys.argv[1] == 'affected':
    full = '--full' in sys.argv
    print(json.dumps(dict(mode='full' if full else 'affected', escalations=['forced'] if full else [],
          invocations=[] if '--head' in sys.argv else [['pkg/test']], local_invocations=[['test/architecture']],
          full_invocations=[['test'], ['pkg/test']] if full else [])))
"""


def scope_source(paths):
    return ("from pathlib import Path\nROOT=Path(__file__).resolve().parents[1]\n"
            + "EVERYTHING=" + repr(paths) + "\n"
            + "def all_targets(): return sorted(p for p in EVERYTHING if (ROOT/p).is_file())\n")


@pytest.fixture
def full_case(repos, monkeypatch):
    main, wt = repos
    files = {"tools/harness/rosy_harness.py": CANONICAL, "tools/harness/affected_tests.py": "# selector\n",
             "tools/land_selection.py": (ROOT / "tools/land_selection.py").read_text(),
             "tools/land_browser.py": (ROOT / "tools/land_browser.py").read_text()
                 + "\nALONE=frozenset({'ui/test/test_alone_browser.py'})\n",
             "tools/remote/remote_pytest.py": "BROWSER_ENV='ROSY_RUN_BROWSER_TESTS=1'\nALONE_ENV='ROSY_BROWSER_ALONE=1'\n",
             "test/browser_scope.py": scope_source(BROWSER_FILES),
             "tools/collect_alone.py": "# real orchestration, fixture executor supplies the report\n",
             "test/test_root.py": "def test_root(): pass\n",
             "test/architecture/test_guard.py": "def test_guard(): pass\n", "env.txt": "env1"}
    files.update({p: "def test_browser(): pass\n" for p in BROWSER_FILES})
    commit(main, files, "canonical fixture")
    git(wt, "merge", "--ff-only", "main")
    commit(wt, {"pkg/a.py": "x = 2\n"}, "affected-only feature")
    case = SimpleNamespace(main=main, wt=wt, remote=[], splits=[], report="complete", safety=set(),
                           flaky=None, mutate=None, outcome=None)
    monkeypatch.setattr(land.land_cache, "env_id", lambda root, sha: git(root, "show", f"{sha}:env.txt") or None)
    monkeypatch.setattr(land.land_guards.land_isolation, "alone_files",
                        lambda *a: (["pkg/test/test_a.py"], case.safety))
    original_split = land.land_cache.split
    def split(root, args, invocations, *args_, **kw):
        case.splits.append((args.tests, args.no_cache, [list(x) for x in invocations]))
        return original_split(root, args, invocations, *args_, **kw)
    monkeypatch.setattr(land.land_cache, "split", split)
    def run(invocations, logs, sha="HEAD", repo=None, label=None, on_done=None, **kw):
        case.remote.append((label, sha, [list(x) for x in invocations]))
        codes, stopped = [], False
        for inv, log in zip(invocations, logs):
            if stopped:
                codes.append(land.remote_pytest.CANCELLED)
                continue
            code, text = GREEN
            if "ROSY_ALONE_FILES=pkg/test/test_a.py" in inv:
                text += ("[isolation] " + case.report + ": "
                         + ("pkg/test/test_a.py" if case.report == "incomplete" else "1") + "\n"
                         if case.report != "missing" else "")
            if case.flaky == "body" and label == "land-pre" and inv == ["pkg/test"]:
                text, code = "F [100%]\nFAILED pkg/test/test_a.py::test_a - TimeoutError\n1 failed\n", 1
            if ((case.flaky == "guard" and label == "land-gpre")
                    or (case.flaky == "turn_guard" and label == "land-g1")) and inv[0] == "test/architecture":
                text, code = "F [100%]\nFAILED test/architecture/test_guard.py::test_guard - TimeoutError\n1 failed\n", 1
            if case.outcome == "vacuous" and BROWSER in inv:
                text, code = "s [100%]\n1 skipped in .01s\n", 0
            log.parent.mkdir(parents=True, exist_ok=True)
            log.write_text(text, encoding="utf-8")
            codes.append(code)
            stopped = bool(on_done and on_done(inv, log))
        if case.mutate and label == "land-pre":
            mutate, case.mutate = case.mutate, None
            mutate()
        return codes[:-1] if case.outcome == "incomplete" and label == "land-pre" and codes else codes
    monkeypatch.setattr(land.remote_pytest, "run", run)
    return case


def full_args(**kw):
    return argparse.Namespace(**{**dict(tests="full", node=False, no_cache=False, no_queue=False), **kw})


def body_calls(case):
    return [inv for label, _, invs in case.remote if label == "land-pre" for inv in invs]


def assert_full_plan(invocations):
    assert all(inv in invocations for inv in NORMAL), invocations
    browsers = [inv for inv in invocations if BROWSER in inv]
    assert sorted(word for inv in browsers for word in inv if not word.startswith("ROSY_")) == sorted(BROWSER_FILES)
    assert any(ALONE in inv and "ui/test/test_alone_browser.py" in inv for inv in browsers)
    assert ["full"] not in invocations


def test_explicit_full_affected_change_executes_canonical_plan_and_real_receipt(full_case):
    case = full_case
    own = git(case.wt, "rev-parse", "HEAD")
    assert land.main(["--tests", "full"]) == 0
    assert_full_plan(body_calls(case))
    record = land.land_record.read(case.main, git(case.main, "rev-parse", "HEAD"))
    assert record and record["tier"] == "full" and record["prepared_candidate"] == own
    assert git(case.main, "rev-parse", "HEAD") == own
    assert all(no_cache for _, no_cache, invs in case.splits if any("tools/collect_alone.py" in inv for inv in invs))


@pytest.mark.parametrize("tier, invocations", [("affected", [["pkg/test"]]), ("full", NORMAL),
                                               ("full", NORMAL + [[BROWSER, BROWSER_FILES[0]]])])
def test_old_or_partial_preparation_never_skips_current_full_prepare(full_case, tier, invocations):
    case = full_case
    land.land_full.save(case.wt, "feat/x", git(case.wt, "rev-parse", "HEAD"),
                        git(case.main, "rev-parse", "HEAD"), tier, invocations)
    assert land.main(["--tests", "full"]) == 0
    assert_full_plan(body_calls(case))
    assert any("tools/collect_alone.py" in inv for label, _, batch in case.remote if label == "land-gpre" for inv in batch)


def test_restart_rechecks_fresh_guards_but_reuses_clean_exact_body_cache(full_case):
    case = full_case
    land.land_prepare.prepare(land, case.wt, "feat/x", full_args(), sys.executable, None, None)
    assert_full_plan(body_calls(case))
    count = len(body_calls(case)); case.remote.clear(); case.splits.clear()
    assert land.main(["--tests", "full"]) == 0
    assert body_calls(case) == [], "current prepare may reuse exact clean body, not old guard proof"
    assert any(no_cache and any("tools/collect_alone.py" in inv for inv in invs) for _, no_cache, invs in case.splits)
    assert count >= 4


def test_no_cache_current_prepare_advances_once_without_endless_preparation(full_case):
    assert land.main(["--tests", "full", "--no-cache"]) == 0
    assert_full_plan(body_calls(full_case))
    assert body_calls(full_case).count(["pkg/test"]) == 1


@pytest.mark.parametrize("where", ["body", "guard"])
def test_explicit_full_flaky_preparation_stops_before_save_or_ff(full_case, where):
    case = full_case; case.flaky = where
    before = git(case.main, "rev-parse", "HEAD")
    assert land.main(["--tests", "full"]) == 1
    assert git(case.main, "rev-parse", "HEAD") == before
    assert not land.land_full._path(case.wt, "feat/x").exists()
    assert land.land_record.read(case.main, git(case.wt, "rev-parse", "HEAD")) is None


@pytest.mark.parametrize("report, safety, expected", [("incomplete", False, 0), ("incomplete", True, 1),
                                                       ("missing", False, 1)])
def test_explicit_full_preserves_isolation_tracking_and_stopping_policy(full_case, report, safety, expected):
    case = full_case; case.report = report
    case.safety = {"pkg/test/test_a.py"} if safety else set()
    if report == "missing":
        old = case.main.parent / "old-isolation.txt"
        old.write_text("[isolation] complete: 1\n", encoding="utf-8")
        ancestor = git(case.wt, "rev-parse", "HEAD^")
        land.land_cache.record(case.wt, ancestor, git(case.wt, "rev-parse", ancestor + "^{tree}"), "stale-env",
                               land.land_guards.land_isolation.job(["pkg/test/test_a.py"])[0], old)
    before = git(case.main, "rev-parse", "HEAD")
    assert land.main(["--tests", "full"]) == expected
    rows = land.land_guards.land_isolation.rows(case.wt)
    assert rows and rows[-1]["incomplete"] == ["pkg/test/test_a.py"]
    assert (git(case.main, "rev-parse", "HEAD") == before) is bool(expected)
    if expected:
        assert land.land_record.read(case.main, git(case.wt, "rev-parse", "HEAD")) is None
        assert not land.land_full._path(case.wt, "feat/x").exists()


def test_absent_environment_cannot_create_explicit_full_witness(full_case, monkeypatch):
    monkeypatch.setattr(land.land_cache, "env_id", lambda *a: None)
    before = git(full_case.main, "rev-parse", "HEAD")
    assert land.main(["--tests", "full"]) == 1
    assert git(full_case.main, "rev-parse", "HEAD") == before


@pytest.mark.parametrize("changed", ["registry", "alone", "environment"])
def test_main_plan_or_environment_change_requires_new_current_preparation(full_case, changed):
    case = full_case
    def advance():
        if changed == "registry":
            files = {"test/browser_scope.py": scope_source(BROWSER_FILES + ["ui/test/test_new_browser.py"]),
                     "ui/test/test_new_browser.py": "def test_new(): pass\n"}
        elif changed == "alone":
            files = {"tools/land_browser.py": (case.main / "tools/land_browser.py").read_text()
                     + "\nALONE=frozenset({'ui/test/test_one_browser.py','ui/test/test_alone_browser.py'})\n"}
        else:
            files = {"env.txt": "env2"}
        commit(case.main, files, "new required plan")
    case.mutate = advance
    assert land.main(["--tests", "full"]) == 0
    own = git(case.wt, "rev-parse", "HEAD")
    record = land.land_record.read(case.main, own)
    assert record and record["tier"] == "full"
    if changed == "registry":
        assert any("ui/test/test_new_browser.py" in inv for inv in body_calls(case))
    elif changed == "alone":
        assert any(ALONE in inv and "ui/test/test_one_browser.py" in inv for inv in body_calls(case))
    else:
        assert body_calls(case).count(["pkg/test"]) == 2


@pytest.mark.parametrize("where", ["body", "guard"])
@pytest.mark.parametrize("marker", ["LOAD-FLAKY node", "reused across trees"])
def test_auto_flaky_preparation_revokes_old_eligibility_but_keeps_delta_bridge(full_case, monkeypatch, where, marker):
    case = full_case
    candidate, base = git(case.wt, "rev-parse", "HEAD"), git(case.main, "rev-parse", "HEAD")
    land.land_full.save(case.wt, "feat/x", candidate, base, "full", [["pkg/test"]])
    monkeypatch.setattr(land, "select", lambda *a, **k: ([], None) if k.get("landed") else ([["pkg/test"]], "FULL"))
    monkeypatch.setattr(land.land_guards, "first", lambda *a, **k: [marker] if where == "guard" else [])
    monkeypatch.setattr(land, "run_tests", lambda *a, **k: [marker] if where == "body" else [])
    land.land_prepare.prepare(land, case.wt, "feat/x", full_args(tests="auto"), sys.executable, None, None)
    saved = json.loads(land.land_full._path(case.wt, "feat/x").read_text())
    assert saved["tier"] is None, "overwrite the old eligible record, never leave it behind"
    assert land.land_full.restore(case.wt, "feat/x") == base
    assert land.land_full.prepared(case.wt, "feat/x", base) is None
    monkeypatch.setattr(land.land_guards, "first", lambda *a, **k: [])
    monkeypatch.setattr(land, "run_tests", lambda *a, **k: [])
    assert land.main(["--tests", "auto"]) == 0
    assert land.land_record.read(case.main, candidate) is None


@pytest.mark.parametrize("where", ["body", "guard"])
@pytest.mark.parametrize("marker", ["LOAD-FLAKY node", "reused across trees"])
def test_auto_turn_full_save_keeps_flaky_landing_but_not_eligibility(full_case, monkeypatch, where, marker):
    case = full_case; saved = []
    monkeypatch.setattr(land, "select", lambda *a, **k: ([["pkg/test"]], "FULL"))
    monkeypatch.setattr(land.land_guards, "first", lambda *a, **k: [marker] if where == "guard" else [])
    monkeypatch.setattr(land, "run_tests", lambda *a, **k: [marker] if where == "body" else [])
    original = land.land_full.save
    def save(*a):
        saved.append(a[4]); return original(*a)
    monkeypatch.setattr(land.land_full, "save", save)
    assert land.main(["--tests", "auto", "--no-queue"]) == 0
    assert saved == [None]
    assert land.land_record.read(case.main, git(case.main, "rev-parse", "HEAD")) is None


@pytest.mark.parametrize("outcome", ["incomplete", "vacuous"])
def test_explicit_full_rejects_incomplete_body_and_vacuous_browser(full_case, outcome):
    case = full_case; case.outcome = outcome
    before = git(case.main, "rev-parse", "HEAD")
    assert land.main(["--tests", "full"]) == 1
    assert git(case.main, "rev-parse", "HEAD") == before
    assert_full_plan(body_calls(case))
    assert land.land_record.read(case.main, git(case.wt, "rev-parse", "HEAD")) is None


def test_explicit_full_turn_guard_load_flaky_cannot_ff(full_case):
    case = full_case; case.flaky = "turn_guard"
    before = git(case.main, "rev-parse", "HEAD")
    assert land.main(["--tests", "full"]) == 1
    assert_full_plan(body_calls(case))
    assert git(case.main, "rev-parse", "HEAD") == before


@pytest.mark.parametrize("fault", ["missing_harness", "empty_plan", "bad_json", "missing_browser_registry"])
def test_explicit_full_missing_canonical_evidence_fails_closed(full_case, fault):
    case = full_case
    if fault == "missing_harness":
        git(case.wt, "rm", "tools/harness/affected_tests.py")
        git(case.wt, "commit", "-qm", "missing selector")
    elif fault == "empty_plan":
        commit(case.wt, {"tools/harness/rosy_harness.py": CANONICAL.replace("[['test'], ['pkg/test']]", "[]")}, fault)
    elif fault == "bad_json":
        commit(case.wt, {"tools/harness/rosy_harness.py": "print('not-json')\n"}, fault)
    else:
        git(case.wt, "rm", "test/browser_scope.py")
        git(case.wt, "commit", "-qm", "missing registry")
    before = git(case.main, "rev-parse", "HEAD")
    assert land.main(["--tests", "full"]) == 1
    assert git(case.main, "rev-parse", "HEAD") == before


def test_custom_pytest_arguments_stay_nonqualifying(full_case):
    assert land.main(["--tests", "pkg/test -k test_a"]) == 0
    assert land.land_record.read(full_case.main, git(full_case.main, "rev-parse", "HEAD")) is None


def test_explicit_full_refuses_incident_no_queue_before_ff_or_receipt(full_case):
    before = git(full_case.main, "rev-parse", "HEAD")
    assert land.main(["--tests", "full", "--no-queue"]) == 1
    assert git(full_case.main, "rev-parse", "HEAD") == before
    assert not full_case.remote
    assert land.land_record.read(full_case.main, git(full_case.wt, "rev-parse", "HEAD")) is None
