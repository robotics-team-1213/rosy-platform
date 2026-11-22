"""The review gate script parses and keeps the strict mode its own comment relies on (a failing git log inside
$(...) must fail the gate, not read as "no overlap"). Naming the path here also maps it for the affected selector:
on 2026-11-02 it was "unknown -> full" and sent a landing's turn back (D-889)."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / ".github/review-gate.sh"


@pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")
def test_review_gate_script_parses():
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True)


def test_review_gate_script_keeps_its_strict_mode():
    text = SCRIPT.read_text(encoding="utf-8")
    assert "set -euo pipefail" in text and "shopt -s inherit_errexit" in text

FAKE_GH = """#!/usr/bin/env python3
import os, sys
args = sys.argv[1:]
url = next((a for a in args if a.startswith("repos/")), "")
if "/pulls/1/files" in url:
    sys.stdout.write(os.environ.get("FAKE_PR_ROWS", ""))
elif "/pulls/1/reviews" in url:
    sys.stdout.write(os.environ.get("FAKE_REVIEW_BODIES", ""))
elif url.endswith("/pulls/1"):
    sys.stdout.write(os.environ.get("FAKE_PR_BODY", ""))
elif "/pulls?state=open" in url:
    sys.stdout.write(os.environ.get("FAKE_OPEN_PRS", ""))
elif "/pulls/2/files" in url:
    sys.stdout.write(os.environ.get("FAKE_OPEN_FILES", ""))
elif "/commits?" in url:
    sys.stdout.write(os.environ.get("FAKE_COMMIT_ROWS", ""))
sys.exit(0)
"""


def _gate(tmp_path, monkeypatch, deletions, **extra_env):
    """Bob changed docs/logs.md on main; alice's PR touches it with `deletions` deleted lines."""
    work = tmp_path / "work"
    work.mkdir(parents=True, exist_ok=True)

    def git(*a):
        return subprocess.run(["git", "-C", str(work), *a], check=True, capture_output=True, text=True).stdout.strip()
    git("init", "-q", "-b", "main")
    git("config", "user.email", "b@example.com")
    git("config", "user.name", "bob")
    (work / "docs").mkdir()
    (work / "docs/logs.md").write_text("one\n", encoding="utf-8")
    git("add", "docs/logs.md")
    git("commit", "-qm", "bob")
    git("update-ref", "refs/remotes/origin/main", "HEAD")
    sha = git("rev-parse", "HEAD")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    (bin_dir / "gh").write_text(FAKE_GH, encoding="utf-8")
    (bin_dir / "gh").chmod(0o755)
    env = {"PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "GH_TOKEN": "x", "REPO": "o/r", "PR": "1",
           "AUTHOR": "alice", "WINDOW_DAYS": "3650",
           "FAKE_PR_ROWS": f"docs/logs.md\t{deletions}\n",
           "FAKE_COMMIT_ROWS": f"{sha}\tbob\n"}
    env.update(extra_env)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return subprocess.run(["bash", str(SCRIPT)], cwd=work, capture_output=True, text=True)


@pytest.mark.skipif(shutil.which("bash") is None or sys.platform == "win32", reason="needs bash and a posix gh stub")
@pytest.mark.parametrize("deletions,code", [(0, 0), (1, 1)])
def test_append_only_journal_changes_do_not_meet_others_but_an_edited_line_does(tmp_path, monkeypatch, deletions, code):
    result = _gate(tmp_path, monkeypatch, deletions)
    assert result.returncode == code, result.stdout + result.stderr
    assert ("no overlap" in result.stdout) == (code == 0)


@pytest.mark.skipif(shutil.which("bash") is None or sys.platform == "win32", reason="needs bash and a posix gh stub")
def test_open_pr_only_default_and_self_review_unblock(tmp_path, monkeypatch):
    # Default WINDOW_DAYS=0 ignores merged main commits and blocks only on another active open PR unless acked.
    r1 = _gate(tmp_path / "a", monkeypatch, 1, WINDOW_DAYS="0")
    assert r1.returncode == 0, r1.stdout + r1.stderr
    r2 = _gate(tmp_path / "b", monkeypatch, 1, WINDOW_DAYS="0",
               FAKE_OPEN_PRS="bob 2\n", FAKE_OPEN_FILES="bob\tdocs/logs.md\n", FAKE_PR_BODY="plain body")
    assert r2.returncode == 1
    r3 = _gate(tmp_path / "c", monkeypatch, 1, WINDOW_DAYS="0",
               FAKE_OPEN_PRS="bob 2\n", FAKE_OPEN_FILES="bob\tdocs/logs.md\n",
               FAKE_PR_BODY="Overlap-Review: self (coordinated solo)")
    assert r3.returncode == 0, r3.stdout + r3.stderr


RECHECK_WF = Path(__file__).resolve().parents[1] / ".github/workflows/review-gate-recheck.yml"

