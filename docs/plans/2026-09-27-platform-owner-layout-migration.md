# 제어기 소유 기준 폴더 이행 계획

**상태:** D-303 Proposed의 검토 가능한 실행 순서. 현재 소스 이동 없음. `main`의 다른 작업과 이미지 릴리스 일정을 확인한 뒤 각 묶음을 독립 커밋으로 실행한다.

## 현재 의존과 보류점

| 확인한 사실 | 이행에 주는 영향 |
|---|---|
| `core_common.protocol.schemas`는 로봇↔Fleet wire 값과 사이트 전용 `FleetTaskStatus`·`DiscoveryScanPayload`를 함께 정의 | 클래스별 생산 소비자를 먼저 기록하고 wire와 사이트 값을 나눈다 |
| `SiteSightingPayload`는 Overhead 발행과 Fleet 수신이 사용 | `site_sighting`은 현재 두 실제 소비자가 있는 추출 후보 |
| Fleet 생산 코드는 `core_common.intent`, `succession`도 사용 | 전체 `core_common`을 `controllers/base`로 옮기기 전 소유·의존을 판정한다 |
| `web_common`은 CORE API와 Fleet이 모두 `exec_depend`로 설치 | 로봇 제어기 아래에 두지 않고 `shared_ui/web`에 둔다 |
| `test/architecture/test_target_layout.py`는 D-231의 24개 패키지 경로를 강제 | 모든 경로 이동과 같은 커밋에서 목표·경계 시험을 갱신한다 |
| 배포·CI·도구의 현행 `src/...` 경로 참조가 다수 존재 | 단순 `git mv`만으로 끝내지 않고 경로 소비자를 한 묶음에서 갱신한다 |

## 실행 묶음

1. **의존 표와 계약 추출 경계:** `core_common` 공개 모듈별 실제 생산 import, 패키지 의존, Docker 이미지 포함 범위를 기록한다. `schemas.py`의 wire 클래스와 사이트 전용 클래스를 분류한다. 현재 JSON 벡터와 API Reference를 기준으로 직렬화 호환 시험을 만든다. Fleet `intent`·`succession`은 실행 규칙이므로 공유 계약 후보에서 제외하고 별도 소유 판정을 기록한다.
2. **사이트 관측 계약:** `SiteSightingPayload`만 `src/contracts/site_sighting/`의 ROS 없는 패키지로 추출한다. Overhead와 Fleet의 생산 import 및 `package.xml`을 전환한다. 기존 공개 import는 이행 기간 호환 재수출을 제공하고, 실제 패키징에서 두 소비자가 새 패키지만으로 설치되는지 검사한다. 반례: 잘못된 provenance·stale 관측은 작업 완료로 승격되지 않는다.
3. **로봇↔Fleet wire 계약:** 실제 교환하는 envelope/handshake/event/ACK 값만 `src/contracts/robot_link/`로 추출한다. `FleetTaskStatus`·`DiscoveryScanPayload`와 로봇 내부 값은 각 소유자로 옮긴다. 기존 `protocol_version`·JSON 형식과 수신 허용 범위를 유지한다. CORE와 Fleet 양쪽에서 별도 설치·import 시험을 한다. OMX 공통 action schema는 실제 DEVICE 표본과 P2 심사 전 추가하지 않는다.
4. **제어기별 물리 이동:** 기존 패키지 이름과 ROS 실행 이름을 유지한 채 D-303 지도에 따라 `git mv`한다. 먼저 `controllers/base`의 `foundation/interfaces/gateway/services/events/api_web/sensing/navigation`, Pinky 하드웨어, 로컬 `dashboard/face`를 한 원자적 경로 묶음으로 옮긴다. `web_common`은 두 소비자가 공유하므로 `shared_ui/web`로 옮긴다. 다음 `controllers/arm/omx/adapter`를 옮긴다. 각 묶음에서 `deploy/robot`, `deploy/omx`, CI, Dockerfile, `.dockerignore`, tools, harness, 테스트의 살아 있는 경로 참조를 함께 갱신한다. 기록용 ADR·과거 로그는 역사적 경로 그대로 둔다.
5. **정적 경계와 배포 게이트:** `test_target_layout.py`와 import 경계 시험을 새 지도에 맞춘다. 사이트 생산 코드가 `controllers/base`와 `controllers/arm`을 import하지 않는지, arm이 base 최종 명령 경로를 import하지 않는지 검증한다. host pytest·flake8·harness lint, ROS Jazzy colcon build, robot/site/omx 이미지 빌드를 각각 기록한다. 실제 장치 readback·정지는 기존 P1/P3 DEVICE/FIELD 게이트로 따로 확인한다.

## 이동 완료 판정

각 단계에서 패키지 경로 중복이 없고, 기존 import와 wire 호환 시험이 통과하며, 이미지에 예상 패키지만 포함되어야 한다. CORE의 최종 `cmd_vel` writer, Fleet 단일 Mission 원장, OMX 로컬 writer와 `omx.enabled: false`는 이동 전후 동일해야 한다. 경로 이동이 실패하면 해당 묶음만 되돌리고 마지막 통과 이미지와 계약을 사용한다. 구조 변경만으로 action 결과 상관관계, OMX 실물 제어, LeRobot 운영 승인 또는 현장 수용을 주장하지 않는다.
