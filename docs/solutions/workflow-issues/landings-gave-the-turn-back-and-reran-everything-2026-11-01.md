---
title: Landings gave the turn back over and over and reran every suite; eight causes behind a 783 min p90
date: 2026-11-01
last_updated: 2026-11-02
category: workflow-issues
module: tools/land.py, tools/land_checks.py, tools/land_selection.py, tools/land_cache.py, tools/land_prepare.py, tools/land_goal.py, tools/land_events.py, tools/land_rollup.py, tools/land_batch.py, tools/remote/host_probe.py, tools/harness/affected_tests.py
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
9. **A daytime landing-tool change makes every later turn rerun the tool suites.** `tools/land*.py` maps
   to the harness tier, so once one lands, each later landing's main delta escalates to FULL and its turn
   reruns the delta's mapped suites, even for a docs-only branch. On 11-02 two tool landings (17:31,
   17:44) were followed by two give-backs: a rollup at 18:00 (10 min cap) and `docs/app-surface-grammar`
   at 18:35 (30 min cap), and main stood 58+ min. Rule: batch landing-tool changes into one landing at
   night; in the day, hold them in a worktree with their tests already passing remotely.
   "Night" alone is not enough. The night batch landed at 23:22 with ten tickets queued; every ticket
   prepared before it carried `tools/land.py` in its main delta. Those turns were not FULL: the log's
   `selector escalated to FULL` line is the intermediate selection, and the next lines narrow it to the
   delta's suites (`test/test_land*.py`, `test_affected_tests.py`: 1,203 tests, 6 min) plus the own
   invocations the delta reaches (a foundation branch: 9,135 tests, 22 min). On test PCs below the floor
   or held by an `alone` job these ran serially, the turns gave the turn back at their cap, and main stood
   51 min (23:31-00:22). Only tickets prepared after the tool landing turn fast. Land tool changes when
   the queue is nearly empty (few `waiting`/`preparing` tickets), not just after a clock time. Read the
   lines after an escalation before calling a turn FULL; `tests` events are written when a round ends, so
   a turn that gave the turn back shows none.

## Measurement trap

`land_goal.py` first took main's stalls from `git log --first-parent --format=%ct main`. A landing's
merge commit is made at prepare time, and main fast-forwards to it later, so the gaps were wrong (360
min reported for a 148 min stall). Use the `landed` events' `t` instead. Lead time must retain a
topic's first queue time across timestamped resubmissions.

Rechecked on 2026-11-02: local main at `f432c4f43a` still used commit times in
`tools/land_stats.py`, despite this guidance. Its CLI reported a 526 min stall while the same
24 h event window gave 137 min; p90 lead time was 518 min under both measurements. The correction
feeds `rows`' `landed` timestamps to `land_goal.report`. Two CLI regressions use an old Git commit
date and recent landing events, and check the user's new 60 min default plus the explicit 120 min
override. Both failed before the fix; the corrected goal/event suites passed all 11 remote tests.
Do not count the stall correction as a throughput gain: compare both windows with event times.
The current `land_goal.topic` collapses timestamped resubmissions to the same topic, so restarting
a landing does not reset its first queue time. Remote regression evidence and actual main landing
are separate checks. Paths under `.git/` here refer to the main checkout's shared Git directory,
not a linked worktree's `.git` pointer file; these local records are not tracked product files.

### Rollup 회원 완료가 다음 요청의 시계를 오염시킨 경우

2026-11-02 성공한 one-ticket rollup 두 건은 carrier의 `landed`만 남겼다. 실제 완료 commit에
회원 후보가 들어 있었지만 회원 topic의 최초 접수가 닫히지 않았다. 이전 camera 요청은 rollup으로
379.54분 만에 끝났는데, 뒤의 새 요청은 실제 18.29분 대신 이전 접수부터 488.59분으로 집계됐다.
carrier는 main FF 한 번이며 여러 논리 요청의 완료다. 짧은 carrier lead를 대신 세면 회원 표본과
완료 경계를 모두 잃는다.

원본 이벤트는 고치지 않는다. 선택 당시 회원 snapshot branch·queue ticket·병합 입력 candidate
OID를 고정하고 성공 완료 metadata에 남긴다. 표준 goal 입력도 보존된 `.members`와 해당 회원의
historical `isolation` prepare·queue를 연결하여 **그 carrier의 landed SHA**에 candidate가 포함되는지
검증한다. 오늘의 main에 포함된다는 사실만으로 완료 담당과 시각을 정하면 안 된다. 늦게 읽은
metadata도 실제 FF 시각에 붙인다. sidecar의 stat/read 실패가 실제 FF 이벤트를 누락시키면 안 된다.
논리 회원 검증이 부족하면 carrier의 짧은 lead로 대체하지 않고 `INCOMPLETE`/FAIL로 표시한다.

