---
title: The turn holder waited behind the landings it held up, and fixes to the landing rules ran under the old rules
date: 2026-10-31
last_updated: 2026-11-02
category: workflow-issues
module: tools/land.py, tools/land_checks.py, tools/land_prepare.py, tools/land_async.py, tools/land_rollup.py, tools/remote/remote_job.py, tools/remote/xdist_plan.py
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
  - "a stopped member was resumed although another live rollup already owned its commits"
applies_when:
  - "main stops moving while a ticket holds the turn and its log shows only 'waiting for host room'"
  - "a branch changes tools/land*.py or the remote test tooling and its effect is expected right after queueing"
  - "reading the 'seconds' of tests events in .git/rosy-land-events.jsonl"
  - "recovering a stopped snapshot or deciding whether its branch is free to queue"
tags: [land-py, queue, priority-inversion, admit, remote-pytest, landed-copy, throughput, rollup, ownership]
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
- Processes already running code without the refresh mechanism below need a bootstrap restart in queue order after a rule fix. Keep their snapshot and passed records.
- Before reasoning from `tests` events, check what their timing fields measure.

## Rechecked on 2026-11-02: prepared waiters missed automatic refresh

`land_prepare.relaunch` could load current main while pending for a preparation slot, but green
waiters never called it. They kept the old overlap rules after main was fixed. The existing queue
also granted an unblocked turn before its merge-preview callback, so adding refresh only to that
callback would still miss immediate acquisition.

The correction reuses the existing child handoff in ordinary queue and reprepare waits. It checks
completion first, then refreshes before deciding blockers or granting a turn. The child adopts the
same ticket filename and start time, retaining FIFO, urgency and metadata; the parent's cleanup
does not unlink a ticket the child owns. This avoids a stop/resubmit loop and does not reset lead time.

An active batch leader or carried member keeps its loaded rules until the batch lifecycle ends.
Raising `SystemExit` inside the leader would skip switch-back, branch cleanup and train reporting.
The suppression belongs in `relaunch` itself because a leader can reach it through preparation
slots and reprepare paths as well as its direct wait.

Regression suites `test/test_land_prepare.py`, `test/test_land_batch.py` and `test/test_land_queue.py`
passed all 104 remote tests after six intended failures on the earlier implementation. They cover
changed and unchanged rules, blocked and immediate acquisition, completion before refresh, child
exit propagation, ticket metadata, and batch suppression. This is source-level regression evidence;
coordinated landing and already-running processes' bootstrap remain separate checks.

Those 104 targeted passes missed compatibility with the miniature Git repositories used by the
broader landing tests. Their `main` has no tracked `tools/land.py`. `rules()` returned an empty
fingerprint, or only unrelated remote-tool blobs, and compared it with the importing repository's
nonempty startup fingerprint. The new immediate refresh then spawned that miniature checkout's
missing `tools/land.py`, exiting 2 before the turn. An untracked stub entrypoint also reproduced an
unwanted child exit 7. Testing the callback with mocked rule fingerprints alone did not exercise
this repository boundary.

The compatibility correction makes `rules()` return `None` unless main tracks the landing
entrypoint. Missing landing code provides no runnable replacement; it is not evidence that the
loaded rules changed. This keeps real repositories eligible for refresh without a fixture-only
bypass. Two real-Git regressions cover absent tooling and unrelated remote tooling.

Verification: committed source `23fafbc089` reproduced the existing log-merge regression's exit 2;
tests-only `3f0f45a653` produced both intended new entrypoint failures. Repaired source `fb845aabfd`
passed all 27 `test/test_land*.py` suites plus worktree, remote-pytest and memory suites remotely (596 tests)
(`$TEMP/rosy-land-refresh-compat-broad/run-1.txt`, exit 0; known-failure comparison: 0 new, 0 known,
0 flaky). The red reports are `$TEMP/rosy-land-refresh-compat-red/run-1.txt` and
`$TEMP/rosy-land-refresh-compat-rules-red/run-1.txt`. This verifies the repair in source; it does not
claim coordinated landing or a measured reduction in queue lead time.

## Rechecked on 2026-11-02: stopped members still had rollup owners

