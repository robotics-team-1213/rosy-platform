# ROSY role-based UX review and implementation plan

> 상태: 조사 중. 현재 UI와 역할 계약을 실제 CORE로 확인한 뒤 점수·결정·수정 범위를 확정한다.

## Goal

ROSY의 현대적 브랜드 팔레트가 작업 의미를 방해하지 않는지 재평가하고, viewer/operator/administrator가 각자의 권한과 주 업무에 맞는 메뉴·정보 우선순위·액션을 실제 웹 화면에서 이해하고 사용할 수 있도록 조정한다.

## Constraints

- `src/hmi/web/tokens.css` is the only colour source. Keep D-82 status, focus, data and safety meanings intact; refine D-277 brand usage only with measured evidence.
- D-270 role gating and D-263 menu/surface ownership are contracts. UI may clarify available capabilities but must never grant access or infer identity from an admin-only route.
- Keep the universal emergency-stop access and confirmation/recovery semantics defined by the existing safety contract.
- Desktop operator console remains spatial; setup/configuration remains a distinct surface. Mobile must remain usable without horizontal overflow.
- Use the real CORE FastAPI path with role-specific dev identities for browser evidence. No robot or motor acceptance claims.
- Do not edit existing main worktree WIP.

## Review and implementation phases

1. Read relevant ADR/SRS/API/UI contracts and capture the current role matrix, menu visibility and panel/action ownership.
2. Inspect the real `/console`, `/setup` and any other registered surface as viewer, operator and administrator at desktop and mobile widths. Record computed palette/contrast, missing button kinds, overflow, permission mismatches and the primary task each surface supports.
3. Write the evaluation and role-to-surface decision in a dated design plan and ADR. Keep the accepted strategy incremental: distinct information/action hierarchy per role while preserving the common shell and safety entry point.
4. Implement only the evidence-backed UI/UX gaps. Add source-level checks for role visibility and semantic color use where needed.
5. Run focused tests and live visible Playwright review for each role/surface at desktop and mobile. Regenerate indexes; record limits separately from device acceptance.
6. Recheck branch ancestry, overlapping main WIP and project lint before local commit/integration.

## Design alternatives to compare

- One shared screen with controls progressively hidden by role.
- Role-first landing surfaces with shared status/safety shell and role-specific content/action hierarchy.
- Separate applications per role.

Evaluate each against role task completion, permission clarity, discoverability, cognitive load, safety visibility and implementation ownership before selecting.

## Findings

### Role and surface review

| Role | Allowed surfaces | Main console content | Setup / device content |
|---|---|---|---|
| Viewer | `/console` | State, map, camera, universal E-stop | Not shown |
| Operator | `/console`, `/setup` | Viewer observations plus mode, teleop, docking and line-follow panels | Waypoints, localization/map, docking prep, traffic policy |
| Administrator | all three | Operator console | Operator setup plus dock registration; device, host, events, diagnostics and security panels |

The role matrix in `panels.yaml` and API matches the task split. Viewer saw only console. Operator saw console and setup, without `setup.dock_admin` or `/device`. Administrator saw all three, including both. The single shared shell keeps role, active surface and E-stop in a stable location.

### Live browser evidence

- CORE was built with `CoreServices.build()` from this checkout and served locally with the real FastAPI app and dev role identities; visible Chromium tested direct `/console`, `/setup`, and `/device` navigation.
- The viewer initially saw active-looking map position and goal controls. Both API mutations require operator and Navigation support, but the UI only gated the canvas commit. The map panel now disables both controls until role and capability are known, names the reason, links the reason using `aria-describedby`, and the map module rechecks the same predicate before mode selection/canvas requests.
- The local Pinky Pro profile does not expose goal Navigation. The operator correctly sees the controls disabled with a profile-specific reason; this does not prove their enabled live-device state. The Viewer sees the role-specific reason. No destructive control was clicked.
- On the first 390px review, the three map layer toggles filled three vertical rows and the E-stop label wrapped. They now form a horizontal 3-item group with 44px targets, use a neutral raised selected state, and keep E-stop text on one line. The viewer, operator and admin direct screens had no horizontal overflow; E-stop stayed visible.
- The map endpoint returned 404 in this CORE-only host, so the map body remains in its waiting/empty state. Device panels also report the host-agent socket unavailable. These are truthful local-runtime limitations, not menu or color failures.

### Palette evaluation

Retain the accepted D-277 tokens. The rose wordmark/current-menu color reads as ROSY identity and has 9.39:1 contrast on the page ground and 8.72:1 on the rose wash. Muted informational text is 6.55:1 on the ground. E-stop white on critical red is 5.31:1. Critical red, warning amber, cool focus/data blue and neutral normal actions retain separate meanings. The selected map layers now use the existing neutral raised surface; role identity does not receive its own color because that would blur task state and authority.

### Alternatives and choice (D-278)

Scores are equal-weighted 1–5 ratings across task fit, permission clarity, discoverability, cognitive load, safety visibility and ownership cost:

| Approach | Fit | Permission | Findability | Load | Safety | Ownership | Total |
|---|---:|---:|---:|---:|---:|---:|---:|
| One screen with role-hidden controls | 2 | 2 | 3 | 2 | 4 | 3 | 16/30 |
| Task surfaces with common role-aware shell | 5 | 5 | 5 | 4 | 5 | 5 | 29/30 |
| Separate application per role | 4 | 5 | 4 | 5 | 4 | 1 | 23/30 |

Decision: keep `/console`, `/setup`, and `/device` as role-aware task surfaces with one shared shell. Use D-270 model B for console actions (visible disabled controls with a reason) and model A for setup/device procedures (hide out-of-role panels). Keep the D-277 palette unchanged; improve layout and control hierarchy without using brand color as a permission or status signal. Full rationale is in [D-278](../adr/D-278-role-based-surface-ux-and-palette-review.md).

## Validation

- `src/hmi/web/test`, `src/hmi/dashboard/test`, gateway dashboard/role tests.
- Real CORE `/console` and `/setup` visible Chromium session for viewer/operator/administrator at 1440px and 390px.
- Contrast and computed-token checks; no missing UI button kinds; no horizontal overflow; role action visibility matches server authorization.
- `python tools/harness/rosy_harness.py generate` / `lint`, `git diff --check`.

## Completion notes

- Role matrix, palette and responsive behavior reviewed in visible CORE Playwright. Map action permission cues and mobile controls improved. Automated verification, source generation, lint, commit and safe local integration remain.
