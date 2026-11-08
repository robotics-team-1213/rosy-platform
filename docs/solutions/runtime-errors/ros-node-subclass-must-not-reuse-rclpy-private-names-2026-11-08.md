---
title: rclpy Node 하위 클래스는 Node의 비공개 이름(_clock 등)을 쓰지 않는다 — 시험 스텁은 이 충돌을 못 본다
date: 2026-11-08
category: runtime-errors
module: middleware/devices/pinky/bringup (battery_publisher)
problem_type: runtime_error
component: device_runtime
severity: high
symptoms:
  - "릴리스 175에서 battery_publisher가 시작 직후 죽음: AttributeError: 'builtin_function_or_method' object has no attribute 'handle'"
  - "트레이스백 맨 위는 install/lib/bringup/battery_publisher 33행(콘솔 스크립트 껍데기)이라 원인 위치가 안 보임"
  - "호스트 pytest는 모두 통과"
root_cause: name_collision
resolution_type: code_fix
tags: [rclpy, node, clock, stub, test-gap, battery]
---

## 증상

2026-11-08 b8xy canary(릴리스 175)에서 `battery_publisher`가 기동 직후 `AttributeError: 'builtin_function_or_method' object has no attribute 'handle'`로 죽었다. 호스트 시험은 모두 녹색이었다.

## 원인

`44faf7ab51`(ADC 재시도 간격)이 시험용으로 주입한 시계를 `self._clock = time.monotonic`에 두었다. `_clock`은 rclpy `Node`가 자기 시계를 두는 비공개 속성이다. 그 뒤 `create_timer`가 `self._clock.handle`을 읽어 내장 함수에서 `.handle`을 찾다 죽는다. 시험의 `ros_stubs` Node에는 시계가 없어서 같은 코드가 통과했다.

## 해결

이름을 `_monotonic`으로 바꿨다(`fix/battery-publisher-node-clock`). 시험 `test_the_injected_clock_does_not_replace_the_rclpy_node_clock`이 주입한 시계가 `_clock`에 놓이지 않음을 고정한다.

## 다음에 적용할 조건

- `Node` 하위 클래스에 `self._<이름>`을 새로 둘 때 rclpy `Node`가 쓰는 이름(`_clock`, `_context`, `_handle`, `_logger`, `_parameters`, `_timers` 등)과 겹치지 않는지 본다. 주입 시계는 `_monotonic`·`_now`처럼 다른 이름을 쓴다.
- 스텁 위에서만 도는 ROS 노드 시험은 rclpy 내부와의 충돌을 증명하지 못한다. 노드 생성자를 바꾸면 실물 또는 ROS가 있는 호스트에서 한 번 기동해 본다.
- 트레이스백 맨 위가 `install/lib/<pkg>/<node>`의 짧은 줄 번호면 콘솔 스크립트 껍데기다. 실제 위치는 그 아래 프레임에 있다.

## 검증

수정 전 코드에서 새 시험은 실패한다(`node._clock is sentinel`). 수정 뒤 bringup 시험 469개 통과. 실물 기동은 다음 릴리스에서 확인한다.
