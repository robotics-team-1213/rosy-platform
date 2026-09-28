---
title: A lost operator link leaves a motion trial unobserved
date: 2026-09-29
category: workflow-issues
module: deploy/robot/pinky_pro/native and attended G4 commissioning
problem_type: workflow_issue
component: development_workflow
severity: high
applies_when:
  - "running a bounded motor or command-loss trial from a remote PC"
  - "the PC loses Wi-Fi while the robot may be energized"
tags: [pinky-pro, commissioning, g4, wifi, watchdog, evidence, physical-stop]
---

# A lost operator link leaves a motion trial unobserved

## Context

During a real floor commissioning session, the operator PC lost its Wi-Fi
connection. SSH, CORE API, and the local Fleet endpoint became unreachable
together. The Windows WLAN event reported a driver disconnect. The attempted
command-loss trial contained no command timestamp or odometry samples; its
cleanup could not get a remote stop acknowledgement. A person at the robot
cut physical power. Earlier, separately captured trials remained separate
records; they did not turn this attempt into a G4 pass.

## Guidance

- Treat an empty, interrupted, stale, or nonmonotonic trial as
  **UNOBSERVED/HOLD**. Preserve its raw file and the transport failure. Never
  fill missing samples, infer a stop from a later reconnection, or reuse another
  trial's measurements.
- Keep the person and reachable physical cut at the robot for every powered
  trial. A best-effort remote zero or E-Stop is useful, but a disconnected PC
  cannot prove that either request arrived.
- Before a motion command, confirm the intended PC network interface, the
  device identity and release, fresh CORE state, E-Stop, one final command
  publisher, and a durable local evidence path. Stop the session when that
  interface or any live evidence disappears; reconnecting does not resume it.
- For the deliberate command-loss test, collect odometry and stop timing on
  the robot or through an independent observation path. The command source
  may disappear by design; the same disappearing link cannot certify the stop.
- Keep calibration, G4 approval, and navigation start as separate verdicts.
  A calibrator's sensor agreement can improve the motion evidence, but it
  does not supply missing command-loss or physical stop evidence.

## Why This Matters

CORE's command watchdog may stop a disconnected client, but its configured
timeout is a design property, not an observed stop latency for this attempt.
The G4 verifier requires ordered pre-stop and post-stop raw samples and
rejects an absent stop time. Power cut is the safe field response; it is not
proof that software braking passed.

## When to Apply

- Any remote Pinky commissioning, calibration, mapping, or navigation trial.
- Any attempt whose operator link drops before final zero-speed readback.

## Related

- [D-314](../../adr/D-314-measured-g4-and-direct-teleop.md)
- [D-321](../../adr/D-321-attended-calibration-g4-mapping.md)
- [Native mapping recovery](../../deployment/pinky-native-mapping-recovery.md)
