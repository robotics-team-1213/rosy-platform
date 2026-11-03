"""Standalone behavior of the selector leaf and its legacy gateway seams."""

from __future__ import annotations

import importlib
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from harness import affected_exclusive as exclusive  # noqa: E402


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
                           subprocess=SimpleNamespace(run=run), lines=lambda *args: [],
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


def test_actual_landing_report_delta_reaches_the_affected_plan(caller, tmp_path):
    import affected_tests

    land, payload, _ = caller
    actual = affected_tests.select(affected_tests.Repo.load(ROOT),
                                   ["tools/land_goal.py", "test/test_land_goal.py"])
    payload.update(actual.to_json())
    invocations, note = load_selection().select(land, tmp_path, "base", "python", head="candidate")
    assert note is None
    assert invocations == actual.invocations + [["ROSY_RUN_BROWSER_TESTS=1", "browser/test"]]
    assert "test/test_land_goal.py" in {word for inv in invocations for word in inv}
    assert "test/test_land_events.py" in {word for inv in invocations for word in inv}
    assert not any("test" in inv for inv in invocations)


def test_explicit_full_accepts_root_exclusion_only_with_strict_timing_companion(caller, tmp_path, monkeypatch):
    selection = load_selection()
    owner, payload, _ = caller
    plan = [['test', '--ignore=' + exclusive.TARGET], exclusive.DEDICATED]
    payload.update(mode='full', full_invocations=plan)
    monkeypatch.setattr(selection, 'all_browsers', lambda *args: [['ROSY_RUN_BROWSER_TESTS=1', 'browser/test']])
    actual, note = selection.select(owner, tmp_path, 'base', 'python', full=True)
    assert actual == plan + [['ROSY_RUN_BROWSER_TESTS=1', 'browser/test']]
    assert note == 'explicit canonical FULL'


@pytest.mark.parametrize('plan', [
    [['test', '--ignore=' + exclusive.TARGET]],
    [exclusive.DEDICATED],
    [['test', '--ignore=' + exclusive.TARGET], exclusive.DEDICATED, exclusive.DEDICATED],
    [['test', '--ignore=' + exclusive.TARGET], exclusive.DEDICATED + ['-k', 'one']],
    [['test', '--ignore=' + exclusive.TARGET], exclusive.DEDICATED[:-1]],
    [['test'], exclusive.DEDICATED],
])
def test_explicit_full_refuses_missing_duplicate_partial_or_ordinary_timing(caller, tmp_path, plan):
    selection = load_selection()
    owner, payload, _ = caller
    payload.update(mode='full', full_invocations=plan)
    with pytest.raises(owner.Stop):
        selection.select(owner, tmp_path, 'base', 'python', full=True)


def test_landed_harness_delta_keeps_local_selection(caller, tmp_path):
    selection = load_selection()
    land, payload, _ = caller
    land.land_guards = SimpleNamespace(GUARDS=("guard/test",))
    payload.update(mode="full", escalations=["tools/harness/x.py" + land.HARNESS_TRIGGER])
    assert selection.select(land, tmp_path, "base", "python", head="main", landed=True) == (
        [["guard/test"], ["ROSY_RUN_BROWSER_TESTS=1", "browser/test"]], None)
    payload["escalations"].append("production: safety")
    assert selection.select(land, tmp_path, "base", "python", landed=True)[0][:2] == [
        ["test"], ["module/test"]]


def test_landed_full_delta_runs_both_changes_own_suites_unless_safety(caller, tmp_path):
    selection = load_selection()
    land, _, calls = caller
    land.land_guards = SimpleNamespace(GUARDS=("guard/test",))
    delta = dict(mode="full", escalations=["conftest.py: pytest conftest"], local_invocations=[["guard/test"]],
                 full_invocations=[["test"]])
    mine = dict(mode="affected", escalations=[], invocations=[["mine/test"], ["guard/test"]])
    answers = [delta, mine]
    land.subprocess = SimpleNamespace(run=lambda command, **kw: calls.append(command) or SimpleNamespace(
        returncode=0, stdout=json.dumps(answers.pop(0)), stderr=""))
    # D-889 18: the delta reaches guard/test only, so mine/test keeps its pretest pass
    assert selection.select(land, tmp_path, "base", "python", head="main", landed=True) == (
        [["guard/test"], ["ROSY_RUN_BROWSER_TESTS=1", "browser/test"]], None)
    assert calls[-1] == ["python", land.HARNESS, "affected", "--base", "main", "--json"]  # this branch on the merge
    answers[:] = [delta, dict(mine, escalations=["safe/x.py" + selection.SAFETY_TRIGGER])]
    assert selection.select(land, tmp_path, "base", "python", head="main", landed=True)[1] is not None



