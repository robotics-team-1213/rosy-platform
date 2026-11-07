## D-996 셀 사실은 항만 사건 4개로만 Harbor에 가고, 화물 신원은 판독값으로만 맞춘다

**Status:** Proposed (2026-11-08, 사용자 결정 D1~D7 「그렇게 처리해줄래」). 시뮬레이션 프로필에서 사건 생산·원장·R relay·S 작업 제안·판독 판정을 구현한다. 실물 팔 단계(D-858·D-911), 마커 인쇄·부착·판독률 측정은 수용 전이다.

설계와 토론 기록: 작업 공간 `docs/research/2026-11-08-harbor-intake-identity-design.md`(8a절이 공유 계약).

### Context

- Harbor는 화물이 장치 작업대에 들어왔는지, 어느 컨테이너인지 모른다. 지금은 S 퇴피 같은 셀 사실을 Harbor가 직접 판정한다(D-965가 막으려던 모양).
- 공급암 S의 load는 `cell_role` 자율 루프가 위 카메라로 센 개수만 보고 고른다. D-858 §1의 "Fleet 승인 작업 → owner" 단일 경로를 거치지 않는다.
- 판독 마커가 없고, `cell_marks.find`는 `DICT_4X4_100`만 읽어 100번 이상 번호를 보지 못한다.

### Decision

1. **항만 사건 4개.** 셀 Fleet이 셀 사실(S 작업 receipt, 컨베이어 끝 판독, 차량 해제)을 아래 사건으로 바꾼다. S·컨베이어·A/B·팔·마커·카탈로그 종류·workcell id는 사건에 넣지 않는다.
   - `container.received_at_intake`(`object_ref`, `intake_point`, `identity`)
   - `container.stored`(`object_ref`, `slot_ref`, `identity`)
   - `container.handling_failed`(`object_ref?`, `observation_ref`, `reason`: `MISMATCH|UNREADABLE|LOST|DAMAGED`)
   - `vehicle.release_permitted`(`vehicle_id`)
   - 모양은 닫힌 모델 `PortEvent`(`core_common.protocol.port_events`)이다. kind마다 필수·금지 필드를 모델이 강제한다. `event_id = sha256(source|observation_ref|kind)`.
2. **원장과 생산자.** 셀 생산자는 장치별 기계 자격(D-807)으로 `POST /api/fleet/workcell-observations/{workcell_id}/port-events`에 보낸다. 토큰은 incidents와 같은 `X-Workcell-Observation-Token`이고 사람 확인과 출처 목록을 섞지 않는다. 원장은 append-only SQLite, 셀마다 seq 단조 증가, 같은 `event_id`는 멱등이다. 생산자는 로컬 outbox에 먼저 쓰고 같은 `event_id`로 재전송한다.
3. **신원 규칙.**
   - 판독한 값으로만 맞춘다. FIFO·순서 추정·마지막 본 것 추정은 금지한다.
   - 추정 신원으로 완료까지 가지 않는다. 모든 판독 지점에서 읽지 못하면 `handling_failed(UNREADABLE)`이고, 진행은 기명 사람 확인(`identity: attested`)으로만 한다.
   - 태그 번호 → `object_ref` 표는 ROSY marker-profile의 `container_tags`가 갖는다. Harbor는 마커 번호를 받지도 저장하지도 않는다.
   - 셀 PC는 읽은 태그 번호만 보낸다(`intake-readings`). 표 변환과 선언 대조는 셀 Fleet이 한다. 그래서 PC도 업무 앱의 화물 코드를 갖지 않는다.
   - 컨베이어 끝에서 읽은 값은 "공급 작업이 끝났고 아직 받지 않은 선언값" 가운데 하나와 같아야 한다. 순서로 짝짓지 않는다.
   - `container.stored`는 손목 판독이 가리킨 A/B 작업이 슬롯 앵커 target에서 `GOAL_CONFIRMED`가 될 때만 낸다. `attested` 경로(기명 사람 확인)는 아직 생산자가 없다. A/B 작업 하나는 컨테이너 하나만 `stored`로 만든다. 손목 판독의 `arm_mission_id`는 carry 설정(`identity.arm_mission_id`)에서 오며, Fleet 하달에서 셀 PC까지 이 값을 자동으로 넘기는 연결은 아직 없다.
4. **판독 판정 (D6).**
   - 여러 프레임 투표: 한 지점에서 N장을 읽어 같은 번호가 k번 이상일 때만 판독으로 인정한다.
   - 두 면 일치: 지붕·옆면 중 하나만 읽혀도 되지만, 둘 다 읽혔는데 번호가 다르면 `MISMATCH`다.
   - 손목 hover 확인: A/B가 놓기 전 손목 카메라로 다시 읽는다. 다르거나 끝단 판독과 어긋나면 놓기 전에 HOLD한다.
   - 선언 대조: 읽은 번호를 태그 표로 바꾼 값이 이송에 선언된 `object_ref`와 다르면 `MISMATCH`로 HOLD한다.
   - 1칸 컨테이너는 지붕 12 mm, 2·3칸은 20 mm, 옆면 마커는 집게가 덮지 않는 면에 붙인다.
