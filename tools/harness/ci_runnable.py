"""Canonical CI-runnable shard classifier (single source of truth, D-1052)."""

from __future__ import annotations

import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
for _extra in (str(Path(__file__).resolve().parent), str(TOOLS / "remote")):
    if _extra not in sys.path:
        sys.path.insert(0, _extra)

import affected_ci  # noqa: E402
import affected_exclusive  # noqa: E402
import work_queue  # noqa: E402

ACT = next(e for e in affected_ci.CI_FULL_MATRIX if e["name"] == "omx-act-cpu")
ROOT_TEST = {"name": "root-test", "invocations": [["test"]]}
EXCLUDED_PREFIXES = ("integrations/simulation/", "learning/envs/isaac/", "middleware/devices/omx/adapter/")


def ci_entry(inv: list[str]) -> dict | None:
    """Matching gating CI_FULL_MATRIX entry (or root test/), or None."""
    paths = [w.split("::", 1)[0].replace("\\", "/") for w in inv if not w.startswith("-")]
    acts = set(ACT["invocations"][0])
    if any(a == p or a.startswith(p.rstrip("/") + "/") for p in paths for a in acts):
        return ACT if all(p in acts for p in paths) else None
    for entry in (*affected_ci.CI_FULL_MATRIX, ROOT_TEST):
        roots = [w for i in entry["invocations"] for w in i if not w.startswith("-")]
        if entry is not ACT and entry.get("gating", True) and all(
                any(p == r or p.startswith(r + "/") for r in roots) for p in paths):
            return entry
    return None


def ci_runnable(inv: list[str]) -> bool:
    """True iff `inv` runs on GitHub Actions rather than lab-only hardware/browser/sim hosts."""
    paths = [w.replace("\\", "/") for w in inv if not w.startswith("-")]
    return bool(paths) and not (
        any(work_queue.ENV_WORD.match(w) for w in inv)
        or work_queue.lab_only(inv, above=False)  # a folder above the lab-only file is CI's root-test, not lab evidence
        or work_queue.host_alone(inv)
        or affected_exclusive.dedicated(inv)
        or any(p.startswith(EXCLUDED_PREFIXES) for p in paths)
    ) and ci_entry(inv) is not None
