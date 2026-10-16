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
