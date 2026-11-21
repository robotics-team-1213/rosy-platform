"""D-1066: browser evidence rides the pull_request run (tools/harness/affected_browser.py)."""

from __future__ import annotations

from pathlib import Path

import pytest

import affected_browser as ab
import affected_ci
import affected_tests as at
import browser_scope
import land_browser
import pr_land

ROOT = Path(__file__).resolve().parents[1]
UI = ["shared/web/surface_shell.js"]
LAB_ONLY = "test/learning/perception/test_learning_workflow_pipeline_browser.py"
GAZEBO = "integrations/simulation/gazebo/test/test_x.py"
FLEET = "operations/fleet/test/test_site_map_browser.py"
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


def test_lab_path_and_split_on_real_paths():
    assert ab.lab_path(LAB_ONLY) and ab.lab_path(GAZEBO)
    assert not ab.lab_path(FLEET) and not ab.lab_path(SHARED)
    assert ab.split([SHARED, LAB_ONLY, FLEET, GAZEBO, SHARED]) == (sorted([FLEET, SHARED]), sorted([GAZEBO, LAB_ONLY]))


def test_one_rule_for_both_sides():
    assert ab.LAB_PREFIXES == pr_land.EXCLUDED_PREFIXES
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert repr(tuple(ab.CI_BROWSER_ROOTS)).replace("'", '"') in workflow


@pytest.mark.parametrize("text, vacuous", [
    ("3 passed in 0.1s", False), ("0 passed, 4 skipped in 0.1s", True), ("2 passed, 1 skipped in 0.1s", True),
    ("5 failed in 1.0s", True), ("", True)])
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
    assert sorted(set(ran) | {p for p in ci if ab._selected(p, sel)}) == ci
    assert not any(ab.lab_path(p) for p in ran)
    assert all(inv[:2] == [ab.OPT_IN, ab.STRICT] for e in entries for inv in e["invocations"])
    assert {p for p in ran if p in land_browser.ALONE} == set(_files([e for e in entries if e["name"] == "browser-alone"]))
    jobs = {}
    for e in _browser(entries):
        if e["name"] != "browser-alone":
            jobs[e["ros"]] = jobs.get(e["ros"], 0) + 1
    assert jobs and max(jobs.values()) <= 4


def test_full_mode_drops_the_fleet_roots(repo, on):
    ran = _files(ab.entries(repo, at.Selection("full", UI)))
    assert ran and not [p for p in ran if p.startswith(tuple(r + "/" for r in ab.CI_BROWSER_ROOTS))]


def test_ci_matrix_carries_them_as_separate_gating_jobs(repo, on):
    include = affected_ci.ci_matrix(repo, at.select(repo, UI))["include"]
    mine = _browser(include)
    assert mine and all(e["kind"] == "pytest" and e["gating"] is True for e in mine)
    assert [e["name"] for e in _browser(affected_ci.consolidated(include))] == [e["name"] for e in mine]
