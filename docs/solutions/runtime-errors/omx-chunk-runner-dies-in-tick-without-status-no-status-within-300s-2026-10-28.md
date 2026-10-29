---
title: A chunk runner that dies inside tick() leaves no status, and "no status within 300 s" meant a guard stop
date: 2026-10-28
category: runtime-errors
module: deploy/robot/omx (chunk_runner.py, cell_pipeline.py)
problem_type: runtime_error
component: development_workflow
symptoms:
  - "caller reports 'no status within 300 s' after a chunk command"
  - "runner live file goes stale and no status line was written for the last chunk"
root_cause: missing_validation
resolution_type: code_fix
severity: medium
tags: [omx, chunk-runner, guard, status, arm-s]
applies_when: "a caller waits for a runner status line and a timeout is the only symptom of a runner exception"
---

# "no status within 300 s" was a runner crash, not a slow arm

## 증상

공급암 S lap 로그 7개 중 2개가 `no status within 300 s`로 끝났다. 호출자는 느린 이동이나
연결 문제로 읽기 쉽다.

## 원인

guard가 추종 오차 5° 초과로 토크를 끄면 runner의 `tick()`이 예외로 죽는다. 그 경로는 상태 줄을
쓰지 않았고, 호출자는 300 s 동안 없는 줄을 기다렸다. 같은 guard 정지가 `lift_place`·
`goto above_place`의 "live.json stale"로도 나타났다.

## 해결

`f30534dd94`: 청크 세션이 도중에 끝나면 죽기 전에 `fault` 상태 줄을 쓰고 예외는 그대로 다시
던진다. guard 동작은 그대로다. 이제 이 문구가 보이면 먼저 guard 로그(`session-guard-*.log`)의
`following error` 줄과 runner 상태의 `fault` 줄을 확인한다.

## 복구와 예방

- 타임아웃만 있는 실패에서 시간·속도 한도를 늘리지 않는다. 먼저 guard 로그로 정지 원인을 가른다.
- 호출자 대기는 "상태 없음"과 "runner 사망"을 구분할 수 있어야 한다. 예외로 끝나는 경로마다
  마지막 상태 줄을 남긴다.
- 정지의 실제 원인(wrist_flex 동적 지연)은
  [follower-joint-short-below-pwm-cap-is-droop.md](follower-joint-short-below-pwm-cap-is-droop.md)의
  2026-10-28 갱신에 있다.
