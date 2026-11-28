
# assessments

**Parent context:** `../AGENTS.md`

## Purpose

Dated, point-in-time evaluations of the whole tree: module coupling and communication protocols. They are measurements and rationale; the decisions they feed are ADRs (the scorecard criteria are D-178).

## Key Files

| File | Description |
|------|-------------|
| `rosy-main-e2b0098-test-evidence.png` | Test-run screenshot for a pinned main commit |

## For AI Agents

### Working In This Directory

- Treat each report as a snapshot of its stated date and tree; do not silently update numbers. Add a dated section or a new file for a re-run.
- Mostly Korean prose with English identifiers. Reports cite their baseline (date, commit, package count); keep that header accurate.
- Acceptance evidence for devices and simulation belongs in `docs/validation/`, not here.

### Testing Requirements

`test/architecture/test_folder_layout.py` asserts `communication-protocol-report.md` and `module-coupling-scorecard.md` exist here. The scorecard's gates are enforced by `test/architecture/test_module_structure.py` (D-168) and `test/test_module_scorecard.py` (D-178):

```bash
python3 -m pytest test/architecture/test_folder_layout.py test/architecture/test_module_structure.py test/test_module_scorecard.py -q
```

### Common Patterns

- The scorecard supersedes the coupling report's framing but keeps it as the evidence base.

## Dependencies

### Internal

- `docs/adr/D-178-module-maintainability-scorecard.md`, `docs/reference/` contracts, `src/` module tree
