<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-10-02 | Updated: 2026-10-02 -->

# architecture

**Parent context:** `../AGENTS.md`
**Updated:** 2026-10-07

## Purpose

Repo-structure tests: where folders, packages, documents and imports are allowed to live. They read the source tree, `package.xml` files, `harness.yaml` and `surfaces.yaml`; they do not need ROS. Most use exception tables checked by set equality (P5), so a new violation fails and so does a stale entry. Update the table in the same commit that creates or removes the violation.

## Key Files

| File | Description |
|------|-------------|
| `test_capability_owners.py` | Every `platform_parts.yaml` root has one `capability:`; `.github/CODEOWNERS` routes each owned root to that capability's logins and names no root without them |
| `test_wheel_structure.py` | Wheels (`pyproject.toml` without `package.xml`) carry `COLCON_IGNORE`, `AGENTS.md` and their own tests; `KNOWN_WITHOUT_OWN_TESTS` is checked both ways |
| `test_module_structure.py` | D-168/D-427 package standard: declared roots, owner guides, harness modules and functional tests; package dependencies and import direction; D-766 absolute size limits (600/800/10,000) against `size_ratchet.txt` and `size_units.txt`; the counting rule is `tools/harness/size_limits.py`. Every tracked code file under a colcon or ops root must be measured (`SIZE_UNMEASURED` lists exceptions with reasons); fleet holders equal `fleet/_source_layout.py` `SOURCE_ROOTS`. Static holder mapping preserves installed package identities |
| `size_ratchet.txt` | D-766 4: files and units already over the limit, `<count> <key>`, frozen at the measured count; rows only go down. `safety <count> <key> <YYYY-MM-DD>` rows are the D-766 8 exception. Data: not a FULL trigger |
| `size_units.txt` | D-766: size units, `<path>` or `<path> small` (grandfathered below the 1,000-line floor). Data: not a FULL trigger |
| `test_target_layout.py` | D-310 source layout: every package has a declared target path, XML package names are unique, moved packages keep their name, product containers hold only declared packages, retired sketch names (`rosy_pinky_pro`, `rosy_decision`, ...) must not appear |
| `test_folder_package_names.py` | D-339/D-231: a source folder whose name differs from its installed package name must be in `FOLDER_TO_PACKAGE`; no stale entries |
| `test_folder_layout.py` | D-186 script/document ownership, declared deployment and data layout, no retired paths in current developer docs. Module-local helpers stay with their actual install/consumer owner; workspace tools compose owners |
| `test_document_placement.py` | D-226 publication first: sample secret/internal paths (`private/`, `.env`, keys, images, bags, `data/teleop`, `*.sqlite3`, worktrees) must be git-ignored; templates, public keys and public material must stay trackable; no tracked file under an ignore rule; repo root carries only the listed files; dated evidence stays out of modules; module roots carry only `README AGENTS CLAUDE progress logs index`. Needs `git` on PATH |
| `test_layer_boundaries.py` | D-229 by AST import scan: perception imports neither decision, vision nor ROS; decision does not import perception; line_follow reads decisions, not pixels; geometry does not import perception |
| `test_fleet_ledger_writers.py` | D-750: the modules that write Fleet's core ledger tables (`fleet_tasks`, `fleet_task_history`, `fleet_robot_reservations`, `fleet_action_claims`) by literal SQL equal `KNOWN_WRITERS`; a new writer or a dropped one fails, so a new writer needs a reviewed edit of the list |
| `test_app_identity.py` | D-377 "Rosy + one English word": each `surfaces.yaml` app row must agree on display names, folder name, `rosy_<word>` package, `<word>.svg` icon and Android ids (`io.github.livsbittt.rosy.<word>`). `PENDING` lists rows not yet renamed; a pending row must still break the rule |
| `test_app_roles.py` | D-370 one role per app: Cam app has no CORE API, Fleet user API, cmd_vel or estop; Vision has no robot command and writes only sightings to Fleet; Fleet vision routes only issue leases; Pilot never calls Fleet; each operation has one owning surface (e-stop and ADR-marked transitional entries excepted) |

## For AI Agents

### Working In This Directory

