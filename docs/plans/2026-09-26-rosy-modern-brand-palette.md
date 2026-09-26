# ROSY Modern Brand Palette Implementation Plan

> **For Codex:** follow the TDD skill, make each palette value testable, and keep safety semantics unchanged.

**Goal:** Give ROSY a modern, recognizable rose-magenta brand accent in the role based web UI while retaining the existing status, focus, and data colour contracts.

**Architecture:** `src/hmi/web/tokens.css` remains the single source for colour values. Add only the rose values used by the wordmark and selected surface navigation; generate them in OKLCH and guard their hue, contrast, and separation from safety colours. Do not recolour E-stop, warning, critical state, map data, or keyboard focus. Repair dynamically-created shared buttons so the red missing-kind diagnostic no longer reads as the product palette.

**Tech Stack:** CSS custom properties, framework-free custom elements, Python/pytest palette and shared-control contracts, existing FastAPI-served dashboard.

---

### Task 1: Pin the ROSY brand colour contract

**Files:**
- Modify: `src/hmi/web/test/test_palette_gates.py`
- Test: `src/hmi/web/test/test_palette_gates.py`

**Steps:** Add failing assertions that the brand rose and its subtle selected-surface tint exist, the main brand colour stays in the rose-magenta OKLCH band, and it remains readable on the neutral ground. Keep brand tokens outside the existing status and map-series sets. Run `python -X utf8 -m pytest src/hmi/web/test/test_palette_gates.py -q --basetemp=X:\DevTemp\rosy-modern-palette-red` and confirm it fails because the tokens are absent.

### Task 2: Apply the tokens to ROSY identity and selected location

**Files:**
- Modify: `src/hmi/web/tokens.css`
- Modify: `src/hmi/web/components.css`
- Modify: `src/hmi/dashboard/styles.css`
- Modify: `src/hmi/dashboard/shell/shell.css`
- Modify: `src/hmi/dashboard/surface.html`
- Modify: `src/hmi/dashboard/index.html`
- Test: `src/hmi/web/test/test_palette_gates.py`

Add OKLCH-derived `--brand-rose` and `--brand-rose-wash` values. Use the accent on the shared ROSY wordmark and current role-menu item only. Keep focus blue, routine actions neutral, and irreversible safety actions red. Align browser chrome with the neutral page ground and contract-test that value against the palette token. Run the palette tests and confirm they pass.

### Task 3: Remove missing button-kind diagnostics from real surfaces

**Files:**
- Modify: `src/hmi/web/test/test_shared_controls.py`
- Modify: affected dynamically-built controls under `src/hmi/dashboard/panels/`

Extend the contract to inspect shared helper-created buttons as well as literal `createElement` calls. First run `python -X utf8 -m pytest src/hmi/web/test/test_shared_controls.py -q --basetemp=X:\DevTemp\rosy-modern-palette-buttons-red` and record the failing callsites. Give every generated button an explicit existing kind (`primary`, `quiet`, `irreversible`, `segment`, or `toggle`) according to its actual action; do not weaken or hide the red diagnostic. Rerun the test to confirm it passes.

### Task 4: Record and validate the decision

**Files:**
- Create: `docs/adr/D-277-rosy-brand-colour-tokens.md`
- Modify: `docs/reference/ROSY ADR Log.md`
- Modify: `src/hmi/web/progress.md`
- Modify: `src/hmi/web/logs.md`
- Generated: `docs/index.md`, `src/hmi/web/index.md`

Document the brand/status/focus separation and the scoped usage rule. Run `python -X utf8 -m pytest src/hmi/web/test src/hmi/dashboard/test -q --basetemp=X:\DevTemp\rosy-modern-palette-final` plus the gateway dashboard route tests, run `python tools/harness/rosy_harness.py generate` and `lint`, and review the real CORE `/console` with visible Playwright at desktop and mobile sizes. Fix any measured narrow viewport overflow in the existing dashboard shell. Leave the robot and motor profile untouched.
