"""D-889 17: narrow cache reuse across a range that is FULL only through main's landed commits."""
import subprocess
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


def _prior_round(repo_pair, changed, sel_extra, monkeypatch, tests="auto"):
    """D-889 37: a pass on ``base``, then main moves by ``changed`` and this branch adds a FULL commit of its own, so
    the range is FULL and _landed_full gives up; ``sel_extra`` is what the selector says about base..head."""
    main, wt = repo_pair
    commit(wt, {"tools/harness/affected_tests.py": ""}, "harness")
    land.land_cache.record(wt, git(wt, "rev-parse", "HEAD"), git(wt, "rev-parse", "HEAD^{tree}"), "env1",
                           ["pkg/test"], Path("log"))
    commit(main, {changed: "x = 1\n"}, "main moves")
    git(wt, "merge", "-q", "--no-edit", "main")
    commit(wt, {"pkg/c.py": "y = 1\n"}, "this branch's FULL fix")
    sel = {"mode": "full", "escalations": [], "unmapped": [], "local_invocations": [["other/test"]], **sel_extra}
    monkeypatch.setattr(land.land_cache, "_selection", lambda *a: sel)
    monkeypatch.setattr(land.land_cache, "_guards_and_browsers", lambda *a: [])
    events = []
    monkeypatch.setattr(land.land_events, "emit", lambda kind, **f: events.append((kind, f)))

    def select(wt_, b, python, head=None, landed=False):
        return [["other/test"]], "FULL"  # the range and the branch's own commit are FULL: no _landed_full
    args = land.argparse.Namespace(tests=tests, no_cache=False)
    return land.land_cache.split(wt, args, [["pkg/test"]], git(wt, "rev-parse", "HEAD"), sys.executable, select), events


def test_prior_round_pass_is_reused_over_a_full_range_that_selects_none_of_its_paths(repos, cached, monkeypatch, capsys):
    (done, todo, _), events = _prior_round(repos, "docs/x.py", {}, monkeypatch)
    assert todo == [] and len(done) == 1
    assert "[cache] reused pkg/test from " in capsys.readouterr().out and "(delta selects none of its paths)" in done[0]
    assert events == [("reuse", {"reused": 1, "prior": 1, "total": 1})]


def test_prior_round_pass_reruns_when_the_range_selects_its_paths(repos, cached, monkeypatch):
    (done, todo, _), events = _prior_round(repos, "docs/x.py", {"local_invocations": [["pkg/test"]]}, monkeypatch)
    assert todo == [["pkg/test"]] and not done and events == []


@pytest.mark.parametrize("changed, sel", [
    ("docs/x.py", {"escalations": ["m.py: safety path (platform_parts concern: safety)"]}),
    ("docs/x.py", {"escalations": ["deploy/compose.yaml: deploy compose manifest"]}),
    ("docs/x.py", {"unmapped": ["docs/x.py"]}),
    ("tools/harness/affected_x.py", {}),           # SELECT_CORE
    ("tools/land_selection.py", {}),
    ("test/known_failures.py", {}),
    ("test/browser_scope.py", {}),
    ("tools/remote/remote_pytest.py", {}),         # RUNNER_TOOLS
    ("tools/land_browser.py", {}),
    ("tools/harness/platform_parts.yaml", {}),     # REGISTRY_FILES
    ("tools/harness/harness.yaml", {}),
    ("conftest.py", {}),
    ("pyproject.toml", {}),
    ("test/known_failures.txt", {}),               # LISTS
    ("test/flaky_quarantine.txt", {}),
])
def test_prior_round_reuse_is_refused_wholesale_for_unknown_reach(repos, cached, monkeypatch, changed, sel):
    (done, todo, _), events = _prior_round(repos, changed, sel, monkeypatch)
    assert todo == [["pkg/test"]] and not done and events == []


