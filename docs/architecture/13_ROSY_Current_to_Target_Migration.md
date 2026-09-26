# 13. ROSY Current-to-Target Migration Plan

## 1. Principle

ROSY is already under implementation.

Therefore:

> Do not perform a full rewrite unless absolutely necessary.

Use incremental refactoring.

## 2. Migration Actions

Every existing module must be classified as:

- KEEP
- MOVE
- RENAME
- REFACTOR
- DEPRECATE
- REWRITE

## 3. Example Mapping

| Current Module | Target Module | Action |
|---|---|---|
| Robot Manager | rosy-device / rosy-control | Refactor |
| ROS Bridge | rosy-fabric | Move |
| Pinky Control | adapters/pinky | Refactor |
| AI Worker | rosy-compute | Move |
| Web API | rosy-api | Keep |
| Fleet Logic | rosy-control | Refactor |

## 4. Migration Phases

### Phase 0 - Freeze Architecture Terms

Done in glossary (D-65, `CONCEPTS.md`): Node, Device, Component, Capability, Asset, Task mapped onto CORE + D-62 slices.

### Phase 1 - Introduce ROSY Base Runtime

Done for v1 identity + inventory: robot number / namespace bind, `GET /api/v1/system/inventory`, derived DeviceState. Not done: apt `rosy-runtime-base`, dynamic plugin manager, separate heartbeat timer (CORE-001 snapshot remains the heartbeat).

### Phase 2 - Move Device-Specific Code

Manifests, not a package move: `src/hardware/bringup/config/adapter.manifest.yaml` (Pinky) and `src/apps/omx_adapter/config/adapter.manifest.yaml` (disabled). UART/Dynamixel stay in `bringup`.

### Phase 3 - Introduce Capability Registry

Done for v1: `TaskKind.concept_id` maps REST actions to concept ids (`mobility.move`, …); inventory `descriptors` carry `available` from DeviceState (SAFE_STOP/FAULT/BOOTING → false). CAP-001 `GET /capabilities` is unchanged. Not done: scheduler that assigns work across nodes.

### Phase 4 - Introduce Compute Fabric

Not v1 (D-71). Do not add Gram/RTX fabric or a model registry in CORE.

### Phase 5 - Composite Asset

Not v1 (D-71, D-55). `Pinky + OMX = MobileManipulator` stays disabled until D-55 is Accepted with evidence.

## 5. Migration Rule

New code should follow target architecture immediately.

Existing code should be migrated only when touched or when it blocks target architecture.
