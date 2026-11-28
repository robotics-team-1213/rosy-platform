"""D-1090: tracked file count per area only goes up by an explicit cap raise.

The 600-line limit (D-766) stopped long files and turned growth into more files: +3,040 tracked files
in the 30 days to 2026-11-28 (230 deleted). These caps hold each area's file count. Adding files past a
cap means deleting or merging as many in the same area, or raising the cap in this file with a reason in
the PR body (`Budget-Raise: <area> +N (why)`). docs/validation and docs/plans have no headroom: dated
evidence goes to $ROSY_SCRATCH and the PR body, and an existing record is updated instead (D-1090 2).
"""

import re
import subprocess
import warnings
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
#: Record fragments (D-1052) the records bot consolidates; transient, so not counted.
FRAGMENT = re.compile(r"(^|/)logs/\d{4}/|^docs/reference/api-changes/")

#: Measured on cd65c8970b (2026-11-28) plus headroom: 20 for code areas (splits), 10 for
#: docs/adr and docs/solutions (PRs in flight), 0 for docs/validation and docs/plans.
CAPS = {
    "applications": 374,
    "contracts": 321,
    "deploy": 1298,
    "docs/adr": 1031,
    "docs/assets": 84,
    "docs/plans": 490,
    "docs/reference": 90,
    "docs/solutions": 306,
    "docs/validation": 1865,
    "integrations": 215,
    "learning": 714,
    "middleware": 2250,
    "operations": 2103,
    "shared": 162,
    "test": 1445,
    "tools": 587,
}
#: Cap minus count above this warns: lower the cap to keep the ratchet tight.
SLACK_WARN = 40


def _area(path: str) -> str:
    parts = path.split("/")
    return "/".join(parts[:2]) if parts[0] == "docs" and len(parts) > 2 else parts[0]


def _counts() -> Counter:
    # Fails, never skips, without git: an unreadable tree is not an empty one.
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, check=True, capture_output=True, text=True).stdout
    return Counter(_area(line) for line in out.splitlines() if line and not FRAGMENT.search(line))


def test_no_area_exceeds_its_file_count_cap():
    counts = _counts()
    over = {area: f"{counts[area]} > {cap}" for area, cap in CAPS.items() if counts[area] > cap}
    assert not over, (
        f"file count over cap: {over}. Delete or merge files in the same area, or raise the cap in "
        "test/architecture/test_file_count_budget.py with 'Budget-Raise: <area> +N (why)' in the PR body (D-1090)."
    )


def test_every_large_area_has_a_cap():
    counts = _counts()
    uncapped = sorted(area for area, n in counts.items() if n >= 50 and area not in CAPS)
    assert uncapped == [], f"areas with 50+ files need a CAPS row (D-1090): {uncapped}"


def test_caps_stay_tight():
    counts = _counts()
    loose = {area: cap - counts[area] for area, cap in CAPS.items() if cap - counts[area] > SLACK_WARN}
    if loose:
        warnings.warn(f"lower these caps to the measured count (D-1090 ratchet): {loose}", stacklevel=2)
