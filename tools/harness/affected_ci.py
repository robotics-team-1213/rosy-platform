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
import affected_exclusive

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
SUITE_SHARDS = {"fleet": 5, "sensing": 2, "core-domain": 3}  # Station suites (D-772) retain the fixed per-shard cost budget.
# Fleet file weights from pytest result-line timestamps in CI 44563719449 and 44568270495.
# Retain prior weights where timings are incomplete or inconsistent. Unlisted files weigh 1.
# The weights only choose runners; every discovered test still runs exactly once.
# shortcut: static timing weights; refresh when CI's slowest Fleet shard drifts.
FLEET_TEST_SECONDS = json.loads(Path(__file__).with_name("fleet_test_seconds.json").read_text(encoding="utf-8"))
# Other slow files (8 s or more), measured the same way in 12 CI runs of 2026-11-20. affected_ros.consolidate
# weighs jobs with both tables: at 1 per file it packed every guard invocation onto one 5-7 min runner.
CI_TEST_SECONDS = {**json.loads(Path(__file__).with_name("ci_test_seconds.json").read_text(encoding="utf-8")),
                   **FLEET_TEST_SECONDS}
MAX_CI_JOBS = 18  # GitHub Free runs 20 jobs at once; scope and ci-result take none while the tests run
_STATION_SCHEDULING = "test/integration/core_fleet/test_station_camera_scheduling.py"


