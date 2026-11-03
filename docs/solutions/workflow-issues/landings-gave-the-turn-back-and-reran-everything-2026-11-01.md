---
title: Landings gave the turn back over and over and reran every suite; eight causes behind a 783 min p90
date: 2026-11-01
last_updated: 2026-11-03
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

   **2026-11-03 follow-up: check each admission, not just the batch's first host selection.**
   A batch selected the model PC at 19:42 UTC, but a later job entered at 19:59:36, immediately
   before the scheduled 20:00 reboot. Its preserved log ended with `Terminated`/143; the host journal
   confirms shutdown and the next boot. The original `reboot_soon` check ran only at placement.
   `host_probe` and remote `ADMIT` now share the existing timer/service predicate, and ADMIT checks
   it on every resource-wait iteration, before TURN/ALONE admission. This adds no SSH calls.
   A deferred job releases admission resources, returns its exact Work index, and retires that
   host worker. Another host or the original bounded placement wait handles the remaining work.
   A deferred quarantine retry carries the original failure/log and retries only the unfinished
   part; it never publishes a pass or reruns the successful part as compensation.
   Verification: 15 regression failures before the fix; source `95abfc2cdb` passed 228 tests across
   nine suites with zero skips/NEW/known/flaky, plus independent review. These are committed-source
   tests, not a new physical reboot experiment. Already-running long jobs can still be interrupted:
   keep D-889 13's 143/official-resume boundary and its reboot schedule. Resume of the observed
   interrupted landing reused 31 passed invocations; do not discard those caches or reset its clock.
   Recovery is the existing `land_async.py resume <hidden-name> --tests auto`; reverting this
   admission fix must preserve the host schedule and the other resource/safety gates.

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
10. **Narrowed is not short enough.** Over 11-02 11:30 to 11-03 11:30 main stood over 30 min 17 times; the
   turns given back were running main's delta suite folders in the lock. Moving them out needed an evidence
   label decision: saved as `full` the record would claim a run that never happened, saved as `affected` the
   older anchor stays and the next turn picks the same folders. D-889 27 (user decision) adds a `delta`
   tier that moves the base forward but reports the tier under it. Judge it on landings started after it
   reaches main; `[land] ... delta tier` lines and `prepared` events with `tier: delta` show it working.
   A turn yields only over a clean earlier tier: on 11-03 14:18 and 14:34 a LOAD-FLAKY pretest (`prepared`
   with `tier: null`) yielded twice and saved nothing, a loop that never lands (`land_selection.delta_yields`).

## 계측 전용 파일의 불필요한 FULL 승격

2026-11-03의 실제 계측 수정은 `tools/land_goal.py`와 그 회귀 시험뿐인데도
`tools/land*.py` 규칙 하나로 FULL을 요청했다. 두 계측 파일의 실제 흐름은 이벤트를
읽는 `land_stats.py`와 집계용 `land_goal.py`이며, 착지 승인·선택기·원격 실행기가
보고 결과를 소비하는 경로는 없었다. 기존 FULL 준비 640초는 이 작업에서 관측한
비용이지, 아래 변경으로 보장되는 절감 시간이 아니다.

safety 우선 판정 뒤 정확히 `land_goal.py`·`land_stats.py`만 해당 global glob에서
분리한다. 별도 매핑을 만들지 않고 기존 local importer 추적이 goal→stats→events
시험까지 선택하게 한다. reader가 없으면 기존 unmapped→FULL 판정을 유지한다.
다른 runtime land 파일·선택기·remote harness·미등록 파일이 섞인 변경도 FULL이다.
보고 결과를 향후 승인이나 실행 경로가 소비하게 되면 이 분류부터 다시 검토한다.

고정 입력 `6b9f3369a7..98738da589`, 같은 `98738da589` 파일 내용, 자동
`without_sim`·변경 browser 없음 조건으로 비교했다. 선택기 `477fa4cea0`의
FULL 27 argv/추적된 시험 파일 2,383개가 `a193f619`에서는 AFFECTED 1 argv/
11개(기존 guard 9개와 goal/events)다. 수집된 testcase 수나 실제 wall 비교가 아니다.
선택 범위 근거는 작업 공간의 `stats-selection-scope-evidence.json`에 보존했다.

코드 `a193f619`는 관련 선택기·실제 land_selection 호출자·goal/events 281개와
pre-push 소비 경로 29개 원격 시험을 통과했다. skip·NEW·known·flaky는 모두 0이다.
독립 검토는 고정 코드의 safety·mixed FULL·빈 coverage 경계를 확인했다.
이 변경 자체는 선택기를 고치므로 정식 착지에서는 여전히 FULL을 거쳐야 한다.
고정 입력의 범위 축소를 전체 p90 60분 달성이나 변경 후 실행시간으로 보고하지 않는다.

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