ticket lead로 바꾸는 것도 오답이다. REST와 install의 최초 topic lead는 1938.64·973.03분인데,
선택된 ticket만 쓰면 853.44·488.89분으로 줄어든다. 이전 성공 이후의 재시도 중 **선택된 회원의
접수 시점 전에** stop이 확인된 branch/PID/queue epoch만 retry coverage로 잇는다. 그 시점에 열린
다른 snapshot은 origin의 앞뒤와 관계없이 보존한다. 뒤늦게 FF 전에 stop된 요청도 소급하여 삼키지
않는다. 같은 frozen snapshot의 완료 전 재접수는 함께 닫되, 이전 성공 전에 남은 stop을 다음 요청의
시작으로 다시 붙이지 않는다. 같은 ticket을 유지한 재launch의 반복 `queue`도 최초 접수 시점을
바꾸지 않는다. prefix 전체 삭제나 최신 queue 시각을 기준으로 한 재분류는 이 경계를 깨뜨린다.

기존 automatic train도 실제 queue origin으로 중복을 제거해야 한다. `(branch, None)`를 영구 완료
표시로 쓰면 공식 direct workflow가 같은 branch를 새 ticket으로 재사용할 때 다음 표본이 사라진다.
선택한 회원 origin을 성공 train에 고정하고, 회원이 뒤늦게 관측한 `landed`를 추가 main 이동으로
세지 않는다. 구형 train의 origin이 모호하면 추측하지 않는다. 다만 무관한 과거 불완전 기록이 현재
조회 기간을 영구 실패시키지 않도록 해당 기간의 표본·미해결 원점에 영향을 주는지 따로 판정한다.
명단에 같은 branch가 여러 ticket으로 중복되면 두 완료 표본으로 만들지 않고 거절한다. producer도
접수·prepare 전에 중복을 거절하며, 동일 metadata 이벤트의 반복 수신은 origin 기준으로 중복 제거한다.

미착지 소스 `d51f653ee5`의 goal/rollup/event/batch 원격 회귀 95개가 통과했고 NEW는 0이었다.
회원 누락·재접수
누출·direct branch 재사용·metadata stat 오류·모호한 train origin·열린 다른 snapshot 삭제·이전
완료 경계·조회 기간 범위를 committed RED로 확인한 뒤 고쳤다. 읽기 전용 실제 기록 재계산으로
회원 네 건과 새 camera 18.2916667분을 복원했다. 고정된 이전 24시간의 원래 집계는 47표본,
p90 517.8227167분이었다. 두 검증된 rollup은 그 기간 뒤에 완료되어 **두 rollup 보정만** 적용하면
이 수치는 변하지 않는다. 열린 다른 snapshot과 stop coverage까지 전체 교정한 같은 기간은 47표본,
p90 491.1793분이다. 이 차이는 측정 교정이며 처리량 개선이 아니다. 구형 automatic train 52건 중
18건의 origin 증거 부족은 별도 한계로 남는다. 후행 회원 `landed`의 PID만으로 경쟁 origin 중
하나를 고르면 별도 요청의 성공을 observer로 오인할 수 있다. 명시 pin이나 선택 근거가 없으면
추정하지 않는다. 빈 목록·부분 손상 metadata는 영향 topic을 모르는 `None`이며, 검증된 빈 범위로
바꾸면 안 된다.

조회 범위도 함께 확인했다. 고정 구간 `[1793497550, 1793583950)`의 47표본/p90 491.1793분에
영향을 주는 불완전 기록은 0건이었다. `t1=1793626432.102415`의 이전 24시간은 57표본/p90
973.0276분, 영향 불완전 0건이었다. 전체 역사 18건과 각 조회의 영향 건수를 섞지 않는다.
다른 기간에 불완전 기록이 영향을 주면 표본 수·백분위는 관측 가능한 부분으로만 보고한다.
소스 시험과 입력 재계산은 main 적용이나 60분 SLO 달성의 증거가 아니다.

재발 시 topic 이름부터 바꾸지 말고 snapshot·ticket·candidate·stop epoch를 대조한다. 보존된
sidecar와 isolation 근거를 복구할 수 없으면 불완전 판정을 유지한다. 원본 시각이나 alias를
추정해서 고치거나, 재접수라는 이유로 최초 접수 시간을 새로 시작하지 않는다.

## How to verify next time

- Turn bounces: `released` events per hour, and for each the log's `[tests] selector escalated to FULL`
  reason in the round before it.
- Reuse: `[cache] ... reused` lines divided by `[remote-pytest] pytest` lines in the same logs.
- A landing-code change applies only to landers started or relaunched after it reaches main
  (`land_checks.landed_copy`); judge it on a window that starts at its landing.
- Each D-889 addendum appends to the same ADR file; two pending ones conflict (`not in the
  auto-resolvable set`). Merge main before queueing the second.