def test_a_safety_path_in_mains_landed_delta_keeps_only_its_mapped_suites(caller, tmp_path):
    """D-889 addendum 8: a safety change in main's delta landed with its own FULL; it no longer makes every
    landing behind it repeat FULL (~745 min/day on 2026-10-30..31). This branch's own safety path still does."""
    selection = load_selection()
    land, _, calls = caller
    delta = dict(mode="full", escalations=["safe/x.py" + selection.SAFETY_TRIGGER],
                 local_invocations=[["guard/test"], ["safe/test"]], full_invocations=[["test"]])
    mine = dict(mode="affected", escalations=[], invocations=[["mine/test"]])
    answers = [delta, mine]
    land.subprocess = SimpleNamespace(run=lambda command, **kw: calls.append(command) or SimpleNamespace(
        returncode=0, stdout=json.dumps(answers.pop(0)), stderr=""))
    invocations, note = selection.select(land, tmp_path, "base", "python", head="main", landed=True)
    assert invocations == [["guard/test"], ["safe/test"], ["ROSY_RUN_BROWSER_TESTS=1", "browser/test"]], "addendum 10"
    assert note.startswith(selection.DELTA_NOTE)  # D-889 27: the safety suite folder runs before the turn
    answers[:] = [delta, dict(mine, mode="full", escalations=["safe/y.py" + selection.SAFETY_TRIGGER],
                              local_invocations=[["mine/test"]])]
    assert selection.select(land, tmp_path, "base", "python", head="main", landed=True)[1] is not None
    answers[:] = [delta]  # not a landed delta (no own FULL to stand on): FULL as before
    assert selection.select(land, tmp_path, "base", "python", head="main")[1] is not None


def test_a_landed_delta_reaching_none_of_this_branchs_suites_does_not_rerun_them(caller, tmp_path):
    """D-889 addendum 10 item 2: own suites re-run only when main's delta reaches them (guards aside)."""
    selection = load_selection()
    land, _, _ = caller
    land.land_guards = SimpleNamespace(GUARDS=("guard/test",))
    delta = dict(mode="full", escalations=["conftest.py: pytest conftest"],
                 local_invocations=[["guard/test"], ["fleet/test"]], full_invocations=[["test"]])
    answers = []
    land.subprocess = SimpleNamespace(run=lambda command, **kw: SimpleNamespace(
        returncode=0, stdout=json.dumps(answers.pop(0)), stderr=""))
    browser = ["ROSY_RUN_BROWSER_TESTS=1", "browser/test"]
    for mine, rerun in ((dict(mode="affected", escalations=[], invocations=[["guard/test"], ["arm/test"]]), False),
                        (dict(mode="affected", escalations=[], invocations=[["fleet/test/test_x.py::t"]]), True),
                        # D-889 16: a FULL-mode own follows the same rule; re-run every turn, it never landed (11-01)
                        (dict(mode="full", escalations=["tools/x.py: harness"], local_invocations=[["arm/test"]]),
                         False),
                        (dict(mode="full", escalations=["tools/x.py: harness"], local_invocations=[["fleet/test/test_y.py"]]),
                         True)):
        answers[:] = [delta, mine]
        got = selection.select(land, tmp_path, "base", "python", head="main", landed=True)[0]
        own = mine.get("invocations") or mine["local_invocations"]
        # D-889 22: reaching nothing either way, the delta's suites do not rerun either: the guards only
        unreached = [["guard/test"], ["fleet/test"]] if mine["mode"] == "full" else [["guard/test"]]  # a FULL own: unknown reach
        assert got == ([["guard/test"], ["fleet/test"]] + [inv for inv in own if inv != ["guard/test"]] if rerun
                       else unreached) + [browser]
    # D-889 18: per invocation, only the own ones the delta reaches rerun (11-01: 485 rerun for a few reached)
    answers[:] = [delta, dict(mode="full", escalations=["contracts/foundation/x.py: shared foundation"],
                              local_invocations=[["fleet/test/test_y.py"], ["arm/test"], ["guard/test"]])]
    assert selection.select(land, tmp_path, "base", "python", head="main", landed=True)[0] == [
        ["guard/test"], ["fleet/test"], ["fleet/test/test_y.py"], browser]
    # D-889 22: an ordinary (not escalated) delta the same way (a safety delta escalates: test above)
    plain = dict(mode="affected", escalations=[], invocations=[["guard/test"], ["fleet/test"]])
    for mine, want in ((["arm/test"], [["guard/test"]]),
                       (["fleet/test/test_x.py"], [["guard/test"], ["fleet/test"]])):
        answers[:] = [plain, dict(mode="affected", escalations=[], invocations=[mine])]
        assert selection.select(land, tmp_path, "base", "python", head="main", landed=True)[0] == want + [browser]
    assert selection.overlaps([["a/test"]], [["ROSY_X=1", "a/test/test_b.py::c"]]) and not selection.overlaps(
        [["a/test"]], [["b/test"]])


