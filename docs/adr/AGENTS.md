<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-10-02 | Updated: 2026-10-02 -->

# adr

## Purpose

One Markdown file per Architecture Decision Record (about 400 files, `D-1` to roughly `D-409`). Each file holds the body of one decision; the index table (ID, title, Status) lives in `docs/reference/ROSY ADR Log.md`. Records preserve why a decision was made, not how the code looks now.

## Key Files

Files are not listed individually. Naming scheme:

| Pattern | Description |
|---------|-------------|
| `D-<n>-<slug>.md` | One ADR. `<n>` is the decision number without zero padding (`D-9`, `D-100`); `<slug>` is a short, sometimes truncated, title slug. Files sort lexically, not numerically |
| `## D-<n> <title>` heading | First heading of the body; the harness matches `^## (D-\d+):? (.+)$` |
| `**Status:**` line | `Proposed`, `Accepted (date)`, or `Superseded by D-<m>` |

Body sections are Status, Context, Decision, Consequences (some add Alternatives). Most are Korean prose with English identifiers.

## For AI Agents

### Working In This Directory

- ADRs are append-only. Never rewrite an accepted decision: mark it `Superseded by D-<m>` and write a new ID.
- Reserve the number right before writing with `python tools/harness/adr_reserve.py next "<topic>"` (D-510; it creates `refs/adr/D-nnn`, one winner per number). Intentional gaps are one `D-nnn reason` line each in `tools/harness/adr_gaps.txt`.
- Every ADR needs a row in `docs/reference/ROSY ADR Log.md` with the same title and Status, and the log must be updated in the same change.
- Accepted does not mean implemented or device-accepted; say so in the body when it matters.
- Internal or strategy material goes in the gitignored `private/`, not in an ADR (public repo).
- After edits, follow the harness steps in `docs/AGENTS.md`.

### Testing Requirements

```bash
python3 tools/harness/rosy_harness.py lint
python3 -m pytest test/test_harness_contracts.py -q
```

Lint merges `docs/adr/*.md` bodies with the log and reports duplicate bodies, missing index rows or bodies, and undeclared numbering gaps. Some tests read a specific ADR (for example `test_module_scorecard.py` reads D-178, `test_site_candidate.py` reads D-301), so renaming those files breaks them.

### Common Patterns

- Cross-references use `D-<n>`; requirement IDs (`SAF-005`) come from `docs/spec/`.
- Many ADRs say "observation decision, not implementation GO".

## Dependencies

### Internal

- `docs/reference/ROSY ADR Log.md` (index), `tools/harness/rosy_harness.py` and `harness.yaml`, `docs/spec/`

### External

None.
