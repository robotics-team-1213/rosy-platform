---
title: A dashboard's safety and capability claims must come from live readiness signals, never from configuration alone
date: 2026-09-24
category: design-patterns
module: src/core/core_api_web, src/core/core_common/core_common/domain/capabilities.py (real device rosy-pinky-e4us, release 2026.09.24-010)
problem_type: design_pattern
component: observability
severity: high
applies_when:
  - a dashboard or API reports whether hardware/motion is available, safe, or ready
  - the underlying system has more than one axis of state (e.g. install/runtime mode, live sensor readiness, an explicit safety interlock) that can disagree with each other
  - an operator-facing status label was originally written for a simpler state space (e.g. one runtime mode) and the system has since grown a second one
tags: [dashboard, safety-ui, observability, capabilities, truthful-status, core-api]
---

# A dashboard's safety and capability claims must come from live readiness signals, never from configuration alone

## Context

On a real Pinky Pro running `rosy-io` in no-motion mode — battery and lidar telemetry live, motor
subsystem intentionally not ready, `/cmd_vel` unsubscribed — the dashboard still reported "SAFETY
CIRCUIT: HW OFF (CORE-only)" and 5-of-5 mobility capabilities as available. Both statements were
read off the device's configured runtime mode rather than off the live motor readiness signal the
device already had (`motor/ready`, `cmd_vel` subscriber count). A related, earlier instance of the
same class of gap: an API-issued e-stop was worded on the dashboard as if it had physically cut motor
power, and `runtime_mode: core` was shown to the operator as `device_state: SAFE_STOP` — a
configuration value standing in for a live safety-circuit reading. `core_common`'s capability model
(`Capability`, `CapabilityDescriptor` — see `CONCEPTS.md`) already exists to describe what a device
can do; the gap is that the dashboard was deriving its answer from `runtime_mode` instead of from
that model's live-evidence path.

## Guidance

- Every operator-facing availability or safety claim must be traceable to a live signal the device
  is currently reporting (a subscriber count, a readiness topic, a heartbeat), not solely to a
  static or install-time configuration value (a runtime mode, a preset, a profile). Configuration
  can *gate* what is possible; it must not by itself *assert* what is currently true.
- When a claim is blocked or unavailable, the reason shown must name the actual blocking condition
  ("motor not ready", "no cmd_vel subscriber") rather than a generic or configuration-derived label
  that happens to be adjacent to the true cause.
- Treat "the system has grown a second state axis since this label was written" as a standing risk:
  a status string authored when `runtime_mode` was the only axis of truth silently becomes
  misleading once a second axis (live hardware readiness) exists alongside it, even though nothing
  about the string itself changed.

## Why This Matters

A dashboard is the thing an operator trusts to decide whether it is safe to approach or interact
with a robot. A capability or safety claim derived from configuration rather than live evidence can
read as "safe" or "available" in exactly the configurations where it is least true — as happened
here: a device already known to be running without motor readiness still reported full mobility and
an off/CORE-only safety circuit, both of which understate the actual, currently-unknown state of the
hardware. The failure mode is dangerous because it is not visibly broken — the UI renders normally
and shows a specific, confident-sounding value.

## When to Apply

- Any screen or API response reporting device readiness, capability availability, or safety-circuit
  state.
- Any status label written against a system with one state axis (e.g. `runtime_mode`) that has since
  gained a second, independent axis of truth (e.g. live hardware readiness signals).
- Review of an e-stop, hold, or interlock display for whether its wording matches what actually
  changed (a software-issued command vs. a physical power cut).

## Examples

Before (illustrative — this is the pattern found, not the literal current code): a "SAFETY CIRCUIT"
label computed only from `runtime_mode == "core"`, and a mobility capability list populated from the
board's configured capability set regardless of `motor/ready` or `cmd_vel` subscriber state.

After (the direction this points toward, not yet implemented as of this writing — see below): the
same label reads a live motor-readiness signal and a live `cmd_vel` subscription check, and only
reports full mobility when both agree with the configured capability set; when they disagree, the
label states which live signal is missing.

This defect was diagnosed and reproduced on the real device on 2026-09-24; a branch
(`fix/hardware-runtime-truth`) exists for the fix but carries no changes yet, so the correction
described above is not yet implemented — this doc captures the diagnosed gap and the general
principle, not a shipped fix.

## Related

- [OpenCV 4.6의 bare aruco.DetectorParameters()는 널 포인터라 필드 하나만 써도 import에서 segfault가 난다](../runtime-errors/opencv-4-6-aruco-detector-parameters-segfault-2026-09-24.md)
- `docs/solutions/design-patterns/a-safety-orchestrator-rechecks-after-every-await-and-lets-every-liveness-signal-decay.md`
