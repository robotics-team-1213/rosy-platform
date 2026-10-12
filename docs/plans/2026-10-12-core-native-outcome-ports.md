# CORE native outcome ports 구현 계획

날짜: 2026-10-12. 브랜치: `feat/native-outcome-ports`. 시작 HEAD: `6211d3823f95`. 계약: D-732, D-728.

1. D-732와 APIRef additive 계약을 독립 검토한다. 기존 manager caller/fixture/export, 실제 승인 잠금과 callback generation을 목록화한다.
2. 실제 docking/swarm protocol 메시지군과 swarm 상태 출력을 분리한다. 공개 import identity와 validator를 보존한다. zero-growth 파일·기존 unit 기준과 새 family의 동시 측정을 독립 검토하기 전에는 baseline을 바꾸지 않는다.
3. 기존 owner 승인 구간에 native UUID와 captured receipt를 연결하고 실제 terminal 경로를 보강한다. NavigationManager→NavExecutor→RosBridge→GoalTracker의 generation 캡처와 취소 callback을 함께 고친다. Legacy 호출은 유지한다.
4. 기존 상태/event/audit 포트에 typed 결과와 bounded retention을 연결한다. 현재 native owner의 quiescence는 pending/callback/lease와 같은 잠금 경계에서 읽고 SAFE_RELEASE 의미를 별도로 유지한다.
5. 먼저 의미 있는 원격 RED 시험을 커밋하고 확인한다. 실제 구현 뒤 manager/API/callback/lease/legacy 회귀, installed CORE closure를 원격 실행하고 모든 로그를 known_failures와 비교한다. 노트북 pytest는 실행하지 않는다.
6. APIRef/버전 pin/metadata/exports/fixture/module log를 마무리하고 SOURCE spec·독립 품질 검토를 받는다. parent 통합은 검토된 정확한 HEAD로 한다. 배포·실제 명령·Discord 발송은 이 작업에서 하지 않는다.

## 수용 기준

- RPC operation은 정확한 승인 구간의 run이며 별도 mutable status 재조회 결과가 아니다.
- caller CID 재사용·새 목표·late callback이 이전 terminal을 새 run에 귀속시키지 않는다.
- dock 성공, undock 성공, 취소, 실패, 추종 hold/선점, teleop watchdog 종료를 구분한다.
- terminal readback은 grant 철회 뒤에도 읽기 전용이며 UNKNOWN 재발행·후속 자동 실행을 만들지 않는다.
- quiescence는 실제 owner generation과 pending backend 가능성까지 증명하고 단순 IDLE/0 속도를 사용하지 않는다.
- 기존 auth/CORE 최종 writer/manager 반환형과 legacy API·executor·패키징 호환을 유지한다.
- 원격 결과·known failure 비교·독립 구조/spec/품질 증거를 분리해 보고한다.

## 2026-10-12 structural extraction and independent precheck

D-732 adds a strict native operation DTO and a small ROS-free receipt ledger. The canonical implementation now lives in `contracts/foundation/core_common/protocol/native/` (106 physical Python lines), and the former `native_operation.py` and `native_receipts.py` paths are stable re-export facades. Their public classes and validators retain object identity. This subpackage is discovered by foundation `find_packages`; installed-wheel/source-image closure is a separate remote check. It owns UUID/boot identity, first immutable terminal, bounded last-32 history and admission epoch bookkeeping only. It does not own an executor, transport, audit writer, persistent store, actuation or authority decision.

The existing physical `middleware/control/drive/behaviors/navigation/` subpackage owns Nav2 goal admission, callback binding, lease, and readback. It is already included by `core_features` `_source_layout`; registration reflects this real owner without moving a route planner or adding a wrapper. No runtime import or callback identity changes merely to satisfy scanning.

The simultaneous independent static precheck by `native-verify` measured the proposed innermost units at native 106 and navigation 773 physical lines. Residual `core_common` was 10,142, within its unchanged 10,031 + 150 verdict; residual `core_features` was 9,410, below 10,000. Control was 34,914 within unchanged 34,855 + 150; swarm unit 945 within 799 + 150. The named files were navigation manager 598 (<600), docking manager 784 (<813), swarm manager 687 (<784), command manager 477 (<600), and RosBridge 910. All prior verdict histories, the schemas zero-growth ceiling 1,389, hard tiers, and file ceilings stay intact. The registry adds these two actual subpackages and their dated verdicts in the same change. The core_features package remains below 10,000, so no new package verdict is registered. Remote architecture and installed import tests still determine final acceptance.
