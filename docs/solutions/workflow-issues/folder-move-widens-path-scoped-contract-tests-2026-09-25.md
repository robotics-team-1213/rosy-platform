---
title: Moving control under src/core silently widened three path-scoped contract tests, and CI caught it only after merge
date: 2026-09-25
category: workflow-issues
module: test (core shutdown guard, native systemd contract) after refactor a93d5188
problem_type: test_failure
component: development_workflow
symptoms:
  - "CI on main failed test_only_main_shuts_rclpy_down_in_core_production_code with 35 offenders, all in control/"
  - "after that fix, CI failed test_declared_paths_account_for_every_write_root_in_the_program[rosy-core.service] on /root/pinky-dynamic-tracks.json"
  - "after excluding control from the directory scan, the same test failed on /etc/machine-id from a control node"
  - "the imported-by resolver for CORE returned every control module instead of the ones CORE imports"
  - "second wave 2026-09-26: after the role-dir regroup, PINNED_RELAYS keys, .gitattributes rules, and guard exclusion lists still pointed at old paths — two CI failures, two Windows-only byte-compare failures, and 38 resurrected shutdown offenders"
root_cause: logic_error
resolution_type: test_fix
severity: medium
related_components: [tooling]
tags: [folder-move, contract-test, path-scope, rclpy-shutdown, systemd-sandbox, refactor]
---

# Moving control under src/core silently widened three path-scoped contract tests, and CI caught it only after merge

## Problem
Refactor a93d5188 moved the `control` package from `src/apps/control` to `src/core/control`. Three contract
tests defined "CORE code" as "everything under `src/core`", so after the move they started treating
control's standalone node processes and its uninstalled Gazebo rig scripts as CORE code. The move merged
to main before CI ran on it; the failures surfaced one at a time over three fix-and-push rounds.

## Symptoms
- `src/core/core/test/test_core_main_shutdown.py`, test `test_only_main_shuts_rclpy_down_in_core_production_code` —
  35 `rclpy.shutdown()` calls: 33 inside control node `main()` functions, 2 in `src/core/control/tools/gz/*.py`.
- `test/test_native_systemd_contract.py` — `rosy-core.service: program names /root/pinky-dynamic-tracks.json`
  (a gz rig script), then `/etc/machine-id` (`startup_calibration_node.py`, its own process).

## What Didn't Work
- Excluding `src/core/control` from the directory scan alone: the second source,
  `imported-by:src/core:control:src/core/control`, used `src/core` as the importer. With control inside it,
  control's own imports counted as CORE's, so the whole package came back through that route.

## Solution
Restore the pre-move scope explicitly instead of loosening the checks:

1. Shutdown guard (7a57c2bb): skip `src/core/control/tools/`, and under `src/core/control/` allow a shutdown only inside a
   module-level `main()` or `if __name__ == "__main__":` block (AST line spans). A new test pins that a
   shutdown in a class method is still caught.
2. Systemd program scan (539a0101): `PROGRAM_EXCLUDES = {"rosy-core.service": ("src/core/control",)}` for
   directory sources, and `_imported_modules()` skips source files inside the imported package's own root.
   CORE production code imports control only through the `control.sensor_provider:PROVIDER` entry-point
   string, so the resolved set is empty, which is what it was before the move.

## Why This Works
Each test encodes a process boundary (CORE process vs control node processes), but expressed it as a
directory boundary. The move made the two diverge. The fix states the process boundary directly: node
entry points and scripts that never run inside CORE are excluded by rule, not by where they sit.

## Prevention
- Before merging a folder move, grep `test/` and `src/**/test/` for tests that walk a directory
  (`rglob`, `Path(__file__).parents[...]`, `PROGRAM_SOURCES`, `imported-by:`) whose root is the move's
  destination or source, and run them. A move that changes what a directory contains changes what these
  tests mean.
- Run the full CI command set (`.github/workflows/ci.yml` steps) locally or on the branch before merging a
  move; three sequential post-merge failures cost three push cycles.

## Second wave: the role-dir regroup (2026-09-26)

The same invariant repeated a level deeper after the D-241/D-242 role-directory regroup moved the map
bundle and core packages (`src/apps/…` → `src/runtime/{gateway,services,api_web,sensing,…}`), this
time hiding in four places a folder-move grep of `test/` alone still misses:

- **Path constants inside tests** — `test_executor_contracts` / `test_v1_import_boundary` /
  `test_swarm` built `runtime/core_features/core_features` and `runtime/core_api_web/core_api_web`;
  the gz contract test still walked `src/navigation/navigation/launch`; `PaintMap.from_bundle()`
  computed `parents[2]/control/map/…`. Four `FileNotFoundError`s, one stale bringup path, and 96+7
  sensing failures all traced to constants that named the old nesting.
- **Path-keyed fingerprint pins** — `PINNED_RELAYS` keys `core_features/core_features/*.py` no longer
  matched the scanner's `services/core_features/*.py`, so the relay exemption lookup missed *and* the
  pin comparison failed: one stale key space produced two differently-worded CI failures. All four
  hashes were identical — only the keys moved, and that equality is the evidence that no reviewed
  relay body had changed.
- **`.gitattributes` rules** — the byte-determinism rules for `map_v2_fleet` still pointed at
  `src/apps/control/map/…`, so `core.autocrlf=true` checked the generated `.yaml`/`.world` out as
  CRLF and two byte-compare tests failed on Windows while Linux CI stayed green (its checkout was
  already LF). Attr paths are config: nothing executes them, only the comparison that reads bytes.
- **Guard exclusion lists** — the shutdown guard's `core/core/main.py` / `control/tools/` /
  `control/` prefixes stopped matching after the move, resurrecting 38 offenders from files that had
  been exempt since this note's original fix: that fix was itself path-keyed, so the next move
  unlatched it.

## Prevention (extended 2026-09-26)

- Grep the **source and destination prefixes of a move across all path-keyed state**, not just tests:
  `.gitattributes`, fingerprint/pin maps (`PINNED_RELAYS`), exclusion allowlists, and `parents[...]`
  constants. `rg '<old>/<old>/'` catches the double-nested era; `rg '<old-prefix>'` catches the rest.
- Two blind spots compound: a suite no CI job runs (sensing before this date) fails only on developer
  machines, and a byte-compare test fails only where the checkout mangles EOL. Run the full suite on
  the platform that actually checks out the files before calling a move done.
- When a pin's *value* is unchanged but its *key* moved, the fix is a key rename — no re-review of the
  pinned body is required, and the equal hashes are the evidence for that claim.

## Related Issues
- `docs/solutions/workflow-issues/installed-layout-import-passes-repo-tests-2026-09-22.md` (layout
  assumptions in tests)
- ADR D-196 multi-robot structure (the reorg that included this move)