## 중첩 회원과 분할 이후 중복 호출

rollup이 다른 rollup을 회원으로 받으면 직접 `.members` 목록은 queue·GC 소유권을 위해
유지해야 한다. 그 목록을 leaf로 바꾸지 말고, 내부 회원의 frozen metadata를 자식으로
붙여 실제 `landed` 이벤트 한 번에 보존한다. 집계는 각 자식 candidate가 직접 부모
candidate의 조상인지와 원래 queue ticket을 확인한 뒤 실제 leaf만 완료 처리한다.
자식 sidecar를 수거한 뒤에도 이벤트만으로 같은 결과가 나와야 한다. 순환·중복·누락된
pin은 불완전이다. leaf 이름이 모두 확인되면 pin 검증 실패의 영향 범위는 보존하되,
자식 목록 자체가 없거나 손상됐으면 범위를 추정하지 않는다.

별도 실행 중에는 같은 tree·환경의 body 시험 다섯 쌍이 중복됐다. 선택기가 큰 묶음을
유지한 상태에서 isolation의 stale singleton을 더하고, 나중에 `work_queue.split`이
큰 묶음을 같은 singleton으로 나누기 때문이다. 분할 결과에서 전체 argv가 같은 호출만
첫 순서대로 하나 남긴다. 큰 묶음과 단독 시험, 환경·옵션·node scope가 다른 호출,
별도 guard와 다음 batch의 실행은 합치지 않는다. `test_work_queue_split.py`의 실제
입력 회귀와 `test_land_goal.py`·`test_land_rollup.py`의 중첩 회귀로 이 경계를 확인한다.
코드·원격 회귀 통과는 착지 완료나 60분 SLO 달성의 증거가 아니다.

### 2026-11-03: 같은 환경의 브라우저 chunk가 일부 파일을 공유할 때

UI 착지의 run-pre-240과 run-pre-257은 같은 candidate `c5bf44b034`, 같은 AI 호스트,
같은 env/freeze에서 실행됐지만, 4파일과 11파일 묶음 양쪽에 arm-transfer-console과
console-queue-inline 파일이 들어 있었다. nodeid·추가 옵션·G1·ALONE 차이는 없었다.
전체 argv가 달라 정확 argv 중복 제거로는 이 반복을 잡지 못했다. 두 호출이 각각 own/delta에서
왔다는 원래 계획 표식은 남지 않아 그 출처까지 추정하지 않는다.

`tools/land_selection.py`의 `_unique_browsers`는 두 browser 결합 경계에서만 사용한다.
leading 환경 단어의 순서까지 같고 모든 대상이 실제 존재하는 순수 `.py` 파일일 때만,
같은 파일을 먼저 나온 chunk에 남긴다. 기존 chunk를 줄일 뿐 다시 pack하지 않아
파일 합집합·기존 순서·basename 분리와 입력 불변성을 유지한다. ALONE/profile 또는
환경 순서가 다르거나 옵션·nodeid·folder·missing/unknown 인자가 있으면 기존 정확 argv
규칙을 유지한다. 일반 pytest 선택과 실패 기준은 바꾸지 않는다. 캐시는 축소된 실제 argv로
조회·기록하며, 원래 whole 키를 축소 호출의 PASS로 추론하지 않는다.

실제 두 호출을 코드 `882915a034`의 helper에 오프라인 재생한 결과는 파일 참조 15→13,
고유 파일 13개·합집합 동일이었다. 이 측정은 전체 UI 계획이나 실제 wall 절감의 측정이 아니다.
운영자 로컬 원본 argv와 결과는 저장소 밖 기존 작업 기록의
`browser-overlap-selection-evidence-20261103.json`에 보존했다.
원격 RED의 유지된 두 결합 경계는 2실패였고, 추가 환경 순서 정규화 기대의 1실패는
범위 밖 요구라 최종 시험에서 서로 다른 순서를 보존하는 기대와 구분했다.
최종 새 회귀·land-selection·land-browser 세 suite는 88 PASS, skip·NEW·known·flaky 0,
독립 P1/P2 없음이었다. 아직 이 소스 검증을 main 착지나 60분 SLO 달성으로 계산하지 않는다.

## 2026-11-03: 실행 이력 없는 큰 묶음도 나눈다

