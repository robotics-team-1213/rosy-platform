---
title: Windows 부하 시험은 제어 세션 종료 뒤 남은 자식까지 확인한다
date: 2026-11-03
category: workflow-issues
module: Windows operator PC / synthetic load experiments
problem_type: workflow_issue
component: development_workflow
severity: medium
applies_when:
  - "로컬 검사 지연과 함께 오래된 synthetic CPU 부하가 관측된다"
  - "원래 제어 프로세스가 사라졌지만 background shell과 자식은 살아 있다"
tags: [windows, cpu-contention, synthetic-load, orphan-process, pid-reuse, process-cleanup]
---

# Windows 부하 시험은 제어 세션 종료 뒤 남은 자식까지 확인한다

## 확인한 상황

2026-11-03 착지 준비 지연을 조사할 때 CPU 98%, 가용 RAM 약 1.17GiB가 관측됐다.
`python -c "while True: pass"` 세 개가 합계 머신 CPU 약 27%를 사용하고 있었다.
생성 시각은 11월 1일 13:01:07 UTC였고, 각각 누적 CPU 약 41시간을 소비했다.
동시에 편집기와 다른 작업도 실행 중이어서 부하 세 개가 지연 전체의 원인이라는 결론은 내리지 않았다.

세 Python의 부모 bash는 과거 OMX `collection_cli.py rehearsal-suite` 부하 실험 명령을 갖고 있었다.
현재 각 bash의 유일한 자식은 무한 부하 Python이었고 실제 rehearsal 자식은 없었다.
세 bash의 원래 제어 부모도 모두 사라져, 이번에는 고아 synthetic 부하로 분류할 근거가 있었다.
단순히 CPU가 높거나 오래됐다는 이유만으로 다른 세션의 작업을 종료하지 않았다.

## 정리 순서와 검증

1. PID, 부모 PID, 실행 파일, 정확한 command line, 생성 시각을 함께 확인한다.
   부모·자식의 현재 활동과 원래 제어 부모의 부재도 확인한다.
2. 부모 스크립트의 종료 경로를 읽는다. 이번 세 스크립트에는 광범위 `taskkill/pkill` 후속 명령이 있었고,
   `trap`은 없었다. 자식을 먼저 끊어 후속 정리 명령이 실행될 가능성을 피하기 위해 정확한 부모 셸부터 종료했다.
3. 자식의 command line과 생성 시각을 다시 확인한 뒤 해당 synthetic Python만 종료했다.
   트리 전체나 이름 패턴으로 종료하지 않았다. 첫 검사는 명령이 절대 Python 경로인 것을 예상하지 못해 거절됐고,
   아무것도 종료하지 않은 상태에서 실제 command line을 읽어 정확한 비교값을 바로잡았다.
4. 직후 원래 대상 여섯 프로세스의 부재를 확인했다. 후속 관측에서는 과거 부모 PID 하나가 새로운 Claude hook
   셸에 재사용돼 있었다. 이후 같은 PID가 보이더라도 다시 종료할 근거가 되지 않는다.

정리 후 짧은 관측은 CPU 96%, 가용 RAM 약 2.03GiB, commit 92%였다.
다른 작업이 계속 실행 중이므로 전후 차이를 전부 이 정리의 효과로 귀속하거나 착지 p90 개선으로 해석하지 않는다.
해결·검증 범위는 확인한 고아 부하의 제거다.

운영자 로컬 증거는 저장소 밖 workspace-records의 2026-11-02 작업 폴더에 있는
`synthetic-load-cleanup-evidence-20261103.json`과 같은 날짜의 착지 처리 기록에 보존했다.
명령 원문은 OS Temp의 조사 파일이며 공개 제품 자료로 복사하지 않았다.

## 다음 실험에서 적용할 조건

- synthetic 부하는 자체 종료 시각이 있는 제한 실행으로 만들고, 실행자가 자식의 PID와 생성 시각을 기록한다.
  정상 종료와 실패 경로에서 자신이 만든 자식을 회수하며, 종료 뒤 실제 부재를 확인한다.
- 세션이 사라진 뒤 정리할 때도 프로세스 트리와 실제 활동을 다시 확인한다.
  살아 있는 시험·시뮬레이션·편집기에는 이 사례의 종료 절차를 적용하지 않는다.
- 셸 원문에 광범위 정리 명령이 있으면 그 스크립트를 복구 명목으로 재실행하지 않는다.
  부모 우선 종료도 이번에 확인한 종료 경로에 대한 판단이며 모든 서비스의 일반 종료 순서가 아니다.

관련 교훈: [병렬 CPU 부하가 카드 검증을 지연시킨 사례](card-readback-slows-under-parallel-cpu-load-2026-09-25.md),
[Windows 터미널 수명이 착지 자식에 영향을 준 사례](land-async-children-got-a-terminal-tab-and-died-together-2026-10-30.md).
