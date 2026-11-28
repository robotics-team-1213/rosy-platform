"""tools/land_freeze.py: the cutover state file and every landing path that must read it (D-1055 panel 11-20)."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tools" / "remote"))

import land_freeze  # noqa: E402

NOW = datetime(2026, 11, 20, 1, 0, 0, tzinfo=timezone.utc)


def _git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    main = tmp_path / "main"
    main.mkdir()
    _git(main, "init", "-q", "-b", "main")
    _git(main, "config", "user.email", "t@example.invalid")
    _git(main, "config", "user.name", "t")
    (main / "a.txt").write_text("1\n")
    _git(main, "add", "a.txt")
    _git(main, "commit", "-q", "-m", "base")
    dev = tmp_path / "dev"
    _git(main, "worktree", "add", "-q", "-b", "feat/x", str(dev))
    (dev / "a.txt").write_text("2\n")
    _git(dev, "commit", "-qam", "change")
    return main, dev


def state_file(main):
    return Path(_git(main, "rev-parse", "--path-format=absolute", "--git-common-dir")) / "rosy-cutover.json"


def freeze(main, phase, *allowed):
    for branch, sha in allowed:
        assert land_freeze.main(["allow", branch, sha]) == 0
    assert land_freeze.main(["set", phase, "--owner", "coord"]) == 0


@pytest.fixture(autouse=True)
def no_real_gh(monkeypatch):
    """land_freeze.main syncs GitHub variables; no test may reach the real gh."""
    real_run = subprocess.run

    def run(cmd, **kwargs):
        if cmd[:3] == ["gh", "variable", "set"]:
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return real_run(cmd, **kwargs)

    monkeypatch.setattr(land_freeze.subprocess, "run", run)


@pytest.fixture(autouse=True)
def in_main(repo, monkeypatch):
    monkeypatch.chdir(repo[0])  # the CLI works on the cwd's clone


def test_missing_file_is_normal_and_changes_nothing(repo):
    main, dev = repo
    assert not state_file(main).exists()
    assert land_freeze.load(main)["phase"] == "normal"
    assert land_freeze.refusal(dev, "feat/x") is None
    assert land_freeze.refusal(dev, "feat/x", new=False) is None


def test_cli_writes_atomically_and_shows(repo, capsys):
    main, dev = repo
    sha = _git(dev, "rev-parse", "HEAD")
    freeze(main, "drain", ("feat/x", sha))
    data = json.loads(state_file(main).read_text(encoding="utf-8"))
    assert data["phase"] == "drain" and data["owner"] == "coord" and data["updated"]
    assert data["allow"] == [{"branch": "feat/x", "sha": sha}]
    assert not list(state_file(main).parent.glob("rosy-cutover.json.*"))  # no temp leftovers
    capsys.readouterr()
    assert land_freeze.main(["show"]) == 0
    assert "rosy-cutover.json" in capsys.readouterr().out
    assert land_freeze.main(["allow", "feat/x", sha, "--remove"]) == 0
    assert land_freeze.load(main)["allow"] == []
    assert land_freeze.main(["set", "bogus"]) == 2
    assert land_freeze.main(["allow", "feat/x", "nope"]) == 1


def test_drain_refuses_unallowed_and_names_the_file(repo):
    main, dev = repo
    freeze(main, "drain")
    why = land_freeze.refusal(dev, "feat/x")
    assert why and "\n" not in why and "rosy-cutover.json" in why and "drain" in why
    with pytest.raises(SystemExit, match="rosy-cutover.json"):
        land_freeze.guard(dev, "feat/x")


def test_drain_allows_the_pinned_sha_and_snapshots_with_main_merged_in(repo):
    main, dev = repo
    freeze(main, "drain", ("feat/x", _git(dev, "rev-parse", "HEAD")))
    assert land_freeze.refusal(dev, "feat/x") is None
    (main / "b.txt").write_text("m\n")  # main moves; the snapshot merges it in
    _git(main, "add", "b.txt")
    _git(main, "commit", "-q", "-m", "main moves")
    _git(main, "branch", "land/feat/x-1", "feat/x")
    _git(main, "checkout", "-q", "land/feat/x-1")
    _git(main, "merge", "-q", "--no-edit", "main")
    _git(main, "checkout", "-q", "main")
    assert land_freeze.refusal(main, "land/feat/x-1", new=False) is None


def test_race_allowed_list_changing_mid_landing_keeps_sha_binding(repo):
    main, dev = repo
    old = _git(dev, "rev-parse", "HEAD")
    freeze(main, "drain", ("feat/x", old))
    assert land_freeze.refusal(dev, "feat/x", new=False) is None  # allowed when it started
    (dev / "a.txt").write_text("3\n")  # the branch moved on: a different sha
    _git(dev, "commit", "-qam", "newer")
    _git(main, "branch", "land/feat/x-2", "feat/x")
    assert land_freeze.refusal(main, "land/feat/x-2", new=False)  # the old sha does not cover it
    land_freeze.main(["allow", "feat/x", old, "--remove"])  # allowed list changes mid-landing
    assert land_freeze.refusal(dev, old, new=False)  # the last guard refuses what is no longer allowed
    land_freeze.main(["allow", "feat/x", _git(dev, "rev-parse", "HEAD")])
    assert land_freeze.refusal(main, "land/feat/x-2", new=False) is None


def test_unreadable_state_is_drain_with_nothing_allowed(repo):
    main, dev = repo
    state_file(main).write_text("{not json", encoding="utf-8")
    assert land_freeze.load(main)["phase"] == "drain"
    assert "unreadable" in land_freeze.refusal(dev, "feat/x")
    assert land_freeze.main(["set", "normal"]) == 0  # the CLI repairs it
    assert land_freeze.refusal(dev, "feat/x") is None


def test_open_refuses_new_on_publish_only_clone_but_running_ones_drain(repo):
    main, dev = repo
    freeze(main, "open")
    assert land_freeze.refusal(dev, "feat/x") is None  # not a publishOnly clone
    _git(main, "config", "rosy.publishOnly", "true")
    assert "pr_land" in land_freeze.refusal(dev, "feat/x")
    assert land_freeze.refusal(dev, "feat/x", new=False) is None  # the last guard: it drains
    hidden = main / ".git" / "rosy-land-wt" / "t"
    hidden.mkdir(parents=True)
    assert land_freeze.refusal(hidden, "feat/x") is None  # a landing already in a hidden tree


def test_set_syncs_github_variables_and_warns_only_on_gh_failure(repo, monkeypatch, capsys):
    main, dev = repo
    sha = _git(dev, "rev-parse", "HEAD")
    assert land_freeze.main(["allow", "feat/x", sha]) == 0
    calls = []
    real_run = subprocess.run

    def fake_run(cmd, **kwargs):
        if cmd[:3] == ["gh", "variable", "set"]:
            calls.append((cmd, kwargs.get("cwd")))
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return real_run(cmd, **kwargs)

    monkeypatch.setattr(land_freeze.subprocess, "run", fake_run)
    assert land_freeze.main(["set", "drain"]) == 0
    assert calls == [
        (["gh", "variable", "set", "ROSY_CUTOVER_PHASE", "--body", "drain"], str(main)),
        (["gh", "variable", "set", "ROSY_CUTOVER_ALLOW", "--body", sha], str(main)),
    ]

    def failing_run(cmd, **kwargs):
        if cmd[:3] == ["gh", "variable", "set"]:
            return subprocess.CompletedProcess(cmd, 1, "", "gh auth missing")
        return real_run(cmd, **kwargs)

    monkeypatch.setattr(land_freeze.subprocess, "run", failing_run)
    assert land_freeze.main(["set", "normal"]) == 0
    assert land_freeze.load(main)["phase"] == "normal"
    assert "warning: gh variable set" in capsys.readouterr().err

    calls.clear()

    def recording_run(cmd, **kwargs):
        if cmd[:3] == ["gh", "variable", "set"]:
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return real_run(cmd, **kwargs)

    monkeypatch.setattr(land_freeze.subprocess, "run", recording_run)
    assert land_freeze.main(["allow", "feat/x", sha, "--remove"]) == 0
    assert ["gh", "variable", "set", "ROSY_CUTOVER_ALLOW", "--body", ""] in calls
