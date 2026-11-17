"""tools/harness/crlf_rule.py: a commit that adds CRLF to a text file fails size_range; LF, old CRLF, old dates and eol=crlf pass."""

from __future__ import annotations

import datetime as dt
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools" / "harness"))

import crlf_rule  # noqa: E402
import size_range  # noqa: E402


def test_crlf_added_to_a_text_file_is_refused(tmp_path, monkeypatch):
    if shutil.which("git") is None:
        pytest.skip("git is required")
    monkeypatch.chdir(tmp_path)
    for key in ("GIT_AUTHOR_NAME", "GIT_COMMITTER_NAME"):
        monkeypatch.setenv(key, "t")
    for key in ("GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL"):
        monkeypatch.setenv(key, "t@x")
    old = (crlf_rule.RULE_SINCE - dt.timedelta(days=1)).isoformat()
    new = (crlf_rule.RULE_SINCE + dt.timedelta(days=1)).isoformat()

    def git(*args):
        return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout.strip()

    def commit(files: dict[str, bytes], when: str) -> str:
        monkeypatch.setenv("GIT_COMMITTER_DATE", when)
        monkeypatch.setenv("GIT_AUTHOR_DATE", when)
        for name, data in files.items():
            (tmp_path / name).write_bytes(data)
        git("add", "-A")
        git("commit", "-q", "--no-verify", "-m", "c")
        return git("rev-parse", "HEAD")

    git("init", "-q", "-b", "main")
    git("config", "core.autocrlf", "false")
    base = commit({"a.py": b"x = 1\n", "legacy.py": b"x = 1\r\ny = 2\r\n", ".gitattributes": b"*.bat eol=crlf\n"}, old)
    crlf = commit({"a.py": b"x = 1\r\ny = 2\r\n"}, new)
    lf = commit({"a.py": b"x = 1\ny = 2\n"}, new)
    already = commit({"legacy.py": b"x = 1\r\ny = 3\r\n"}, new)
    bat = commit({"run.bat": b"echo\r\n"}, new)
    binary = commit({"img.png": b"\0\r\n\0"}, new)
    grandfathered = commit({"b.py": b"x\r\n"}, old)
    assert crlf_rule.problems(crlf, size_range._git) and "a.py" in crlf_rule.problems(crlf, size_range._git)[0]
    for ok in (lf, already, bat, binary, grandfathered):
        assert crlf_rule.problems(ok, size_range._git) == []
    assert size_range.main([base, crlf]) == 1
    assert size_range.main([crlf, bat]) == 0
