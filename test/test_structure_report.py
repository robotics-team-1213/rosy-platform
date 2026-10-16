"""D-773: the structure report uses the size gate's own counter and only reads the tree."""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools/harness"))

import size_limits  # noqa: E402
import structure_report  # noqa: E402


def test_units_over_the_limit_match_the_frozen_ratchet_rows():
    data = structure_report.report()
    rows, _ = size_limits.parse_ratchet((ROOT / "test/architecture/size_ratchet.txt").read_text(encoding="utf-8"))
    for unit in data["units_over_limit"]:
        assert unit["lines"] > size_limits.UNIT_LIMIT
        assert rows.get(unit["unit"]) == unit["lines"], unit["unit"]  # the gate keeps these equal
        assert sum(c["lines"] for c in unit["split_candidates"]) <= unit["lines"]
        assert all(c["lines"] >= structure_report.MIN_GROUP_LINES for c in unit["split_candidates"])


def test_frozen_lists_are_counted():
    names = {f["list"].split("::")[1]: f["entries"] for f in structure_report.report()["frozen_lists"]}
    assert names["KNOWN_VIOLATIONS"] >= 0 and names["KNOWN_SAFETY_VIOLATIONS"] >= 0


def _unit(name, excess, *cands):
    return {"unit": name, "lines": 10_000 + excess, "excess": excess, "limit": 10_000,
            "split_candidates": [{"group": g, "lines": n, "files": fs} for g, n, fs in cands]}


def test_pick_rules_skip_with_reasons_and_take_one_per_unit(monkeypatch):
    monkeypatch.setattr(structure_report, "_safety_paths", lambda: ({"m/safe/b.py"}, ("m/root",)))
    pending = next(iter(structure_report.PENDING))
    data = {"units_over_limit": [
        _unit("small", 10, ("a/one*", 2000, ["a/one.py"]), ("a/two*", 1500, ["a/two.py", "a/two_b.py"])),
        _unit("big", 900,
              ("w/site*", 1200, ["w/site.js", "w/site.css"]),
              ("m/thin*", 600, ["m/thin.py", "m/thin_b.py"]),
              ("m/safe*", 1400, ["m/safe/a.py", "m/safe/b.py"]),
              ("m/root*", 1400, ["m/root/a.py", "m/root/b.py"]),
              ("p/pend*", 1300, [pending, "p/other.py"]),
              ("operations/fleet/x*", 1100, ["operations/fleet/x.py", "operations/fleet/x_b.py"]),
              ("operations/fleet/y*", 1050, ["operations/fleet/y.py", "operations/fleet/y_b.py"])),
    ]}
    picks, skipped = structure_report.pick(data)
    assert [(p["unit"], p["group"], p["epic"]) for p in picks] == [
        ("big", "operations/fleet/x*", "KAN-19"), ("small", "a/two*", None)]
    reasons = {s["group"]: s["reason"] for s in skipped}
    assert reasons["w/site*"].startswith("not Python") and reasons["a/one*"].startswith("one file")
    assert "floor" in reasons["m/thin*"] and "safety" in reasons["m/safe*"] and "safety" in reasons["m/root*"]
    assert reasons["p/pend*"] == structure_report.PENDING[pending]


def test_epics_follow_the_team_guide_paths():
    assert structure_report.epic_for("middleware/devices/omx/adapter/x.py") == "KAN-21"
    assert structure_report.epic_for("learning/training/omx/act_job.py") == "KAN-21"
    assert structure_report.epic_for("learning/curation/perception/x.py") == "KAN-22"
    assert structure_report.epic_for("middleware/drive/x.py") == "KAN-20"
    assert structure_report.epic_for("middleware/perception/nodes/x.py") is None


def test_issue_body_has_the_task_form_sections():
    text = structure_report.issue(structure_report.report())
    for heading in ("### 문제와 원하는 결과", "### 담당자와 수정 경로", "### 완료 조건과 검증 방법",
                    "### 관련 계약과 참고 자료"):
        assert heading in text
    assert "\n## " not in text  # the report's own headings sit below the form sections


def test_cli_prints_markdown_and_json_without_changing_the_tree():
    before = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True).stdout
    script = str(ROOT / "tools/harness/structure_report.py")
    text = subprocess.run([sys.executable, script], capture_output=True, text=True, check=True).stdout
    assert text.startswith("# Structure report") and "## Units over the 10,000-line limit" in text
    data = json.loads(subprocess.run([sys.executable, script, "--json", "--top", "2"],
                                     capture_output=True, text=True, check=True).stdout)
    assert all(len(u["split_candidates"]) <= 2 for u in data["units_over_limit"])
    after = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True).stdout
    assert before == after
