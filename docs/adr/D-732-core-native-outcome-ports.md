# D-732 CORE native 실행 결과 식별과 readback

- 상태: 제안, 계약 검토 중
- 날짜: 2026-10-12
- 선행: D-728, D-550, D-2

## 문제

귀환·도킹·추종·단발 teleop의 현재 상태만으로는 원래 Discord 요청의 실행 결과를 식별할 수 없다. 같은 도크나 목표, 재사용한 caller correlation, UNDOCKED/IDLE 상태는 실행 성공 증거가 아니다. 승인 후 잠금을 풀고 상태를 다시 읽으면 다른 실행의 결과를 RPC 응답에 넣을 수도 있다.

## 계약

기존 CORE owner의 실제 승인 잠금 안에서 새 UUID `run_id`를 만든다. caller가 선택하는 `correlation_id`는 선택적 연결 정보이며 승인·멱등·재시도 권한이 아니다. 동일 correlation을 재사용해도 새 run이다. 새 command writer, 프로세스, 저장 프레임워크는 만들지 않는다.

기존 RPC 응답에 선택적 `operation` 객체를 추가한다. 필드는 `run_id`, `kind`(navigate/home/dock/undock/follow/teleop), `correlation_id`, `phase`(SUBMITTED/RUNNING/TERMINAL), `result`(null/SUCCEEDED/FAILED/CANCELED/PREEMPTED/EXPIRED), `reason`이다. SUBMITTED는 owner가 제출을 받아들였다는 뜻이며 backend 승인·실제 운동·측정 거리 달성을 뜻하지 않는다. 정확한 승인 receipt는 owner 잠금 안에서 복사해 반환한다. API가 나중의 상태를 다시 읽어 원래 승인을 만들지 않는다.

`run_id`와 `boot_id`는 CORE가 만든 UUID이며 operation은 `boot_id`도 포함한다. `reason`은 null 또는 고정 machine code다. 원문·exception 메시지를 넣지 않는다. SUBMITTED/RUNNING의 result는 null, TERMINAL의 result는 반드시 위 종결 enum이다. 거절된 admission은 기존 오류로 끝나며 operation을 생성하지 않는다.

기존 상태 포트는 현재 또는 마지막 operation을 제공한다. navigation/state, docking/status, swarm/state를 사용하고 단발 teleop은 control owner의 읽기 전용 상태 포트를 계약에 추가한다. 각 owner가 보유하는 terminal view는 마지막 32개까지이며 재부팅 후 복원된 실행 권한이 아니다. 기존 event/audit 조회는 이전 native identity의 종결 증거를 읽는 데 사용한다. FileAuditLog의 기존 30일 보존·buffered append/no per-event fsync 한계와 FleetCoreEventStore의 기존 보존을 그대로 기록한다. 사라진/pruned/재부팅 후 불명 identity는 UNKNOWN이다.

정확한 readback은 기존 GET `/api/v1/navigation/state`, `/api/v1/docking/status`, `/api/v1/swarm/state`와 새 GET `/api/v1/teleop/state`의 선택적 UUID `run_id` query로 조회한다. query가 없으면 current 또는 가장 최근 operation, 있으면 current/최근 32 terminal 중 일치하는 것만 `operation`에 반환한다. 없으면 `operation:null`이며 `lookup:UNKNOWN`; 있으면 `lookup:FOUND`다. 다른 실행의 최신 receipt로 요청한 실행을 대신하지 않는다. 기존 snapshot 필드와 auth는 유지한다.

NavigationManager의 run identity는 실제 RosBridge/GoalTracker backend generation에 캡처된다. 늦은 승인·취소·결과 callback은 캡처한 native identity에만 적용하며 새 run 상태를 바꾸지 않는다. 기존 Fleet Task의 caller correlation 이벤트 projection은 유지한다. home은 선택적 correlation/goal lease 본문을 기존 goal owner로 전달하며 본문 없는 호출도 유지한다.

home→goal은 `kind:home`의 단 하나의 native run을 만든다. 별도 home UUID를 만든 뒤 navigate UUID를 만들지 않는다. backend 거절은 FAILED/BACKEND_REJECTED, 검증된 owner 실패는 FAILED/BACKEND_ERROR, native lease 만료는 EXPIRED/LEASE_EXPIRED, 명시적 취소는 CANCELED/CANCELED, 안전 취소는 CANCELED/SAFETY_STOP이다. 제출·결과 exception이 backend 수락 여부를 증명하지 못하면 nonterminal phase/result=null과 BACKEND_RESULT_UNKNOWN reason을 유지한다. UNKNOWN은 lookup/evidence 분류이지 operation phase가 아니다. 기존 NAV-006 stuck 취소는 FAILED/STUCK이다. 첫 terminal은 불변이며 late callback·충전 변화·조회가 다른 결과로 다시 쓰지 못한다.

도킹은 도착과 성공적인 undock을 SUCCEEDED로, 취소를 CANCELED로 구분한다. 충전 상태 관측은 도킹 terminal 결과를 다시 쓰지 않는다. 추종 hold는 RUNNING이며 자원을 계속 소유한다. re-follow는 이전 run PREEMPTED, 취소·owner session 종료는 캡처한 이전 run의 terminal이다. Teleop은 watchdog에 제한된 한 번의 velocity pulse다. 새 입력의 선점·watchdog 만료·안전 정지·모드 이탈을 owner 종료로 기록하며 거리 달성을 주장하지 않는다. Fleet keepalive는 추가하지 않는다.

