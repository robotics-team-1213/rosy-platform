<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-10-02 | Updated: 2026-10-02 -->

# architecture

## Purpose

Repo-structure tests: where folders, packages, documents and imports are allowed to live. They read the source tree, `package.xml` files, `harness.yaml` and `surfaces.yaml`; they do not need ROS. Most use exception tables checked by set equality (P5), so a new violation fails and so does a stale entry. Update the table in the same commit that creates or removes the violation.

## Key Files

| File | Description |
|------|-------------|
| `test_module_structure.py` | D-168 package standard. P2: every package sits under a domain group (`contracts runtime drivers products hmi site sim`) at its declared root, has `AGENTS.md`, is a `harness.yaml` module, owns `test/test_*.py` (exceptions: `KNOWN_WITHOUT_OWN_TESTS`); library packages write N/A for ROS-SIM..FIELD. P3: every import, include and launch reference to another package is declared in `package.xml`. P4: cross-domain edges follow the direction table, the core chain stays `common <- events <- features <- api_web <- core`. P6 (D-362): 600 lines per production `.py/.cpp/.hpp/.sh` (also under `deploy/ tools/ firmware/`), 800 for web assets, 10 000 per package, zero growth above 1 000; over-budget code needs a recorded verdict in `SIZE_VERDICTS`. Also unit-tests the direction and layout rules as pure functions |
| `test_target_layout.py` | D-310 source layout: every package has a declared target path, XML package names are unique, moved packages keep their name, product containers hold only declared packages, retired sketch names (`rosy_pinky_pro`, `rosy_decision`, ...) must not appear |
| `test_folder_package_names.py` | D-339/D-231: a package whose folder name differs from its `package.xml` name must be in `FOLDER_TO_PACKAGE` (mirrored in `src/AGENTS.md`), and no entry may go stale |
| `test_folder_layout.py` | D-186 script and markdown ownership: root has only `env.sh` as a shell script, no second installer under `src/**/deploy`, developer scripts under `tools/`, deploy sources grouped by robot product, validation shells only inside `evidence/`, `progress.md/logs.md/index.md` only in registered harness modules, `data/` holds only its README markdown and the seven tracked teleop clips, no retired paths in current docs |
| `test_document_placement.py` | D-226 publication first: sample secret/internal paths (`private/`, `.env`, keys, images, bags, `data/teleop`, `*.sqlite3`, worktrees) must be git-ignored; templates, public keys and public material must stay trackable; no tracked file under an ignore rule; repo root carries only the listed files; dated evidence stays out of modules; module roots carry only `README AGENTS CLAUDE progress logs index`. Needs `git` on PATH |
| `test_layer_boundaries.py` | D-229 by AST import scan: perception imports neither decision, vision nor ROS; decision does not import perception; line_follow reads decisions, not pixels; geometry does not import perception |
| `test_app_identity.py` | D-377 "Rosy + one English word": each `surfaces.yaml` app row must agree on display names, folder name, `rosy_<word>` package, `<word>.svg` icon and Android ids (`io.github.livsbittt.rosy.<word>`). `PENDING` lists rows not yet renamed; a pending row must still break the rule |
| `test_app_roles.py` | D-370 one role per app: Cam app has no CORE API, Fleet user API, cmd_vel or estop; Vision has no robot command and writes only sightings to Fleet; Fleet vision routes only issue leases; Pilot never calls Fleet; each operation has one owning surface (e-stop and ADR-marked transitional entries excepted) |

## For AI Agents

### Working In This Directory

- Fix the layout, not the test. If a move is intended, update the target/exception table in the same commit.
- New package: add `AGENTS.md`, a `harness.yaml` entry, `test/`, declare cross-package use in `package.xml`, and add a `FOLDER_TO_PACKAGE` row if folder and package names differ.
- A file over budget: split it before adding a verdict. Verdict text is a decision record, not a way to pass.
- Launch coupling is found only through literal package-name calls; dynamic imports are invisible to these scans. Packages are found under every `colcon_roots` entry (`src`, `learning`, `operations`).
- Prove a new guard by mutation: break the guarded thing, see red, restore, see green.

### Testing Requirements

```bash
python -m pytest test/architecture -q
```

`test_module_structure.py` is also part of the D-346 pre-push fast gate (`tools/hooks/`).

### Common Patterns

- `ROOT = Path(__file__).resolve().parents[2]`; scans skip `build install log .worktrees .git node_modules __pycache__`.
- Exception tables are dicts of `key -> reason`; the reason is mandatory.

## Dependencies

### Internal

- `tools/harness/harness.yaml`, `src/hmi/web_common/surfaces.yaml`, every `src/**/package.xml`, `src/AGENTS.md`

### External

- pytest, PyYAML, git

<!-- MANUAL: -->
