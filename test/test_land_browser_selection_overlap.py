"""Overlapping own/delta browser chunks retain their first safe file occurrence."""
import copy
import json
from types import SimpleNamespace

import pytest

from test_land_selection import caller, load_selection  # noqa: F401

BROWSER = "ROSY_RUN_BROWSER_TESTS=1"
A, B, C = "browser/shared_browser.py", "left/test_same_browser.py", "right/test_same_browser.py"


def choose(caller, tmp_path, own, delta, escalated=False):
    land, payload, _ = caller
    for name in (A, B, C):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    if escalated:
        payload.update(mode="full", escalations=["harness"], local_invocations=[["suite/test"]])
        mine = dict(mode="affected", escalations=[], invocations=[["suite/test"]])
        answers = [payload, mine]
        land.subprocess = SimpleNamespace(run=lambda *a, **k: SimpleNamespace(
            returncode=0, stdout=json.dumps(answers.pop(0)), stderr=""))
    land.browser_tier = lambda *args: own if len(args) == 2 else delta
    return load_selection().select(land, tmp_path, "base", "python", head="main", landed=True)[0]


@pytest.mark.parametrize("escalated", [False, True])
def test_overlapping_chunks_keep_first_files_without_repacking_or_mutating(caller, tmp_path, escalated):
    own = [[BROWSER, A, B]]
    delta = [[BROWSER, A, C], [BROWSER, A]]
    before = copy.deepcopy((own, delta))
    got = choose(caller, tmp_path, own, delta, escalated)
    browser = [inv for inv in got if BROWSER in inv]
    assert browser == ([[BROWSER, A, C], [BROWSER, B]] if escalated else [[BROWSER, A, B], [BROWSER, C]])
    assert (own, delta) == before
    assert sorted(word for inv in browser for word in inv if word != BROWSER) == sorted([A, B, C])
    assert ["suite/test"] in got if escalated else ["selected/test"] in got


@pytest.mark.parametrize("extra", ["ROSY_JOB_ALONE=1", "ROSY_BROWSER_ALONE=1", "ROSY_TEST_PROFILE=other"])
def test_different_execution_environment_keeps_both_occurrences(caller, tmp_path, extra):
    own, delta = [[BROWSER, A, B]], [[BROWSER, extra, A, C]]
    assert choose(caller, tmp_path, own, delta)[1:] == own + delta


@pytest.mark.parametrize("tail", [["-q", A, C], [A + "::test_one", C], ["browser", A],
                                   ["unknown-word", A], ["missing.py", A], [A, BROWSER, C]])
def test_options_nodes_folders_and_unknown_words_keep_exact_argv_behavior(caller, tmp_path, tail):
    own, delta = [[BROWSER, A, B]], [[BROWSER, *tail]]
    assert choose(caller, tmp_path, own, delta)[1:] == own + delta


def test_equivalent_environment_order_keeps_first_chunk_order(caller, tmp_path):
    own = [[BROWSER, "ROSY_TEST_PROFILE=one", A, B]]
    delta = [["ROSY_TEST_PROFILE=one", BROWSER, A, C]]
    assert choose(caller, tmp_path, own, delta)[1:] == own + [["ROSY_TEST_PROFILE=one", BROWSER, C]]


def test_regular_pytest_chunks_are_only_exact_argv_deduplicated(caller, tmp_path):
    own, delta = [[A, B]], [[A, C], [A, B]]
    assert choose(caller, tmp_path, own, delta)[1:] == own + [[A, C]]
