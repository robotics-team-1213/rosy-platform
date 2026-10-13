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
| `test_module_structure.py` | D-168/D-427 package standard: declared roots, owner guides, harness modules and functional tests; package dependencies and import direction; D-362 file/package size limits and recorded `SIZE_VERDICTS`. Static holder mapping preserves installed package identities |
| `test_target_layout.py` | D-310 source layout: every package has a declared target path, XML package names are unique, moved packages keep their name, product containers hold only declared packages, retired sketch names (`rosy_pinky_pro`, `rosy_decision`, ...) must not appear |
| `test_folder_package_names.py` | D-339/D-231: a source folder whose name differs from its installed package name must be in `FOLDER_TO_PACKAGE`; no stale entries |
| `test_folder_layout.py` | D-186 script/document ownership, declared deployment and data layout, no retired paths in current developer docs. Module-local helpers stay with their actual install/consumer owner; workspace tools compose owners |
| `test_document_placement.py` | D-226 publication first: sample secret/internal paths (`private/`, `.env`, keys, images, bags, `data/teleop`, `*.sqlite3`, worktrees) must be git-ignored; templates, public keys and public material must stay trackable; no tracked file under an ignore rule; repo root carries only the listed files; dated evidence stays out of modules; module roots carry only `README AGENTS CLAUDE progress logs index`. Needs `git` on PATH |
| `test_layer_boundaries.py` | D-229 by AST import scan: perception imports neither decision, vision nor ROS; decision does not import perception; line_follow reads decisions, not pixels; geometry does not import perception |
| `test_app_identity.py` | D-377 "Rosy + one English word": each `surfaces.yaml` app row must agree on display names, folder name, `rosy_<word>` package, `<word>.svg` icon and Android ids (`io.github.livsbittt.rosy.<word>`). `PENDING` lists rows not yet renamed; a pending row must still break the rule |
| `test_app_roles.py` | D-370 one role per app: Cam app has no CORE API, Fleet user API, cmd_vel or estop; Vision has no robot command and writes only sightings to Fleet; Fleet vision routes only issue leases; Pilot never calls Fleet; each operation has one owning surface (e-stop and ADR-marked transitional entries excepted) |

## For AI Agents

### Working In This Directory

- Fix the layout, not the test. If a move is intended, update the target/exception table in the same commit.
- New package: add `AGENTS.md`, a `harness.yaml` entry, `test/`, declare cross-package use in `package.xml`, and add a `FOLDER_TO_PACKAGE` row if folder and package names differ.
- A file over budget: split it before adding a verdict. Verdict text is a decision record, not a way to pass.
- Launch coupling is found only through literal package-name calls; dynamic imports need functional coverage. Packages are found under manifest `colcon_roots`: `learning`, `operations`, `middleware`, `contracts`, `integrations`, `shared`.
- Prove a new guard by mutation: break the guarded thing, see red, restore, see green.

### Testing Requirements

```bash
python tools/remote/remote_pytest.py --log-dir X:/DevTemp/architecture-check -- test/architecture -q
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
