# ROSY surface typography and focus token plan

**Decision:** [D-296](../adr/D-296-surface-typography-and-focus-token-contract.md)
**Status:** Complete (local source and browser verification)

## Goal

Apply the shared typography and keyboard-focus vocabulary consistently to repeated rules in the HMI dashboard, Fleet console, and games board without changing the rendered hierarchy, palette, spacing, or surface layout.

## Steps

1. [x] Add failing surface CSS contract tests for repeated weights, canonical leading/tracking values, and standard `:focus-visible` ring dimensions.
2. [x] Add the regular-weight and outer-focus-offset tokens, then migrate the three surface CSS domains while preserving computed values. Retain only the documented surface-specific exceptions.
3. [x] Append module journals and update web-common/dashboard/Fleet/games progress references.
4. [x] Run focused contract tests, browser-enabled HMI tests, Fleet and games suites, and harness lint/generation. Compare unrelated failures against the base branch without hiding them.
5. [x] Review Fleet and games browser captures at desktop viewport dimensions. Captures are under `X:\DevTemp`.
6. [ ] Commit exact changed paths, merge latest `main` into the branch, rerun relevant checks, and fast-forward local `main` if clean. Do not push.

## Acceptance

- Repeated weights, line heights, tracking values, and standard keyboard focus-ring dimensions use shared tokens in all three surface domains.
- Computed visual metrics remain unchanged; unique brand tracking, extended Fleet prose leading, canvas focus offset, and operational active outlines retain their documented treatment.
- Browser review finds no new page errors or horizontal overflow.
- Local source and browser evidence are reported separately from device or field acceptance.

## Verification note

- Surface/token contracts: 40 passed. Browser-enabled HMI suite: 102 passed.
- Base `0dc7e8a4` Fleet and games host suite: 619 passed, 5 skipped, with one stale API-reference version assertion (`v1.35` expected; document was `v1.39`). Latest `main` (`2230d26e`) updated both to v1.40; rerun after integration.
- Fleet/games browser suite: 17 passed, 2 Fleet keyboard/queued interaction timeouts; both reproduce on latest unmodified `main`.
- Harness generation and lint: 0 errors, 18 existing warnings.
- Local commit and merge remain the final step.
