"""Publication needs executed canonical FULL evidence, including real browser chunks."""

from argparse import Namespace
import sys

import pytest

from test_publish_main import FULL, _commit, _git, _view, repo, tool
import land_cache


@pytest.mark.parametrize("legacy", [False, True])
def test_tier_or_root_test_marker_without_execution_proof_never_qualifies(repo, monkeypatch, legacy):
    local, _ = repo
    sha = _commit(local, "app.py", "unproven FULL")
    tool.land_record.write(local, sha, _git(local, "rev-parse", f"{sha}^"), FULL, [],
                           tier=None if legacy else "full")
    assert tool.publish_sha(local) is None
    calls = []
    monkeypatch.setattr(tool, "run_gh", lambda _, *args: calls.append(args) or _view(local, sha))
    with pytest.raises(tool.Stop, match="no green FULL"):
        tool.merge_when_green(local, "7", True, tool.datetime.now(tool.timezone.utc))
    assert not any(args[:2] == ("pr", "merge") for args in calls)


def test_no_cache_forbids_reuse_but_preserves_fresh_exact_execution_proof(repo, monkeypatch, tmp_path):
    local, _ = repo
    sha = _commit(local, "app.py", "fresh evidence")
    inv = ["test"]
    monkeypatch.setattr(land_cache, "env_id", lambda *_: "fixture-env")
    reused, todo, keep = land_cache.split(local, Namespace(no_cache=True, tests="full"), [inv],
                                         sha, sys.executable, None)
    log = tmp_path / "fresh.txt"
    log.write_text("1 passed in 0.01s\n", encoding="utf-8")
    keep(inv, log)
    assert reused == [] and todo == [inv]
    row, = land_cache.entries(local)
    assert (row["commit"], row["tree"], row["env"], row["argv"], row["log"]) == (
        sha, _git(local, "rev-parse", f"{sha}^{{tree}}"), "fixture-env", inv, str(log))
