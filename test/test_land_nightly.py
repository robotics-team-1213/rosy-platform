"""tools/land_nightly.py: the night's complete FULL tier (D-889 addendum 12)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import land_nightly  # noqa: E402


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
        logs[0].write_text("FAILED test/test_a.py::test_new - boom\n1 failed\n", encoding="utf-8")
        logs[1].write_text("1 passed\n", encoding="utf-8")
    monkeypatch.setattr(land_nightly.remote_pytest, "run", run)
    reds = []
    monkeypatch.setattr(land_nightly.land_mainred, "red", lambda wt, main, ids, text, env, by: reds.append((ids, by)))
    assert land_nightly.main([]) == 1
    assert reds == [(["test/test_a.py::test_new"], "nightly")]


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
