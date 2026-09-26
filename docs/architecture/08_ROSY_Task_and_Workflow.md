# 08. ROSY Task & Workflow Specification

**범위:** 장기 작업 모델 예시다. 현재 `CONCEPTS.md`의 `TaskKind`는 로봇 원자 액션이고, Fleet의 영속 작업은 로봇별 이동 요청 중심이다. 아래 `Transport`/Workflow와 상태 목록은 현행 `/api/fleet/tasks/*` schema나 중앙 다장치 미션 실행기가 아니다. 첫 이종 장비 미션을 구현할 때 [D-290](../adr/D-290-rosy-platform-naming-and-site-intent-boundaries.md)과 D-18에 따라 Intent 후보 → Fleet Mission → 장치 Action → Episode의 identity/상태를 API Reference와 공유 schema에서 함께 결정한다.

## 1. Task

A Task is a requested unit of work.

Examples:

- Navigate
- Pick
- Place
- Transport
- Inspect
- Dock

## 2. Workflow

A Workflow combines multiple Tasks.

Example:

```text
TransportObject
  -> DetectObject
  -> NavigateToObject
  -> AlignBase
  -> Pick
  -> VerifyGrip
  -> NavigateToDestination
  -> Place
  -> VerifyPlace
```

## 3. Task State

```text
PENDING
ASSIGNED
RUNNING
SUCCEEDED
FAILED
CANCELLED
BLOCKED
```

## 4. Task Requirements

A Task may declare:

- capabilities
- deadline
- priority
- preferred node
- preferred asset
- safety class
- retry policy

## 5. Task Execution Boundary

Low-level safety and actuator loops remain local.

ROSY Task orchestration issues higher-level commands.
