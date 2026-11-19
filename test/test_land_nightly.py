"""tools/land_nightly.py: the night's complete FULL tier (D-889 addendum 12)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import land_nightly  # noqa: E402
import land_record  # noqa: E402  (tools/hooks, put on sys.path by land_nightly)
from publish_fixtures import BROWSERS, FULL  # noqa: E402
from test_publish_main import _commit, repo, tool  # noqa: E402,F401


def test_the_night_runs_full_plus_every_browser_suite_and_records_new_failures_as_main_red(tmp_path, monkeypatch):
    answers = {"tools/harness/rosy_harness.py": {"full_invocations": [["test"], ["integrations/simulation/gazebo/test"]]},
               "tools/land_selection.py": [["ROSY_RUN_BROWSER_TESTS=1", "a/test_x_browser.py"]]}
    monkeypatch.setattr(land_nightly, "_json", lambda *command: answers[command[0]])
    assert land_nightly.plan() == [["test"], ["integrations/simulation/gazebo/test"],
                                   ["ROSY_RUN_BROWSER_TESTS=1", "a/test_x_browser.py"]]
    monkeypatch.setattr(land_nightly.land_checks, "tmp_dir", lambda name: tmp_path)
    # A PR checkout (CI) has no local `main` branch.
    monkeypatch.setattr(land_nightly, "_main_sha", lambda: "0" * 40)
    monkeypatch.setattr(land_nightly, "_green_marker", lambda: tmp_path / "green")

    def run(invocations, logs, sha, repo, label):
        if label == "nightly-rerun":
            return None  # a rerun with no exit codes clears nothing: its ids stay NEW
        logs[0].write_text("FAILED test/test_a.py::test_new - boom\n1 failed\n", encoding="utf-8")
        logs[1].write_text("1 passed\n", encoding="utf-8")
        logs[2].write_text("FAILED a/test_x_browser.py::test_b - boom\n1 failed\n", encoding="utf-8")
    monkeypatch.setattr(land_nightly.remote_pytest, "run", run)
    monkeypatch.setattr(land_nightly.land_mainred, "recheck", lambda *a: None)
    reds = []
    monkeypatch.setattr(land_nightly.land_mainred, "red",
                        lambda wt, main, ids, text, env, by: reds.append((ids, env, by)))
    assert land_nightly.main([]) == 1
    # A browser red keeps its opt-in: recheck reruns it instead of skipping it (2026-11-09).
    assert reds == [(["test/test_a.py::test_new"], [], "nightly"),
                    (["a/test_x_browser.py::test_b"], ["ROSY_RUN_BROWSER_TESTS=1"], "nightly")]


def test_nightly_records_usable_clean_passes_in_land_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(land_nightly, "_json", lambda *a: [] if "--all-browsers" in a else {"full_invocations": [["pkg/test"]]})
    monkeypatch.setattr(land_nightly.land_checks, "tmp_dir", lambda name: tmp_path)
    monkeypatch.setattr(land_nightly, "_main_sha", lambda: "a" * 40)
    monkeypatch.setattr(land_nightly, "_green_marker", lambda: tmp_path / "green")
    monkeypatch.setattr(land_nightly.land_mainred, "recheck", lambda *a: None)
    monkeypatch.setattr(land_nightly.land_cache, "env_id", lambda *a: "env1")
    monkeypatch.setattr(land_nightly.land_cache, "_git", lambda *a: type("R", (), {"stdout": "b" * 40})())
    recorded = []
    monkeypatch.setattr(land_nightly.land_cache, "record", lambda *a: recorded.append(a))
    monkeypatch.setattr(land_nightly.remote_pytest, "run",
                        lambda invs, logs, *a, **kw: [p.write_text("1 passed in 0.1s\n") for p in logs] and [0])
    assert land_nightly.main([]) == 0
    assert len(recorded) == 1 and recorded[0][4] == ["pkg/test"]


def test_a_green_night_is_not_rerun_on_the_same_main(tmp_path, monkeypatch):
    monkeypatch.setattr(land_nightly, "_json", lambda *command: [["test"]] if "--all-browsers" in command
                        else {"full_invocations": [["test"]]})
    monkeypatch.setattr(land_nightly.land_checks, "tmp_dir", lambda name: tmp_path)
    monkeypatch.setattr(land_nightly.land_mainred, "recheck", lambda *a: None)
    monkeypatch.setattr(land_nightly, "_green_marker", lambda: tmp_path / "green")
    sha = ["a" * 40]
    monkeypatch.setattr(land_nightly, "_main_sha", lambda: sha[0])
    runs = []

    def run(invocations, logs, sha_, repo, label):
        runs.append(sha_)
        for log in logs:
            log.write_text("1 passed in 0.10s\n" if sha_ != "c" * 40 else "", encoding="utf-8")
    monkeypatch.setattr(land_nightly.remote_pytest, "run", run)
    assert land_nightly.main([]) == 0 and land_nightly.main([]) == 0
    assert runs == ["a" * 40]  # the second night on the same main skipped the tier
    sha[0] = "c" * 40  # a cut log compares as 0 NEW but is no green night
    assert land_nightly.main([]) == 0 and land_nightly.main([]) == 0
    assert runs == ["a" * 40, "c" * 40, "c" * 40]
    runs.clear()
    sha[0] = "b" * 40
    assert land_nightly.main([]) == 0
    assert runs == ["b" * 40]


def _night(local, monkeypatch, tmp_path, sha, failing=False, fail_runs=None, bad="FAILED test/test_a.py::test_new"):
    """Invocation 1 fails in its first ``fail_runs`` runs (``failing``: every run); the rest pass."""
    fail_runs = (99 if failing else 0) if fail_runs is None else fail_runs
    monkeypatch.setattr(land_nightly, "ROOT", local)
    calls = []
    monkeypatch.setattr(land_nightly, "_json", lambda *c: calls.append(c) or ([i for i in BROWSERS] if "--all-browsers" in c
                                                                              else {"full_invocations": FULL[:3]}))
    monkeypatch.setattr(land_nightly, "_main_sha", lambda: sha)
    monkeypatch.setattr(land_nightly, "_green_marker", lambda: tmp_path / "green")
    monkeypatch.setattr(land_nightly.land_checks, "tmp_dir", lambda name: tmp_path)
    monkeypatch.setattr(land_nightly.land_mainred, "recheck", lambda *a: None)
    monkeypatch.setattr(land_nightly.land_mainred, "red", lambda *a, **k: None)
    monkeypatch.setattr(land_nightly, "_candidates", lambda: tmp_path / "candidates.txt")
    runs = []

    def run(invs, logs, *a, **k):
        runs.append(len(invs))
        codes = []
        for inv, log in zip(invs, logs):
            receipt = ("[g1-timing-gate] expected=1 collected=1 passed=1 skipped=0 clean=1" + chr(10)
                       if land_nightly.affected_exclusive.dedicated(inv) else "")
            fails = inv == FULL[1] and len(runs) <= fail_runs
            log.write_text(receipt + (f"{bad} - boom{chr(10)}1 failed in 0.1s" if fails else "1 passed in 0.01s")
                           + chr(10), encoding="utf-8")
            codes.append(1 if fails else 0)
        return codes
    monkeypatch.setattr(land_nightly.remote_pytest, "run", run)
    return calls, runs  # runs: invocations per remote_pytest.run call


def test_a_green_night_writes_the_full_record_publication_qualifies(repo, tmp_path, monkeypatch):
    local, _ = repo
    sha = _commit(local, "app.py", "night")
    calls, _ = _night(local, monkeypatch, tmp_path, sha)
    assert land_nightly.main([]) == 0
    assert ("--base", sha, "--head", sha) == tuple(calls[0][calls[0].index("--base"):calls[0].index("--base") + 4])
    assert land_record.read(local, sha)["tier"] == "full"
    assert tool.green_full(local, sha)


def test_a_night_with_a_new_failure_writes_no_land_record(repo, tmp_path, monkeypatch):
    local, _ = repo
    sha = _commit(local, "app.py", "red night")
    _night(local, monkeypatch, tmp_path, sha, failing=True)
    assert land_nightly.main([]) == 1
    assert land_record.read(local, sha) is None

def test_a_new_failure_that_passes_on_the_same_sha_rerun_is_green_and_a_flaky_candidate(repo, tmp_path, monkeypatch):
    local, _ = repo
    sha = _commit(local, "app.py", "flaky night")
    _, runs = _night(local, monkeypatch, tmp_path, sha, fail_runs=1)
    assert land_nightly.main([]) == 0
    assert runs[1] == 1  # only the red invocation reran
    record = land_record.read(local, sha)
    assert record["tier"] == "full" and record["logs"][1].endswith("nightly-1-rerun.txt")
    assert tool.green_full(local, sha)
    assert (tmp_path / "candidates.txt").read_text(encoding="utf-8").startswith("test/test_a.py::test_new  # LOAD-FLAKY")


def test_a_new_failure_that_fails_its_rerun_too_stays_red(repo, tmp_path, monkeypatch):
    local, _ = repo
    sha = _commit(local, "app.py", "red twice")
    _, runs = _night(local, monkeypatch, tmp_path, sha, fail_runs=2)
    assert land_nightly.main([]) == 1
    assert runs[1:] == [1] and land_record.read(local, sha) is None
    assert not (tmp_path / "candidates.txt").exists()


def test_a_quarantined_only_invocation_is_rerun_and_its_clean_row_recorded(repo, tmp_path, monkeypatch):
    local, _ = repo
    (local / "test").mkdir(exist_ok=True)
    (local / "test/flaky_quarantine.txt").write_text("test/test_q.py::test_q  # load flake\n", encoding="utf-8")
    sha = _commit(local, "app.py", "quarantined night")
    _, runs = _night(local, monkeypatch, tmp_path, sha, fail_runs=1, bad="FAILED test/test_q.py::test_q")
    assert land_nightly.main([]) == 0
    assert runs[1] == 1 and land_record.read(local, sha)["logs"][1].endswith("nightly-1-rerun.txt")
    assert not (tmp_path / "candidates.txt").exists()  # a quarantined id is no new candidate


def test_reruns_are_capped_per_night(tmp_path, monkeypatch, capsys):
    many = [[f"pkg/test_{n}.py"] for n in range(land_nightly.MAX_RERUNS + 3)]
    monkeypatch.setattr(land_nightly, "_json", lambda *a: [] if "--all-browsers" in a else {"full_invocations": many})
    monkeypatch.setattr(land_nightly.land_checks, "tmp_dir", lambda name: tmp_path)
    monkeypatch.setattr(land_nightly, "_main_sha", lambda: "a" * 40)
    monkeypatch.setattr(land_nightly, "_green_marker", lambda: tmp_path / "green")
    monkeypatch.setattr(land_nightly.land_mainred, "recheck", lambda *a: None)
    monkeypatch.setattr(land_nightly.land_mainred, "red", lambda *a, **k: None)
    monkeypatch.setattr(land_nightly.land_checks, "_safety", lambda *a: [])
    runs = []

    def run(invs, logs, *a, **k):
        runs.append(len(invs))
        for inv, log in zip(invs, logs):
            log.write_text(f"FAILED {inv[0]}::test_x - boom{chr(10)}1 failed in 0.1s{chr(10)}", encoding="utf-8")
        return [1] * len(invs)
    monkeypatch.setattr(land_nightly.remote_pytest, "run", run)
    assert land_nightly.main([]) == 1
    assert runs == [len(many), land_nightly.MAX_RERUNS]
    assert f"rerun: {land_nightly.MAX_RERUNS} of {len(many)} invocation(s)" in capsys.readouterr().out