def test_a_landed_delta_reaching_whole_suite_folders_runs_them_before_the_turn(caller, tmp_path):
    """D-889 27: 11-03 turns ran the delta's suite folders for 15-22 min in the lock and gave the turn back."""
    selection = load_selection()
    land, _, _ = caller
    land.land_guards = SimpleNamespace(GUARDS=("guard/test",))
    mine = dict(mode="full", escalations=["tools/x.py: harness"], local_invocations=[["fleet/test/test_y.py"]])
    answers = []
    land.subprocess = SimpleNamespace(run=lambda command, **kw: SimpleNamespace(
        returncode=0, stdout=json.dumps(answers.pop(0)), stderr=""))
    folders = dict(mode="full", escalations=["contracts/foundation/x.py: shared foundation"],
                   local_invocations=[["guard/test"], ["fleet/test"]], full_invocations=[["test"]])
    answers[:] = [folders, mine]
    invocations, note = selection.select(land, tmp_path, "base", "python", head="main", landed=True)
    assert ["fleet/test"] in invocations and note.startswith(selection.DELTA_NOTE)
    files = dict(folders, local_invocations=[["guard/test"], ["fleet/test/test_x.py"]])
    answers[:] = [files, mine]
    assert selection.select(land, tmp_path, "base", "python", head="main", landed=True)[1] is None  # files stay in the turn


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


# Orchestration stays in this small owner; test_land.py is already above its95% size boundary.
import argparse
import sys
from test_land import GREEN, commit, git, land, repos  # noqa: E402,F401

Stop = land.Stop  # land_isolation obtains the caller's exception from run_tests.__globals__.
BROWSER = "ROSY_RUN_BROWSER_TESTS=1"
ALONE = "ROSY_BROWSER_ALONE=1"
NORMAL = [["test", '--ignore=' + exclusive.TARGET], ["pkg/test"], exclusive.DEDICATED]
BROWSER_FILES = ["ui/test/test_one_browser.py", "ui/test/test_alone_browser.py"]
CANONICAL = 'FULL_PLAN = ' + repr(NORMAL) + '\n' + """import json, sys
from pathlib import Path
def generated_targets(repo): return {}
def generate(repo): return []
if __name__ == '__main__' and sys.argv[1] == 'affected':
    full = '--full' in sys.argv
    print(json.dumps(dict(mode='full' if full else 'affected', escalations=['forced'] if full else [],
          invocations=[] if '--head' in sys.argv else [['pkg/test']], local_invocations=[['test/architecture']],
          full_invocations=FULL_PLAN if full else [])))
"""


def scope_source(paths):
    return ("from pathlib import Path\nROOT=Path(__file__).resolve().parents[1]\n"
            + "EVERYTHING=" + repr(paths) + "\n"
            + "def all_targets(): return sorted(p for p in EVERYTHING if (ROOT/p).is_file())\n")


