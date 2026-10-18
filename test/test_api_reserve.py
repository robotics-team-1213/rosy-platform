"""tools/harness/api_reserve.py: API reference versions claimed like ADR numbers (D-510)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import api_reserve

REF = "docs/reference/ROSY API & Protocol Reference.md"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True,
                          text=True, encoding="utf-8").stdout


def _repo(path: Path) -> Path:
    path.mkdir(parents=True)
    _git(path, "init", "-q", "-b", "main")
    _git(path, "config", "user.email", "t@example.invalid")
    _git(path, "config", "user.name", "t")
    return path


def _reference(version: int, *rows: int) -> str:
    changelog = "".join(f"### v1.{n} change {n}\n\n" for n in rows)
    return f"﻿# Ref\n\n**Version:** v1.{version}\n\n{changelog}"


def _commit(repo: Path, files: dict[str, str], message: str) -> None:
    for rel, text in files.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_bytes(text.encode("utf-8"))
        _git(repo, "add", rel)
    _git(repo, "commit", "-qm", message)


def test_next_claims_above_branches_remotes_worktrees_and_refs(tmp_path, monkeypatch, capsys):
    repo = _repo(tmp_path / "r")
    _commit(repo, {REF: _reference(5, 5, 4)}, "base")
    for branch, version in (("other", 6), ("stray", 500)):
        _git(repo, "checkout", "-qb", branch, "main")
        _commit(repo, {REF: _reference(version, version, 5, 4)}, branch)
    _git(repo, "checkout", "-q", "main")
    _git(repo, "update-ref", "refs/remotes/origin/other", "other")
    _git(repo, "branch", "-qD", "other")  # v1.6 now exists only on a remote-tracking ref
    _git(repo, "worktree", "add", "-q", "-b", "wip", str(tmp_path / "wt"), "main")
    (tmp_path / "wt" / REF).write_bytes(_reference(7, 7, 5, 4).encode("utf-8"))  # uncommitted
    monkeypatch.chdir(repo)

    assert api_reserve.main(["next", "first topic"]) == 0
    out = capsys.readouterr()
    assert out.out.strip() == "v1.8"
    assert "ignoring v1.500 (more than 20 above main's v1.5) from stray" in out.err
    assert "highest in use: v1.7 from " in out.err and "wt" in out.err
    assert api_reserve.main(["next", "second topic"]) == 0
    assert capsys.readouterr().out.strip() == "v1.9"

    # A peer claimed v1.10 after our scan: create-only update-ref fails, the tool moves on.
    _git(repo, "update-ref", "refs/api/v1.10", "HEAD")
    monkeypatch.setattr(api_reserve, "used_numbers", lambda: {9: "test"})
    assert api_reserve.main(["next", "raced"]) == 0
    assert capsys.readouterr().out.strip() == "v1.11"

    api_reserve.main(["list"])
    listing = capsys.readouterr().out.splitlines()
    assert [line.split("\t")[0] for line in listing] == ["v1.8", "v1.9", "v1.10", "v1.11"]
    assert "first topic" in listing[0]
    assert api_reserve.main(["release", "v1.8"]) == 1  # not proven to be ours
    assert "reserved for 'first topic'" in capsys.readouterr().err
    assert api_reserve.main(["release", "v1.8", "--reason", "first topic"]) == 0
    assert capsys.readouterr().out.strip() == "released v1.8 (first topic)"
    assert api_reserve.main(["release", "v1.9", "--force"]) == 0
    assert _git(repo, "for-each-ref", "--format=%(refname)", "refs/api").split() == [
        "refs/api/v1.10", "refs/api/v1.11"]
    assert _git(repo, "for-each-ref", "--format=%(refname)", "refs/adr") == ""  # namespaces apart


def test_bump_rewrites_only_live_version_pins(tmp_path, monkeypatch, capsys):
    repo = _repo(tmp_path / "b")
    app = "core_api_web/api/app.py"
    files = {
        REF: _reference(9, 9, 8).replace("\n", "\r\n"),
        app: ('"""factory. 계약: ROSY-API-REF-001 v1.9."""\n'
              'DESC = "계약: ROSY-API-REF-001 (v1.9)"\n'
              'OLD = "added in v1.9"\n'),
        "test/test_pin.py": ('    assert "**Version:** v1.9" in reference\n'
                             '    assert header and "v1.9" in header[0]\n'
                             '    assert "v1.90" not in reference\n'),
        "logs.md": "## 2026-10-15 · 계약 버전 v1.9\n**Version:** v1.8 was before\n",
    }
    _commit(repo, files, "base")
    _git(repo, "update-ref", "refs/api/v1.10", "HEAD")
    monkeypatch.chdir(repo)

    assert api_reserve.main(["bump", "v1.10"]) == 0
    out = capsys.readouterr()
    assert "v1.9 -> v1.10: 5 pins" in out.out
    assert f"warning: {app}:3 still names v1.9" in out.err

    reference = (repo / REF).read_bytes().decode("utf-8")
    assert reference.startswith("﻿") and "\r\n**Version:** v1.10\r\n" in reference
    assert "### v1.9 change 9\r\n" in reference  # changelog history stays
    assert (repo / app).read_text(encoding="utf-8") == (
        '"""factory. 계약: ROSY-API-REF-001 v1.10."""\n'
        'DESC = "계약: ROSY-API-REF-001 (v1.10)"\n'
        'OLD = "added in v1.9"\n')
    assert (repo / "test/test_pin.py").read_text(encoding="utf-8") == (
        '    assert "**Version:** v1.10" in reference\n'
        '    assert header and "v1.10" in header[0]\n'
        '    assert "v1.90" not in reference\n')
    assert (repo / "logs.md").read_text(encoding="utf-8") == files["logs.md"]

    assert api_reserve.main(["bump", "v1.10"]) == 0
    assert capsys.readouterr().out.strip() == "already v1.10"
    assert api_reserve.main(["bump", "v1.12"]) == 0
    assert "v1.12 is not reserved here" in capsys.readouterr().err


def test_list_survives_a_cp949_console(tmp_path, monkeypatch):
    import io
    import sys

    repo = _repo(tmp_path / "c")
    _commit(repo, {"a": "a\n"}, "base")
    monkeypatch.chdir(repo)
    assert api_reserve.main(["next", "drive — hold"]) == 0
    console = io.TextIOWrapper(io.BytesIO(), encoding="cp949")
    monkeypatch.setattr(sys, "stdout", console)
    assert api_reserve.main(["list"]) == 0
    console.flush()
    assert "v1.1\t" in console.buffer.getvalue().decode("cp949")
