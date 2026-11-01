"""D-889 17: narrow cache reuse across a range that is FULL only through main's landed commits."""
import sys
from pathlib import Path

import pytest

from test_land import cached, commit, git, land, repos  # noqa: F401


@pytest.mark.parametrize("own_fix, own_full, delta_picks, reused", [
    (False, False, [["other/test"]], True),         # main's FULL delta maps elsewhere: the pass stands
    (False, False, [["pkg/test/test_a.py"]], False),  # main's delta maps to this invocation: rerun
    (True, False, [["other/test"]], True),          # plus a fix commit of this branch that selects other tests
    (True, True, [["other/test"]], False),          # a fix commit of this branch that is FULL itself
])
def test_a_full_range_through_mains_landed_commits_keeps_untouched_passes(repos, cached, own_fix, own_full,
                                                                          delta_picks, reused):
    """11-01: 30 of 40 sampled narrow tries were FULL, mostly main's landing-tool and harness changes."""
    main, _ = repos
    wt, run, calls = cached
    commit(wt, {"tools/harness/affected_tests.py": ""}, "harness")
    land.land_cache.record(wt, git(wt, "rev-parse", "HEAD"), git(wt, "rev-parse", "HEAD^{tree}"), "env1",
                           ["pkg/test"], Path("log"))
    base = git(wt, "rev-parse", "HEAD")
    commit(main, {"tools/land_x.py": "x = 1\n"}, "main changes the landing tools")
    git(wt, "merge", "-q", "--no-edit", "main")
    if own_fix:
        commit(wt, {"pkg/c.py": "y = 1\n"}, "this branch's fix")
    fix = git(wt, "rev-parse", "HEAD") if own_fix else None
    asked = []

    def select(wt_, b, python, head=None, landed=False):
        asked.append((b, head, landed))
        if landed:
            return delta_picks, None
        if head == fix and b == f"{fix}^":
            return [["fix/test"]], ("FULL" if own_full else None)
        return [["other/test"]], "FULL"  # base..head as a whole: FULL through main's landing tools
    args = land.argparse.Namespace(tests="auto", no_cache=False)
    done, todo, _ = land.land_cache.split(wt, args, [["pkg/test"]], git(wt, "rev-parse", "HEAD"), sys.executable,
                                          select)
    assert (todo, bool(done)) == (([], True) if reused else ([["pkg/test"]], False))
    assert ((f"{fix}^", fix, False) in asked) == own_fix, "each own commit of the branch is selected by itself"
    assert any(b == base and landed for b, _, landed in asked) == (not (own_fix and own_full))
