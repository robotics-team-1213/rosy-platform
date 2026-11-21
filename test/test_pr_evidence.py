"""tools/pr_evidence.py: lists pr_land's lab invocations, records only clean remote passes."""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import pr_evidence  # noqa: E402


def _repo(tmp_path):
    for cmd in (["init", "-q"], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "x"]):
        subprocess.run(["git", "-C", str(tmp_path), *cmd], check=True)
    return tmp_path


def _fakes(monkeypatch, invs):
    monkeypatch.setattr(pr_evidence.pr_land, "required_lab_invocations", lambda cwd, base, head: invs)
    monkeypatch.setattr(pr_evidence.pr_land, "lab_missing", lambda cwd, head, required: list(required))
    monkeypatch.setattr(pr_evidence.land_cache, "env_id", lambda cwd, head: "e" * 8)
    rows = []
    monkeypatch.setattr(pr_evidence.land_cache, "record", lambda *a: rows.append(a))
    monkeypatch.setattr(pr_evidence.land_browser, "vacuous", lambda inv, log: False)
    return rows


def test_dry_run_lists_and_runs_nothing(tmp_path, monkeypatch, capsys):
    repo = _repo(tmp_path)
    _fakes(monkeypatch, [["test/a.py"]])
    assert pr_evidence.main(["HEAD", "--dry-run"], repo=repo, run=lambda *a, **k: 1 / 0) == 0
    assert "test/a.py" in capsys.readouterr().out


def test_records_only_clean_passes(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    rows = _fakes(monkeypatch, [["test/a.py"], ["test/b.py"]])
    monkeypatch.setattr(pr_evidence.land_checks, "tmp_dir", lambda name: tmp_path)

    def run(invs, logs, sha, repo=None, label=None):
        assert invs[0] == ["test/a.py", "-rA"]
        logs[0].write_text("PASSED test/a.py::t\n", encoding="utf-8")
        logs[1].write_text("FAILED test/b.py::t\n", encoding="utf-8")
        return [0, 1]

    assert pr_evidence.main(["HEAD"], repo=repo, run=run) == 1
    assert [r[4] for r in rows] == [["test/a.py"]]


def test_exit5_all_skipped_is_a_verdict_but_other_exit5_is_not(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    rows = _fakes(monkeypatch, [["test/a.py"], ["test/b.py"]])
    monkeypatch.setattr(pr_evidence.pr_land, "lab_missing", lambda cwd, head, required: required)
    monkeypatch.setattr(pr_evidence.land_checks, "tmp_dir", lambda name: tmp_path)

    def run(invs, logs, sha, repo=None, label=None):
        logs[0].write_text("SKIPPED [1] test/a.py:3: no rclpy\n== 1 skipped in 0.10s ==\n", encoding="utf-8")
        logs[1].write_text("no tests ran in 0.01s\n", encoding="utf-8")
        return [5, 5]

    assert pr_evidence.main(["HEAD"], repo=repo, run=run) == 1
    assert [r[4] for r in rows] == [["test/a.py"]]


def test_solo_runs_one_invocation_per_call_alone_and_records_only_passes(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    rows = _fakes(monkeypatch, [["test/a.py"], ["test/b.py"]])
    monkeypatch.setattr(pr_evidence.pr_land, "lab_missing", lambda cwd, head, required: required)
    monkeypatch.setattr(pr_evidence.land_checks, "tmp_dir", lambda name: tmp_path)
    calls = []

    def run(invs, logs, sha, repo=None, label=None):
        calls.append(invs)
        logs[0].write_text("PASSED x::t\n" if "test/a.py" in invs[0] else "FAILED x::t\n", encoding="utf-8")
        return [0 if "test/a.py" in invs[0] else 1]

    assert pr_evidence.main(["HEAD", "--solo"], repo=repo, run=run) == 1
    assert calls == [[["ROSY_JOB_ALONE=1", "test/a.py", "-rA"]], [["ROSY_JOB_ALONE=1", "test/b.py", "-rA"]]]
    assert [r[4] for r in rows] == [["test/a.py"]]
    assert (tmp_path / "solo.txt").read_text(encoding="utf-8") == "test/a.py\ntest/b.py\n"


def test_an_intact_earlier_pass_is_kept_and_not_rerun(tmp_path, monkeypatch, capsys):
    repo = _repo(tmp_path)
    rows = _fakes(monkeypatch, [["test/a.py"], ["test/b.py"]])
    monkeypatch.setattr(pr_evidence.pr_land, "lab_missing", lambda cwd, head, required: [["test/b.py"]])
    monkeypatch.setattr(pr_evidence.land_checks, "tmp_dir", lambda name: tmp_path)
    ran = []

    def run(invs, logs, sha, repo=None, label=None):
        ran.extend(invs)
        logs[0].write_text("PASSED test/b.py::t\n", encoding="utf-8")
        return [0]

    assert pr_evidence.main(["HEAD"], repo=repo, run=run) == 0
    assert ran == [["test/b.py", "-rA"]] and [r[4] for r in rows] == [["test/b.py"]]
    assert "1 kept" in capsys.readouterr().out
    monkeypatch.setattr(pr_evidence.pr_land, "lab_missing", lambda cwd, head, required: [])
    assert pr_evidence.main(["HEAD"], repo=repo, run=lambda *a, **k: 1 / 0) == 0


def test_placement_lines_remote_pytest_prints_are_kept_in_placement_txt(tmp_path, monkeypatch, capsys):
    repo = _repo(tmp_path)
    _fakes(monkeypatch, [["test/a.py"]])
    monkeypatch.setattr(pr_evidence.land_checks, "tmp_dir", lambda name: tmp_path)

    def run(invs, logs, sha, repo=None, label=None):
        print("[remote-pytest] ai: 20.0 cores, 90.0 GB free - ok", file=sys.stderr)
        print("[remote-pytest] pytest -> ai")
        logs[0].write_text("PASSED test/a.py::t\n", encoding="utf-8")
        return [0]

    assert pr_evidence.main(["HEAD"], repo=repo, run=run) == 0
    assert (tmp_path / "placement.txt").read_text(encoding="utf-8") == (
        "[remote-pytest] ai: 20.0 cores, 90.0 GB free - ok\n[remote-pytest] pytest -> ai\n")
    captured = capsys.readouterr()  # still shown on the console
    assert "pytest -> ai" in captured.out and "ai: 20.0 cores" in captured.err


def test_each_run_writes_new_logs_so_recorded_hashes_stay_valid(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    _fakes(monkeypatch, [["test/a.py"]])
    names = []
    monkeypatch.setattr(pr_evidence.land_checks, "tmp_dir", lambda name: names.append(name) or tmp_path)
    times = iter(["20261120T090000", "20261120T090001"])
    monkeypatch.setattr(pr_evidence.time, "strftime", lambda fmt: next(times))

    def run(invs, logs, sha, repo=None, label=None):
        logs[0].write_text("PASSED test/a.py::t\n", encoding="utf-8")
        return [0]

    pr_evidence.main(["HEAD"], repo=repo, run=run)
    pr_evidence.main(["HEAD"], repo=repo, run=run)
    assert len(set(names)) == 2