새 main을 합친 첫 차례에서 83경로 묶음 하나가 99%까지 진행했지만, 완료 판정 전에
20분 조기상한을 만나 취소됐다. 본문 37개 중 실제 시작은 하나뿐이었고 PASS는 0개였다.
99%를 성공으로 저장하거나, 추가 10분이면 전체가 끝났다고 추정하면 안 된다.
이 묶음은 직렬 제한 대상이 아니며 측정 이력이 없었다. 기존 `cost()`는 파일 크기로
큰 비용을 추정했지만 `split()`은 없는 이력을 0으로 보고 통째로 뒀다. 완료되지 못하면
다음에도 완료 시간 이력이 생기지 않아 같은 큰 단위가 남는다.

분할 판정과 단일 디렉터리 그룹 수에 같은 `cost()` 값을 사용한다. 측정 이력은 0을
포함해 항상 추정보다 우선한다. 기존 240초 경계, 최대 분할 수, ALONE·serial·옵션·node
범위와 환경 복제, 정확 argv 중복 제거는 유지한다. 선택 범위나 시간 예산을 바꾸지 않는다.
고정 `167e3738af` Git blob 기준 실제 입력은 1→83묶음으로 나뉘며 83경로/620개 .py의
합집합이 같다. 최대 byte 기반 추정은 3468→995초다. 현재 체크아웃의 3542초 추정과
혼합하지 않는다. 기존 한 번 분할 정책 때문에 240초 이상 추정되는 자식 3개는 남는다.

검증: RED 3 FAIL/9 PASS 뒤 코드 `8f4cf7e0bc`의 관련 3 suite 145 PASS·skip/NEW/known/flaky 0,
독립 P1/P2 없음. 이력이 있는 현재 캐시 argv 527개의 old/new 분할 계획도 동일했다.
실제 wall 단축과 startup 비용은 미측정이다. 원래 PASS 데이터는 지우지 않지만 분할로
명령이 달라지면 whole 키를 자식 PASS로 추론하지 않는다. 이력이 없는 과거 whole 키가
재사용되지 않을 수 있는 한계도 같은 명령·트리·환경을 요구하는 기존 캐시 계약 안에서 다룬다.
되돌릴 때는 비용 판정과 디렉터리 그룹 수를 함께 되돌리고 완료 캐시·최초 요청 시계는 보존한다.

## How to verify next time

- Turn bounces: `released` events per hour, and for each the log's `[tests] selector escalated to FULL`
  reason in the round before it.
- Reuse: `[cache] ... reused` lines divided by `[remote-pytest] pytest` lines in the same logs.
- A landing-code change applies only to landers started or relaunched after it reaches main
  (`land_checks.landed_copy`); judge it on a window that starts at its landing.
- Each D-889 addendum appends to the same ADR file; two pending ones conflict (`not in the
  auto-resolvable set`). Merge main before queueing the second.

## 규칙 재시작의 STOP과 최초 대기시간

2026-11-03 실제 원장에서 최초 queue와 같은 ticket을 인수한 queue의 PID는 달랐고,
충돌로 종료된 다음 자식 PID는 queue 전에 STOP했다. branch와 PID가 모두 같아야 하는
기존 `stopped_before`는 앞선 두 queue를 연결하지 못했다. 새 snapshot이 완료되면
11월2일20:44:55.984부터 11월3일00:13:39.790까지의 208.7301분이 빠지는 조인이었다.
당시 새 snapshot은 미착지였으므로 가짜 완료 행이나 실제 lead 값을 만들지 않았다.

동일 PID 판정은 유지한다. 추가 연결은 정확한 frozen snapshot에서 같은 ticket의
복수 queue PID가 확인되고, 미완료 구간에 경쟁 ticket이 없으며, STOP이 마지막 queue
뒤이자 새 접수 전일 때만 허용한다. 다른 snapshot·완료된 cycle·후속 재접수·일반
브랜치를 topic 이름만으로 합치지 않는다. 이 증거가 없는 인계를 추측해 연결하지 않는다.

`d49d9ab33f` 원격 RED는 직접/rollup 두 사례에서 2실패·49통과였다.
수정 `98738da589`의 goal/events 원격 회귀는 57통과, skip·NEW·known·flaky0이며,
실제 원장에서도 앞선 두 queue의 연결을 확인했다. 원장·시각·ticket은 바꾸지 않았다.
복구 시 원본 queue/STOP과 ticket 인계부터 확인한다. 통계 시계의 복원은 처리시간 단축,
main 착지 또는 60분 목표 달성의 증거가 아니다.
