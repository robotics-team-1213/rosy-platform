"""pre-push 훅의 지켜볼 것들 (D-346·D-347 회차).

훅 전체를 돌리는 건 push 자체와 같아서 시험로는 무겁다 — 여기선 두 가지만 고정한다:
파싱이 살아있고, '재생성됐지만 미커밋인 생성 기록은 push 를 막는다'는 가드가
스크립트에 존재한다. 가드의 실동 증명은 실제 push 에서 보인다(2026-09-29 두 건의
CI 적신이 이 가드의 명세다).
"""

from pathlib import Path
import os
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "hooks" / "pre-push"
BASH = shutil.which("bash")


@pytest.mark.skipif(BASH is None or shutil.which("git") is None, reason="bash and git are required")
def test_hook_clears_repository_environment_before_foreign_repo_fixtures(tmp_path):
    # Exercise the actual hook initialization against disposable real Git repos.
    # Exported hook variables override git -C, including fixture config/commits.
    clean_env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}

    def git(directory, *args):
        return subprocess.run(["git", "-C", str(directory), *args], check=True,
                              capture_output=True, text=True, env=clean_env).stdout.strip()

    parent = tmp_path / "parent"
    parent.mkdir()
    git(parent, "init", "-q")
    git(parent, "config", "user.name", "parent")
    git(parent, "config", "user.email", "parent@example.invalid")
    git(parent, "commit", "--allow-empty", "-qm", "parent")
    linked = tmp_path / "linked"
    git(parent, "worktree", "add", "-q", "-b", "linked", str(linked))
    common = parent / ".git"
    git_dir = Path(git(linked, "rev-parse", "--absolute-git-dir"))
    config_before = (common / "config").read_bytes()
    refs_before = git(parent, "show-ref")
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    hook_env = {**clean_env, "GIT_DIR": str(git_dir), "GIT_COMMON_DIR": str(common),
                "GIT_WORK_TREE": str(linked), "GIT_INDEX_FILE": str(git_dir / "index")}
    initialization = SCRIPT.read_text(encoding="utf-8").split('PY=""', 1)[0]
    probe = initialization + '''
git -C "$1" init -q
git -C "$1" config user.name fixture
git -C "$1" config user.email fixture@example.invalid
git -C "$1" commit --allow-empty -qm fixture
'''
    completed = subprocess.run([BASH, "-c", probe, "hook-probe", foreign.as_posix()],
                               cwd=linked, env=hook_env, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
    assert (common / "config").read_bytes() == config_before
    assert git(parent, "show-ref") == refs_before
    assert git(foreign, "config", "user.name") == "fixture"
    assert git(foreign, "log", "-1", "--format=%s") == "fixture"


@pytest.mark.skipif(BASH is None, reason="bash is required")
def test_the_hook_parses():
    assert subprocess.run([BASH, "-n", str(SCRIPT)], capture_output=True).returncode == 0


@pytest.mark.skipif(BASH is None, reason="bash is required")
def test_regenerated_but_uncommitted_records_block_the_push():
    text = SCRIPT.read_text(encoding="utf-8")
    assert "uncommitted generated records" in text, (
        "the dirty-generated guard must stay in the hook: a push with a "
        "regenerated-but-uncommitted index ships the stale committed copy "
        "(red CI on 2026-09-29, twice)"
    )
    assert "generated_targets(repo)" in text, (
        "the guard must enumerate the exact harness targets, not a glob — "
        "an unrelated index.md must never block a push"
    )


@pytest.mark.skipif(BASH is None, reason="bash is required")
def test_affected_tier_runs_after_the_fast_gate():
    """D-436: the affected tier is added on top of the fast gate, never instead of it."""
    text = SCRIPT.read_text(encoding="utf-8")
    fast = text.index("test/test_release_boundary_guards.py")
    step = text.index("rosy_harness.py affected")
    assert fast < step, "the fast suites must stay ahead of the affected tier"
    assert "affected --base" in text and "--run" in text
    assert "--full" not in text, "the full suite runs on GitHub runners, never in the hook"
    assert '--skip "$suite"' in text and '"${FAST_SUITES[@]}"' in text, (
        "the affected run skips the fast suites the hook already ran (review: guards ran twice)")


INSTALLER = ROOT / "tools" / "hooks" / "install.sh"
INSTALL_BASH = (str(Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Git/bin/bash.exe")
                if os.name == "nt" else BASH)


@pytest.mark.skipif(not INSTALL_BASH or not Path(INSTALL_BASH).is_file(), reason="native bash is required")
@pytest.mark.parametrize("location", ["default", "relative", "absolute"])
def test_installer_uses_the_hooks_path_git_uses_from_a_linked_worktree(tmp_path, location):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    def git(root, *args):
        return subprocess.run(["git", "-C", str(root), *args], check=True, env=env,
                              capture_output=True, text=True).stdout.strip()
    parent = tmp_path / "parent repo"
    parent.mkdir()
    git(parent, "init", "-q")
    source = parent / "tools/hooks/pre-push"
    source.parent.mkdir(parents=True)
    source.write_bytes(SCRIPT.read_bytes())
    git(parent, "add", "tools/hooks/pre-push")
    git(parent, "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "fixture")
    linked = tmp_path / "linked worktree"
    git(parent, "worktree", "add", "-qb", "linked", str(linked))
    if location != "default":
        configured = ".local hooks" if location == "relative" else (tmp_path / "external hooks").as_posix()
        git(linked, "config", "core.hooksPath", configured)
    hook_dir = Path(git(linked, "rev-parse", "--git-path", "hooks"))
    if not hook_dir.is_absolute(): hook_dir = linked / hook_dir
    config_before = (parent / ".git/config").read_bytes()
    refs_before = git(parent, "show-ref")
    result = subprocess.run([INSTALL_BASH, "-c", INSTALLER.read_text(encoding="utf-8")],
                            cwd=linked, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert result.returncode == 0, result.stderr
    assert (hook_dir / "pre-push").read_bytes() == (linked / "tools/hooks/pre-push").read_bytes()
    assert (linked / ".git").is_file()
    assert (parent / ".git/config").read_bytes() == config_before
    assert git(parent, "show-ref") == refs_before
