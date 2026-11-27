## D-1079 이동 요청 수락 기한(admit_within_s)과 불확실 이동 표시 해제

**Status:** Proposed (2026-11-27, 설계 방향 승인: 장원종. 독립 D-430 검토 4회차 APPROVE·5회차(변경분 e496ca632d..b053a0413d) APPROVE; 원격 회귀 통과; CORE 배포·실물 수용은 후속)

### Context

Fleet의 이동 요청이 5초 timeout으로 끝나도 CORE의 동기 핸들러는 위치 추정·지도 격자·navigation 락에서 기다릴 수 있다. plain cancel은 이미 열린 `_admitting`만 철회한다. 따라서 표시 이후 측정 정지만으로 `_uncertain_motion`을 풀면 뒤늦은 목표가 새로 수락될 수 있다. D-550 목표 임대는 수락 이후의 수명이라 이 대기를 막지 않는다. 독립 안전 검토 REQUEST_CHANGES 1번에 따른 계약 보완이다.

### Decision

1. CORE navigation 시작 요청은 선택 `admit_within_s: float | None`을 받는다. 유한한 `0 < s <= 10`이며 생략·null은 기존 동작이다. `/api/v1/navigation/{goal,bound-goal,line-handoff-goal,home,route,bound-route}`에 적용한다. `bound-plan`은 GoalRequest 계열 필드를 상속하지만 경로 준비뿐이며 이동 수락·실행 기한을 만들지 않는다. lease 갱신·cancel·handover는 새 이동 수락이 아니다.
2. CORE HTTP 라우트 진입 즉시 단조 시각을 보관하고 동기 핸들러 첫 줄에서 읽는다. 본문 파싱·의존성·threadpool 대기와 위치 추정·격자·nav 락 대기를 모두 포함한다. 실제 navigation 수락 락 안에서 handoff 검사 전과 native admission 직전 `now > received + admit_within_s`면 이동 없이 `409 MOTION_ADMIT_DEADLINE_EXCEEDED`로 거절한다. ERR-101의 기존 NavigationError → ApiError 형식을 재사용한다. 경계와 같은 시각은 허용한다. 이미 수락된 route의 다음 구간에는 이 기한을 다시 적용하지 않는다.
3. `GET /api/v1/system/capabilities`의 `navigation.admit_deadline: true`가 위 여섯 경로 지원을 알린다. 주행 가능 여부나 정지 증명은 아니다. 다른 구동 API가 이 기능을 지원한다고 해석하지 않는다.
4. Fleet의 기존 capabilities 조회 결과를 재사용하되 `navigation.admit_deadline`과 `navigation.generation_fence`가 **둘 다** true일 때만 `GET /api/v1/navigation/state`의 `owner.boot_id`·`owner.owner_generation`에 묶는다. 본문에 `expected_boot_id`와 `expected_owner_generation`이 **둘 다** 실리고 두 capability가 모두 true일 때만 위 navigation 시작 본문에 `admit_within_s=3.0`을 싣는다(세대 조회가 실패하거나 둘 중 하나라도 없으면 `admit_within_s`를 붙이지 않고 unbounded로 처리). 기존 5초 전송 예산 중 응답에 2초를 남기고 오래 대기한 수락을 자르려는 기본값이다. httpx의 단계별 timeout과 별도로 해당 요청 전체에 총 transport timeout(기본 5초, `asyncio.wait_for`)을 적용하며, 라우트 진입 전 지연된 요청은 해제 전에 확정하는 세대 fence가 막는다. 값은 실물 측정 결과가 아니다.
5. 불확실 표지는 보낸 단조 시각, 실제 transport timeout, 실제 보낸 payload의 `admit_within_s`·`expected_boot_id`·`expected_owner_generation`(client 캐시 fallback 없음; 세 값 중 하나라도 없으면 `release_after=None`) 및 해제 가능한 최초 시각을 저장한다. 표시 이후의 기존 측정 정지·E-stop·exact custody 증거 규칙에 더해 **증거 조회 시작 >= 보낸 시각 + transport timeout + admit_within_s + 0.5초**를 요구한다. `MOTION_RELEASE_MARGIN_S=0.5`(`motion_ingress.py:18`)는 설계 여유값이며 실측값이 아니다(실물 측정 필요). 기본값은 보낸 뒤 8.5초다. 또한 정지 증거를 읽기 **전에** 먼저 참고용 사전 조회(`GET /api/v1/navigation/state`)로 CORE `boot_id`가 표지의 `boot_id`와 같은지 확인하고(바뀌었으면 해제하지 않고 클라이언트의 capability를 지운다), 불확실 로봇은 `navigation`이 비활성(`IDLE`/`ARRIVED`/`CANCELED`/`FAILED`, 기존 정지 상태 집합 재사용)일 때만 아래 보충 세대 fence(`POST /api/v1/navigation/cancel` `{"advance_generation": true}`)를 보내 그 cancel 응답 자체의 `owner.owner_generation`으로 세대 전진을 확정한 뒤, 그 fence 확정 시각 **이후**에 측정된 정지 표본이 있고 표본 뒤에도 비활성 `navigation`과 같은 `fenced_generation`이 유지될 때만 해제한다. 사전 조회에서 `navigation`이 활성이면 fence(cancel advance)하지 않고 해제도 하지 않으며(표시 유지), cancel 응답에 갱신된 `owner`가 없거나 `advance_generation` 호출이 `TypeError`로 거절되면 plain cancel+GET으로 대체하지 않고 fence 실패(`False`)로 처리한다. 시간 경과나 `gen > expected`만으로 해제하지 않으며 자동 재출발·래치 해제는 없다. 새 불확실 요청은 앞선 무기한 표시나 더 긴 기한을 짧게 만들지 못한다.
6. 기한 없는 옛 CORE, 재부팅·D-225 롤백으로 `boot_id`가 바뀌거나 세대 fence를 올리지 못하는 CORE, 아직 capability를 읽지 않은 클라이언트, 지원 범위 밖 이동 요청은 표시를 해제하지 않고 보류한다. 기존 로그에 `기한 없는 CORE라 해제 불가`를 남긴다. 새 Fleet API는 만들지 않는다. 실물 CORE 배포 전에는 지금 main과 같은 보수적 보류가 유지된다.

