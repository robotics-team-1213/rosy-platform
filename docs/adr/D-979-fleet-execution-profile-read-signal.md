## D-979 앱이 읽는 실행 프로필 신호: `GET /api/fleet/execution-profile`은 읽기 전용이고 증명되지 않으면 닫힘이다

**Status:** Accepted (2026-11-04, 사용자 지시: "실제로 이제 동작해야 하는 시간", "나머지도 처리해줄래"). 실물 팔 수용은 별도다.

잇는 결정: [D-797](D-797-real-device-dispatch-trip-production-arm-device-trial.md) §2·§3(`device_trial`과 실물 identity) · [D-858](D-858-omx-real-device-path-device-core-absorption.md) S4 · [D-856](D-856-neutral-arm-transfer-surface.md) 중립 경로. Harbor ADR 0022(관문 점검표)의 조건 (f1)·(f2-ii)가 이 신호를 읽는다.

### Context

- 앱이 "팔이 실제로 움직이는 환경인가"를 알 길이 없어 점검표를 사람이 채웠다. Fleet만이 프로필과 owner 신원을 안다.
- D-977(Proposed)은 같은 신원 판정을 하달 쪽에 쓴다. 이 결정은 하달 경로를 바꾸지 않고 판정 결과를 읽기만 한다.

### Decision

1. `GET /api/fleet/execution-profile`(API v1.361)은 `require_viewer`다. 다른 앱 읽기 경로(trip-jobs)와 같아 service 역할도 읽는다. 쓰기 메서드는 없다.
2. `arm_execution`: `simulation`은 `simulated`. `device_trial`은 설치된 팔이 정확히 하나이고, owner가 `device: true`(`simulation` 아님)·같은 workcell/instance·설정의 `commissioning_revision`과 같은 값을 보고한 동안만 `physical`. 그 밖의 모든 경우(`production`, 알 수 없는 프로필, owner 없음·불일치·조회 실패)는 `closed`.
3. owner에는 기존 신원 조회(`GetOwnerIdentity`, 읽기)만 보내고 10초(거절은 5초) 캐시한다. 새 장치 명령은 없다. 상태를 바꾸지 않는다.
4. `observation_producers`·`evidence_producers`는 Fleet에 실제로 등록되고 만료되지 않은 생산자만 `{id, kind, authenticated: true}`로 싣는다. 없으면 빈 목록이다. 지어내지 않는다.
5. **앱 규칙:** 앱은 이 신호로 실행 가능 여부를 읽는다. 신호가 없거나(요청 실패·필드 누락) `checked_at`이 오래됐으면 앱은 `closed`로, 곧 거짓으로 본다. `physical`은 신호가 새로울 때만 참이다.

### 기존 결정과의 관계

| 결정 | 관계 |
|---|---|
| D-427·D-429 | 새 최상위 폴더 없음. `operations/fleet/fleet/server/` 안 모듈 하나 |
| D-797 §2·§3, D-977 | 같은 신원 조건을 읽기로만 쓴다. D-977 3항이 함수를 추출하면 이 모듈이 그것을 쓴다(지금은 같은 조건의 사본) |
| D-856 | 중립 어휘 유지. 하달·승인 경로는 바뀌지 않는다 |
| D-430 | 읽기 전용이고 safety 태그 경로 밖이라 `Safety-Review:`는 필요 없다 |

### Consequences

- `device_trial` 프로필이 main에 들어오기 전에는 이 프로필 값이 응답에 나오지 않는다. 판정 코드는 시험으로 먼저 고정한다.
- 신호는 실물 수용을 대신하지 않는다. `physical`은 owner 신원이 맞다는 뜻이지 동작이 검증됐다는 뜻이 아니다.

### Validation

- SOURCE: `operations/fleet/test/test_execution_profile_api.py`(프로필별 응답, 신원 일치·불일치·owner 없음, 캐시, 생산자 목록, service 읽기·쓰기 405).
- DEVICE: 해당 없음(읽기 전용, 실물 미사용).

**References:** D-797, D-856, D-858, D-977, D-430.
