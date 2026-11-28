<!-- Parent: ../AGENTS.md -->

# architecture

**Parent context:** `../AGENTS.md`

Repo-structure tests: where folders, packages, documents and imports may live. They read the tree, `package.xml`, `harness.yaml`, `platform_parts.yaml` and `surfaces.yaml`; no ROS. Each test's docstring states its rule.
Exception tables use set equality (P5): a new violation fails and so does a stale entry. Update the table in the commit that creates or removes the violation.
Shrink-only lists use `test/ratchet_lists.py` (new entry fails, stale warns).

## For AI Agents

### Working In This Directory

- Fix the layout, not the test. Exception tables are `key -> reason`; the reason is mandatory.
- New package: `AGENTS.md`, a `harness.yaml` entry, `test/`, cross-package use declared in `package.xml`, and a `FOLDER_TO_PACKAGE` row if folder and package names differ.
- File count (D-1090): `test_file_count_budget.py` caps tracked files per area; past a cap, delete or merge in the same area, or raise the cap with `Budget-Raise: <area> +N (why)` in the PR body.
- Size (D-766 rev 2): a file over 600 lines (`.html`/`.css` 800, a test file 1,500) or a unit over 10,000 is split in the same commit as the growth or earlier; no verdict, no allowance. Each commit passes `python tools/harness/size_range.py main HEAD`; `tools/land.py` does not run it.
- Ratchet rows (`size_ratchet.txt`, `size_units.txt`) only go down: set a shrunk file's row to the new count in the same change; delete it under the limit (`python test/architecture/test_module_structure.py` rewrites measured rows).
- A raised or new row against the base is refused; without git history the test fails, never skips. A pure move renames the row with a count not above the old one.
- New units need a docstring and their package `AGENTS.md` row; no new `small` marks.
- Safety exception: a D-430 safety fix in a frozen file may go up to +30 over its row via `safety <count> <key> <expiry>` (expiry at most 7 days out) in a commit with a `Safety-Review:` trailer. Split and delete the row before expiry; after it every run is red.
- A safety row already in the base is never renewed. Safety-Review applies to every such edit.
- Merging `main` across D-766: `git merge --no-commit main`, set rows to measured counts, then commit.
- `python tools/harness/split_check.py <base> <head>` proves a pure move (boundary review only, D-766 3); compression is not a split.
- Registries only shrink: `known_app_imports.txt` (D-1036 add. 3; `ALLOWED_EDGES` consumer to library), `known_duplicates.txt` (D-940, reason names the bucket), `size_tiers` queues (D-949), `KNOWN_WRITERS` for Fleet ledger tables (D-750: a new writer needs a reviewed list edit).
- Boundaries: perception does not import decision, vision or ROS (D-229); an app imports only itself and `core` (D-1036); Cam has no CORE API, Vision issues no robot command, Pilot never calls Fleet (D-370).
- Meshes only under the five runtime roots with `SOURCE.json`, no CAD sources (2026-11-19); sample secret paths stay git-ignored (D-226).
- A commit adding a ratchet (`ratchet_lists` user or `*only_shrink` test) outside this folder adds it to `GUARD_SET` in `tools/harness/affected_tests.py` in the same commit (`test/test_harness_contracts.py`).
- `ROOT = Path(__file__).resolve().parents[2]`; scans skip `build install log .worktrees .git node_modules __pycache__`.
- Prove a new guard by mutation: break the guarded thing, see red, restore, see green.
- Launch coupling is found only through literal package-name calls; dynamic imports need functional coverage.

### Testing Requirements

```bash
python tools/remote/remote_pytest.py --log-dir "${ROSY_SCRATCH:-${TMPDIR:-/tmp}}/architecture-check" -- test/architecture -q
```

`test_module_structure.py` is also in the D-346 pre-push fast gate.



