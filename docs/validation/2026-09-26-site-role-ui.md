# Site Fleet role-aware console validation (2026-09-26)

## Scope

The site console now asks Fleet for the authenticated principal and role. It
shows that identity, leaves operational controls disabled until an
`operator` identity is confirmed, and keeps server-side authorization as the
authority. Unknown roles are treated as read-only.

## Checks

- Fleet site-focused suite: `528 passed, 5 skipped`.
- Node role-control unit tests: `2 passed`.
- `node --check` on `console.js`, targeted flake8, `git diff --check`, and the
  generated-record contract test passed.
- Built local `linux/amd64` image `rosy-fleet:site-role-ui`:
  `sha256:7ec34595ecea314ecc16643998c53c76093d1f549a17cd5b2827c36695030c70`.
- Ran the built image's FastAPI app in a local container. No credential gave
  `401`; a synthetic viewer got only its principal and role from
  `/api/fleet/session`; `/console/assets/authorization.js` returned `200`.

## Remaining acceptance

No browser was used to verify rendered layout, keyboard behavior, or role
changes through the actual page. Ubuntu site deployment, real credential
handoff/revocation, CORE readback, GPU/camera behavior, and physical robot
acceptance remain open. No real robot endpoint was contacted.