5. **S load는 Fleet `ARM_TRANSFER` 작업이다 (D5).**
   - `POST /api/fleet/trip-proposals`에 선택 필드 `object_ref`(≤128)를 더한다. ROSY는 해석하지 않는다(D-908의 "화물 ID 없음"을 이 불투명 참조 하나만 예외로 고친다). 값이 있을 때만 `request_digest`(정렬 키·공백 없는 JSON의 sha256)에 `object_ref` 키로 들어간다. 그래서 값 없는 제안의 digest는 그대로이고, 같은 키로 다른 값을 보내면 충돌이다.
   - 이 필드가 있는 이송이 공급 장소에서 `GOAL_CONFIRMED`가 되면 Fleet이 S의 `ARM_TRANSFER`(Pinky → 컨베이어)를 스스로 **제안**한다. 제안자는 Fleet 내부 서비스 principal(`fleet-intake`)이고 요청 키는 이송 mission에서 만든다(재시작해도 하나).
   - ARM 요청의 `object_ref`는 설치 정책의 물체 프로필 그대로다. owner grant·receipt·증거가 그 값에 묶여 있기 때문이다. 이송의 `object_ref`는 같은 트랜잭션에서 `fleet_intake_bindings`(ARM mission → 선언값)에 붙어 따라가고, 항만 사건 생산자만 읽는다.
   - 실행은 기존대로 기명 승인(D-977)·인계 확인·D-911 가드를 거친다. 이 ADR은 승인·가드를 줄이지 않는다.
   - 시뮬레이션 정책 승인 worker의 proposer 범위에 `fleet-intake`를 기본으로 넣지 않는다. 넣는 것은 운영자가 정하는 별도 결정이다.
   - `vehicle.release_permitted`는 Fleet만 쓴다(S 작업 `GOAL_CONFIRMED`에서). 셀 토큰 POST는 이 kind를 거절한다.
   - `cell_role` 자율 루프에는 rescue만 남긴다. load와 retrieve는 설정에 적혀 있어도 코드에서 거부한다.
6. **마커 번호.**
   - D-954 2항(팔 슬롯 `50 + 15 (n - 1)`)은 그대로다. `cell_marks.py`는 이미 50을 쓴다. 설계 토론의 "35와 50 불일치"는 D-933 8항(대체됨)을 읽은 것이다.
   - `container_tag`는 4X4 계열 `DICT_4X4_250`의 100~199번이다. 셀 카메라 판독(`cell_marks.find`)은 `DICT_4X4_250`을 읽는다. 0~99는 같은 그림이라 기존 번호는 그대로 읽힌다.
   - 천장 Vision(`DICT_4X4_50`, 비트 고침 없음)과 팔 슬롯 번호에서 컨테이너 태그가 회전 포함 최소 3비트 떨어지는지 시험으로 고정한다. 떨어지지 않는 번호는 `container_tags` 표에 올리지 않는다.
7. **R relay 범위 (D-965 후속).**
   - `GET /api/fleet/port-events?after=&limit=`은 R에서만 연다. R은 workcell을 가진 **직계 자식 셀**에만 묻는다. 손자 셀은 범위 밖이다(기존 ARM relay의 `topology.child` 지름길과 같다).
   - `after`는 R이 만든 불투명 문자열이다. 셀별 읽은 seq를 담는다. 닿지 않은 셀이 있거나 셀 안 seq에 빈 곳이 있으면 `complete: false`이고, 그 셀 cursor는 빈 곳 앞까지만 나아간다.
   - peer 경로는 셀의 `GET /api/fleet/control-unit/port-events?after_seq=&limit=` 하나다. peer 허용 목록에 이것만 더한다.

### 관계

| ADR | 관계 |
|---|---|
| D-965 | 7항이 relay 범위 규칙을 더한다. 4항(위임 종류 없이는 접수하지 않음)은 그대로다. 사건 조회는 읽기 전용이다. |
| D-977 | S 작업도 기명 승인·인계 확인을 그대로 거친다. 자동 제안은 승인이 아니다. |
| D-858 | S load가 "Fleet 승인 작업 → owner" 단일 경로로 들어온다. 자율 루프의 load·retrieve를 뺀다. |
| D-911 | 가드 한계·strain·retreat·2회 실패 인계를 바꾸지 않는다. |
| D-954 | 2항 번호는 유지하고 `container_tag` 범위를 프로필에 더한다. |
| D-807 | 사건 생산자는 workcell 관측 토큰(기계 자격)을 쓴다. 사람 확인 출처와 섞지 않는다. |
| D-908 | 이송 제안에 불투명 `object_ref` 하나를 허용한다. 공정 어휘는 여전히 넣지 않는다. |
| D-427·D-429·D-430 | 새 최상위 폴더 없음. safety 태그 경로는 바꾸지 않는다. |

### Consequences

- Harbor는 셀마다 따로가 아니라 R 하나에서 불투명 cursor로 읽는다. workcell id를 몰라도 된다(D4).
- 판독 실패는 늘 사람 확인으로 간다. 판독률이 낮으면 일이 사람에게 몰리므로 지점별 판독률 측정(약 20장)이 수용 조건이다.
- 남은 일: 마커 인쇄·부착·판독률 측정(사람), 실물 팔에서 손목 hover 판독(D-911 범위 안), Harbor ADR 0028·소비 구현(팀 저장소).
