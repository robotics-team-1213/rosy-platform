"""The GitHub full-run matrix for the D-436 ``affected`` tier (split from ``affected_tests.py``, pure move).

``CI_FULL_MATRIX`` and its shard settings are what ``ci.yml`` runs on a full event and what
``affected_tests.lab_full_invocations`` runs on the lab PCs; ``ci_matrix`` emits the job matrix
(``rosy_harness.py affected --ci-matrix``). ``affected_tests`` re-exports every name here.
"""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

import affected_ros  # PR #96: per-path full-tier ROS environment for affected runners

if TYPE_CHECKING:
    from affected_tests import Repo, Selection

# Whole suites the CI full run (.github/workflows/ci.yml) executes beyond the
# registered module `tests`; the printed full tier is their union.
FULL_SUITES = (
    "learning/training/pinky/test",
    "learning/registry/policy/test",
    "learning/training/omx/test",
    "learning/training/world_model/test",
    "learning/evaluation/world_model/test",
    "operations/prediction/world_model/test",
    "learning/curation/omx/test",
    "learning/curation/pinky/test",
    "middleware/core/events/test",
    "middleware/core/services/test",
    "shared/web/test",
    "contracts/foundation/test",
)

# D-436 4: the GitHub full run as parallel matrix entries. Each entry is one
# runner; its `invocations` run in order (suites sharing a test basename stay in
# separate invocations: gateway and sensing both ship test_battery.py, vision and
# games test_preview.py). `ros`: none (host conditions), base (/opt/ros) or
# overlay (+ colcon install, which also builds). `gating: False` reports only.
ROOT_SHARDS = 3
# D-553 1: the slowest suites split by test file, like the root shards. fleet
# alone held the CI critical path at ~580 s of a ~12 min run.
SUITE_SHARDS = {"fleet": 5, "sensing": 2}  # Station suites (D-772) retain the fixed per-shard cost budget.
# Seconds per Fleet file of 5 s or more, the mean of CI 38807338775, 38711952782 and 38830518002
# (2026-10-15/16, timestamps of the -v result lines); others weigh 1. These only choose runners;
# every discovered test still runs exactly once.
# shortcut: static timing weights; refresh when CI's slowest Fleet shard drifts.
FLEET_TEST_SECONDS = json.loads(Path(__file__).with_name("fleet_test_seconds.json").read_text(encoding="utf-8"))
CI_FULL_MATRIX = (
    # #181: actual ACT CPU weights run on their own gating runner, not behind learning-policy's optional imports.
    {"name": "omx-act-cpu", "invocations": [[
        "learning/training/omx/test/test_act_inference_native.py",
        "learning/training/omx/test/test_act_owner_capture.py",
        "learning/training/omx/test/test_act_parent_chain.py"]], "ros": "none"},
    {"name": "learning-policy", "invocations": [
        ["learning/registry/policy/test"], ["learning/training/omx/test"], ["learning/training/pinky/test"],
        ["learning/curation/omx/test"], ["learning/curation/pinky/test"],
        ["learning/training/world_model/test"], ["learning/evaluation/world_model/test"],
        ["operations/prediction/world_model/test"]], "ros": "none"},
    {"name": "core-domain", "invocations": [[
        "middleware/core/gateway/test", "middleware/core/events/test", "middleware/core/services/test",
        "shared/web/test", "contracts/foundation/test",
        "middleware/devices/pinky/profile/test", "middleware/devices/omx/profile/test"], [
        "middleware/core/gateway/test/test_account_pipeline.py"
    ]], "ros": "none"},
    # Never ran in CI before D-436 (D-191 follow-up); reports until its first green run.
    {"name": "sensing", "invocations": [["middleware/perception/test"]], "ros": "none", "gating": False},
    {"name": "fleet", "invocations": [["operations/fleet/test"]], "ros": "none"},
    {"name": "app-fleet", "invocations": [["applications/fleet/test"]], "ros": "none"},
    {"name": "monitoring-browser", "invocations": [["test/test_monitoring_browser.py"]], "ros": "none"},
    {"name": "site-vision-cell", "invocations": [
        ["operations/overhead/test"], ["operations/processes/cell/test"], ["operations/situation/test"],
        ["operations/world/test"], ["operations/monitoring/test"],
        ["test/test_platform_palletizing_compat.py", "test/test_platform_cell_submission.py",
         "test/architecture/test_platform_dependency_boundaries.py"]], "ros": "none"},
    {"name": "gz-sim", "invocations": [["integrations/simulation/gazebo/test"]], "ros": "overlay"},
    {"name": "hardware-safety", "invocations": [[
        "middleware/devices/pinky/bringup/test", "middleware/drivers/pinky_adc/test",
        "middleware/perception/test/test_ir_adc_lock.py",
        "--ignore=middleware/devices/pinky/bringup/test/test_flake8.py",
        "--ignore=middleware/devices/pinky/bringup/test/test_pep257.py",
        "--ignore=middleware/devices/pinky/bringup/test/test_copyright.py"]], "ros": "base"},
)
# D-762 stage 1: the only registered test files CI's full tier skips, each with its reason.
# Every other registered module suite CI_FULL_MATRIX does not name runs on the `modules` runner.
CI_FULL_EXCLUDED = {
    f"middleware/devices/pinky/bringup/test/test_{name}.py":
        "ament lint template, not a product contract; CI never ran it and the lab full tier --ignores it too"
    for name in ("flake8", "pep257", "copyright")
}


