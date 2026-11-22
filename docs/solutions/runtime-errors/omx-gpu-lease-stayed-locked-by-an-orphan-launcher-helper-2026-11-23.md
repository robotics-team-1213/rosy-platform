---
title: OMX GPU lease stayed locked after a launcher session ended
date: 2026-11-23
module: tools/remote/hold_gpu.sh and OMX offline training
problem_type: runtime_error
component: learning
symptoms:
  - "GPU lease acquisition refused while the GPU reported no compute processes."
  - "The test scheduler reported no live training lock."
root_cause: inherited_file_descriptor
resolution_type: workflow_improvement
severity: medium
tags: [omx, gpu, hold-gpu, flock, launcher]
applies_when: "A lab GPU job cannot acquire the learning flock even though train locks and GPU telemetry show no active job."
---

# Find the process holding the GPU lease

The scheduler and Learning Center observe different parts of a single reservation. `tools/remote/hold_gpu.sh` acquires the kernel flock and then advertises the job to the test scheduler. A process spawned by a launcher can retain the open descriptor after the advertised job and its SSH connection end.

On 2026-11-23 the AI PC had no live training marker or GPU compute process. An exclusive nonblocking flock still failed. The kernel lock entry pointed to the lease inode. Process file descriptors showed an Omniverse Hub helper held the same file. The helper was the sole process in a closing SSH session, parented to PID 1, with no child processes, GPU device descriptors, or established TCP connections.

1. Check the GPU process list and live test scheduler markers. Check the actual lease with `flock -n ~/.cache/rosy-learning/gpu.lock true`.
2. If acquisition fails, look up the lease inode in `/proc/locks` and identify processes with an open descriptor to that inode. A surviving holder can have a different PID from the process that first acquired the lock.
3. Verify the holder belongs to an abandoned session and that no live job or established client is using it. In this incident, sending TERM to the sole orphan helper released the lease. Keep the lock file so all contenders continue to coordinate on the same inode.
4. Recheck acquisition and start the retry through the current `tools/remote/hold_gpu.sh`. The post-recovery check succeeded, and the ACT evaluation retried under the kernel lease and a live scheduler marker.

Keep long-lived launcher helpers outside the GPU job's descriptor inheritance. When changing a launcher, verify lease reacquisition after its training process exits, including when the launcher leaves a helper running.