- Fix the layout, not the test. If a move is intended, update the target/exception table in the same commit.
- New package: add `AGENTS.md`, a `harness.yaml` entry, `test/`, declare cross-package use in `package.xml`, and add a `FOLDER_TO_PACKAGE` row if folder and package names differ.
- Size (D-766, revision 2). A file over 600 lines (`.js`/`.mjs`/`.ts` too; `.html`/`.css` 800 with at most 600 lines of inline `<script>`; a test file 1,500) or a unit over 10,000 is split in the same commit as the growth or an earlier one; there is no verdict and no allowance. Each commit passes on its own: `python tools/harness/size_range.py main HEAD` (git only, no tests); the pre-push hook and CI run it beside the Safety-Review check. `tools/land.py` does not.
  - **Lower a ratchet row.** When a change shrinks a frozen file or unit, set its `size_ratchet.txt` row to the new count in the same change; delete the row when it is back under the limit. `python test/architecture/test_module_structure.py` rewrites the measured rows (comments and `safety` rows stay). The script never writes a row above its value and keeps the row of a `safety` key. The guard refuses a raised row or a new row against the base: the newest of `ROSY_SIZE_BASE` and the merge-bases with `main` and `origin/main` whose tree has `size_ratchet.txt`, else the nearest first-parent ancestor that has it. Without git history the test fails, it never skips.
  - **Move a frozen file.** A pure move of a frozen file (e.g. `proposal_store.py` into a new holder) renames its row: delete the old row and add the new key in the same change, with a count not above the old row. Any other new row is refused.
  - **Register a unit.** Add the path to `size_units.txt`. It must be a Python subpackage or a declared holder (Fleet `SERVER_HOLDERS`, control `_source_layout.py` `PACKAGE_DIRS`/`FLAT_ROOTS`/`CONTROL_ROOTS`, or a CMake `install(DIRECTORY …)` folder), have a module docstring and its package `AGENTS.md` row, and be 1,000 lines or more when its parent was 2,000 or more. No new `small` marks.
  - **Safety exception.** A D-430 safety fix inside a frozen file or unit may go up to +30 over its row: add `safety <count> <key> <expiry>` (expiry at most 7 days after the commit) in the same commit, which carries a `Safety-Review:` trailer. Split it and delete the row before the expiry; the expiry is checked against the run date, so after it every run is red. A safety row already in the base is never edited (no renewal).
  - **Merging main.** Before D-766 lands, main grows under the old rule; merge it with `git merge --no-commit main`, set the rows to the measured counts, then commit. A merge with a parent that has no `size_ratchet.txt` is the transition: it has no base (like the landing commit) and is the base for the commits after it, in the guard and in `size_range.py`.
  - **Pure moves.** `python tools/harness/split_check.py <base> <head>` prints `AST identical, only imports/paths changed` (exit 0) or what differs: a definition, its order, a non-path string constant, an import to a module outside the moved set, or any changed non-`.py` file. A pure move gets a boundary review only (D-766 3). Compression (joining lines, dropping docstrings) is not a split.
- Launch coupling is found only through literal package-name calls; dynamic imports need functional coverage. Packages are found under manifest `colcon_roots`: `learning`, `operations`, `middleware`, `contracts`, `integrations`, `shared`.
- Prove a new guard by mutation: break the guarded thing, see red, restore, see green.

### Testing Requirements

```bash
python tools/remote/remote_pytest.py --log-dir "${ROSY_SCRATCH:-${TMPDIR:-/tmp}}/architecture-check" -- test/architecture -q
```

`test_module_structure.py` is also part of the D-346 pre-push fast gate (`tools/hooks/`).

### Common Patterns

- `ROOT = Path(__file__).resolve().parents[2]`; scans skip `build install log .worktrees .git node_modules __pycache__`.
- Exception tables are dicts of `key -> reason`; the reason is mandatory.

## Dependencies

### Internal

- `tools/harness/harness.yaml`, `platform_parts.yaml`, `shared/web/surfaces.yaml`, package manifests and owner guides under the current declared roots

### External

- pytest, PyYAML, git

<!-- MANUAL: -->