A stopped supervisor and an absent member ticket do not establish that a snapshot is free to resume.
Recovery checked the queue's legacy `batch` field, but a one-ticket rollup deliberately has no such
field: its member snapshots are recorded beside its log in a `.members` JSON array. Mobile was
resumed despite a live covering rollup. REST2 was resumed after checking that first rollup, but a
second rollup owned it by the next inspection. A rollup can also hold its supervisor's lifetime
lease while its slow startup has not yet produced a queue ticket.

Recovery stopped only the duplicate waiting originals. Before each stop, the operator verified that
the complete source was an ancestor of the covering rollup, no extra non-merge topic commits would
be lost, and the original was clean and had no Git operation in progress. The source heads were
preserved under `refs/wip/2026-11-02/`; the covering rollups and active tests were left running.
Those checks establish safe recovery for these two cases, not permission to stop an arbitrary
member based only on a similar branch name.

The pending gateway correction reads existing `.members` records for live ticket owners and for
generated rollup snapshots holding the existing supervisor lease. Both `start` and `resume` use
that ownership view; it never synthesizes persisted queue `batch` state. Missing or malformed
membership for an active generated leader fails closed. Dead leases and dead tickets do not make
old metadata an owner. The generated leader has two timestamp suffixes; an ordinary code branch
such as `fix/land-rollup-member-ownership` must not be mistaken for a leader with missing metadata.
`--replace` validates every owner before executing any stop, so encountering a direct member first
cannot bypass a later rollup owner.

Unlanded source evidence: `fb01a870b1` produced 15 intended failures for live-ticket membership;
`ae34b23513` produced seven for pre-ticket leases, and `207f10a89d` showed that replacement stopped
a direct member before refusing its carrier. Repaired source `1ba2ed8e85` passed 157 remote tests
across async, rollup, GC, worktree and queue suites, with 0 new, 0 known and 0 flaky failures
(`$TEMP/rosy-rollup-final-green/run-1.txt`). Red reports are
`$TEMP/rosy-rollup-owner-red/run-1.txt`, `$TEMP/rosy-rollup-lease-red/run-1.txt` and
`$TEMP/rosy-rollup-replace-red/run-1.txt`. These checks verify source behavior; deployment,
already-running older gateways and measured lead-time targets remain separate acceptance checks.

## 병렬 준비와 폴백에서 사라진 급행 표시

급행 표라도 뒤쪽 작업이 일반 admission 대기에 들어갈 수 있었다. 준비의 guard와 body가
같은 프로세스에서 병렬로 `land.run_tests`를 호출하고, 먼저 끝난 호출의 `finally`가
공유 `ROSY_LAND_TURN`을 지웠기 때문이다. 실제 job의 표시는 batch 시작 때가 아니라
각 launch 직전 `xdist_plan.plan`에서 읽는다. 기존 플래그를 저장했다가 복원하는 방식도
두 호출의 종료 순서가 뒤집히면 틀린다.

활성 turn/urgent 호출 수를 짧은 Lock 구간에서 관리해 마지막 호출이 끝날 때만 표시를
지운다. 시험 실행 자체는 잠그지 않는다. 자원 정보가 없는 폴백도 기존 serial/자원
설정에 `TURN_JOB`만 전달한다. worker 수·메모리·host floor·ALONE 규칙은 바꾸지 않는다.
같은 시기 후반 작업 세 개의 admission 대기1997/1988/1988초를 관측했지만, 그 전량을
수정의 벽시계 절약으로 계산하지 않는다.

`test_land_tests_flag.py`와 `test_remote_pytest.py`에서 두 종료 순서, normal 중첩,
예외 정리와 fallback 표시를 검증했다. 소스 `d27b7a625c`는 의도한6개 실패를 냈고,
수정 `150a10701e`의 flags/remote_pytest/host_admission 원격125개는 skip/NEW/known/flaky0으로
통과했다. 독립 검토에 추가P1/P2가 없었다. 이미 표시 없이 launch된 remote job은
코드 착지만으로 소급 변경되지 않으므로 새 controller/job의 표시를 별도로 확인한다.
복구는 기존 착지 경로로 이 변경을 되돌린 뒤 급행 표와 실제 job 표시를 다시 대조한다.
