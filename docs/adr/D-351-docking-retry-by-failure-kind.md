## D-351 도킹 재시도는 실패 종류를 가린다 — 도달 못 함은 재시도, 도달했는데 전류 없음은 폴트

**Status:** Accepted (2026-09-30, 행동 결정). 구현 이 변경에 포함.

### Context

D-28 계약이 `load_present`와 `charging`를 별개 필드로 정의한 이유가 정확히 이것이다: 접점이 물렸는데 전류가 없는 것(산화·만충·래치된 보호보드)과 접근 자체가 실패한 것(위치·타이밍)은 복구 방법이 다르다. 전자는 재시도해도 소용없고 폴트 보고가 정답이며, 후자는 위치를 약간 틀어 재시도할 가치가 있다.

지금 구현은 이 둘을 구분하지 않는다 — 모든 실패가 `_retry`를 거쳐 같은 백오프·재시도 한계를 쓴다. 만춫(HOLD) 상태에서 전류가 끊기는 것(충전기 종단)은 실패가 아닌데도 `charge_lost`로 재시도 로직을 건드릴 수 있다.

### Decision

**세 갈래로 나눈다:**

1. **도달 실패 (approach failure)** — Nav2 스테이징 실패·타임아웃, 검출 실패, 접근 타임아웃.
   → 기존 재시도 (백오프 + 최대 횟수). 위치를 약간 바꿔 다시 시도할 가치가 있다.

2. **도달했는데 전류 없음 (contact without current)** — `load_present=true`인데 `charging=false`가 `settle_timeout` 내 지속.
   → **즉시 `DOCK_FAILED`, 재시도 없음.** 폴트 사유 `contact_no_current`로 이벤트.
   운영자가 접점을 확인해야 한다 — 재시도는 산화된 접점을 치유하지 못한다.

3. **충전 중 단절 (charging interrupted)** — 확정된 충전이 뒤늦게 깨짐 (`charge_lost`).
   → **DOCKED 유지, 재시도 없음.** 배터리 정책이 다음 임계에서 다시 오퍼한다.
   `docking.charge_lost` 이벤트만 나가고 로봇은 앉아 있는다.

### Alternatives

- **전부 같은 재시도:** 접점 문제를 재시도로 덮으면 산화가 진행되는 동안 배터리가 소모된다. 기각.
- **전부 즉시 실패:** 접근 실패까지 재시도 안 하면 cm급 조정 한 번으로 해결될 것을 포기한다. 기각.
- **충전 단절에 자동 재시도:** 종단(만춫)과 단절(접점 불량)을 구분할 신호가 1개뿐이라 자동 재시도는 오승격 위험. D-350 만춫 히스테리시스가 이미 있으므로 불필요. 기각.

### Transition / validation

- manager `_tick_settling`에 갈래 2 판정 추가: `load_present && !charging && timeout` → `_fail("contact_no_current")`.
- `charge_lost` 경로에 재시도 로직이 없는지 확인 (이미 없음 — 확인만).
- 신규 시험: 접촉-무전류 즉시 실패, 도달 실패 기존 재시도 유지.
- `display/info`에 충전 상태 표시 (CHARGING·CHARGED_HOLD·DOCK_FAILED).

**Consequences:** 접점 산화가 로봇을 죽이는 경로가 사라진다. 재시도 예산은 도달 실패에만 쓰인다. 운영자는 `contact_no_current` 폴트를 보면 접점을 닦는다.

**References:** [D-28 도크 계약](D-28-nav2.md), [D-350 단계](D-350-dock-hardware-phase-tiers.md), `docking/manager.py`, `firmware/dock/README.md` §"load_present and charging are different questions".
