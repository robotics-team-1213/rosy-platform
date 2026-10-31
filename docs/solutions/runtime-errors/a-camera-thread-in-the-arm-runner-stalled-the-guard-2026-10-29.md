---
title: A camera-recording thread inside the arm runner stalled the guard's effort sample and dropped the arm
date: 2026-10-29
category: runtime-errors
module: deploy/robot/omx (episode_recorder.py, chunk_runner.py, guarded_native.py)
problem_type: runtime_error
component: development_workflow
symptoms:
  - "run park: session ended: ValueError: stale effort sample (>0.5 seconds)"
  - "torque OFF mid-park; the arm slumped over its own base"
root_cause: wrong_assumption
resolution_type: code_fix
severity: critical
tags: [omx, arm-s, guard, recording, threads, safety]
applies_when: "adding any work (I/O, network, image handling) to the process that runs the arm loop"
---

# Nothing heavy in the arm runner's process

**The design.** The raw episode recorder ran a camera thread inside the chunk runner process. That thread fetched two viewer JPEGs over HTTP 30 times a second and wrote them to disk. Episodes reached 1300–1700 frames per camera. The assumption was that a thread is cheap and the arm loop would not notice.

**What happened.** After several recorded carries, the guard raised "stale effort sample (>0.5 seconds)" during a park. The session ended and torque went off, and the arm came down onto its own base. It was recovered with a park from a fresh session.

On 2026-10-25 a bus read stall had already shown that the guard drops torque when the loop is late.

**Fix.**
- The runner's `Recorder` has no camera thread by default; it only appends one row per tick.
- `CameraSession` records the frames in the pipeline process (`cell_auto_pick`) and adds the frame counts to `result.json` at the end. Test: `test_the_runner_recorder_has_no_camera_thread_and_the_pipeline_session_counts_frames`.

**Rule.** The process that streams arm targets does only the arm loop and cheap bookkeeping. Cameras, encoding, network and disk-heavy work run in another process.
