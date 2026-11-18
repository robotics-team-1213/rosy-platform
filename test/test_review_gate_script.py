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
    sys.stdout.write(os.environ["FAKE_PR_ROWS"])
elif "/commits?" in url:
    sys.stdout.write(os.environ["FAKE_COMMIT_ROWS"])
sys.exit(0)
"""


def _gate(tmp_path, monkeypatch, deletions):
    """Bob changed docs/logs.md on main; alice's PR touches it with `deletions` deleted lines."""
    work = tmp_path / "work"
    work.mkdir()

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
    bin_dir.mkdir()
    (bin_dir / "gh").write_text(FAKE_GH, encoding="utf-8")
    (bin_dir / "gh").chmod(0o755)
    for key, value in {"PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "GH_TOKEN": "x", "REPO": "o/r", "PR": "1",
                       "AUTHOR": "alice", "WINDOW_DAYS": "3650",
                       "FAKE_PR_ROWS": f"docs/logs.md\t{deletions}\n",
                       "FAKE_COMMIT_ROWS": f"{sha}\tbob\n"}.items():
        monkeypatch.setenv(key, value)
    return subprocess.run(["bash", str(SCRIPT)], cwd=work, capture_output=True, text=True)


@pytest.mark.skipif(shutil.which("bash") is None or sys.platform == "win32", reason="needs bash and a posix gh stub")
@pytest.mark.parametrize("deletions,code", [(0, 0), (1, 1)])
def test_append_only_journal_changes_do_not_meet_others_but_an_edited_line_does(tmp_path, monkeypatch, deletions, code):
    result = _gate(tmp_path, monkeypatch, deletions)
    assert result.returncode == code, result.stdout + result.stderr
    assert ("no overlap" in result.stdout) == (code == 0)
