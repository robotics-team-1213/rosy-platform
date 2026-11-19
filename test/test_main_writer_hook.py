"""tools/hooks/reference-transaction: local main moves only through land.py (2026-11-13 main-red)."""

from pathlib import Path
import os
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "tools" / "hooks" / "reference-transaction"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None or shutil.which("git") is None,
                                reason="bash and git are required")


@pytest.fixture
def repo(tmp_path):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_") and k != "ROSY_MAIN_WRITER"}

    def git(*args, writer=None, check=True):
        run_env = {**env, "ROSY_MAIN_WRITER": writer} if writer else env
        return subprocess.run(["git", "-C", str(tmp_path), *args], capture_output=True, text=True,
                              env=run_env, check=check)

    git("init", "-q", "-b", "main")
    git("config", "user.name", "t")
    git("config", "user.email", "t@example.invalid")
    git("commit", "--allow-empty", "-qm", "base")
    hooks = tmp_path / ".git" / "hooks"
    (hooks / "reference-transaction").write_bytes(HOOK.read_bytes().replace(b"\r\n", b"\n"))
    (hooks / "reference-transaction").chmod(0o755)
    return git


def test_commit_on_main_is_refused(repo):
    before = repo("rev-parse", "main").stdout
    result = repo("commit", "--allow-empty", "-qm", "direct", check=False)
    assert result.returncode != 0 and "main-guard" in result.stderr
    assert repo("rev-parse", "main").stdout == before


def test_branch_commit_and_land_fast_forward_pass(repo):
    repo("switch", "-q", "-c", "fix/x")
    repo("commit", "--allow-empty", "-qm", "work")
    repo("switch", "-q", "main")
    assert repo("merge", "--ff-only", "fix/x", check=False).returncode != 0
    repo("merge", "--ff-only", "fix/x", writer="land")
    assert repo("rev-parse", "main").stdout == repo("rev-parse", "fix/x").stdout


def test_sync_to_origin_main_and_noop_rewrite_pass(repo):
    repo("switch", "-q", "-c", "pub")
    repo("commit", "--allow-empty", "-qm", "merge commit on origin")
    repo("update-ref", "refs/remotes/origin/main", "pub")
    repo("switch", "-q", "main")
    repo("merge", "--ff-only", "origin/main")
    repo("pack-refs", "--all")
    assert repo("rev-parse", "main").stdout == repo("rev-parse", "pub").stdout


def test_reset_back_to_origin_main_is_refused(repo):
    repo("update-ref", "refs/remotes/origin/main", "main")
    repo("switch", "-q", "-c", "fix/y")
    repo("commit", "--allow-empty", "-qm", "landed")
    repo("switch", "-q", "main")
    repo("merge", "--ff-only", "fix/y", writer="land")
    assert repo("reset", "-q", "--hard", "origin/main", check=False).returncode != 0
    assert repo("rev-parse", "main").stdout == repo("rev-parse", "fix/y").stdout
