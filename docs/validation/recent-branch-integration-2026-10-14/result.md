# Recent branch integration, 2026-10-14

User scope: inspect Oct 13/14 commit state and merge ready work into local main. No push or deployment requested. Initial inventory at main `commit 22811dc39`: 13 unmerged recent branches. Shared main subsequently received OMX simulation preparation, worktree gateway and the D-762 held-branch register from their owners.

## Included

- docs/fleet-robot-bounds-ride-through, including docs/robot-held-map-anchor.
- feat/bend-next-line-in, preserving both D-754 next_line_in_m and main's D-759 map_entry.
- feat/fleet-rule-m-warn, diagnostic-only Rule M.
- fix/crosswalk-misread-edges-lane-width.
- feat/fleet-app-bar, remaining merge history only.
- feat/omx-sim-preparation and feat/worktree-gateway were already landed by owners during this session.

## Held

Respect docs/reference/held-branches.md, which arrived during integration:

- refactor/d171-track1-port: ROS import/rig A-B and size judgement outstanding.
- feat/device-power-policy-port: safety tagging, size, browser and device evidence outstanding.
- feat/sd-identity-mode-port: PowerShell tests on a test host outstanding.
- fix/lane-odom-cross-veto-port: requires redesign; do not merge raw candidate.
- fix/gazebo-map-lap: owner has six uncommitted safety/source paths.

The exploratory combined candidate remains on refactor/merge-oct13-14 (`commit 19f3c0020`), including the independently reviewed readiness correction (remote 14 passed, NEW 0). It is not the landing candidate. No held port, readiness change or D-171 exemption is included in refactor/merge-ready-oct13-14. Original topic refs and other sessions' WIP are preserved.

## Integration review

Independent /root/integration_review SOURCE review verified D-754/D-759 schema, API validation, capability reporting, Fleet fields and CORE next-line/map-entry storage. A missing property decorator in the exploratory union was corrected before this candidate. A combined-capability trip regression exercises both transmitted fields. Latest API reference and live pins are v1.225. Logs retain both intents in chronological order; generated indexes are regenerated. Only ADR gap rows for existing ADR files were removed.

Final remote affected gate and safety check remain pending at this record's commit. Full CI, browser, ARM64 image, Gazebo, deployment, robot actuation and physical acceptance are separate and are not established here. Pytest never ran on the development laptop.
