
# plans

**Parent context:** `../AGENTS.md`

## Purpose

Dated design and execute plans (2026-08-31 onward): the working trail for Pi runtime, motors, power, dashboard, docking, battery integrity, Wi-Fi, ROS graph observability, OS image/release, Fleet, signals, Pilot and policy evidence. `ls docs/plans` is the index; filenames are `YYYY-MM-DD-kebab.md`, design (`-design`) and execute plans are separate files. `docs/plan/` was closed on 2026-09-20; its historical WBS (`ROSY Implementation Plan.md`) and Flask parity checklist live here as records, not as execution basis.

## For AI Agents

### Working In This Directory

- Read the matching `-design.md` before changing power, docking, battery or release code. Plans are not the API contract; that stays in `docs/reference/`.
- Input notes (`*-input-v0.*.md`) bind only the scope the ADR adopted: ownership naming D-227, decision lane D-228/D-229 (`2026-09-25-folder-map.md` is the folder reading map after D-229), layered move D-231.
- D-315 (`2026-09-28-source-folder-roles-and-runtime-audit.md`) is source-role interpretation plus a separately gated runtime/sensing ownership audit; D-317 audits `control` and `core_common` boundaries before any further move.
- Policy evidence plans (D-268 disposition, `2026-09-29-policy-evidence-contract*.md`, D-348 goal evidence) keep the invariants: dispatch valve False, empty registry rejects, no success without evidence, caller `max_age` ignored. Do not relax them in code without the plan's promotion ladder.
- Branch `feat/swarm-formation-slice` maps to `2026-09-08-swarm-formation-slice-design.md` (D-35 candidate).

### Testing Requirements

Each execute plan names its pytest modules (usually `test_power.py`, `test_battery.py`, `test_docking.py` or repo `test/`); run them through the remote test PC (D-584).