#### 보충: 세대 fence

라우트 진입(`request.state.motion_received_at`) 전에 네트워크·커널·역프록시·소켓 버퍼에 머문 요청은 `admit_within_s`만으로는 막히지 않고, 기존 `POST /api/v1/navigation/cancel`(`manager.py:502-512`)은 이미 IDLE/종료 상태이고 `_admitting is None`일 때 `owner_generation`을 올리지 않는다. 따라서 다음 보충 계약을 함께 둔다.

1. `POST /api/v1/navigation/cancel`은 선택 본문 `{"advance_generation": true}`(기본 `false`)를 받는다. `NavigationManager.cancel(..., advance_generation=True)`는 `nav._lock` 안에서 이미 정지/종료(`_nav_state in _IDLE_STATES`, `_admitting is None`, `session is None`)여도 이동이나 `nav.canceled` 이벤트 없이 `self.native.generation`을 1 올리고 응답 `owner`에 갱신된 `{boot_id, owner_generation, owner_run_id}`를 담아 돌려준다.
2. `GET /api/v1/system/capabilities`는 `navigation.generation_fence: true`로 이 무동작 세대 전진 지원을 알린다.
3. Fleet은 bounded navigation 시작 요청에 `expected_boot_id`·`expected_owner_generation`을 싣고, 8.5초 경계 이후 정지 증거를 읽기 **전에** 참고용 사전 조회(`GET /api/v1/navigation/state`)에서 `navigation`이 비활성(`IDLE`/`ARRIVED`/`CANCELED`/`FAILED`)일 때만 `POST /api/v1/navigation/cancel`(`{"advance_generation": true}`)을 보내 응답의 `owner`에서 같은 `boot_id`의 `fenced_generation` 전진을 먼저 확정한다(`navigation`이 활성이면 cancel을 보내지 않고 표시를 유지하며, 사전 조회와 cancel 사이에 주행이 시작될 수 있으므로 fence 뒤 정지 표본과 세대 재확인 규칙은 그대로 유지한다). 그 뒤에야 라우트에 진입하는 옛 요청은 여섯 시작 경로 모두 `reserve_goal`/`reserve_planned_goal`의 `self.native.expect`에서 `409 OWNER_GENERATION_CHANGED`로 거절되며, Fleet은 fence 확정 시각 이후의 정지 표본과 동일한 `fenced_generation` 유지를 함께 확인한 뒤에만 `_uncertain_motion`을 지운다.

