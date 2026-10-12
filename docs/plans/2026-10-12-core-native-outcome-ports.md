# CORE native outcome ports 구현 계획

날짜: 2026-10-12. 브랜치: `feat/native-outcome-ports`. 시작 HEAD: `6211d3823f95fac83252187775697b3d765551e6`. 계약: D-732, D-728.

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
