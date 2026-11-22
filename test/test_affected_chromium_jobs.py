"""D-1066: browser evidence rides the pull_request run (tools/harness/affected_browser.py)."""

from __future__ import annotations

from pathlib import Path

import pytest

import affected_browser as ab
import affected_ci
import affected_tests as at
import browser_scope
import ci_runnable
import land_browser
import pr_land

ROOT = Path(__file__).resolve().parents[1]
UI = ["shared/web/surface_shell.js"]
LAB_ONLY = "test/learning/perception/test_learning_workflow_pipeline_browser.py"
GAZEBO = "integrations/simulation/gazebo/test/test_x.py"
FLEET = "operations/fleet/test/test_site_map_browser.py"  # a land_browser.ALONE file
FLEET_PLAIN = next(p for p in browser_scope.all_targets()
                   if p.startswith("operations/fleet/test/") and p not in land_browser.ALONE)
SHARED = "test/test_dashboard_browser.py"


@pytest.fixture(scope="module")
def repo():
    return at.Repo.load(ROOT)


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setenv(ab.ENV, "1")


def _browser(entries):
    return [e for e in entries if e["name"].startswith("browser-")]


def _files(entries):
    return [w for e in entries for inv in e["invocations"] for w in inv if w.endswith(".py")]


def _whole_file_selected(path, sel):
    return any(path == w or path.startswith(w.rstrip("/") + "/")
               for inv in sel.invocations if not any(x.startswith(("--ignore", "--deselect", "-k")) for x in inv)
               for w in inv if not w.startswith("-") and "::" not in w)


def test_lab_path_and_split_on_real_paths():
    assert ab.lab_path(LAB_ONLY) and ab.lab_path(GAZEBO)
    assert not ab.lab_path(FLEET) and not ab.lab_path(SHARED)
    assert ab.split([SHARED, LAB_ONLY, FLEET, GAZEBO, SHARED]) == (sorted([FLEET, SHARED]), sorted([GAZEBO, LAB_ONLY]))


def test_calibration_browser_file_is_lab_only_until_its_runner_failure_is_found():
    cal = "test/test_measured_calibration_browser.py"
    assert ab.split([SHARED, cal]) == ([SHARED], [cal])


def test_pixel_measuring_browser_files_run_in_ci_with_noto_cjk_fonts():
    px = ["middleware/robot_ui/pilot/test/test_pilot_browser.py",
          "test/learning/perception/test_pixel_workspace_browser.py",
          "test/learning/perception/test_review_flow_browser.py"]
    assert ab.split([SHARED, *px]) == (sorted([SHARED, *px]), [])


def test_one_rule_for_both_sides():
    assert ab.LAB_PREFIXES == pr_land.EXCLUDED_PREFIXES == ci_runnable.EXCLUDED_PREFIXES
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert repr(tuple(ab.CI_BROWSER_ROOTS)).replace("'", '"') in workflow


@pytest.mark.parametrize("text, vacuous", [
    ("=== 3 passed in 0.1s ===", False), ("=== 0 passed, 4 skipped in 0.1s ===", True),
    ("=== 2 passed, 1 skipped in 0.1s ===", True), ("=== 5 failed in 1.0s ===", True), ("", True),
    ("=== 3 passed ===", True),  # no " in N.NNs": not a summary line
    ("3 passed in 0.1s", True),  # no banner: not pytest's final summary
    ("test_x[3 passed] PASSED\n=== 1 failed in 0.1s ===", True),  # a test id is no summary
    ("=== 1 failed, 2 passed in 3.0s (0:00:03) ===", False),
    ("=== 1 failed in 0.1s ===\n=== 1 passed in 0.1s ===", False),  # first run plus a passing quarantine rerun
    ("=== 1 passed in 0.1s ===\n=== 1 skipped in 0.1s ===", True),
    ("=== 3 passed in 0.1s ===\ntest_vacuous[0 passed, 4 skipped in 0.1s-True] PASSED\n=== 2 passed in 0.1s ===", False)])  # a -v id line is no banner
def test_vacuous(text, vacuous):
    assert bool(ab.vacuous(text)) is vacuous


def test_no_entries_without_the_env(repo, monkeypatch):
    monkeypatch.delenv(ab.ENV, raising=False)
    assert ab.entries(repo, at.select(repo, UI)) == []