| 기존 결정 | 관계 |
|---|---|
| D-427 | 소스 위치·배포 파트·단일 writer를 바꾸지 않는다 |
| D-429 | CORE 장치 수락과 Fleet 관제 판단의 권한을 유지한다 |
| D-430 | 기존 safety 태그 경로는 독립 검토와 사람의 Safety-Review trailer 대상이다 |
| D-550 | 수락 뒤 목표 임대와 별개로 수락 전 대기를 제한한다 |
| D-1061 | API·모듈 Log는 조각만 추가하고 번호·Log 행은 기록 봇에 맡긴다 |
| D-1077 | 사람 존재 주장 대신 관측 증명을 쓰는 방향을 따르되 셀 stop proof 계약은 바꾸지 않는다 |

### Alternatives

- Fleet 시간 경과나 cancel ACK만으로 해제: CORE에 남은 수락 대기를 끝내지 못하므로 기각.
- 목표 lease TTL만 사용: 수락 뒤부터 세므로 기각.
- `admit_within_s` 단독 사용(세대 fence·`boot_id` 귀속 없음): 재부팅·D-225 롤백 뒤 옛 CORE가 필드를 무시하거나 라우트 진입 전 버퍼에 머문 늦은 요청이 8.5초 뒤 들어올 때 수락될 수 있어 보충 세대 fence와 `boot_id` 귀속을 함께 적용.
- 구형 CORE에도 필드 전송: 필드를 무시할 수 있으므로 기각.

### Consequences and validation

기존 클라이언트는 필드 없이 동작한다. capability가 없는 로봇이나 재부팅·롤백으로 `boot_id`가 바뀐 로봇은 표시를 해제하지 않으므로 배포 순서는 CORE 후 Fleet 확인이다. 다른 이동 API는 이번 기한 계약 밖이며 보수적 보류를 유지한다.

보장은 CORE 라우트 수신 이후 수락 대기에 대한 `admit_within_s`, 총 5초 전송 대기 상한(`asyncio.wait_for`), 그리고 라우트 진입 전 지연 패킷을 `409 OWNER_GENERATION_CHANGED`로 차단하는 `boot_id` 귀속 + 선행 `owner_generation` 세대 fence를 결합한다. CORE/Fleet wall clock 오차와 표본 인과성, 메모리 표지의 재시작 영속화는 이번 범위 밖이다. `MOTION_RELEASE_MARGIN_S=0.5`는 설계 여유값이며 실측값이 아니므로 실물 측정이 필요하다(실물 측정 필요).

기한 내·경계·기한 초과·필드 생략, 여섯 시작 경로 전체의 localization/nav 락·의존성 대기 및 무동작 세대 fence 거절(`OWNER_GENERATION_CHANGED`), bound goal·handoff, capability와 Fleet `boot_id` 귀속·세대 갱신 실패 시 unbounded 유지·비활성 nav일 때만 선행 fence 전송(활성 nav는 cancel 미전송·표시 유지)·cancel 응답 `owner` 부재 시 fence 실패·선행 fence 뒤 정지 표본 검증·구형 CORE·boot 변경·중복 불확실성 회귀를 작성했다. 원격 시험(모델 PC·AI PC)에서 CORE 630 passed, Fleet 546 passed, `known_failures` 0 new(`b053a0413d`)를 확인했고 독립 D-430 검토 4회차 APPROVE·5회차(변경분 e496ca632d..b053a0413d) APPROVE를 받았으며, 비차단 지적 2건(비활성 nav일 때만 fence 전송, cancel 응답 `owner` 필수)을 반영했다. 문법·import·lint 확인과 safety 경로 목록은 [검증 기록](../validation/fleet-uncertain-motion-2026-11-27/result.md)의 D-1079 절에 남긴다. DEVICE/FIELD 수용을 주장하지 않는다.
