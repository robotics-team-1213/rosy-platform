---
title: 시뮬 결과는 두 시계로 읽는다 — WSL 벽시계 점프는 재실행 대상이고, CORE 선 추종 신선도는 sim 시계로 잰다
date: 2026-09-24
category: logic-errors
module: sim/gz_sim harness + core bridge (차선 교차로 시나리오)
problem_type: logic_error
component: development_workflow
severity: high
symptoms:
  - "교차로 시나리오 한 건에서 관측 노드는 매 프레임 유효한 증거를 내는데 로봇이 멈춘 채 시간 초과"
  - "그 시나리오의 launch.log 벽시계 타임스탬프가 뒤로 점프(약 -945 s), 커널에 hv_utils TimeSync IC와 Time jumped backwards"
  - "Gazebo 실시간 비율 0.2-0.4에서 CORE가 선 추종을 HOLD-출발-HOLD로 끊고 LOST로 래치"
  - "부하가 걸린 호스트에서 CORE 부팅이 45 s를 넘겨 시나리오가 boot_timeout으로 빠짐"
root_cause: async_timing
resolution_type: code_fix
related_components:
  - testing_framework
  - observability
tags: [wsl, wall-clock, use-sim-time, line-follow, staleness, gazebo, harness, rerun]
---

# 시뮬 결과는 두 시계로 읽는다 — WSL 벽시계 점프는 재실행 대상이고, CORE 선 추종 신선도는 sim 시계로 잰다

## Problem

`feat/lane-network-junctions`의 Gazebo 교차로 시나리오에서 로봇이 영구 정지했다. 원인은 로봇도
인식도 아니고 시계였다. 두 가지가 겹쳤다. (1) WSL의 realtime 시계가 시나리오 도중 약 945 s
뒤로 점프했다. (2) CORE가 sim 속도로 오는 카메라 프레임의 나이를 벽시계로 쟀다.

## Symptoms

- r4 scenario 09(route_ab)가 시간 초과로 끝났다. 정지 지점에서도 관측 노드는 유효한 증거를
  매 프레임 내고 있었다. 102개 launch.log 중 벽시계 타임스탬프가 뒤로 가는 것은 그 하나였다
  (커밋 "fix(sim): junction harness records wall-clock steps and CORE line status" 메시지).
- 커널 로그에 `hv_utils: TimeSync IC`, journald에 `Time jumped backwards`가 시나리오 시작
  시점에 찍혔다. 이 세션의 관찰로는 Docker Desktop이 컨테이너를 띄운 시점과 겹쳤다.
- CORE 상태를 기록하지 않았으므로 정지 원인을 CORE 쪽에서 확인할 수 없었다.

## What Didn't Work

- 관측 노드와 교차로 분기 로직을 먼저 의심했다. 같은 값으로 다른 회차(r5)는 지나갔으므로
  인식 결함이 아니었다. 이렇게 시계가 점프한 결과를 디버깅하는 것은 시간 낭비다.

## Solution

**1. 하네스가 벽시계 점프를 스스로 기록한다.** `src/sim/gz_sim/scripts/junction_harness.py`:

```python
CLOCK_STEP_TOLERANCE_S = 1.0

def wall_clock_offset():
    """Realtime minus monotonic: constant unless the wall clock is stepped."""
    return time.time() - time.monotonic()
```

시나리오 시작과 끝의 offset 차이가 `result["clock_step_s"]`로 남는다. 절댓값이 1 s를 넘으면
stderr에 `clock-step: ... infrastructure, rerun it`를 찍는다. CORE의 선 추종 상태는 벽시계 1초마다
`core_status.jsonl`에 샘플링된다. `coverage_harness.py`와 `mission_harness.py`도
`junction_harness.clock_step_s`/`CLOCK_STEP_TOLERANCE_S`와 `core_status.jsonl`을 같은 방식으로 쓴다.

**규칙:** `clock_step_s`가 허용치를 넘은 결과는 추종기 증거가 아니라 인프라 증거다. 디버깅하지
말고 다시 돌린다.

**2. CORE 선 추종 신선도는 sim 시계로 잰다.** `src/core/core/core/bridge/traffic_gate.py`:

```python
def line_clock(use_sim_time, ros_now):
    return ros_now if use_sim_time else time.monotonic
```

`ros_bridge.py`는 시작할 때 이 시계 하나를 고르고, 선/도로 증거의 `received_at=self._line_clock()`,
tick, 트래픽 게이트 `now`에 쓴다. 선 추종 manager와 docking에도 `bind_clock`으로 묶는다.
`CommandManager` 스탬프만 `time.monotonic`에 남는다. nav twist의 나이를 그 시계로 재기 때문이다.
장치(`use_sim_time` false)에서는 `time.monotonic` 그대로라 동작이 바뀌지 않는다.

**3. 부팅 대기를 늘렸다.** `BOOT_S = 150.0`. r9-r11에서 36개 중 9개가 45 s `boot_timeout`으로
빠졌고, 부팅된 27개는 모두 통과했다(커밋 "fix(sim): give Gazebo+CORE 150 s to boot before a scenario is dropped" 메시지). 부팅 시간은 주행 판정 기준이 아니다.

## Why This Works

선 추종 기본값은 `stale_after_s = 0.3`, `lost_after_s = 3.0`이다
(`src/core/core_features/core_features/line_follow/manager.py`). 손실이 3 s를 넘으면
`_lost_latched`가 켜지고, 이를 푸는 것은 `set_mode()`뿐이다. 그러니 한 번 LOST가 되면 로봇은
운영자가 모드를 다시 고를 때까지 서 있다.

- 실시간 비율 0.25-0.4의 Gazebo에서 5 Hz sim 프레임은 벽시계로 0.5-0.8 s마다 온다. 벽시계로 재면
  프레임 사이에 0.3 s를 넘겨 매번 stale이 되고, 손실 시간이 쌓여 LOST로 래치된다. sim 시계로 재면
  프레임 간격은 sim 기준 0.2 s라 신선하다. 이 세션의 측정으로는 벽시계 판정일 때 교차로 통과가
  10/12에서 8/12로 떨어졌다.
- 벽시계 점프는 `time.time()`만 움직이고 `time.monotonic()`은 움직이지 않는다. 둘의 차이를
  시작과 끝에서 비교하면 점프를 정확히 드러낸다. 시나리오 판정을 흔들 수 있는 사건을 결과 옆에
  남겨 두면 "재실행할지, 디버깅할지"가 기계적으로 정해진다.

## Prevention

- sim에서 시간에 민감한 판정(신선도, 타임아웃, 래치)을 만들면 "`use_sim_time`에서 이 나이는 어느
  시계로 재는가"를 먼저 정한다. 장치 경로가 `time.monotonic`이라고 sim도 그래야 하는 것은 아니다.
- 하네스 결과에는 판정만이 아니라 인프라 상태(`clock_step_s`, `real_time_factor`)와
  시스템 자신의 상태(`core_status.jsonl`)를 함께 남긴다. 정지를 CORE의 말로 설명할 수 있어야 한다.
- WSL에서 Docker Desktop 같은 VM 사건이 시나리오와 겹치면 시계 점프를 의심한다.

## Related Issues

- [호스트 pytest가 초록이어도 Gazebo 인식 경로는 실제로 돌려서 렌더된 값을 재야 한다](../workflow-issues/sim-perception-green-host-tests-hide-live-gazebo-defects-2026-09-22.md)
- 교차로 비교 기록: `docs/validation/lane-junction-spike/2026-09-23/comparison.md`