별도의 현재 권한을 가진 명시적 follow_cancel/stop 요청은 RUNNING 자원을 멈출 수 있다. 기존 취소 RPC는 실제로 닫힌 이전 run의 captured `operation`을 반환하며 concurrent 새 run의 상태로 바꾸지 않는다. site stop은 각 로봇 receipt를 별도로 유지한다. 응답 유실은 UNKNOWN이며 자동 재발행하지 않는다. 일반 안전 stop의 latch 상태는 물리적 정지 성공을 뜻하지 않는다.

읽기 전용 terminal 증거 확정은 원래 grant의 만료·철회 뒤에도 가능하지만 새 command를 발행하지 않는다. SAFE_RELEASE는 owner/run generation의 최신 quiescence 증거와 CAS가 있어야 한다. 실행 가능한 pending/admitting 명령, callback generation, lease가 하나라도 있으면 반환하지 않는다. IDLE 또는 0 velocity만으로 quiescence를 증명하지 않는다. SAFE_RELEASED는 COMPLETED가 아니며 후속 이동 승인이 아니다.

상태 응답의 `quiescence`는 `boot_id`, `owner_run_id`(없으면 null), `requested_run_id`, `observed_at`(UTC), `admitting`, `pending_submission`, `actuating_callback`, `lease_active`, `quiescent` 필드를 갖는다. boolean은 실제 owner/transport generation 상태를 잠금 경계에서 관측한다. `quiescent:true`는 요청 identity가 동일 boot의 retained terminal이고 현재 owner가 없으며 앞의 네 실행 가능성이 모두 false일 때만 허용한다. lease 만료 시각이 지났다는 사실만으로 callback이 취소되었다고 보지 않는다. 취소한 backend의 승인·결과 callback이 아직 실행을 살릴 수 있다면 false다. 자료가 없거나 reboot/boot 불일치면 proof를 null로 반환한다. Fleet는 정확한 robot/boot/run/claim generation CAS로 이 proof를 적용하고 새로운 owner가 생기면 해당 적용을 무효화한다. terminal 결과와 quiescence는 별도 증거다.

proof는 추가로 owner 범위의 단조 증가 `owner_generation`과 실제 backend `transport_generation`을 포함한다. owner 승인·취소·종결·lease 변경과 backend pending/handle/callback 변경은 각각 generation을 증가시킨다. 두 잠금 경계의 generation을 전후 비교해 변경이 없었던 관측만 proof로 반환한다. Fleet는 자기 monotonic clock으로 readback RPC 시작부터 SAFE_RELEASE CAS까지 최대2초를 허용하며 wall clock observed_at만으로 freshness를 판정하지 않는다. 이것은 remote CORE와 Fleet DB의 원자적 transaction이라는 주장이 아니다. SAFE_RELEASE는 해당 local claim을 끝내는 읽기 전용 분류이고 이후 motion 권한이 아니다.

조회 이후 다른 native run이 생기는 경쟁을 막기 위해 새로운 선택적 command 필드 `expected_owner_generation`(nonnegative integer)을 해당 기존 goal/home/dock/undock/follow/teleop 본문에 추가한다. 선택적 `expected_boot_id` UUID와 함께만 사용한다. 해당 owner의 실제 승인 잠금/Mode commit 안에서 side effect 전에 둘을 검증하며 불일치는 기존409 `OWNER_GENERATION_CHANGED`로 거절한다. Fleet가 SAFE_RELEASE 후 새 명령을 만들 때는 최신 generation을 다시 읽고 기존 원문·권한·안전 gate와 이 native CAS를 모두 통과해야 한다. 기존 본문에 이 필드가 없으면 legacy 동작을 유지한다. CORE의 다른 owner/mode/lease 배타 검사도 그대로 적용하며 SAFE_RELEASE가 그것을 우회하지 않는다.

readback은 lookup UNKNOWN·빈 초기 상태에서도 `owner` 객체의 현재 `boot_id`, `owner_generation`, `owner_run_id`를 항상 제공한다. 이것은 command CAS epoch를 읽는 metadata이며 unknown 요청의 quiescence 증거가 아니다. 조회한 run의 operation/quiescence가 null이어도 현재 admission epoch는 읽을 수 있다. paired expected fields의 검증은 mode transition보다 앞서고 제출까지 같은 승인 구간에 결속한다. 기존 실제 잠금 순서를 보존한다. ModeMachine은 docking owner→mode 순서를 사용하고 listener를 mode lock 밖에서 부른다. API의 mode 전환을 owner lock에 감싸 callback/다른 owner 역순 잠금을 만들지 않는다. mode 변경 전 owner 잠금에서 CAS와 admitting reservation을 확정하고, 잠금을 풀어 mode 전환 후 같은 reservation을 실제 제출 잠금에서 다시 검증한다. 경쟁 취소는 reservation을 철회하여 backend 제출을 막는다.

기존 manager 반환형, 본문 없는 home/undock, keyword 없는 executor, auth/capability/localization/calibration/readiness/mode/lease 검사는 유지한다. E-stop 해제나 불명 명령 자동 재발행은 추가하지 않는다. CORE만 최종 cmd_vel을 선택한다.

## 문서와 검증

현재 API Reference v1.219를 확인했다. 계약 검토 후 v1.220 additive 포트를 기록하고 envelope 1.0은 유지한다. schemas.py의 기존 공개 export를 유지하며 실제 도킹·swarm 메시지군을 분리한다. 구조 baseline 변경은 실제 동시 측정과 독립 검토 후에만 한다.

원격 시험은 legacy body/return/keyword 호환, 승인 중 경쟁, CID 재사용, 늦은 callback, 도킹/undock 성공과 취소, 추종 hold·preemption·session 종료, teleop expiry·mode/stop 선점, bounded retention/reboot UNKNOWN, native quiescence와 설치된 import closure를 검증한다. 이 ADR의 SOURCE 검증은 실제 장치·Discord 운영 수용을 대신하지 않는다.
