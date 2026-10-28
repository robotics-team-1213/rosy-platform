"""pre-push 훅의 지켜볼 것들 (D-346·D-347 회차).

훅 전체를 돌리는 건 push 자체와 같아서 시험로는 무겁다 — 여기선 두 가지만 고정한다:
파싱이 살아있고, '재생성됐지만 미커밋인 생성 기록은 push 를 막는다'는 가드가
스크립트에 존재한다. 가드의 실동 증명은 실제 push 에서 보인다(2026-09-29 두 건의
CI 적신이 이 가드의 명세다).
"""

from pathlib import Path
import os
import re
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "hooks" / "pre-push"
BASH = shutil.which("bash")


@pytest.mark.skipif(BASH is None, reason="bash is required")
@pytest.mark.parametrize("owed", ["first.py\nsecond.py", "first.py\r\nsecond.py\r"])
def test_owed_suites_accept_windows_python_line_endings(owed):
    line = next(line for line in SCRIPT.read_text(encoding="utf-8").splitlines()
                if "mapfile -t OWED_SUITES" in line)
    result = subprocess.run([BASH, "-c", line + '\nprintf "%s\\0" "${OWED_SUITES[@]}"'],
                            env={**os.environ, "OWED": owed}, capture_output=True, check=True)
    assert result.stdout == b"first.py\0second.py\0"


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
    assert "affected --base" in text and "--json" in text
    assert "--full" not in text, "the full suite runs on GitHub runners, never in the hook"
    assert '--skip "$suite"' in text and '"${FAST_SUITES[@]}"' in text, (
        "the affected run skips the fast suites the hook already ran (review: guards ran twice)")


@pytest.mark.skipif(BASH is None, reason="bash is required")
def test_pytest_runs_through_the_remote_runner_on_the_pushed_commit():
    """2026-10-08: pytest runs on the model PC / AI PC, never directly in the hook."""
    text = SCRIPT.read_text(encoding="utf-8")
    assert '-m pytest' not in text, "pytest goes through tools/remote/remote_pytest.py"
    assert 'tools/remote/remote_pytest.py --sha "$PUSH_SHA"' in text
    stdin_part = text.split("# Git exports repository-local", 1)[0].split("set -euo pipefail", 1)[1]
    probe = stdin_part.replace('cd "$(git rev-parse --show-toplevel)"', "") + 'echo "$PUSH_SHA"'
    lines = (f"refs/heads/gone {'0' * 40} refs/heads/gone abc\n"  # a deletion: skipped
             f"refs/heads/x {'1' * 40} refs/heads/x {'0' * 40}\n")
    pushed = subprocess.run([BASH, "-c", probe, "hook", "origin", "url"], input=lines,
                            capture_output=True, text=True, cwd=ROOT)
    assert pushed.stdout.strip() == "1" * 40, pushed.stderr


@pytest.mark.skipif(BASH is None or shutil.which("git") is None, reason="bash and git are required")
@pytest.mark.parametrize("refs, config, reason, allowed", [
    (["publish/main-20261026"], "true", "", True),
    (["feat/x"], "true", "", False),
    (["publish/main-20261026", "main"], "true", "", False),  # one ungated ref refuses the push
    (["feat/x"], "true", "incident 42", True),
    (["feat/x"], None, "", True),                            # teammates' clones are not gated
])
def test_publish_only_clone_pushes_publish_branches_only(tmp_path, refs, config, reason, allowed):
    """D-868: the shared agent clone reaches origin only through publish/main-* PRs."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_") and k != "ROSY_PUSH_REASON"}
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, env=env)
    if config:
        subprocess.run(["git", "-C", str(tmp_path), "config", "rosy.publishOnly", config], check=True, env=env)
    text = SCRIPT.read_text(encoding="utf-8")
    stdin_part = text.split("# Git exports repository-local", 1)[0].split("set -euo pipefail", 1)[1]
    probe = stdin_part.replace('cd "$(git rev-parse --show-toplevel)"', "")
    lines = f"refs/heads/gone {'0' * 40} refs/heads/gone abc\n"  # a deletion is never gated
    lines += "".join(f"refs/heads/b {'1' * 40} refs/heads/{ref} {'0' * 40}\n" for ref in refs)
    pushed = subprocess.run([BASH, "-c", probe, "hook", "origin", "url"], input=lines, capture_output=True,
                            text=True, cwd=tmp_path, env={**env, "ROSY_PUSH_REASON": reason})
    assert (pushed.returncode == 0) == allowed, pushed.stderr
    if not allowed:
        assert "ROSY_PUSH_REASON" in pushed.stderr


@pytest.mark.skipif(BASH is None, reason="bash is required")
@pytest.mark.parametrize("ref, scanned", [("publish/main-20261027", "1"), ("feat/x", "")])
def test_only_a_publish_ref_runs_the_secret_scan_before_safety_review(ref, scanned):
    """2026-10-27: a plain git push to publish/main-* skipped publish_main.py's per-commit secret scan."""
    text = SCRIPT.read_text(encoding="utf-8")
    scan = text.index('tools/publish_main.py --secret-scan "$PUSH_SHA"')
    assert scan < text.index("safety_review.py origin/main"), "scan before the slower range checks"
    stdin_part = text.split("# Git exports repository-local", 1)[0].split("set -euo pipefail", 1)[1]
    probe = stdin_part.replace('cd "$(git rev-parse --show-toplevel)"', "") + 'echo "$PUBLISH_REF"'
    line = f"refs/heads/b {'1' * 40} refs/heads/{ref} {'0' * 40}\n"
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    pushed = subprocess.run([BASH, "-c", probe, "hook", "origin", "url"], input=line, capture_output=True,
                            text=True, cwd=ROOT, env={**env, "ROSY_PUSH_REASON": "test"})
    assert pushed.stdout.strip() == scanned, pushed


