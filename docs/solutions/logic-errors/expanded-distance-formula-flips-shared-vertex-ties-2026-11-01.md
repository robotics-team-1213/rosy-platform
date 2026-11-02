---
title: 거리 계산을 전개식으로 빠르게 바꾸면 공유 끝점의 동점이 뒤집힌다 — 같은 연산을 성분별로 나눠 비트 동일을 지킨다
date: 2026-11-01
category: logic-errors
module: control.sensing.scan_motion (교정 회전 match_motion)
problem_type: logic_error
component: tooling
severity: high
symptoms:
  - "행렬곱 전개 시제품이 합성 상자 방 41건에서는 원본과 수락·거절이 모두 같았다"
  - "2026-09-09 실제 기록 프레임 6건에서 원본이 수락한 정합을 전개식은 거절했다"
  - "interior 검사를 통과한 대응점(keep)이 155개에서 83개로 줄었다"
root_cause: logic_error
resolution_type: code_fix
related_components:
  - testing_framework
tags: [numpy, floating-point, cancellation, point-to-segment, equivalence-test, recorded-frames, d-953, d-185]
---

# 거리 계산을 전개식으로 빠르게 바꾸면 공유 끝점의 동점이 뒤집힌다 — 같은 연산을 성분별로 나눠 비트 동일을 지킨다

## Problem

D-953에서 Pi 4·5 예산을 맞추려고 `scan_motion._fit_segments`의 점-선분 대응을 빠르게 바꾸려 했다. 원본은 (점, 선분, 2) 브로드캐스트로 투영점을 만들고 차이를 제곱해 더한다. 시제품은 이것을 |a|²−2a·s+|s|²에서 출발한 전개식 `dd − 2t·(d·e) + t²|e|²`과 행렬곱으로 바꿨다.

합성 상자 방 41건에서는 판정이 같았고, 위치 차이도 최대 4e-9 m였다. 그러나 실제 기록 프레임(`middleware/perception/test/fixtures/registration_stationary_endpoints_20260909.json.gz`)에서는 6건이 수락에서 거절로 바뀌었다.

## Root cause

연속한 두 선분은 끝점 하나를 공유한다. 그 끝점 근처의 점에서는 두 선분까지의 실제 거리 제곱 차이가 약 1e-20 m²다. 전개식은 큰 항끼리 빼므로 상쇄 오차가 약 1e-16 m²다. 오차가 실제 차이보다 커서 `argmin`이 점이 바깥에 놓인(fraction이 [0,1] 밖인) 선분을 고른다. 그 점은 interior 검사에서 빠지고, keep 비율이 `.6*len(cur)` 아래로 떨어져 정합 전체가 거절된다.

합성 상자 방은 점이 공유 끝점 바로 위에 덜 놓여서 이 동점이 드러나지 않았다.

## Solution

계산식을 바꾸지 않고 메모리 배치만 바꿨다. 원본과 같은 연산을 같은 순서로 하되, x·y 성분을 따로 (점, 선분) 배열로 계산한다. (P,S,2) 임시 배열과 `np.sum(axis=2)`가 사라진다. 2성분 합은 `x + y` 한 번이라 순서가 같다. `_segments`의 창별 SVD 루프도 묶음 SVD로 바꿨다(커밋 `d09dd4673b`, 브랜치 `refactor/pi45-cpu-budget`, 착지 전).

- 결과: 55건(합성·잡음·실제 기록 프레임·거절 경우)에서 `match_motion` 결과가 원본과 `==`로 같다.
- 속도: 노트북 중앙값 31~32ms에서 10.6~11.7ms로 줄었다.
- 시험: `middleware/perception/test/test_scan_motion_equivalence.py`가 원본 사본과 비교한다. 변이 확인에서 clip 제거, interior 하한 뒤집기, extent 기준 변경이 모두 실패했다. 모델 PC 원격 시험 99개가 통과했다.

## Prevention

- 거리·투영·argmin이 걸린 기하 커널을 빠르게 바꿀 때는 실제 기록 프레임을 차등 시험에 넣는다. 합성 사례만 통과했다고 동일하다고 보지 않는다.
- "차이가 작다(1e-9)"는 동일성의 근거가 아니다. 판정이 argmin·임계값을 거치면 작은 오차가 판정 전체를 바꾼다. 비트 동일(`==`)을 목표로 하고, 안 되면 D-185 2의 동작 변경(B)으로 다룬다.
- D-953 4의 PyO3 이전도 같은 기준을 따른다. 커널 안에서 같은 식, 같은 순서를 쓰고 이 차등 시험을 통과해야 한다.
