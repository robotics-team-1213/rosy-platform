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

    def run(invocations, logs, sha, repo, label):
        logs[0].write_text("FAILED test/test_a.py::test_new - boom\n1 failed\n", encoding="utf-8")
        logs[1].write_text("1 passed\n", encoding="utf-8")
    monkeypatch.setattr(land_nightly.remote_pytest, "run", run)
    reds = []
    monkeypatch.setattr(land_nightly.land_mainred, "red", lambda wt, main, ids, text, env, by: reds.append((ids, by)))
    assert land_nightly.main([]) == 1
    assert reds == [(["test/test_a.py::test_new"], "nightly")]