@pytest.mark.skipif(BASH is None or shutil.which("git") is None, reason="bash and git are required")
@pytest.mark.parametrize("same", [True, False])
def test_a_stale_installed_copy_refuses_the_push(tmp_path, same):
    """2026-10-26: the shared clone ran a 10-11 copy for two weeks; a copy unlike the pushed hook stops."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_") and k != "ROSY_PUSH_REASON"}
    git = lambda *a: subprocess.run(["git", "-C", str(tmp_path), *a], check=True, env=env,
                                    capture_output=True, text=True).stdout.strip()
    git("init", "-q")
    git("config", "rosy.publishOnly", "true")
    stdin_part = SCRIPT.read_text(encoding="utf-8").split("# Git exports repository-local", 1)[0]
    installed = tmp_path / "installed-pre-push"
    installed.write_text(stdin_part.replace('cd "$(git rev-parse --show-toplevel)"', ""), encoding="utf-8")
    tracked = tmp_path / "tools/hooks/pre-push"
    tracked.parent.mkdir(parents=True)
    tracked.write_text(installed.read_text(encoding="utf-8") + ("" if same else "# newer gate\n"), encoding="utf-8")
    git("add", "tools/hooks/pre-push")
    git("-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-qm", "hook")
    line = f"refs/heads/b {git('rev-parse', 'HEAD')} refs/heads/publish/main-20261026 {'0' * 40}\n"
    pushed = subprocess.run([BASH, str(installed), "origin", "url"], input=line, capture_output=True,
                            text=True, cwd=tmp_path, env=env)
    assert (pushed.returncode == 0) == same, pushed.stderr
    if not same:
        assert "install.sh" in pushed.stderr


def _safety_step_repo(tmp_path, manifest="roots:\n  - path: safe\n    concern: safety\n"):
    """A throwaway clone layout: the real safety_review.py (BASELINE = its root commit) and a safety root."""
    def git(*args):
        return subprocess.run(["git", "-C", str(tmp_path), *args], check=True, capture_output=True,
                              text=True).stdout.strip()

    def commit(files, message):
        for name, data in files.items():
            (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
            (tmp_path / name).write_bytes(data if isinstance(data, bytes) else data.encode())
        git("add", "--", *files)
        git("commit", "-q", "--no-verify", "-m", message)

    git("init", "-q", "-b", "main")
    git("config", "user.name", "Peer Author")
    git("config", "user.email", "p@example.invalid")
    commit({"README": "x\n"}, "root")
    rule = re.sub(r'BASELINE = "[0-9a-f]{40}"', f'BASELINE = "{git("rev-parse", "HEAD")}"',
                  (ROOT / "tools/harness/safety_review.py").read_text(encoding="utf-8"), count=1)
    files = {"tools/harness/safety_review.py": rule, "tools/harness/platform_parts.yaml": manifest,
             "safe/stop.py": "LIMIT = 1\n"}
    for data in sorted((ROOT / "tools/harness").glob("safety_review_*")):
        files[f"tools/harness/{data.name}"] = data.read_bytes()
    commit(files, "rule\n\nSafety-Review: t unit")
    git("update-ref", "refs/remotes/origin/main", "HEAD")
    return git, commit


def _run_safety_step(repo, **env):
    """The hook's Safety-Review step, exactly as written, in `repo`."""
    step = (SCRIPT.read_text(encoding="utf-8").split("# No origin/main would narrow", 1)[1]
            .split("\n", 1)[1].split("FAST_SUITES=(", 1)[0])
    head = 'set -euo pipefail\nPUSH_SHA="$(git rev-parse HEAD)"\n'
    return subprocess.run([BASH, "-c", head + step], cwd=repo, capture_output=True, text=True,
                          env={**os.environ, "PY": sys.executable, **env})