def _shard_groups(repo: Repo, entry: dict) -> list[list[str]]:
    """A SUITE_SHARDS suite's (or root test/'s) files in balanced groups (Fleet by measured seconds); [] if unsplit."""
    import affected_tests as at
    n = ROOT_SHARDS if entry["name"] == "root-test" else SUITE_SHARDS.get(entry["name"], 1)
    fleet = entry["name"] == "fleet"
    files = sorted(t for t in repo.test_files if at._under(t, entry["invocations"][0][0])) if n > 1 else []
    groups, loads = [[] for _ in range(n)], [0] * n
    for path in sorted(files, key=lambda p: (-FLEET_TEST_SECONDS.get(PurePosixPath(p).name, 1), p)) if fleet else files:
        i = min(range(n), key=lambda i: (loads[i], i))
        groups[i].append(path)
        loads[i] += FLEET_TEST_SECONDS.get(PurePosixPath(path).name, 1) if fleet else 1
    return [sorted(group) for group in groups] if n > 1 and len(files) >= n else []


def ci_matrix(repo: Repo, sel: Selection) -> dict:
    """The GitHub job matrix: CI_FULL_MATRIX plus root test/ shards, or one entry per invocation."""
    import affected_tests as at  # here, not at the top: affected_tests imports this module
    if sel.mode == "full":
        root_tests = sorted(t for t in repo.test_files if at._under(t, "test"))
        entries = []
        for entry in CI_FULL_MATRIX:
            groups = _shard_groups(repo, entry)
            entries += [dict(entry, name=f"{entry['name']}-{i + 1}of{len(groups)}", invocations=[g])
                        for i, g in enumerate(groups)] or [dict(entry)]
        for i in range(ROOT_SHARDS):
            entries.append({"name": f"root-test-{i + 1}of{ROOT_SHARDS}",
                            "invocations": [root_tests[i::ROOT_SHARDS]], "ros": "overlay"})
        # D-762 stage 1: every other registered module suite, so CI's full tier is the lab full tier.
        # Gates since 2026-10-27: green on every main run since 2026-10-25 (it reported until then, like sensing).
        modules = at.pack(repo, at._outside_ci_matrix(at._full_paths(repo)))
        if modules:
            entries.append({"name": "modules", "invocations": modules, "ros": "overlay"})
    else:  # one runner per invocation; a whole SUITE_SHARDS suite keeps its full-tier groups (25 min limit)
        whole, out = {e["invocations"][0][0]: e for e in CI_FULL_MATRIX if SUITE_SHARDS.get(e["name"], 1) > 1}, []
        whole["test"] = {"name": "root-test", "invocations": [["test"]]}
        for inv in sel.invocations:
            split = [p for p in inv if p in whole and _shard_groups(repo, whole[p])]
            rest, flags = [p for p in inv if p not in split], [p for p in inv if p.startswith("-")]
            out += [rest] if any(not p.startswith("-") for p in rest) or not split else []
            out += [[*group, *flags] for p in split for group in _shard_groups(repo, whole[p])]
        entries = affected_ros.entries(out, CI_FULL_MATRIX)
        if any(at._under(p.split("::", 1)[0], "learning/training/omx/test")
               for inv in sel.invocations for p in inv):
            entries.append(dict(next(e for e in CI_FULL_MATRIX if e["name"] == "omx-act-cpu")))
    entries.append({"name": "build-smoke", "kind": "smoke", "invocations": []})
    for entry in entries:
        entry.setdefault("kind", "pytest")
        entry.setdefault("gating", True)
        entry.setdefault("ros", "overlay")
    return {"include": entries}
