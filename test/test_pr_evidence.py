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
