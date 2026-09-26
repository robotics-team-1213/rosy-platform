# 08. ROSY Mission and Device Action Model

**범위:** 장기 작업 모델 예시다. 현재 `CONCEPTS.md`의 `TaskKind`는 로봇 원자 액션이고, Fleet의 영속 작업은 로봇별 이동 요청 중심이다. 아래 `Transport`와 상태 목록은 현행 `/api/fleet/tasks/*` schema나 중앙 다장치 미션 실행기가 아니다. 첫 이종 장비 미션을 구현할 때 [D-298](../adr/D-298-mission-action-and-stop-evidence-terminology.md)과 D-18에 따라 Intent 후보 → Fleet Mission → Mission Step → Device Action → Local Transaction → Episode의 identity/상태를 API Reference와 공유 schema에서 함께 결정한다.

## 1. Device Action

A Device Action is a bounded request accepted by one device-local controller.

Examples:

- Navigate
- Pick
- Place
- Inspect
- Dock

## 2. Fleet Mission

A Fleet Mission sequences Mission Steps and records cross-device handoffs. `TransportObject` is a proposed Mission, not an atomic device action.

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

## 3. Proposed Mission State

```text
PENDING
ASSIGNED
RUNNING
SUCCEEDED
FAILED
CANCELLED
BLOCKED
```

## 4. Mission Requirements

A Mission may declare:

- capabilities
- deadline
- priority
- preferred node
- preferred asset
- safety class
- retry policy

## 5. Execution Boundary

Low-level safety and actuator loops remain local.

Fleet issues Device Actions through public APIs. A Local Transaction may sequence approach, grasp and placement within one accepted action; it does not own final actuator publication. The Mission state and Local Transaction state require separate IDs and result evidence.