def test_prior_round_reuse_is_refused_when_the_range_deletes_a_file(repos, cached, monkeypatch):
    main, wt = repos
    commit(main, {"docs/gone.py": "x = 1\n"}, "main adds")
    git(wt, "merge", "-q", "--no-edit", "main")
    commit(wt, {"tools/harness/affected_tests.py": ""}, "harness")
    land.land_cache.record(wt, git(wt, "rev-parse", "HEAD"), git(wt, "rev-parse", "HEAD^{tree}"), "env1",
                           ["pkg/test"], Path("log"))
    git(main, "rm", "-q", "docs/gone.py")
    git(main, "commit", "-q", "-m", "main deletes")
    git(wt, "merge", "-q", "--no-edit", "main")
    commit(wt, {"pkg/c.py": "y = 1\n"}, "own")
    monkeypatch.setattr(land.land_cache, "_selection", lambda *a: {"mode": "full", "escalations": [], "unmapped": [],
                                                                    "local_invocations": [["other/test"]]})
    monkeypatch.setattr(land.land_cache, "_guards_and_browsers", lambda *a: [])
    args = land.argparse.Namespace(tests="auto", no_cache=False)
    done, todo, _ = land.land_cache.split(wt, args, [["pkg/test"]], git(wt, "rev-parse", "HEAD"), sys.executable,
                                          lambda *a, **k: ([["other/test"]], "FULL"))
    assert todo == [["pkg/test"]] and not done


def test_explicit_full_keeps_the_strict_rule_and_never_uses_the_prior_round_rule(repos, cached, monkeypatch):
    (done, todo, _), events = _prior_round(repos, "docs/x.py", {}, monkeypatch, tests="full")
    assert todo == [["pkg/test"]] and not done and events == []


def _sibling(repo_pair, changed, monkeypatch, select_result):
    """D-889 37: a pass on merge(old main, branch); main then moves by ``changed`` and the candidate is
    merge(new main, branch), which does not descend from the recorded commit. Returns (split result, events)."""
    main, wt = repo_pair
    commit(wt, {"tools/harness/affected_tests.py": ""}, "harness")
    commit(wt, {"pkg/c.py": "y = 1\n"}, "branch work")
    branch = git(wt, "rev-parse", "HEAD")
    commit(main, {"docs/old.py": "x = 1\n"}, "main before")
    git(wt, "merge", "-q", "--no-edit", "main")
    land.land_cache.record(wt, git(wt, "rev-parse", "HEAD"), git(wt, "rev-parse", "HEAD^{tree}"), "env1",
                           ["pkg/test"], Path("log"))
    old = git(wt, "rev-parse", "HEAD")
    git(wt, "reset", "-q", "--hard", branch)
    commit(main, {changed: "x = 2\n"}, "main after")
    git(wt, "merge", "-q", "--no-edit", "main")
    head = git(wt, "rev-parse", "HEAD")
    assert subprocess.run(["git", "-C", str(wt), "merge-base", "--is-ancestor", old, head]).returncode != 0
    monkeypatch.setattr(land.land_cache, "_selection",
                        lambda *a: {"mode": "full", "escalations": [], "unmapped": [], "local_invocations": [["other/test"]]})
    monkeypatch.setattr(land.land_cache, "_guards_and_browsers", lambda *a: [])
    events = []
    monkeypatch.setattr(land.land_events, "emit", lambda kind, **f: events.append((kind, f)))
    asked = []

    def select(wt_, b, python, head=None, landed=False):
        asked.append((b, head))
        return select_result
    args = land.argparse.Namespace(tests="auto", no_cache=False)
    return land.land_cache.split(wt, args, [["pkg/test"]], head, sys.executable, select), events, (old, asked)


def test_sibling_merge_candidate_reuses_suites_the_new_main_commits_did_not_touch(repos, cached, monkeypatch, capsys):
    (done, todo, _), events, (old, asked) = _sibling(repos, "docs/x.py", monkeypatch, ([["other/test"]], None))
    assert todo == [] and len(done) == 1 and "[cache] reused pkg/test from " + old[:10] in capsys.readouterr().out
    assert events == [("reuse", {"reused": 1, "prior": 1, "total": 1})] and asked and asked[0][0] == old


def test_sibling_merge_candidate_reruns_a_suite_the_tree_diff_selects(repos, cached, monkeypatch):
    (done, todo, _), events, _ = _sibling(repos, "docs/x.py", monkeypatch, ([["pkg/test"]], None))
    assert todo == [["pkg/test"]] and not done and events == []