@pytest.fixture
def full_case(repos, monkeypatch):
    main, wt = repos
    files = {".gitignore": "__pycache__/\n", "tools/harness/rosy_harness.py": CANONICAL, "tools/harness/affected_tests.py": "# selector\n",
             "tools/land_selection.py": (ROOT / "tools/land_selection.py").read_text(),
             "tools/harness/affected_exclusive.py": (ROOT / "tools/harness/affected_exclusive.py").read_text(),
             "tools/land_browser.py": (ROOT / "tools/land_browser.py").read_text()
                 + "\nALONE=frozenset({'ui/test/test_alone_browser.py'})\n",
             "tools/remote/remote_pytest.py": "BROWSER_ENV='ROSY_RUN_BROWSER_TESTS=1'\nALONE_ENV='ROSY_BROWSER_ALONE=1'\n",
             "test/browser_scope.py": scope_source(BROWSER_FILES),
             "tools/collect_alone.py": "# real orchestration, fixture executor supplies the report\n",
             "test/test_root.py": "def test_root(): pass\n",
             exclusive.TARGET: "def test_timing_stub(): pass\n",
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
            text = "1 passed in 0.01s\n"  # Browser gate requires a real pytest-summary shape.
            if exclusive.dedicated(inv):
                text += '[g1-timing-gate] expected=1 collected=1 passed=1 skipped=0 clean=1\n'
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
    assert body_calls(case) == [exclusive.DEDICATED], 'ordinary body cache remains; timing needs a fresh receipt'
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
    mapped_delta = CANONICAL.replace("invocations=[] if '--head' in sys.argv else [['pkg/test']]",
        "invocations=([['pkg/test']] if Path('pkg/util.py').is_file() else []) if '--head' in sys.argv else [['pkg/test']]")
    commit(case.wt, {"tools/harness/rosy_harness.py": mapped_delta,
                    "tools/harness/harness.yaml": "modules: [{id: fixture, path: pkg, tests: [pkg/test]}]\n",
                    "tools/harness/platform_parts.yaml": "roots: [{path: pkg, import_prefix: [pkg], concern: other}]\n"},
           "map a genuine peer delta")
    case.mutate = lambda: commit(case.main, {"pkg/util.py": "VALUE = 1\n"}, "peer dependency change")
    before = git(case.main, "rev-parse", "HEAD")
    assert land.main(["--tests", "full"]) == 1
    assert_full_plan(body_calls(case))
    assert any(label == "land-g1" and any(inv[0] == "test/architecture" for inv in invs)
               for label, _, invs in case.remote)
    assert git(case.main, "rev-parse", "HEAD") != before  # the peer is preserved
    assert (case.main / "pkg/a.py").read_text() == "x = 1\n"  # our affected feature was not ff'd
    assert land.land_record.read(case.main, git(case.wt, "rev-parse", "HEAD")) is None


@pytest.mark.parametrize("fault", ["missing_harness", "empty_plan", "bad_json", "missing_browser_registry"])
def test_explicit_full_missing_canonical_evidence_fails_closed(full_case, fault):
    case = full_case
    if fault == "missing_harness":
        git(case.wt, "rm", "tools/harness/affected_tests.py")
        git(case.wt, "commit", "-qm", "missing selector")
    elif fault == "empty_plan":
        commit(case.wt, {"tools/harness/rosy_harness.py": CANONICAL.replace(
            "full_invocations=FULL_PLAN if full else []", "full_invocations=[]")}, fault)
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


def test_a_landed_delta_repeats_its_browser_tests_only_for_a_branch_that_changes_ui(caller, tmp_path):
    """D-889 addendum 12 (user decision 2026-11-01): main's delta passed its own browser tests when it landed."""
    selection = load_selection()
    land, payload, _ = caller
    ui = ["ROSY_RUN_BROWSER_TESTS=1", "browser/test"]
    land.browser_tier = lambda wt, base, head=None: [ui] if head else []  # own change (base=main tip): no UI
    assert selection.select(land, tmp_path, "base", "python", head="main", landed=True)[0] == [["selected/test"]]
    land.browser_tier = lambda wt, base, head=None: [ui]  # this branch changes UI too: both run
    assert ui in selection.select(land, tmp_path, "base", "python", head="main", landed=True)[0]
    assert ui in selection.select(land, tmp_path, "base", "python")[0], "a pretest keeps its own browser tier"


def test_an_automatic_full_tier_runs_simulation_suites_only_for_a_simulation_change(caller, tmp_path):
    selection = load_selection()
    land, payload, _ = caller
    payload.update(mode="full", escalations=["x"], full_invocations=[
        ["test"], ["integrations/simulation/gazebo/test"], ["ROSY_JOB_CORES=2", "learning/envs/isaac/test"]])
    assert selection.select(land, tmp_path, "base", "python")[0][:1] == [["test"]]
    assert len(selection.select(land, tmp_path, "base", "python")[0]) == 2, "only test + browser"
    land.lines = lambda *a: ["integrations/simulation/gazebo/launch/x.py"]
    assert ["integrations/simulation/gazebo/test"] in selection.select(land, tmp_path, "base", "python")[0]
    assert selection.without_sim([["a/test", "learning/envs/isaac/test/test_x.py"]], []) == [["a/test"]]


def test_own_browser_chunks_rerun_only_where_the_deltas_browser_chunks_reach(caller, tmp_path):
    """D-889 24, 11-02 03:32: the delta's suite folder holds the browser files, so every own chunk counted as reached
    and a 6-invocation turn ran 7 serial browser chunks for 34 min."""
    selection = load_selection()
    land, _, _ = caller
    ui = ["ROSY_RUN_BROWSER_TESTS=1", "fleet/test/test_panel_browser.py"]
    delta = dict(mode="full", escalations=["tools/land.py: harness"], local_invocations=[["fleet/test"]],
                 full_invocations=[["test"]])
    mine = dict(mode="affected", escalations=[], invocations=[["fleet/test/test_panel.py"]])
    other = ["ROSY_RUN_BROWSER_TESTS=1", "fleet/test/test_map_browser.py"]  # a delta chunk this branch does not touch
    for delta_ui, want in (([], []), ([ui], [ui]), ([other], []), ([other, ui], [ui])):
        answers = [delta, mine]
        land.subprocess = SimpleNamespace(run=lambda command, **kw: SimpleNamespace(
            returncode=0, stdout=json.dumps(answers.pop(0)), stderr=""))
        land.browser_tier = lambda *args, _d=delta_ui: [ui] if len(args) == 2 else _d  # (wt, head): own
        got = selection.select(land, tmp_path, "base", "python", head="main", landed=True)[0]
        assert [inv for inv in got if inv[0].startswith("ROSY_RUN_BROWSER")] == want


def test_the_guard_set_and_paths_under_an_ignored_folder_are_no_overlap():
    """D-889 25, 11-02: every selection carried test_protocol_version_alignment and test/architecture tests, so
    every pair of landings overlapped and the rollup and guards-only rules (22, 23) never applied."""
    selection = load_selection()
    shared = ["middleware/core/gateway/test/test_protocol_version_alignment.py",
              "test/architecture/test_document_placement.py"]
    assert not selection.overlaps([shared + ["fleet/test"]], [shared + ["arm/test"]])
    assert selection.overlaps([shared + ["fleet/test"]], [shared + ["fleet/test/test_x.py"]])
    assert not selection.overlaps([["guard/test/test_a.py"]], [["guard/test/test_a.py"]], ignore=("guard/test",))


def test_load_flaky_ids_keep_the_invocation_environment_and_refuse_unreadable_lines():
    """D-970 4: a browser id rerun without ROSY_RUN_BROWSER_TESTS=1 would skip and look green."""
    selection = load_selection()
    line = ("pytest ROSY_RUN_BROWSER_TESTS=1 ops/test/test_x_browser.py ok (run-pre-3.txt), "
            "LOAD-FLAKY ['ops/test/test_x_browser.py::test_a']")
    assert selection.load_flaky_ids(["pytest a/test ok (run-pre-1.txt)", line]) == [
        ["ROSY_RUN_BROWSER_TESTS=1", "ops/test/test_x_browser.py::test_a"]]
    assert selection.load_flaky_ids(["pytest a/test ok (run-pre-1.txt)"]) == []
    assert selection.load_flaky_ids(["LOAD-FLAKY node"]) is None
