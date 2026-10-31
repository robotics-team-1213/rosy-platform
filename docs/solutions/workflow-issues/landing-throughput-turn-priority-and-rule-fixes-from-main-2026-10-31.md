---
title: The turn holder waited behind the landings it held up, and fixes to the landing rules ran under the old rules
date: 2026-10-31
category: workflow-issues
module: tools/land.py, tools/land_checks.py, tools/land_prepare.py, tools/remote/remote_job.py, tools/remote/xdist_plan.py
problem_type: workflow_issue
component: development_workflow
severity: high
root_cause: logic_error
resolution_type: code_fix
symptoms:
  - "main did not move 02:26-04:10 (2026-10-31); the turn's guard job log showed only '[remote-pytest] waiting for host room (2 job(s), 13c 16GB in use)' for 75 min while 34 tickets waited"
  - "a landing waited p50 52 / p90 239 min for a prepare slot while prepare took p50 23 min, its turn p50 6 min, and the model and AI PCs ran at load ~2-5 of 24 cores"
  - "a fix raising MAX_PREPARING to 6 and letting urgent tickets skip pending reservations stayed pending at position ~31, even resubmitted with --urgent"
  - "tests events reported invocations of p50 20 / p90 79 min while pytest itself ran p50 14 s"
applies_when:
  - "main stops moving while a ticket holds the turn and its log shows only 'waiting for host room'"
  - "a branch changes tools/land*.py or the remote test tooling and its effect is expected right after queueing"
  - "reading the 'seconds' of tests events in .git/rosy-land-events.jsonl"
tags: [land-py, queue, priority-inversion, admit, remote-pytest, landed-copy, throughput]
---

# The turn holder waited behind the landings it held up, and fixes to the landing rules ran under the old rules

## 1. Priority inversion: the turn's job waited for host room

**What happened.** On 2026-10-31, from 02:56 to 04:11, the landing that held the turn ran its guard round (`run-g1-1.txt`) on the site PC. There, two other landings' prepare jobs held the ADMIT budget of cores and GB. `remote_job.ADMIT` treats every job alike, so the turn's job waited for room for 75 min. Every ticket behind it waited too: 34 at the time. Those prepare jobs belonged to the very landings waiting for the turn.

**Recovery used.** It was our own landing, so we killed its `land.py`. The supervisor marks the snapshot stopped. We then resumed the same snapshot with `land_async.py --supervise <tree> <snapshot> --tests auto`. The turn passed on at once.

**Fix (branch `fix/remote-turn-jobs-skip-host-queue`, inside `fix/land-throughput-bundle`).** `land.run_tests` sets `xdist_plan.TURN_ENV` for turn rounds (round numbers and `g<n>`, not `pre`). `xdist_plan.plan` then adds the job word `ROSY_JOB_TURN=1`. ADMIT starts such a job at once, but never beside an alone job. `test/test_host_admission.py` pins both cases.

**Measuring it.** The `seconds` of a `tests` event is the whole round's elapsed time, written to every invocation in the round (`land_checks.py`). It is not one invocation's time. Over 24 h, pytest itself ran p50 14 s when admitted at once, 52 s after waiting for room. 31% of jobs waited. The round's ~20 min went to shipping, venv, queueing behind the run's own workers, and host-room waits. Branch `fix/land-events-invocation-timing` adds per-invocation `host`, `queued_s`, `wait_s` and `run_s`; `land_stats.py` prints their p50/p90.

## 2. A fix to the landing rules runs under the old rules

Since 2026-10-26, `land_checks.landed_copy` makes every landing run main's `tools/land*.py` whenever the branch's copy differs (see [landing blockers](landing-blockers-cost-hours-2026-10-18.md)). Two consequences:

- **A rule fix lands at old-rule speed.** The fix that raised `MAX_PREPARING` 3→6 and let an urgent ticket skip older pending reservations waited first-come under the old rules. Resubmitting it twice, once with `--urgent`, changed nothing: its lander ran `D:\...\rosy-platform\tools\land.py`, main's copy. A fresh snapshot does not help.
- **Running landers keep the rules they loaded.** After the fix landed (05:42), the 13 pending landers still prepared at most 3 at a time. A pending lander has run no tests, so restarting it loses nothing. On 09:25 we killed each pending `land.py` in queue order and resumed its existing snapshot with `--supervise`. The landing that already sat in `main` only had its snapshot removed. Preparing went from 3 to 5 at once.

**Check which copy runs.** The lander's command line names main's checkout path without `-X utf8`. The supervisor's own child, as `land_async` starts it, is `-X utf8 tools/land.py` in the hidden tree.

## The waste that drove the fixes (2026-10-30..31, events log)

| Stage | p50 | p90 |
|---|---|---|
| Pending for a prepare slot | 52 min | 239 min |
| Prepare | 23 min | 51 min |
| Prepared → turn | 5 min | 64 min |
| Turn | 6 min | 27 min |

- **Re-prepares.** 24 of 53 landings prepared 2–4 times. 30 of those re-runs were FULL before the turn, ~984 min/day. They came from D-889 6: a safety path in main's delta keeps FULL.
- **D-889 addendum 7.** A ticket tested on the current main goes before stale ones, for up to 1 h.
- **D-889 addendum 8.** A safety change in main's delta that landed with its own FULL no longer forces FULL on a branch that touches no safety path.
- **Browser tier.** Browser lanes per host went 2→4 and browser chunks 8→12. The browser tier took 62–163 min per FULL round across 4 lanes for all landings.

These ship in `fix/land-throughput-bundle`. Their savings are **expected**, not yet measured. Compare the table above after the bundle lands, and roll back addendum 8 if MAIN-RED rises.

## Prevention

- Treat any shared resource the turn holder needs as a priority-inversion risk: a host budget, a lock, an alone drain. The turn must not queue behind tickets that queue behind it.
- After a landing-rule fix lands, restart the pending landers in queue order. Do not expect the queue to speed up by itself.
- Before reasoning from `tests` events, check what their timing fields measure.
