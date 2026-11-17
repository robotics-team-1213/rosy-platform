## D-1016 등록 로봇 30일 비활동 «삭제 예정» 표시 — 비활성은 토큰 만료 그대로, 해제는 이름 있는 운영자만

**Status:** Proposed (2026-11-11, 사용자 방침 "30일이 넘으면 기체는 비활성화로 놔두고 삭제 예정 처리". 구현·호스트 시험 포함, 실물 현장 수용 없음)

잇는 결정: [D-361](D-361-site-console-enrolls-robot-by-screen-code.md)(화면 코드 등록) · [D-456](D-456-choose-robot-on-lan-approve-on-their-screen.md)(**오프라인·로그인 만료는 페어링 해제가 아니다**) · [D-580](D-580-site-roster-follows-fleet-enrollment.md)(로스터=등록부) · [D-555](D-555-enrolled-robot-hub-pairing.md)(허브 페어링)

### Context

1. 등록부에는 돌아올 기체와 실제로 정리할 기체가 섞여 있다(2026-11-11: 6대 중 `active` 1대, 만료 `needs_new_code` 4대, `pending_logout` 1대). 운영자는 로스터에서 "오래 쉬는 기체"를 한눈에 구분하지 못한다.
2. 비활성화는 이미 자동이다. 페어링 토큰 수명이 지나면 로봇은 스스로 401을 내고 등록 행은 `needs_new_code`로 비활성된다. 없는 것은 "이 기체를 정리 대상으로 본다"는 표시뿐이다.
3. 반대로 삭제(unenroll)는 재등록이 사람 물리 작업(기체 전원·화면 코드·Account 콘솔, TLS binding 재묶음)이라 자동화하면 돌아올 기체의 자동 갱신 경로(감시기)를 끊는다. D-456의 원칙("오프라인·로그인 만료는 페어링 해제가 아니다")이 이를 이미 못박는다.

### Decision

1. **마지막 활동이 30일(기본)을 넘은 등록 행을 `removal_pending: true`(«삭제 예정»)으로 표시한다.** 표시는 읽기 시점 계산이고 DB 상태·전이를 늘리지 않는다(`needs_new_code` 표시와 같은 패턴). `GET /api/fleet/enrollment/robots` 행에 `last_activity_at`·`days_idle`·`removal_pending`이 실린다(API v1.386).
2. **"활동"의 정의는 (a) 마지막으로 수용된 CORE 이벤트(`core_event_audit`의 `received_at` 최댓값, `CoreEventStore.last_received_times`) 또는 (b) 등록 행 마지막 기록(`updated_at`, 없으면 `created_at`) 가운데 늦은 쪽이다.** 이벤트 저장소가 없는 구성에서는 (b)만으로 계산한다. 하트비트 신선도는 메모리 3초 창이라 30일 판정의 근거로 쓰지 않는다.
3. **임계값은 사이트 설정 `fleet.enrollment.idle_removal_days`(기본 30, 1..3650)로 바꾼다.** 없으면 기본값, 잘못된 값은 시작 거부(다른 `fleet.*` 설정과 같은 규칙).
4. **`removal_pending`은 무엇도 해제하지 않는다.** 로봇 정지·격리·토큰 회수·자동 unenroll가 없다. 해제는 이름 있는 운영자의 기존 `DELETE /api/fleet/enrollment/robots/{robot_id}`(removal blocker 검사·감사 포함) 그대로다. 표시가 unenroll 버튼을 활성화하지도 않는다.
5. **경계.** 이벤트 조회는 이벤트 소유 모듈(`fleet/observe/events.py`)에 두고 등록 서비스는 `last_activity` 콜백으로 주입받는다 — 등록 저장소가 이벤트 표를 직접 읽지 않는다.

### Consequences

- 운영자는 등록 화면 목록에서 "삭제 예정(며칠 쉼)"을 바로 본다. nsfh처럼 결정이 걸린 기체가 표로 떠오른다.
- 이 표시만으로 알림(D-661 outbox)을 보내지 않는다. 팀 통지가 필요해지면 별도 변경으로 outbox에 새 `kind`를 얹는다(설계만 남긴다).
- 장기 절전·계획된 실내 보관 기체도 30일이면 표시된다. 거짓 양성은 표시이므로 해가 없고, 재등록 절차가 바뀌지 않는다.
- `removal_pending`은 유도된 값이라 감사에 남지 않는다. 실제 해제는 기존 unenroll 감사(`device_pairing_audit`)에만 기록된다.

### 검증 (Validation / Transition)

- 호스트: `operations/fleet/test/test_enrollment_service.py`(30일 경과 표시·29일 미표시·이벤트가 등록 기록을 이김·임계값 설정 반영), `test_core_event_store.py`(`last_received_times`), `test_site_config` 계열(값 검증). 원격 시험으로만 돈다(D-584).
- 실물: R 현장 배포 뒤 실제 등록부에서 표시가 나오는 것을 관제 화면 응답으로 1회 확인한다(사람 몫). FIELD 게이트는 그대로다.

### References

`operations/fleet/fleet/server/auth/enrollment.py`(`_idle_facts`, `listing`), `operations/fleet/fleet/observe/events.py`(`last_received_times`), `operations/fleet/fleet/console_site_config.py`(`_enrollment_config`), `operations/fleet/fleet/server/console/console_builders.py`, `operations/fleet/fleet/cli.py`
