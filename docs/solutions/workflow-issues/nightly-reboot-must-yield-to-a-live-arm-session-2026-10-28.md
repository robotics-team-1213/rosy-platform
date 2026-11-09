---
title: The site nightly reboot restarted the Fleet PC in the middle of an arm move
date: 2026-10-28
category: workflow-issues
module: deploy/site/host-state (rosy-nightly-reboot timer and service)
problem_type: workflow_issue
component: deployment
symptoms:
  - "Fleet PC rebooted at 06:10 while an OMX arm session was moving"
  - "gripper camera preview shows 'No fresh frame' after the reboot"
root_cause: missing_validation
resolution_type: code_fix
severity: high
tags: [omx, nightly-reboot, session-lock, host-maintenance, arm-s]
applies_when: "a host maintenance timer (reboot, update, cleanup) can fire while a person or runner drives a real device"
---

# Host maintenance must yield to the cell session lock

## 문제

`rosy-nightly-reboot.timer`(06:08, 재부팅 06:10)가 2026-10-28 06:10에 팔 이동 중 Fleet PC를
재부팅했다. 서비스의 조건은 업데이트 동결뿐이었고, 장치 세션은 보지 않았다. 현장 벽 경고는
원격 운영자에게 닿지 않으므로 사람이 막을 방법이 없었다.

## 해결

`9e0a75971d`: 세션 잠금(OMX 세션 lock 파일)이 잡혀 있으면 그날 재부팅을 건너뛴다. 시험 통과.
**Fleet PC에는 아직 설치되지 않았다**(sudo 필요). 설치 전까지 같은 사고가 다시 난다. 설치 후
이 줄을 실물 확인 결과로 바꾼다.

## 2026-11-07 보완: 야간 타이머만 고쳤다

같은 사고 경로가 둘 더 남아 있었다. 화면 버튼과 guard 복구는 도우미 `reboot`를 부르는데 잠금을 보지 않았고, `shutdown -r +10`의 10분 안에 시작한 세션도 막지 못했다. 정기 작업만 고치면 같은 동작을 하는 다른 호출자가 남는다. 판단을 호출자마다 넣지 말고 실행하는 곳 하나에 둔다.

D-991이 도우미에서 잠금을 보고 예약 30초 전에 다시 본다. 시험은 `operations/fleet/test/test_host_control.py`이며 실물 재부팅 수용이 아니다. 각 PC에 도우미를 설치해야 경로가 닫힌다.

## 복구

재부팅 뒤 그리퍼 카메라 미리보기가 `No fresh frame`이면
`systemctl --user restart rosy-omx-camera@front`로 복구했다(검증됨).

## 적용 조건

장치를 구동하는 세션이 있는 호스트의 모든 정기 작업(재부팅·업데이트·정리). 조건에 "동결"만
있고 "세션 중 아님"이 없으면 같은 구멍이다. 관련: 정리 타이머와 업데이트 경로 기록.

## 2026-11-09 보완: 모델·AI PC의 야간 재부팅은 아무것도 보지 않았다

10-28에는 관제 PC 타이머에만 팔 세션 조건을 넣었다. 같은 날 복사해 온 모델 PC(05:00)·AI PC(06:00) 타이머는 업데이트 동결만 봤다. 그래서 학습·FULL 시험·Isaac 생산이 매일 끊겼다. 11-09 03:30에도 AI PC에서 잠금을 잡은 `lerobot-train`이 2시간째 돌고 있었다(그날은 런타임 drop-in으로 한 번 건너뜀).

판정을 도우미 한 곳에 둔다는 해결은 맞았다. 하지만 "작업"의 정의가 한 곳에 있지 않았다. 학습 코드(`train_job`, `experiment_train`, Isaac admission)는 `~/rosy-jobs`가 아니라 `~/.cache/rosy-learning/gpu.lock`을 잡는다. `~/rosy-jobs`만 보는 게이트는 정작 지켜야 할 학습을 놓친다. GPU를 쓰는 프로세스가 있다는 것만으로는 판정할 수 없다. `rosy-ollama`가 모델을 GPU에 늘 올려 두기 때문이다. 그래서 cgroup으로 유닛과 손으로 띄운 작업을 가른다. 잠금 경로를 더 만들면 `jobs_live`(D-991 보강)에도 더해야 한다.

적용 조건: 호스트 정비 작업이 무엇을 "작업"으로 보는지 정할 때는 잠금을 잡는 코드를 grep으로 모두 찾는다(`flock`, `*.lock`, `*.resv`). 한 디렉터리 관례만 믿지 않는다. 시험은 `operations/fleet/test/test_host_control.py`이고, 실물 재부팅 수용은 PC마다 설치한 뒤 따로 확인한다.
