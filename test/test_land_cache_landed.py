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


def test_narrow_reuse_skips_non_ancestor_sibling_commits_in_shared_cache(cached):
    """Non-ancestor commits from concurrent worktrees must not consume the NARROW_COMMITS budget."""
    wt, _, _ = cached
    commit(wt, {"tools/harness/affected_tests.py": ""}, "harness")
    ancestor = git(wt, "rev-parse", "HEAD")
    land.land_cache.record(wt, ancestor, git(wt, "rev-parse", "HEAD^{tree}"), "env1", ["pkg/test"], Path("log"))
    for n in range(land.land_cache.NARROW_COMMITS + 2):
        land.land_cache.record(wt, f"{n + 1:040x}", f"{n + 100:040x}", "env1", ["pkg/test"], Path("log"))
    commit(wt, {"pkg/b.py": "y = 1\n"}, "delta")
    asked = []
    select = lambda wt_, base, python, head=None: (asked.append(base) or [["other/test"]], None)
    args = land.argparse.Namespace(tests="auto", no_cache=False)
    done, todo, _ = land.land_cache.split(wt, args, [["pkg/test"]], git(wt, "rev-parse", "HEAD"), sys.executable,
                                          select)
    assert todo == [] and len(done) == 1 and asked == [ancestor]
    # A second split on the same range (e.g. gpre and pre threads) reuses the memoized delta paths.
    done2, todo2, _ = land.land_cache.split(wt, args, [["pkg/test"]], git(wt, "rev-parse", "HEAD"), sys.executable,
                                            select)
    assert todo2 == [] and len(done2) == 1 and asked == [ancestor]


def test_generate_records_handles_title_with_unhashable_frontmatter_dict(tmp_path):
    """07571bd128 passed fm: dict as the second argument of _title(p, fm); lru_cache must not hash the dict."""
    import land_merge

    (tmp_path / "tools" / "harness").mkdir(parents=True)
    (tmp_path / "docs").mkdir(parents=True)
    script = tmp_path / land.HARNESS
    script.write_text(
        "from pathlib import Path\n"
        "def _optional_frontmatter(p): return {'title': 'T'}\n"
        "def _title(p, meta=None):\n"
        "    meta = _optional_frontmatter(p) if meta is None else meta\n"
        "    return meta.get('title') or p.stem\n"
        "def generated_targets(repo):\n"
        "    p = repo / 'docs/index.md'\n"
        "    return {p: _title(p, {'title': 'FromDict'}) + '/' + _title(p, {}) + '\\n'}\n"
        "def generate(repo):\n"
        "    targets = generated_targets(repo)\n"
        "    for p, text in targets.items(): p.write_text(text, encoding='utf-8')\n"
        "    return list(targets)\n",
        encoding="utf-8",
    )
    written = land_merge.generate_records(tmp_path, sys.executable, land.HARNESS)
    assert written == ["docs/index.md"]
    assert (tmp_path / "docs/index.md").read_text(encoding="utf-8") == "FromDict/T\n"