@pytest.mark.skipif(BASH is None, reason="bash is required")
def test_only_publish_mains_own_check_of_this_sha_skips_the_repeated_scans(tmp_path):
    """D-889: publish_main --apply passed the secret scan and Safety-Review for this SHA just before its push."""
    git, commit = _safety_step_repo(tmp_path, "roots:\n  - path: safe\n    concern: safety\n")
    commit({"safe/stop.py": "LIMIT = 2\n"}, "loosen")  # no trailer: the step refuses it when it runs
    sha = git("rev-parse", "HEAD").strip()
    assert _run_safety_step(tmp_path, PUBLISH_REF="", ROSY_PUBLISH_CHECKED=sha).returncode == 1  # a branch push
    assert _run_safety_step(tmp_path, PUBLISH_REF="1", ROSY_PUBLISH_CHECKED="0" * 40).returncode == 1
    skipped = _run_safety_step(tmp_path, PUBLISH_REF="1", ROSY_PUBLISH_CHECKED=sha)
    assert skipped.returncode == 0 and "publish_main.py passed them" in skipped.stdout, skipped.stderr


@pytest.mark.skipif(BASH is None, reason="bash is required")
def test_publish_mains_push_skips_the_size_rule_every_other_push_runs_it(tmp_path):
    """Each landing ran the size rule on its commits and CI reruns it on the range; 40+ min here (2026-10-28)."""
    git, commit = _safety_step_repo(tmp_path, "roots: []\n")
    commit({"app.py": "x = 1\n"}, "change\n\nSafety-Review: t unit")
    sha = git("rev-parse", "HEAD").strip()
    (tmp_path / "tools/harness/size_range.py").write_text("import sys\nprint('SIZE-RAN')\nsys.exit(1)\n")
    ran = _run_safety_step(tmp_path, PUBLISH_REF="1", ROSY_PUBLISH_CHECKED="0" * 40)
    assert ran.returncode == 1 and "SIZE-RAN" in ran.stdout, ran.stderr  # a plain push to publish/main-*
    assert _run_safety_step(tmp_path, PUBLISH_REF="", ROSY_PUBLISH_CHECKED=sha).returncode == 1  # a branch push
    skipped = _run_safety_step(tmp_path, PUBLISH_REF="1", ROSY_PUBLISH_CHECKED=sha)
    assert skipped.returncode == 0 and "SIZE-RAN" not in skipped.stdout, skipped.stderr


@pytest.mark.skipif(BASH is None, reason="bash is required")
@pytest.mark.parametrize("case", ["trailer", "missing", "no-origin", "crash"])
def test_safety_step_refuses_the_range_ci_checks(tmp_path, case):
    """D-762 stage 0: origin/main..tip, the range a push to main makes CI check, refused not warned."""
    manifest = "roots: [unclosed\n" if case == "crash" else "roots:\n  - path: safe\n    concern: safety\n"
    git, commit = _safety_step_repo(tmp_path, manifest)
    commit({"safe/stop.py": "LIMIT = 2\n"}, "loosen" + ("\n\nSafety-Review: t unit" if case == "trailer" else ""))
    if case == "no-origin":
        git("update-ref", "-d", "refs/remotes/origin/main")
    result = _run_safety_step(tmp_path)
    assert result.returncode == (0 if case == "trailer" else 1), result.stderr
    assert ("safety_review_exempt.json" in result.stderr) == (case == "missing")
    if case == "missing":
        assert "Peer Author" in result.stderr and "loosen" in result.stderr
    if case == "no-origin":
        assert "no origin/main ref" in result.stderr


