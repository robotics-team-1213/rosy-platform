---
title: "홈 단계는 느린 그리퍼가 홈에 닿을 때까지 기다린다"
module: OMX Cell
date: 2026-11-27
problem_type: runtime_error
component: tooling
severity: high
tags: [omx, cell-unwedge, home, gripper, arm-s]
symptoms:
  - "주차 뒤 홈 복귀마다 \"stopped: measured body or gripper did not reach home\"로 끝났다 (3회 중 3회)."
  - "이어서 정책 시작이 START_POSE_OFF_HOME으로 거절됐다."
root_cause: async_timing
resolution_type: code_fix
---

# 홈 단계는 느린 그리퍼가 홈에 닿을 때까지 기다린다

`cell_unwedge`의 홈 단계는 그리퍼 명령 뒤 2초를 고정으로 자고 그리퍼를 한 번만 읽었다.
arm_s 집게는 초당 약 2.8단위로 열리므로 주차 49에서 홈 58.1까지 약 3.2초가 걸린다.
읽는 시점에 아직 도착 전이라 홈 단계가 매번 실패했고, 몸체 자세가 맞아도 정책 시작이 START_POSE_OFF_HOME으로 거절됐다.

단위 시험의 가짜 그리퍼는 명령 즉시 홈에 닿았다. 그래서 고정 대기가 충분한지 시험이 물을 수 없었다.

수정(PR #1149)은 홈에 닿거나 값이 더 변하지 않을 때까지, 상한을 두고 읽는다.
집게가 모자란 채 멈추면 이전처럼 정지한다.

## 재발 방지

- 느린 관절의 "도착" 검사 앞에 고정 sleep이 있으면 의심한다. 도착 또는 정체까지 읽는다.
- 시험의 가짜 장치는 실제 속도(단위/초)를 흉내 낸다. 즉시 도착하는 가짜는 대기 결함을 숨긴다.
- 홈 복귀가 "도착하지 못함"으로 반복되면 몸체보다 먼저 그리퍼 속도와 읽는 시점을 비교한다.
