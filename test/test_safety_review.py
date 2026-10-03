"""D-430 §5 trailer check (tools/harness/safety_review.py) on throwaway git repos."""

import shutil
import subprocess

import pytest
import yaml

import safety_review

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is required")

TRAILER = "Safety-Review: verifier lane docs/x.md"


def _manifest(modules=(), anchors=()):
    return yaml.safe_dump({
        "roots": [{"path": "pkg", "concern": "control"}, {"path": "guard", "concern": "safety"}],
        "safety_modules": list(modules),
        "safety_anchors": [{"symbol": symbol} for symbol in anchors],
    })


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for key, value in {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x", "GIT_COMMITTER_NAME": "t",
                       "GIT_COMMITTER_EMAIL": "t@x"}.items():
        monkeypatch.setenv(key, value)

    def git(*args):
        return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout.strip()

    def commit(files, message="change", *, trailer=False):
        for path, text in files.items():
            (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
            (tmp_path / path).write_text(text, encoding="utf-8")
        git("add", "-A")
        git("commit", "-q", "--no-verify", "-m", message, *(["-m", TRAILER] if trailer else []))
        return git("rev-parse", "HEAD")

    git("init", "-q", "-b", "main")
    git("config", "core.autocrlf", "false")
    base = commit({safety_review.MANIFEST: _manifest(anchors=["pkg.x.Stop"]), "pkg/x.py": "a = 1\n",
                   "guard/g.py": "g = 1\n"}, "root")
    monkeypatch.setattr(safety_review, "BASELINE", base)
    git.commit, git.base = commit, base
    return git


def test_branch_forked_before_the_tag_still_needs_the_trailer(repo):
    repo("checkout", "-q", "-b", "feat")
    touched = repo.commit({"pkg/x.py": "a = 2\n"}, "edit x before it was tagged")
    repo("checkout", "-q", "main")
    tag = repo.commit({safety_review.MANIFEST: _manifest(modules=["pkg/x.py"], anchors=["pkg.x.Stop"])}, "tag x")
    repo("merge", "-q", "--no-ff", "--no-edit", "feat")
    assert safety_review.main([tag, "HEAD"]) == 1
    reasons = safety_review.needs_review(touched, (safety_review._manifest("HEAD"),))
    assert reasons == ["touches pkg/x.py"]
    assert safety_review.needs_review(repo("rev-parse", "HEAD"), (safety_review._manifest("HEAD"),)) == []


def test_trailer_satisfies_and_safety_root_edits_need_it(repo):
    start = repo.commit({"pkg/x.py": "a = 3\n"}, "control only")
    assert safety_review.main([start, "HEAD"]) == 0
    repo.commit({"guard/g.py": "g = 2\n"}, "guard edit", trailer=True)
    assert safety_review.main([start, "HEAD"]) == 0
    repo.commit({"guard/g.py": "g = 3\n"}, "guard edit without trailer")
    assert safety_review.main([start, "HEAD"]) == 1


def test_removing_an_anchor_is_a_safety_change(repo):
    repo.commit({safety_review.MANIFEST: _manifest()}, "drop anchor")
    assert safety_review.needs_review(repo("rev-parse", "HEAD"), ()) == ["untags anchor:pkg.x.Stop"]
    assert safety_review.main([repo.base, "HEAD"]) == 1


def test_new_branch_or_force_push_checks_only_the_tip_and_exempt_skips(repo, monkeypatch):
    old = repo.commit({"guard/g.py": "g = 9\n"}, "old untrailered safety edit")
    repo.commit({"pkg/x.py": "a = 4\n"}, "tip")
    for base in ("", "0" * 40, "deadbeef" * 5):
        assert safety_review.commits(safety_review.resolve_base(base, "HEAD"), "HEAD") == [repo("rev-parse", "HEAD")]
        assert safety_review.main([base, "HEAD"]) == 0
    assert safety_review.main([repo.base, "HEAD"]) == 1
    monkeypatch.setattr(safety_review, "EXEMPT", {old: "reviewed: test"})
    assert safety_review.main([repo.base, "HEAD"]) == 0
