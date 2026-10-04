# D-443 immediate signal supervision verification — 2026-10-04

Candidate: `fix/d427-signals`, parent `62f8f0a84`; source diff committed with this record. Design: Accepted D-443. Scope is the handoff immediate Fleet signal safety fixes; firmware, PLC, contract types and new admission consumers remain separate.

Fleet lifespan owns continuous supervision. A gap of at least 10 s latches old intent stale before a successful response updates contact time. Reconnection and renewed operator presence cannot replay it. Manual lamps require configured operator authentication and the same actor's visible console presence; expiry sends safe flash_red while preserving the old intent. Device locks serialize poll/command/restore, recheck intent generation and stale_seq inside the lock, and prevent a queued restore after failed safe stop. Status and 409 sequences advance monotonically; only all_red/flash_red retry once. Absent, pending and unknown observations are non-agree. Offline rows preserve values with ages and re-command indication.

## Local evidence

- RED before fix: initial supervision suite 9 failures; presence/lifespan additions 6 failures. Independent review then reproduced two additional failures: queued restore after safe-stop 409 and anonymous loopback presence. Both became regression tests. Nonboolean measured light was also RED before changing it to unknown.
- Related Python suites and module structure: **176 passed**, 190.32 s. Command: `python -m pytest operations/fleet/test/test_signal_supervision.py operations/fleet/test/test_server_signals.py operations/fleet/test/test_server_app.py operations/fleet/test/test_server_console.py operations/fleet/test/test_server_formation.py test/architecture/test_module_structure.py -q`. Scratch/basetemp stayed on X:. Output: `X:/DevTemp/rosy-d427/resume/signals-green-7.txt`.
- Fleet Node tests: **107 passed**, including operator/visibility/configuration presence filtering. Output: `X:/DevTemp/rosy-d427/resume/signals-node.txt`.
- Python flake8 on changed server files: exit 0. Structure quotas were retained; signal routes have one owner, and the existing proposal expiry worker was extracted with identical behavior and the same App logger.
- Independent reviewer `/root/d427_safety_review`: **APPROVE**, no remaining blocker in bounded immediate fixes. Checked queued restore fence, configured credential requirement, nonboolean measurement and worker extraction. Independent deterministic race replay: `X:/DevTemp/rosy-d427/resume/review/signal_queued_restore_repro.py`.

## Evidence limits

SOURCE/local host regression proof only. CI, ROS-SIM, ARM64 artifact, real signal/observer/device and FIELD are NOT_RUN for this candidate. No production writer, firmware wire or hardware activation was added. New signal-based admission must implement D-443's full predicates in its own step. Firmware S7 bad_cycle mutation and uint32 overflow remain next firmware revision; no flash performed.
