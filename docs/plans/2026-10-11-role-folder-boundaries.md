# Drive responsibility folders implementation plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Move the remaining Base behavior implementations and legacy motion adapters into Drive with unchanged installed identities and safety authority.

**Architecture:** D-649 separates source ownership from Python/ROS identity. Reuse existing holder packaging; preserve common CORE policy and Perception evidence rather than moving files by their names alone.

**Tech Stack:** Python, setuptools/ament, ROS 2 Jazzy, existing remote pytest runner and architecture manifest.

## Task 1: Record exact moves and consumers

- ADR: `docs/adr/D-649-drive-behavior-source-ownership.md` and the matching ADR Log row.
- Move seven existing directories from `middleware/core/services/core_features/` into `middleware/control/drive/behaviors/`: `line_follow`, `docking`, `navigation`, `localization`, `swarm`, `road_behaviour`, `traffic_policy`.
- Move `middleware/perception/control/{control_node,goal_node,wander_node,safety_node}.py` into `middleware/control/drive/runtime/`.
- Preserve `core_features.*`, `control.*`, ROS entry points, Command/Safety arbitration, callback order and every implementation byte.
- Reach callers/imports, source audits, package setup and sdist, native/container closure, safety tags/anchors, architecture coupling and size units, isolated packaging fixtures, guides and ownership manifest. Historical ADR/log/validation evidence stays historical.

## Task 2: Apply source and installation mappings

- Add a narrow static source layout for the existing `core_features` distribution; source imports search the declared behaviors holder only when in a source checkout. Installed imports have no repository dependency.
- Extend its ordinary package mappings and self-contained sdist snapshot using the existing Perception holder pattern.
- Extend Perception's existing holder build/source archive and source audit to include Drive runtime modules once. Do not duplicate wrappers or activate a writer.
- Move Safety file paths and register semantic ownership. Keep existing budgets and independent size units; make the architecture scanner count moved source under its actual installing distribution.

## Task 3: Verify and integrate

- Build a self-contained `core_features` sdist and wheel in remote scratch; check imports of line-follow, docking, localization and traffic policy from an isolated installed target, one copy and no repository path.
- Extend Perception's isolated wheel proof to cover the four moved entry modules and unchanged provider/map resources.
- Commit exact files with independently reviewed `Safety-Review:` evidence.
- Run `python tools/remote/remote_pytest.py --log-dir <X-session>/core -- middleware/core/services/test/ middleware/core/gateway/test/ test/architecture/ test/test_structure_installed_packages.py`; compare its `run-1.txt` with `python test/known_failures.py`.
- Run Perception in a separate remote invocation to avoid duplicate test basenames; compare its log likewise.
- Lint, then `python tools/land.py --tests auto` for local fast-forward integration under existing user authorization. Publish/deploy only a candidate with exact successful release/CI gates. The offline Pinky robots remain on their existing automatic-update path.

## Progress

- ADR, 80-file migration, installation/source/archive mappings, Safety review and current responsibility guides committed. Perception: 3,028 passed; corrected CORE/source/install proof: 117 passed; move tool: 23 passed. [Detailed evidence](../validation/d649-drive-boundaries-2026-10-11/result.md) distinguishes initial failures and rechecks.
- Latest-main integration and affected-test recheck pending. Source folder and install proof do not establish deployment/device acceptance.
- Previous source candidate `53c557136957` failed CI in `test_console_roles_browser` map-label assertions; it is not signed/applied. Online-target deployment remains an open goal.