@pytest.mark.parametrize("changed", ["tools/harness/platform_parts.yaml", "tools/remote/remote_pytest.py", "conftest.py"])
def test_a_refused_path_in_the_tree_diff_disables_sibling_reuse(repos, cached, monkeypatch, changed):
    (done, todo, _), events, _ = _sibling(repos, changed, monkeypatch, ([["other/test"]], "FULL"))
    assert todo == [["pkg/test"]] and not done and events == []


def test_a_sibling_row_is_not_used_for_the_explicit_full_rule(repos, cached, monkeypatch):
    main, wt = repos
    args_full = land.argparse.Namespace(tests="full", no_cache=False)
    monkeypatch.setattr(land.land_cache, "_selection",
                        lambda *a: {"mode": "affected", "escalations": [], "unmapped": [], "invocations": [["other/test"]]})
    monkeypatch.setattr(land.land_cache, "_guards_and_browsers", lambda *a: [])
    commit(wt, {"tools/harness/affected_tests.py": ""}, "harness")
    branch = git(wt, "rev-parse", "HEAD")
    commit(main, {"docs/old.py": "x = 1\n"}, "main before")
    git(wt, "merge", "-q", "--no-edit", "main")
    land.land_cache.record(wt, git(wt, "rev-parse", "HEAD"), git(wt, "rev-parse", "HEAD^{tree}"), "env1",
                           ["pkg/test"], Path("log"))
    git(wt, "reset", "-q", "--hard", branch)
    commit(main, {"docs/x.py": "x = 2\n"}, "main after")
    git(wt, "merge", "-q", "--no-edit", "main")
    done, todo, _ = land.land_cache.split(wt, args_full, [["pkg/test"]], git(wt, "rev-parse", "HEAD"), sys.executable,
                                          lambda *a, **k: ([["other/test"]], None))
    assert todo == [["pkg/test"]] and not done


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


def test_warm_main_records_missing_non_dedicated_suites(cached, monkeypatch):
    wt, _, _ = cached
    (wt / "test/architecture").mkdir(parents=True, exist_ok=True)
    sha = git(wt, "rev-parse", "HEAD")
    monkeypatch.setattr(land.land_cache, "env_id", lambda *_: "env1")
    ran = []

    def fake_run(invs, logs, run_sha, repo=None, label=None):
        ran.extend(invs)
        for p in logs:
            p.write_text("1 passed in 0.1s\n", encoding="utf-8")
        return [0] * len(invs)

    monkeypatch.setattr(land.remote_pytest, "run", fake_run)
    done, total = land.land_cache.warm_main(wt, limit=2, main_ref=sha)
    assert (done, total) == (1, 1) and ran == [["test/architecture"]]
    assert land.land_cache.warm_main(wt, limit=2, main_ref=sha) == (0, 0)


def test_paths_extracts_isolation_envs_skips_ignore_and_batches_is_ancestor(cached, monkeypatch):
    wt, _, _ = cached
    head = git(wt, "rev-parse", "HEAD")
    base = head
    cache = land.land_cache
    assert cache._paths(["ROSY_JOB_CORES=6", "ROSY_ALONE_FILES=a/test_a.py,b/test_b.py",
                         "tools/collect_alone.py", "--ignore=test/test_slow.py"]) == [
        "a/test_a.py", "b/test_b.py", "tools/collect_alone.py"]
    assert cache._paths(["ROSY_COLLECT_PATHS=.", "tools/collect_alone.py"]) is None
    assert cache._paths(["pkg/test", "-k", "only"]) is None

    calls = []
    real_git = cache._git
    monkeypatch.setattr(cache, "_git", lambda *a: calls.append(a[1:]) or real_git(*a))
    cache._anc_cache.clear()
    cache._anc_neg.clear()
    assert cache.is_ancestor(wt, base, head) is True
    assert cache.is_ancestor(wt, base, head) is True
    assert len(calls) == 1 and calls[0][:2] == ("rev-list", "-n")


