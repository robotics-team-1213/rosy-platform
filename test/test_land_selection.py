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


def test_safety_trigger_is_the_selectors_text():
    selection = load_selection()
    text = (ROOT / "tools/harness/affected_tests.py").read_text(encoding="utf-8")
    assert f'SAFETY_TRIGGER = "{selection.SAFETY_TRIGGER[2:]}"' in text


# Orchestration stays in this small owner; test_land.py is already above its95% size boundary.
import argparse
import sys

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


def test_the_guard_set_and_paths_under_an_ignored_folder_are_no_overlap():
    """D-889 25, 11-02: every selection carried test_protocol_version_alignment and test/architecture tests, so
    every pair of landings overlapped and the rollup and guards-only rules (22, 23) never applied."""
    selection = load_selection()
    shared = ["middleware/core/gateway/test/test_protocol_version_alignment.py",
              "test/architecture/test_document_placement.py"]
    assert not selection.overlaps([shared + ["fleet/test"]], [shared + ["arm/test"]])
    assert selection.overlaps([shared + ["fleet/test"]], [shared + ["fleet/test/test_x.py"]])
    assert not selection.overlaps([["guard/test/test_a.py"]], [["guard/test/test_a.py"]], ignore=("guard/test",))


def test_a_delta_turn_yields_only_with_a_ticket_and_a_clean_tier_under_it():
    """D-889 27: 11-03 a LOAD-FLAKY pretest (no tier) yielded its turn twice and saved nothing."""
    selection = load_selection()
    base = {"tier": "affected", "invocations": [["mine/test"]]}
    assert selection.delta_yields("ticket.json", base)
    assert not selection.delta_yields("ticket.json", base, False)
    assert not selection.delta_yields("ticket.json", None)
    assert not selection.delta_yields(None, base)


def test_load_flaky_ids_keep_the_invocation_environment_and_refuse_unreadable_lines():
    """D-970 4: a browser id rerun without ROSY_RUN_BROWSER_TESTS=1 would skip and look green."""
    selection = load_selection()
    line = ("pytest ROSY_RUN_BROWSER_TESTS=1 ops/test/test_x_browser.py ok (run-pre-3.txt), "
            "LOAD-FLAKY ['ops/test/test_x_browser.py::test_a']")
    assert selection.load_flaky_ids(["pytest a/test ok (run-pre-1.txt)", line]) == [
        ["ROSY_RUN_BROWSER_TESTS=1", "ops/test/test_x_browser.py::test_a"]]
    assert selection.load_flaky_ids(["pytest a/test ok (run-pre-1.txt)"]) == []
    assert selection.load_flaky_ids(["LOAD-FLAKY node"]) is None


def test_a_delta_turn_stops_yielding_after_two_delta_records():
    """D-970 1: 11-03 one ticket yielded three times while main kept moving past it."""
    selection = load_selection()
    assert selection.delta_yields("ticket.json", {"tier": "affected", "yields": 1})
    assert not selection.delta_yields("ticket.json", {"tier": "affected", "yields": selection.MAX_DELTA_YIELDS})


