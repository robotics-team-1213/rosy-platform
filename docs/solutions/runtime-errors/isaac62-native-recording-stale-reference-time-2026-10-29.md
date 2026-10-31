---
title: "Isaac native camera readback can lag a physically advanced task"
date: 2026-10-29
category: runtime-errors
module: learning/envs/isaac
problem_type: runtime_error
component: simulation
severity: medium
symptoms:
  - "NativeRecorder rejected the second frame although the physics clock and finite joint positions changed"
  - "One-frame MP4 and cached camera rendering_frame equal to integer zero"
root_cause: stale_native_render_readback_treated_as_ready_frame
resolution_type: code_fix
tags: [isaac, sdk62, native-camera, ffmpeg, frame-freshness]
applies_when: "Recording a contact task with sparse rendering and manual physics steps on the pinned SDK 6.2 setup"
---

## Problem

The current-map container task could import and move, but its first continuous
recording stopped before pickup. A later attempt wrote one frame, then the
unchanged freshness guard refused frame two. Shape checks and a working FFmpeg
pipe did not establish a fresh rendered observation.

## Observed cause

The diagnostic run measured native ReferenceTime as 8333333/1000000000 at both
control ticks 0 and 12. During that interval the observed world clock advanced
from 0.008333334 to 0.108333339 seconds and joint positions changed to finite
values. Native readback was stale relative to physical advancement.

The installed Camera source initializes its cached rendering fields to integer
zero and updates them in its acquisition callback. Reading that cache immediately
after initialization is not a readiness proof. Separately, one manual render
and SDG evaluation did not make the native readback fresh in this runtime.
The underlying renderer scheduling mechanism was not isolated; do not label
this a universal SDK defect or assume every camera needs the same retry count.

## Working solution

The unmerged experiment implementation at source `83756cf68e` uses
[container_recording.py](../../../learning/envs/isaac/container_recording.py)
and [mapped_stack_task.py](../../../learning/envs/isaac/mapped_stack_task.py):

1. An actual ReferenceTime annotator on the same render product as the recording
   camera, with synchronous SDGPipeline evaluation before reading its data.
2. A native rendered physics step on each 12th control tick. Its measured world
   time delta must equal the 120 Hz control period; legacy stepping is unchanged.
3. At most 8 actual render/readback updates per capture until the native rational
   timestamp strictly exceeds the previous accepted timestamp. Permanent stale
   data remains an error. Physics time, native reference seconds and video frame
   number are recorded separately; none is synthesized from another clock.
4. A physical hold to the next capture boundary before finalization, retaining
   a final settling observation. Otherwise the final off-cadence frame would
   reuse a native timestamp. Encoder close runs even when capture fails.

The successful candidate's decisive change was bounded fresh-readback waiting;
the preceding diagnostics with the other changes still stopped on stale data.
Do not replace the guard with duplicate timestamps or a loop counter. The
10 fps MP4 must also pass complete FFmpeg decoding, exact frame-count/physics
coverage checks and artifact hashes before it is admitted.

## Verification

Run `e64626136b965d3296768110654bbf82` on SDK 6.2.0.0 completed its one-floor
physical task and registered 1595 native frames at 10 fps, 159.5 seconds, 800×600.
SDK exit 0, import, video verification and owned process/GPU release were
confirmed. Frames decoded at 3, 80 and 158 seconds showed the initial conveyor
container, physical transport and completed floor. This is an IK reference,
not a learned policy or hardware result.

Video sha256: `306900c65cfedd15a2d782860e1d08773d827c45dcd2f2c080c2df065dc16dde`.
Report sha256: `cb4b32d07e1541810c73caa7ca12075980ff3fffd9e441f9c2007c72433f9140`.
The focused 15 remote tests include stale-readback retries followed by a fresh
receipt, rejection of permanently stale receipts, finite data, frame chronology,
and the current three-layer geometry's offline owner reachability.

## Recovery and applicability

Keep failed and UNKNOWN receipts. One earlier run remained UNKNOWN without a
final report; only after its owned unit had MainPID=0, empty cgroup and a fresh
GPU-ready observation was its own stale reservation removed. That observation
did not convert the old run into a success. Use the existing status/stop/fetch
runner; do not reuse the unit or signal another GPU process.

For an SDK, renderer, camera or cadence change, rerun the recorded contact task
and inspect actual decoded frames. Unit stubs alone missed this runtime
readiness failure. The declared retry budget is a bound, not a guarantee of
rendering readiness on other configurations.

The [SDK 6.2 camera documentation](https://docs.isaacsim.omniverse.nvidia.com/6.2.0/py/source/deprecated/isaacsim.sensors.camera/docs/index.html)
describes initialization and frame collection. The particular startup/readback
failure above is established by the recorded experiment, not that general guide.