INSTALLER = ROOT / "tools" / "hooks" / "install.sh"
INSTALL_BASH = (str(Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Git/bin/bash.exe")
                if os.name == "nt" else BASH)


@pytest.mark.skipif(not INSTALL_BASH or not Path(INSTALL_BASH).is_file(), reason="native bash is required")
@pytest.mark.parametrize("location", ["default", "relative", "absolute", "tracked"])
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
    source.write_bytes(SCRIPT.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    git(parent, "add", "tools/hooks/pre-push")
    git(parent, "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "fixture")
    linked = tmp_path / "linked worktree"
    git(parent, "worktree", "add", "-qb", "linked", str(linked))
    if location != "default":
        configured = {"relative": ".local hooks", "tracked": "tools/hooks"}.get(location, (tmp_path / "external hooks").as_posix())
        git(linked, "config", "core.hooksPath", configured)
    hook_dir = Path(git(linked, "rev-parse", "--git-path", "hooks"))
    if not hook_dir.is_absolute(): hook_dir = linked / hook_dir
    config_before = (parent / ".git/config").read_bytes()
    refs_before = git(parent, "show-ref")
    result = subprocess.run([INSTALL_BASH, "-c", INSTALLER.read_text(encoding="utf-8")],
                            cwd=linked, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if location == "tracked":
        assert result.returncode != 0
        assert (linked / "tools/hooks/pre-push").read_bytes() == source.read_bytes()
        assert (parent / ".git/config").read_bytes() == config_before
        assert git(parent, "show-ref") == refs_before
        return
    assert result.returncode == 0, result.stderr
    installed = hook_dir / "pre-push"
    assert installed.read_bytes() == (linked / "tools/hooks/pre-push").read_bytes().replace(b"\r\n", b"\n")
    parse = subprocess.run([INSTALL_BASH, "-n", installed.as_posix()], capture_output=True)
    assert parse.returncode == 0, parse.stderr
    assert (linked / ".git").is_file()
    assert (parent / ".git/config").read_bytes() == config_before
    assert git(parent, "show-ref") == refs_before


@pytest.mark.skipif(BASH is None or shutil.which("git") is None, reason="bash and git are required")
@pytest.mark.parametrize("checkout", ["moved", "staged", "same"])
def test_selection_reads_the_pushed_commit_not_the_checkout(tmp_path, checkout):
    """robot-4d 2026-10-26: main moved past PUSH_SHA, the selector read the checkout and sent tests absent
    from the pushed commit (pytest exit 4). The selector's test list (Repo.load) comes from PUSH_SHA."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    git = lambda *a: subprocess.run(["git", "-C", str(tmp_path), *a], check=True, env=env,
                                    capture_output=True, text=True).stdout.strip()
    git("init", "-q", "-b", "main")
    for name, text in {"tools/harness/harness.yaml": "modules: []\n",
                       "tools/harness/platform_parts.yaml": "roots: []\n", "test/test_old.py": ""}.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(text, encoding="utf-8")
    commit = lambda m: git("-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-qm", m)
    git("add", ".")
    commit("pushed")
    pushed = git("rev-parse", "HEAD")
    (tmp_path / "test/test_extra.py").write_text("", encoding="utf-8")
    git("add", "test/test_extra.py")
    if checkout != "staged":
        commit("main moved on")
    if checkout == "same":
        pushed = git("rev-parse", "HEAD")
    step = SCRIPT.read_text(encoding="utf-8").split("done < <(git rev-parse --local-env-vars)", 1)[1].split('PY=""', 1)[0]
    probe = (f'set -euo pipefail\nPUSH_SHA={pushed}\n{step}\n"$PY" -c "import sys; sys.path.insert(0, sys.argv[1]);'
             f' import affected_tests as a, pathlib; print(a.Repo.load(pathlib.Path(\'.\')).test_files)"'
             f' {(ROOT / "tools/harness").as_posix()}\npwd -W 2>/dev/null || pwd\n')
    result = subprocess.run([BASH, "-c", probe], cwd=tmp_path, capture_output=True, text=True,
                            env={**env, "PY": sys.executable})
    assert result.returncode == 0, result.stderr
    selected, where = result.stdout.strip().splitlines()[-2:]
    assert ("test_extra.py" in selected) == (checkout == "same"), result.stdout
    assert "test/test_old.py" in selected
    assert (Path(where).resolve() == tmp_path.resolve()) == (checkout == "same")
    assert len(git("worktree", "list").splitlines()) == 1, "the detached copy is removed on exit"
