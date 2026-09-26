## D-279 역할별 빈 상태와 복구 안내

**Status:** Accepted (2026-09-26)

Related: [D-278](D-278-role-based-surface-ux-and-palette-review.md),
[D-284](D-284-shared-role-surface-status-component.md).

**Context:**

The console map treats every first read as loading although `GET /api/v1/map`
returns HTTP 404 with `error.code=NOT_FOUND` when no occupancy map has arrived.
Other failures such as 403 and transport errors need different guidance. Host
Agent relay responses already include `available`, `code`, `detail`, and
`recovery`; the dashboard must report those fields without guessing a cause.
Setup navigation also varies by role and current surface manifest.

**Decision:**

1. The dashboard API client preserves the HTTP status and structured error code.
   Only the documented `404 / NOT_FOUND` response for optional map data becomes
   an empty result. Other 404s, 403s, and request failures remain distinct.
2. The map reports loading, empty, ready, forbidden, and request-error states
   separately. It does not present an older map as fresh because the API has no
   map freshness field.
3. A Viewer sees the missing-map explanation without a setup action. An
   Operator or Administrator sees the `/setup` recovery link only when the
   current surface manifest grants setup. Server authorization remains
   authoritative.
4. Host Agent unavailability shows its known status and only the recovery
   guidance supplied by CORE. Diagnostic detail is separate, escaped as text,
   and does not become an inferred explanation. Request-level 403 and other
   failures remain distinct from `available: false`.
5. Host operations remain disabled until a successful readback. A later
   successful poll clears the unavailable state and re-enables controls only
   under existing role and capability rules.

**Alternatives:**

- Treat every map 404 as an empty map: rejected because an unrelated missing
  route would be mislabeled as valid absence.
- Show one generic error for every failure: rejected because it hides whether
  data is absent, forbidden, or temporarily unreadable.
- Guess a recovery action from arbitrary backend detail: rejected because the
  detail is diagnostic data, not a trusted command or role grant.

**Consequences:**

Each panel owns truthful endpoint-specific copy and recovery actions. Shared
announcement semantics and palette styling are supplied by D-284's `ui-status`.
Roles, API authorization, and capability checks are unchanged.

**Validation:**

Browser coverage exercises map loading, empty, ready, forbidden, unexpected 404,
and request error, plus role-gated setup navigation. Host coverage exercises
unavailability with and without recovery guidance, escaped diagnostic text,
blocked controls, and later successful readback. Visible CORE review covers
Viewer `/console`, Operator `/console` and `/setup`, and Administrator `/device`
at desktop and mobile widths. This is local CORE/browser evidence only; it does
not establish ROS-SIM, ARM64, device, or field acceptance.