def consolidated(include: list[dict]) -> list[dict]:
    """Measured seconds spread a PR's small jobs over runners; a selection that would pass MAX_CI_JOBS keeps the coarser packing.

    A 60 s share per job was tried on 2026-11-21 (#343) and dropped: runs used 55% more runner seconds (984 to 1546)
    and, with several runs sharing the 20 concurrent jobs, the median job waited 177 s for a runner (45 s before)."""
    fine = affected_ros.consolidate(include, CI_TEST_SECONDS)
    return fine if len(fine) <= MAX_CI_JOBS else affected_ros.consolidate(include, FLEET_TEST_SECONDS)

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
    # 2026-11-18: core-domain was CI's longest runner (pytest step 16.5 and 22.4 min of a 25 min budget, runs
    # 43769060136 and 42596065578) and again 20 min in 44745980037; SUITE_SHARDS splits its gateway files across
    # runners, same tests. The browser journey stays its own invocation on the last shard.
    {"name": "core-domain", "invocations": [["middleware/core/gateway/test"], [
        "test/integration/core_fleet/test_account_pipeline.py"
    ]], "ros": "none"},
    # Runs the known load-sensitive simulation in a fresh runner (PRs #249 and #250).
    {"name": "core-station-simulation", "invocations": [[_STATION_SCHEDULING]], "ros": "none"},
    {"name": "core-services", "invocations": [[
        "middleware/core/events/test", "middleware/core/services/test",
        "shared/web/test", "contracts/foundation/test",
        "middleware/devices/pinky/profile/test", "middleware/devices/omx/profile/test"]], "ros": "none"},
    # Never ran in CI before D-436 (D-191 follow-up); reports until its first green run.
    {"name": "sensing", "invocations": [["middleware/perception/test"]], "ros": "none", "gating": False},
    {"name": "fleet", "invocations": [["operations/fleet/test"]], "ros": "none"},
    {"name": "app-fleet", "invocations": [["applications/fleet/test"]], "ros": "none"},
    {"name": "monitoring-browser", "invocations": [["test/test_monitoring_browser.py"]], "ros": "none"},
    {"name": "site-vision-cell", "invocations": [
        ["operations/overhead/test"], ["operations/processes/cell/test"], ["operations/situation/test"],
        ["operations/world/test"], ["operations/monitoring/test"], ["operations/account/test"],
        ["operations/notifications/test"],
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


#: Panel 2026-11-20 (aff-narrow): a change of only these files builds nothing, so CI skips build-smoke (colcon,
#: flake8, boot smoke); the selected tests (guard set, record and document readers) still run.
DOC_SUFFIXES = (".md", ".png", ".jpg", ".jpeg", ".svg", ".gif", ".drawio")

#: build-smoke's steps (colcon build, flake8, core boot, SaveMap) read only files inside a colcon root
#: (platform_parts.yaml ``colcon_roots``, which also feeds colcon_roots.py): a change of documents or of
#: trees outside every root (tools, root test/, deploy, .github) builds nothing, so the job skips.
#: platform_parts.yaml is build data — it changes what colcon_roots.py prints, so it keeps the job.
BUILD_DATA = ("tools/harness/platform_parts.yaml", "tools/harness/colcon_roots.py")
#: prefixes that can change what the smoke job itself runs or boots with (its workflow, CI image, deploy
#: configs the boot may read): conservative, the job stays for any change under them (11-20 review)
BUILD_PREFIXES = (".github/", "deploy/")


def docs_only(sel: Selection) -> bool:
    return (sel.mode == "affected" and not sel.escalations and bool(sel.changed)
            and all(p.endswith(".md") or (p.startswith("docs/") and p.endswith(DOC_SUFFIXES)) for p in sel.changed))


def buildable(repo: Repo, sel: Selection) -> bool:
    """False only when nothing build-smoke reads can have changed: no changed file inside a colcon root
    (documents aside) and none of BUILD_DATA. A missing manifest means unknown, so the job stays."""
    if sel.mode != "affected" or sel.escalations:
        return True
    roots = repo.parts.get("colcon_roots") or ()
    if not roots:
        return True
    return any(p in BUILD_DATA or p.startswith(BUILD_PREFIXES) or (not p.endswith(DOC_SUFFIXES)
                                   and any(affected_ros._under(p, r) for r in roots))
               for p in sel.changed)


# Slow root test files that dominate affected GUARD_SET runners when packed together.
_HEAVY_ROOT_TESTS = (
    "test/test_harness_contracts.py",
    "test/test_affected_tests.py",
    "test/test_land.py",
    "test/test_robot_cd.py",
    "test/test_readme_agent_start.py",
    "test/test_ci_dependencies.py",
    "test/test_remote_test_tools.py",
)


def _shard_py_invocation(inv: list[str], n: int = ROOT_SHARDS) -> list[list[str]]:
    """Split an invocation with 12 or more .py targets across runners, slowest measured files first.

    Directories in it go round the shards like files (#343: 28 files beside two directories ran 9 min on one runner)."""
    flags = [p for p in inv if p.startswith("-")]
    targets = [p for p in inv if not p.startswith("-")]
    if n <= 1 or sum(p.endswith(".py") for p in targets) < 12:
        return [inv]
    rank = {p: i for i, p in enumerate(_HEAVY_ROOT_TESTS)}
    ordered = sorted(targets, key=lambda p: (not p.endswith(".py"), -CI_TEST_SECONDS.get(PurePosixPath(p).name, 0),
                                             rank.get(p, len(rank)), p))
    return [[*ordered[i::n], *flags] for i in range(n) if ordered[i::n]]


def _shard_groups(repo: Repo, entry: dict, flags: list[str] | None = None) -> list[list[str]]:
    """A SUITE_SHARDS suite's (or root test/'s) files in balanced groups (Fleet by measured seconds); [] if unsplit.

    Files the entry's own `--ignore=` flags give another runner stay out, since pytest runs a file named on
    the command line even when it is also ignored. `flags` None is the full tier, which also leaves out
    files a later invocation of the entry runs; an affected invocation drops only the ones it ignores too."""
    import affected_tests as at
    skip = {f.split("=", 1)[1] for f in entry["invocations"][0] if f.startswith("--ignore=")}
    skip = skip | {p for inv in entry["invocations"][1:] for p in inv} if flags is None else {p for p in skip if f"--ignore={p}" in flags}
    n = ROOT_SHARDS if entry["name"] == "root-test" else SUITE_SHARDS.get(entry["name"], 1)
    fleet = entry["name"] == "fleet"
    files = sorted(t for t in repo.test_files if at._under(t, entry["invocations"][0][0])
                   and t not in skip and t != _STATION_SCHEDULING) if n > 1 else []
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
        root_tests = sorted(t for t in repo.test_files if at._under(t, "test") and t != _STATION_SCHEDULING)
        entries = []
        for entry in CI_FULL_MATRIX:
            groups = _shard_groups(repo, entry)
            later = entry["invocations"][1:]  # e.g. the account browser journey: once, on the last shard
            entries += [dict(entry, name=f"{entry['name']}-{i + 1}of{len(groups)}",
                             invocations=[g, *(later if i == len(groups) - 1 else [])])
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
            if affected_exclusive.dedicated(inv):
                continue  # ROS environment grouping must not split the job's leading environment.
            split = [p for p in inv if p in whole and _shard_groups(repo, whole[p], inv)]
            rest, flags = [p for p in inv if p not in split], [p for p in inv if p.startswith("-")]
            if any(not p.startswith("-") for p in rest) or not split:
                out += _shard_py_invocation(rest) if not split else [rest]
            out += [[*group, *flags] for p in split for group in _shard_groups(repo, whole[p], inv)]
        entries = affected_ros.entries(out, CI_FULL_MATRIX)
        exclusive_jobs = [inv for inv in sel.invocations if affected_exclusive.dedicated(inv)]
        if exclusive_jobs:
            entries.append({'name': 'g1-timing-exclusive', 'invocations': exclusive_jobs, 'ros': 'overlay'})
        if any(at._under(p.split("::", 1)[0], "learning/training/omx/test")
               for inv in sel.invocations for p in inv):
            entries.append(dict(next(e for e in CI_FULL_MATRIX if e["name"] == "omx-act-cpu")))
    if not docs_only(sel) and buildable(repo, sel):
        entries.append({"name": "build-smoke", "kind": "smoke", "invocations": []})
    for entry in entries:
        entry.setdefault("kind", "pytest")
        entry.setdefault("gating", True)
        entry.setdefault("ros", "overlay")
    return {"include": affected_exclusive.matrix(entries, affected_exclusive.TARGET in repo.test_files)}
