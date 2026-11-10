"""tools/land_precheck.py: the cheap gates fail in the owner's terminal, before land_async makes a snapshot or ticket."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Stop(Exception):
    pass


def fake_land(tmp_path, fail=None, merged=True):
    (tmp_path / "h.py").write_text("")
    calls = []

    def gate(name):
        def run(*args):
            calls.append(name)
            if fail == name:
                raise Stop(name)
        return run
    return calls, SimpleNamespace(
        Stop=Stop, HARNESS="h.py", out=lambda *a: "main-sha", lines=lambda *a: [], safety_review=gate("safety"), size_check=gate("size"),
        step=lambda wt, cmd, log, label: gate("lint")(), secret_scan=gate("secret"),
        git=lambda *a, **k: SimpleNamespace(returncode=0 if merged else 1))


def test_every_cheap_gate_runs_in_order(tmp_path):
    calls, land = fake_land(tmp_path)
    load("land_precheck").precheck(land, tmp_path, "python")
    assert calls == ["safety", "size", "lint", "secret"]


@pytest.mark.parametrize("gate,after", [("safety", []), ("size", ["safety"]), ("lint", ["safety", "size"]),
                                        ("secret", ["safety", "size", "lint"])])
def test_the_first_failing_gate_stops_the_rest(tmp_path, gate, after):
    calls, land = fake_land(tmp_path, fail=gate)
    with pytest.raises(Stop):
        load("land_precheck").precheck(land, tmp_path, "python")
    assert calls == [*after, gate]


def test_lint_before_main_is_merged_is_advisory_only(tmp_path, capsys):
    calls, land = fake_land(tmp_path, fail="lint", merged=False)
    load("land_precheck").precheck(land, tmp_path, "python")
    assert calls[-1] == "secret" and "supervisor re-lints" in capsys.readouterr().out


def test_land_async_stops_before_any_snapshot_when_the_precheck_fails(monkeypatch):
    tool = load("land_async")
    seen = []
    monkeypatch.setattr(tool.subprocess, "call", lambda argv, **k: seen.append(argv) or 1)
    monkeypatch.setattr(tool, "start", lambda *a, **k: pytest.fail("a snapshot was made after a failed precheck"))
    assert tool.main(["--tests", "auto"]) == 1
    assert seen[0][-1] == "--precheck" and seen[0][1].endswith("land.py")


def test_land_async_queues_after_a_passing_precheck(monkeypatch, tmp_path):
    tool = load("land_async")
    monkeypatch.setattr(tool.subprocess, "call", lambda argv, **k: 0)
    monkeypatch.setattr(tool, "start", lambda *a, **k: ("land/x", tmp_path / "x.log"))
    assert tool.main(["--tests", "auto"]) == 0


def _git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def eol_repo(tmp_path):
    """main holds LF a.py, CRLF old.py and a ``-text`` bin.dat; HEAD is a branch off it. Raw bytes, no autocrlf."""
    _git(tmp_path, "init", "-q", "-b", "main")
    for key, value in (("user.email", "t@example.invalid"), ("user.name", "t"), ("core.autocrlf", "false")):
        _git(tmp_path, "config", key, value)
    (tmp_path / ".gitattributes").write_bytes(b"*.dat -text\n")
    (tmp_path / "a.py").write_bytes(b"a\nb\nc\nd\ne\n")
    (tmp_path / "old.py").write_bytes(b"x\r\ny\r\n")
    (tmp_path / "bin.dat").write_bytes(b"p\nq\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "base")
    _git(tmp_path, "switch", "-qc", "feat/x")
    return tmp_path


def commit(repo, files):
    for name, data in files.items():
        (repo / name).write_bytes(data)
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "edit")


def real_land():
    sys.path.insert(0, str(ROOT / "tools"))
    import land
    return land


def test_crlf_added_names_text_files_that_gain_crlf_only(eol_repo):
    commit(eol_repo, {"a.py": b"a\r\nb\r\n", "new.md": b"n\r\n", "old.py": b"x\r\ny\r\nz\r\n",
                      "bin.dat": b"p\r\n", "lf.py": b"ok\n"})
    land = real_land()
    changed = land.lines(eol_repo, "diff", "--name-only", "main...HEAD")
    # old.py was CRLF at the base already; bin.dat is -text and keeps its bytes
    assert load("land_precheck").crlf_added(land, eol_repo, "main", changed) == ["a.py", "new.md"]


def test_precheck_refuses_a_branch_adding_crlf_with_the_fix_command(eol_repo):
    commit(eol_repo, {"a.py": b"a\r\nb\r\n"})
    with pytest.raises(real_land().Stop, match=r'CRLF.*a\.py.*git add --renormalize -- "a\.py"'):
        load("land_precheck").precheck(real_land(), eol_repo, sys.executable)
    # the printed fix (core.autocrlf=false here, so the text attribute does the converting)
    (eol_repo / ".gitattributes").write_bytes(b"*.dat -text\n*.py text\n")
    _git(eol_repo, "add", "--renormalize", "--", "a.py")
    assert _git(eol_repo, "ls-files", "--eol", "a.py").startswith("i/lf")


def test_landing_merge_ignores_a_line_ending_only_difference(eol_repo):
    """main stores a.py CRLF, the branch stores it LF; each edits a different line. Plain git: whole-file conflict."""
    _git(eol_repo, "switch", "-q", "main")
    commit(eol_repo, {"a.py": b"a\r\nb\r\nc\r\nd\r\nE\r\n"})
    _git(eol_repo, "switch", "-q", "feat/x")
    commit(eol_repo, {"a.py": b"a\nB\nc\nd\ne\n", ".gitattributes": b"*.dat -text\n*.py text\n"})
    plain = ["merge-tree", "--write-tree", "--no-messages", "HEAD", "main"]
    assert subprocess.run(["git", "-C", str(eol_repo), *plain], capture_output=True).returncode == 1
    tree = _git(eol_repo, "merge-tree", "--write-tree", "--no-messages", *real_land().RENORMALIZE, "HEAD", "main")
    assert _git(eol_repo, "cat-file", "-p", f"{tree}:a.py") == "a\nB\nc\nd\nE"
