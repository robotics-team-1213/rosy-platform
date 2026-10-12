# D-732 CORE native 실행 결과 식별과 readback

- 상태: 제안, 계약 검토 중
- 날짜: 2026-10-12
- 선행: D-728, D-550, D-2

## 문제

귀환·도킹·추종·단발 teleop의 현재 상태만으로는 원래 Discord 요청의 실행 결과를 식별할 수 없다. 같은 도크나 목표, 재사용한 caller correlation, UNDOCKED/IDLE 상태는 실행 성공 증거가 아니다. 승인 후 잠금을 풀고 상태를 다시 읽으면 다른 실행의 결과를 RPC 응답에 넣을 수도 있다.

## 계약

기존 CORE owner의 실제 승인 잠금 안에서 새 UUID `run_id`를 만든다. caller가 선택하는 `correlation_id`는 선택적 연결 정보이며 승인·멱등·재시도 권한이 아니다. 동일 correlation을 재사용해도 새 run이다. 새 command writer, 프로세스, 저장 프레임워크는 만들지 않는다.

기존 RPC 응답에 선택적 `operation` 객체를 추가한다. 필드는 `run_id`, `kind`(navigate/home/dock/undock/follow/teleop), `correlation_id`, `phase`(SUBMITTED/RUNNING/TERMINAL), `result`(null/SUCCEEDED/FAILED/CANCELED/PREEMPTED/EXPIRED), `reason`이다. SUBMITTED는 owner가 제출을 받아들였다는 뜻이며 backend 승인·실제 운동·측정 거리 달성을 뜻하지 않는다. 정확한 승인 receipt는 owner 잠금 안에서 복사해 반환한다. API가 나중의 상태를 다시 읽어 원래 승인을 만들지 않는다.

기존 상태 포트는 현재 또는 마지막 operation을 제공한다. navigation/state, docking/status, swarm/state를 사용하고 단발 teleop은 control owner의 읽기 전용 상태 포트를 계약에 추가한다. 각 owner가 보유하는 terminal view는 마지막 32개까지이며 재부팅 후 복원된 실행 권한이 아니다. 기존 event/audit 조회는 이전 native identity의 종결 증거를 읽는 데 사용한다. FileAuditLog의 기존 30일 보존·buffered append/no per-event fsync 한계와 FleetCoreEventStore의 기존 보존을 그대로 기록한다. 사라진/pruned/재부팅 후 불명 identity는 UNKNOWN이다.

NavigationManager의 run identity는 실제 RosBridge/GoalTracker backend generation에 캡처된다. 늦은 승인·취소·결과 callback은 캡처한 native identity에만 적용하며 새 run 상태를 바꾸지 않는다. 기존 Fleet Task의 caller correlation 이벤트 projection은 유지한다. home은 선택적 correlation/goal lease 본문을 기존 goal owner로 전달하며 본문 없는 호출도 유지한다.

도킹은 도착과 성공적인 undock을 SUCCEEDED로, 취소를 CANCELED로 구분한다. 충전 상태 관측은 도킹 terminal 결과를 다시 쓰지 않는다. 추종 hold는 RUNNING이며 자원을 계속 소유한다. re-follow는 이전 run PREEMPTED, 취소·owner session 종료는 캡처한 이전 run의 terminal이다. Teleop은 watchdog에 제한된 한 번의 velocity pulse다. 새 입력의 선점·watchdog 만료·안전 정지·모드 이탈을 owner 종료로 기록하며 거리 달성을 주장하지 않는다. Fleet keepalive는 추가하지 않는다.

읽기 전용 terminal 증거 확정은 원래 grant의 만료·철회 뒤에도 가능하지만 새 command를 발행하지 않는다. SAFE_RELEASE는 owner/run generation의 최신 quiescence 증거와 CAS가 있어야 한다. 실행 가능한 pending/admitting 명령, callback generation, lease가 하나라도 있으면 반환하지 않는다. IDLE 또는 0 velocity만으로 quiescence를 증명하지 않는다. SAFE_RELEASED는 COMPLETED가 아니며 후속 이동 승인이 아니다.

기존 manager 반환형, 본문 없는 home/undock, keyword 없는 executor, auth/capability/localization/calibration/readiness/mode/lease 검사는 유지한다. E-stop 해제나 불명 명령 자동 재발행은 추가하지 않는다. CORE만 최종 cmd_vel을 선택한다.

## 문서와 검증

현재 API Reference v1.219를 확인했다. 계약 검토 후 v1.220 additive 포트를 기록하고 envelope 1.0은 유지한다. schemas.py의 기존 공개 export를 유지하며 실제 도킹·swarm 메시지군을 분리한다. 구조 baseline 변경은 실제 동시 측정과 독립 검토 후에만 한다.

원격 시험은 legacy body/return/keyword 호환, 승인 중 경쟁, CID 재사용, 늦은 callback, 도킹/undock 성공과 취소, 추종 hold·preemption·session 종료, teleop expiry·mode/stop 선점, bounded retention/reboot UNKNOWN, native quiescence와 설치된 import closure를 검증한다. 이 ADR의 SOURCE 검증은 실제 장치·Discord 운영 수용을 대신하지 않는다.