RECHECK_FAKE_GH = """#!/usr/bin/env python3
import os, sys
args = sys.argv[1:]
url = next((a for a in args if a.startswith("repos/")), "")
if "pulls?state=open" in url:
    sys.stdout.write(os.environ.get("FAKE_OPEN", ""))
elif url.endswith("/rerun"):
    with open(os.environ["RERUN_LOG"], "a", encoding="utf-8") as fh:
        fh.write(url + "\\n")
elif "/files?" in url:
    pr = url.split("/pulls/")[1].split("/")[0]
    sys.stdout.write(os.environ.get(f"FAKE_FILES_{pr}", ""))
elif "/runs?" in url:
    sha = url.split("head_sha=")[1].split("&")[0]
    sys.stdout.write(os.environ.get(f"FAKE_RUN_{sha}", ""))
"""


def test_review_gate_recheck_contract_and_bash_syntax(tmp_path):
    import yaml

    doc = yaml.safe_load(RECHECK_WF.read_text(encoding="utf-8"))
    triggers = doc.get("on", doc.get(True))
    assert "ready_for_review" in triggers["pull_request"]["types"]
    assert doc["concurrency"] == {
        "group": "review-gate-recheck-${{ github.event.pull_request.number || 'push' }}",
        "cancel-in-progress": True,
    }
    step = doc["jobs"]["recheck"]["steps"][0]
    script = step["run"]
    assert "export LC_ALL=C" in script and "comm -12" in script and "conclusion" in script and "PR_DRAFT" in step["env"]
    if shutil.which("bash") is not None and sys.platform != "win32":
        p = tmp_path / "recheck.sh"
        p.write_text(script, encoding="utf-8")
        subprocess.run(["bash", "-n", str(p)], check=True)


@pytest.mark.skipif(shutil.which("bash") is None or sys.platform == "win32", reason="needs bash and a posix gh stub")
def test_review_gate_recheck_filters_by_draft_author_overlap_and_failure(tmp_path):
    import yaml

    script = yaml.safe_load(RECHECK_WF.read_text(encoding="utf-8"))["jobs"]["recheck"]["steps"][0]["run"]
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text(RECHECK_FAKE_GH, encoding="utf-8")
    gh.chmod(0o755)
    rerun_log = tmp_path / "reruns.txt"
    base_env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "GH_TOKEN": "x", "REPO": "o/r",
                "IGNORE_USERS": "codex", "RERUN_LOG": str(rerun_log)}

    def run_recheck(extra):
        rerun_log.unlink(missing_ok=True)
        res = subprocess.run(["bash", "-e", "-c", script], capture_output=True, text=True, env={**base_env, **extra})
        assert res.returncode == 0, res.stdout + res.stderr
        return rerun_log.read_text(encoding="utf-8").splitlines() if rerun_log.exists() else []

    assert run_recheck({"EVENT_NAME": "pull_request", "CURRENT": "1", "PR_DRAFT": "true",
                        "PR_AUTHOR": "alice", "PR_AUTHOR_TYPE": "User", "FAKE_OPEN": "2\tfalse\ts2\tbob\tUser\n"}) == []
    assert run_recheck({"EVENT_NAME": "pull_request", "CURRENT": "1", "PR_DRAFT": "false",
                        "PR_AUTHOR": "rosy[bot]", "PR_AUTHOR_TYPE": "Bot"}) == []
    pr_reruns = run_recheck({
        "EVENT_NAME": "pull_request", "CURRENT": "1", "PR_DRAFT": "false",
        "PR_AUTHOR": "alice", "PR_AUTHOR_TYPE": "User",
        "FAKE_OPEN": ("2\tfalse\ts2\tbob\tUser\n3\tfalse\ts3\talice\tUser\n"
                      "4\ttrue\ts4\tcarol\tUser\n5\tfalse\ts5\tdave\tUser\n6\tfalse\ts6\tcodex\tUser\n"),
        "FAKE_FILES_1": "a.py\n", "FAKE_FILES_2": "a.py\n", "FAKE_FILES_3": "a.py\n",
        "FAKE_FILES_4": "a.py\n", "FAKE_FILES_5": "b.py\n", "FAKE_FILES_6": "a.py\n",
        "FAKE_RUN_s2": "202\tcompleted\tsuccess\n",
    })
    assert pr_reruns == ["repos/o/r/actions/runs/202/rerun"]
    push_reruns = run_recheck({
        "EVENT_NAME": "push", "CURRENT": "", "PR_DRAFT": "", "PR_AUTHOR": "", "PR_AUTHOR_TYPE": "",
        "FAKE_OPEN": "10\tfalse\ts10\n11\tfalse\ts11\n12\ttrue\ts12\n",
        "FAKE_RUN_s10": "1010\tcompleted\tsuccess\n",
        "FAKE_RUN_s11": "1011\tcompleted\tfailure\n",
        "FAKE_RUN_s12": "1012\tcompleted\tfailure\n",
    })
    assert push_reruns == ["repos/o/r/actions/runs/1011/rerun"]