def test_every_ci_target_runs_once(repo, on):
    sel = at.select(repo, UI)
    ci, _ = ab.split(browser_scope.targets(sel.changed))
    entries = ab.entries(repo, sel)
    ran = _files(entries)
    assert len(ran) == len(set(ran))
    roots = tuple(r + "/" for r in ab.CI_BROWSER_ROOTS)
    for p in ci:  # in exactly one browser-* entry, or a Fleet-root file inside a selected whole-file invocation
        assert ran.count(p) == 1 or (p.startswith(roots) and _whole_file_selected(p, sel)), p
    assert not any(ab.lab_path(p) for p in ran)
    assert all(inv[:2] == [ab.OPT_IN, ab.STRICT] for e in entries for inv in e["invocations"])
    assert {p for p in ran if p in land_browser.ALONE} == set(_files([e for e in entries if e["name"] == "browser-alone"]))
    jobs = {}
    for e in _browser(entries):
        if e["name"] != "browser-alone":
            jobs[e["ros"]] = jobs.get(e["ros"], 0) + 1
    assert jobs and max(jobs.values()) <= ab.MAX_JOBS


def test_full_mode_drops_the_fleet_roots(repo, on):
    ran = _files(ab.entries(repo, at.Selection("full", UI)))
    assert ran and not [p for p in ran if p.startswith(tuple(r + "/" for r in ab.CI_BROWSER_ROOTS))
                        and p not in land_browser.ALONE]


def test_ci_matrix_carries_them_as_separate_gating_jobs(repo, on):
    include = affected_ci.ci_matrix(repo, at.select(repo, UI))["include"]
    mine = _browser(include)
    assert mine and all(e["kind"] == "pytest" and e["gating"] is True for e in mine)
    assert [e["name"] for e in _browser(affected_ci.consolidated(include))] == [e["name"] for e in mine]


def _only(monkeypatch, *paths):
    monkeypatch.setattr(browser_scope, "targets", lambda changed: list(paths))


def test_an_alone_file_is_never_dropped_for_a_fleet_shard(repo, on, monkeypatch):
    assert FLEET in land_browser.ALONE
    _only(monkeypatch, FLEET, FLEET_PLAIN)
    sel = at.Selection("affected", UI, invocations=[["operations/fleet/test"]])
    assert [e["name"] for e in ab.entries(repo, sel)] == ["browser-alone"]
    assert _files(ab.entries(repo, sel)) == [FLEET]  # the plain Fleet file is dropped, the ALONE one is not


@pytest.mark.parametrize("invocation, runs", [
    (["operations/fleet/test"], False),
    ([FLEET_PLAIN], False),
    (["operations/fleet/test", "--ignore=operations/fleet/test/test_x.py"], True),
    (["operations/fleet/test", "--deselect", FLEET_PLAIN + "::test_a"], True),
    (["operations/fleet/test", "-k", "not site_map"], True),
    ([FLEET_PLAIN + "::test_a"], True)])
def test_fleet_rule_counts_only_whole_file_invocations(repo, on, monkeypatch, invocation, runs):
    _only(monkeypatch, FLEET_PLAIN)
    assert (FLEET_PLAIN in _files(ab.entries(repo, at.Selection("affected", UI, invocations=[invocation])))) is runs


def test_full_matrix_fleet_roots_run_whole(repo, on):
    roots = {w for e in at.CI_FULL_MATRIX for inv in e["invocations"] for w in inv}
    for entry in at.CI_FULL_MATRIX:
        if entry["name"] in ("fleet", "app-fleet"):
            assert all(not w.startswith("-") and "::" not in w for inv in entry["invocations"] for w in inv)
    assert set(ab.CI_BROWSER_ROOTS) <= roots


def test_full_selection_without_a_diff_runs_every_ci_browser_file(repo, on, monkeypatch):
    ci, _ = ab.split(browser_scope.all_targets())
    ran = _files(ab.entries(repo, at.Selection("full", [])))
    assert sorted(ran) == [p for p in ci if p in land_browser.ALONE
                           or not p.startswith(tuple(r + "/" for r in ab.CI_BROWSER_ROOTS))]
    assert ab.entries(repo, at.Selection("affected", [])) == []
    monkeypatch.delenv(ab.ENV)
    assert ab.entries(repo, at.Selection("full", [])) == []


def test_browser_alone_marks_env_and_none_shards_balance(repo, on):
    include = affected_ci.ci_matrix(repo, at.select(repo, UI))["include"]
    mine = [e for e in include if e["name"].startswith("browser-")]
    assert mine
    alone = next(e for e in mine if e["name"] == "browser-alone")
    assert land_browser.ALONE_ENV in alone["invocations"][0]

    none_bins = [e for e in mine if e["name"].startswith("browser-none-")]
    if len(none_bins) >= 2:
        from pathlib import PurePosixPath
        weights = [
            sum(affected_ci.CI_TEST_SECONDS.get(PurePosixPath(p).name, 1)
                for inv in e["invocations"] for p in inv
                if not p.startswith("-") and "=" not in p)
            for e in none_bins
        ]
        assert max(weights) <= min(weights) + max(
            affected_ci.CI_TEST_SECONDS.get(PurePosixPath(p).name, 1)
            for e in none_bins for inv in e["invocations"] for p in inv
            if not p.startswith("-") and "=" not in p
        ), weights
