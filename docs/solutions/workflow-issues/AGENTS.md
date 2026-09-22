<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-14 | Updated: 2026-09-14 -->

# workflow-issues

## Purpose

Compound lessons about verification process: a gate that cannot actually check is not a pass. Apply when adding tests, deploy guards, or documented human procedures.

## Key Files

| File | Description |
|------|-------------|
| `inability-to-check-recorded-as-clean-result.md` | An inability to check is not a clean result: mutation-test gates, check subprocess exit status, do not treat skip as pass |
| `a-fixture-from-the-same-model-is-one-belief-not-two.md` | A fixture generated from the same mental model as the code is one belief, not two: seed tests with scenes the author did not design (evidence lives on the archived dock-rig tag) |

## Subdirectories

None.

## For AI Agents

### Working In This Directory

- When adding a guard, prove it fails when the protected thing is broken. Green without that probe is not evidence.
- Shell probes must check exit status; empty stdout from a failed command is not "nothing found."
- A documented human path (README, deploy script) that is untested is a finding, not an implicit pass.

### Testing Requirements

None here. The lesson is for how tests and gates are written elsewhere.

### Common Patterns

YAML frontmatter `problem_type: workflow_issue`. Tags: fail-open, mutation-testing, silent-failure.

## Dependencies

### Internal

- Deploy/image/release tests under `test/` and package `test/` trees

### External

None.

<!-- MANUAL: -->
