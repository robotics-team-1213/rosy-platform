# D-626 holder migration independent Safety review

## API holder — source approval

2026-10-11, independent reviewer `/root/safety_structure_review`, requesting-code-review workflow. Reviewed staged candidate against `ae8e0fe5b` before the first migration commit.

**Verdict: APPROVE, source only.** `middleware/core/api_web` becomes `middleware/core/api`. `core_api_web/api/v1/safety.py` is an R100 move with identical Git blob `313f8c550`. All production API Python and package/setup/resource bytes remain identical. Manifest current root and `safety_modules` path change while `d427_target`, `legacy`, import identity and symbol/string anchors remain unchanged. Docker source changes while `/opt/rosy_ws/src/runtime/api_web` stays the installation destination.

Review found and required correction of gateway `CORE / "api_web"` and the live `ROLE_DIR` physical-layout tuple. Both now refer to `api`. CORE final writer, command/Safety source and external API contracts remain unchanged. Gate commands now address the current source suite through the remote test runner.

This review authorizes the source migration's `Safety-Review:` trailer. Candidate remote tests, package installation, ARM64 artifact, device stop/readback and field acceptance are separate requirements. No device acceptance is claimed.

## Pinky holder — source approval

2026-10-11, same independent reviewer, staged candidate against `74a1db355`: **APPROVE, source only.** Driver, command deadman, launch, setup, package.xml and physical description bodies are unchanged. Numeric geometry and Docker installation destinations remain unchanged. Current manifest paths/layout_target and physical package-role tuples change; D-427 ownership identity remains frozen. Moved test repository ancestors are corrected. The source profile resolver is verified separately by remote robot-selection tests. Movement commit: `7b0a8d965`.

## OMX holder — source approval

2026-10-11, same independent reviewer, staged candidate against `828e10ed5`: **APPROVE, source only.** Five tagged Safety files retain their original blobs. Arm owner, HOLD, StopLocal/RearmLocal, unresolved action readback and recovery implementation are unchanged. Package/setup/agent wheel metadata stay unchanged. Docker source, caller PYTHONPATH, CI wheel path, manifest Safety paths and test repository ancestors are updated. Pilot simulation source hashing reads the current folder; installed destinations and ownership identifiers are retained. Movement commit: `9de41f5c7`.

## Nav2 holder — source approval

2026-10-11, same independent reviewer, staged candidate against `9de41f5c7`: **APPROVE, source only.** All launch, Python, params, package.xml, CMake, maps and RViz bytes remain identical. Standalone and composed launches retain `cmd_vel_smoothed -> nav_cmd_vel`. Docker installation destination remains unchanged. Physical layout declaration changes without changing ownership concern or import identity. Movement commit: `291d03a9f`.

## D-627 CORE Drive composition — source approval

2026-10-11, same independent reviewer, staged candidate against `062e79d3c`: **APPROVE, source only.** Existing line-follow implementation is moved unchanged with explicit compatibility exports. Docking/swarm construction, same manager objects/providers, deferred docking closures, expected-mode checks, Nav2 cancellation order and leave-docking stop/clear remain equivalent. `data_path` is the original `waypoints_path.parent`; logger name stays `core.services`. Global mode and E-stop listener registration order stays in `CoreServices` unchanged.

Review required Safety anchors for both newly tagged implementation files; four module-qualified anchors are now present. Independently counted `services.py` at 481 lines, so the obsolete >600 size verdict is removed without raising any budget. `find_packages` includes the new `core.drive` package. Implementation commit: `1691d395c`.

Planning/tracking/recovery algorithm extraction, new curvature policy and recovery behavior are still subsequent work. Remote characterization, actual installed wheel discovery, Jazzy launch, ARM64 image, device stop/readback and field acceptance remain separate from every source approval above.
