---
title: 자체 중복 lander는 완료된 FULL을 보존하고 supervisor부터 종료한다
date: "2026-10-29"
category: workflow-issues
module: tools/land_async.py, tools/land_full.py, tools/remote/remote_job.py
problem_type: workflow_issue
component: development_workflow
severity: high
applies_when:
  - 같은 소유자의 동일 변경을 일반 등록과 긴급 등록이 동시에 검증할 때
  - 외부 협력 취소 기능이 없는 실행에서 중복 검증을 수동 정리해야 할 때
tags: [land, full-validation, cancellation, process-ownership, remote-tests, windows]
---

# 자체 중복 lander는 완료된 FULL을 보존하고 supervisor부터 종료한다

## Context

긴급 등록이 앞선 일반 등록을 대체하지 않아 같은 tree와 parents를 가진 두 자체 coordinator가 FULL을 수행했다. 처음에는 일반 작업을 정리하려 했지만 실행 직전 상태가 preparing에서 waiting으로 바뀌어 조작을 중단했다. 일반 작업에 정식 FULL 기록이 완성돼 있었으므로 이를 보존하고 미완료 긴급 중복만 종료했다. 이는 다른 소유자의 작업을 취소하거나 검증 기준을 변경한 사례가 아니다.

tree 일치는 코드 중복의 증거다. main 포함 여부나 검증 완료의 증거는 따로 확인해야 한다. 이 사례에서 별도 standalone FULL 결과는 실패였고, 이를 공식 준비 기록으로 옮기지 않았다.

## Guidance

1. **보존할 실행을 증거로 고른다.** [land_full.py](../../../tools/land_full.py)의 prepared/restore로 실제 candidate, main, tier, invocations를 읽는다. 완료된 FULL과 guards를 가진 실행을 유지한다. 기록·witness·cache를 다른 branch로 복사하지 않는다.
2. **중단 대상의 신원을 새로 확인한다.** PID와 생성 시각, supervisor→gateway→coordinator 계보, snapshot 경로, ticket phase, batch와 carrier 참조를 묶는다. 이 수동 복구는 자체 중복이 preparing이고 다른 branch를 운반하지 않으며 Git 쓰기 자식이 없는 조건에서만 진행했다. 상태나 소유가 달라지면 중단 계획을 다시 세운다.
3. **supervisor를 먼저 멈추고 실제 종료를 기다린다.** [land_async.py](../../../tools/land_async.py)의 supervise는 자식 종료 뒤 snapshot이 main의 조상이라고 판정하면 작업 공간과 branch를 정리할 수 있다. supervisor를 남긴 채 coordinator부터 종료하면 참조 보존과 경합한다. Windows에서는 Stop-Process 직후 객체가 잠시 보일 수 있어 WaitForExit와 새 신원 조회로 확인한 뒤 진행한다.
4. **같은 소유의 로컬 추가 배정을 멈춘다.** gateway, coordinator와 신원을 확인한 dispatch 자식만 종료한다. 원격 job만 먼저 종료하면 살아 있는 coordinator가 다음 시험을 배정할 수 있다. 완료된 실행과 다른 세션의 프로세스는 유지한다.
5. **원격 상태를 다시 읽는다.** 로컬 로그의 run 이름은 역사 기록이다. 실제 jobs 디렉터리의 PID·rc, process 시작 tick·PGID·cwd·command line·source와 lock을 다시 결속한다. 배정 중이던 job은 admission lock 없이 살아 있을 수도 있다. 이미 끝난 job은 건너뛴다.
6. **기존 job 종료 경로와 후조건을 확인한다.** [remote_job.py](../../../tools/remote/remote_job.py)의 KILL은 지정한 run/key의 process group에 TERM을 보낸다. 이때 반환값 대신 rc, process group 부재, 해당 lock 해제를 확인한다. rc·lock·ticket를 직접 만들거나 지우지 않는다. 디렉터리 정리는 별도 완료·소유 확인 뒤 공식 경로로 처리한다.

실행 중단 직전에 소유·phase·source를 다시 확인해야 한다. 이 사례의 상태와 PID를 다른 실행에 재사용할 수 없다. 외부 협력 취소 기능이 제공되는 버전에서는 그 경로를 먼저 사용한다.

## Verified evidence

- 보존한 일반 candidate와 중단한 긴급 candidate의 tree와 parents가 같았고 활성 batch/carrier 참조는 없었다.
- 두 후보는 증거 수집 당시 main 미반영인 보존 snapshot 참조였다. PR이나 공개 게시 완료의 근거로 인용한 것이 아니다. 실제 commit 식별자는 외부 receipt에 보존했다.
- 일반 실행의 실제 기록은 기록된 main 기준 tier full, 27 invocations였다. guard와 isolation 완료도 확인했다. 기록 바이트와 양쪽 branch 참조는 중복 종료 전후에 같았다.
- 로컬 추가 배정 종료 뒤 원격 key가 바뀐 것을 새 inventory에서 확인했다. 완료된 key는 건너뛰고 새로 소유가 확인된 key만 기존 KILL로 종료했다. rc 143, process group 잔존 0, lock 해제를 확인했다.
- Git 밖 `Rosy/artifacts/receipts/2026-10-29-queue-own-batch-slots/owned-duplicate-cancel.json`과 날짜별 workspace 기록에 검증 범위를 남겼다. 이는 시험 호스트의 작업 정리 수용이며 Pinky 부팅·OTA·현장 수용을 뜻하지 않는다.
- 위 receipt는 workspace의 외부 증거(outside repository)다. 제품 Git tree의 파일 경로가 아니며 비공개 원본에서 주소를 제외한 종료 후조건만 보존한다.

## Applicability

같은 소유자의 중복 실행과 완료된 공식 검증이 모두 확인된 경우의 복구 근거다. 단순히 오래 기다리거나 자원이 부족하다는 이유로 다른 실행을 종료하는 근거가 아니다. 재발 방지는 등록 전에 동일 변경의 기존 실행을 확인하고, 우선 등록과 기존 실행의 취소를 별개 동작으로 취급하는 것이다.
