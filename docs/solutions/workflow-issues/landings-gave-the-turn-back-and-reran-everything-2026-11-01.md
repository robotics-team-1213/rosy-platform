---
title: Landings gave the turn back over and over and reran every suite; eight causes behind a 783 min p90
date: 2026-11-01
category: workflow-issues
module: tools/land.py, tools/land_checks.py, tools/land_selection.py, tools/land_cache.py, tools/land_prepare.py, tools/remote/host_probe.py, tools/harness/affected_tests.py
problem_type: workflow_issue
component: development_workflow
severity: high
root_cause: logic_error
resolution_type: code_fix
symptoms:
  - "the same landing took the turn 3-6 times, held it 12-13 min each and released it (turn cap) while main stood still"
  - "main had no turn at all for ~55 min every morning (05:15-06:10)"
  - "a re-prepare after a one-line fix or a main move reran every passed suite (~470 reuses in ~4,700 invocations over 12 h)"
  - "a landing stopped after a 66 min pretest on a test main had already fixed"
  - "the goal script reported a 360 min stall while landings arrived every few minutes"
applies_when:
  - "a landing's turn ends in a 'released' event instead of 'landed'"
  - "main is quiet while tickets are 'waiting' or a 'turn' ticket is quiet"
  - "re-prepares take as long as the first pretest"
  - "measuring landing lead time or main stalls"
tags: [land-py, turn-cap, turn-bounce, land-cache, affected-tier, reboot-window, main-red, measurement]
---

# Landings gave the turn back over and over and reran every suite; eight causes behind a 783 min p90

## Context

On 2026-11-01 the goal was "90 % of landings reach main within 2 h, the queue never stuck over 30 min".
The 24 h p90 was 783 min and the longest stall 155 min. Per-landing work was short (pretest p50 ~30 min,
turn 2-10 min); the time went to waiting for a turn behind landings that gave theirs back, and to
reruns. Each cause below was found from `.git/rosy-land-events.jsonl` and `.git/rosy-land-wt/*.log`.

## Causes and fixes

1. **Unmapped paths force FULL in every turn round.** Four new tool files
   (`tools/sim/{run_arm_transfer_sim.sh,transfer_installation.py,without_devices.sh}`,
   `tools/calibration/extract_world_paint.py`) were named by no test (one loaded by f-string), so any
   main delta holding them escalated "unknown -> full": 73 escalations in one day. A FULL turn round
   passes the 10 min cap and the turn goes back. Fix: name the path literally in a real test.
   Find them with `grep -ohE "[^ ]+: maps to no module" .git/rosy-land-wt/*.log | sort | uniq -c`.
2. **The sent-back mark lived in process memory** (D-889 15 then 16). A landing relaunched on main's
   new landing code lost it and was capped again. Fix: `Overtime` writes `overtime: true` into the
   held ticket; `land_checks.overtimed` reads it. A landing started on older code still bounces once
   more after the change lands (seen 16:22 and 17:08); that is the transition, not a bug.
3. **FULL-mode own selections skipped the overlap rule** (addendum 10 item 2 excluded them), so a
   landing whose own selection is FULL (shared foundation, folder moves) reran it every turn and never
   fit the cap. Fix: apply `overlaps()` to FULL own selections too (D-889 16). Landings that change the
   landing tools or `contracts/foundation` still rerun FULL: expect one long turn each.
4. **Narrow cache reuse gave up on any FULL range** (D-889 17). 30 of 40 sampled reuse tries were FULL,
   mostly through main's landing-tool and harness commits that had already landed with their own FULL.
   Fix: select the branch's own new commits one by one and treat main's landed commits by the turn's
   rule; reuse passes that touch neither. The test-environment hash was not the cause (5 values over 24
   commits).
5. **Fixed schedules and stale bases.** The three test PCs rebooted within 10 min and `land_prepare`
   held every pretest 05:15-06:10 (~55 min stall daily). Fix: each host reports `reboot_soon` 15 min
   before its own `rosy-nightly-reboot.timer` and the model PC moved to 05:00 (D-889 13). A pretest on a
   66 min old main stopped on a MAIN-RED that main fixed meanwhile; it now re-prepares once on the new
   main (D-889 14).

## Later the same evening

6. **All-or-nothing overlap.** Even with the overlap rule, one reached suite reran *every* own invocation:
   a shared-foundation landing's uncapped turn reran 485 invocations plus its browser tier serially and held
   main ~100 min (18:01-19:45, stopped by hand with the user's approval). Fix: filter per invocation and per
   browser chunk (D-889 18, 19), and grow the cap per send-back (10 min, 30 min, then none) instead of
   lifting it after one (D-889 19). Addendum 15's "no cap after one send-back" was the wrong bound.
7. **Exit 5 of a file run alone.** Splitting long invocations put
   `middleware/devices/omx/adapter/test/test_omx_fleet_ros_actionserver.py` in its own invocation. Without
   rclpy it skips at import, pytest collects nothing and exits 5, and `land_cache.unusable` called that no
   verdict: four turns stopped in an hour and main stood 85 min. Fix: the directory's conftest turns a
   skip-only exit 5 into 0, and `land_cache` reads a skip-only summary as a verdict (D-889 20).
8. **A landing-code fix cannot rescue its own landing.** `land.py` always runs main's copy
   (`land_checks.landed_copy`), so the exit-5 fix in `land_cache` hit the same exit 5 in its own turn. When
   the blocker is in the judging code, put a fix in the tested tree first (here the conftest), land that,
   then land the tooling change.

## Measurement trap

`land_goal.py` first took main's stalls from `git log --first-parent --format=%ct main`. A landing's
merge commit is made at prepare time, and main fast-forwards to it later, so the gaps were wrong (360
min reported for a 148 min stall). Use the `landed` events' `t` instead. Lead time keys on the ticket
branch (`land/<branch>-<stamp>`), so a resubmission starts a new clock.

## How to verify next time

- Turn bounces: `released` events per hour, and for each the log's `[tests] selector escalated to FULL`
  reason in the round before it.
- Reuse: `[cache] ... reused` lines divided by `[remote-pytest] pytest` lines in the same logs.
- A landing-code change applies only to landers started or relaunched after it reaches main
  (`land_checks.landed_copy`); judge it on a window that starts at its landing.
- Each D-889 addendum appends to the same ADR file; two pending ones conflict (`not in the
  auto-resolvable set`). Merge main before queueing the second.
