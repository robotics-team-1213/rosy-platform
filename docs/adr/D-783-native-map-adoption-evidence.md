## D-783 Native adopted-map readback with finite parent evidence

**Status:** Accepted (2026-10-17)

사용자가 승인한 스테이션 자동 접안·충전·재투입·위치 변경 실행 범위의 설계 결정이다. 독립 architecture/critic 검토 3라운드의 R3가 승인됐으며, 구현·native 시험·장치/현장 수용은 별도다.

## Context

CORE의 원본 지도 수신과 TF freshness는 실제 AMCL과 전역 StaticLayer가 그 지도를 처리했다는 증거가 아니다. MapServer GetMap과 lifecycle 상태만으로 채택을 추정하면 원본 A를 받은 CORE가 B를 쓰는 소비자와 운행할 수 있다. 현재 로컬 costmap에는 StaticLayer가 활성화돼 있지 않다.

## Decision

기존 navigation 패키지에 opt-in native 소비자를 둔다. AMCL과 전역 StaticLayer의 첫 subscription부터 소유하고 실제 native 처리 호출/적용 뒤 원본 grid identity를 보관한다. 초기 지원은 고정 SDK의 standalone AMCL과 비회전 전역 정적지도이며 원본 내용은 instance 동안 불변이다. 상세 startup·lock·lifecycle·SDK 조건과 실제 시험 절차는 [실행 계획](../plans/2026-10-17-native-map-adoption.md)에 둔다. 임의 callback 교체나 ordinary backend로의 자동 fallback을 허용하지 않는다.

로봇 내부의 새 읽기 전용 ROS service는 기존 `interfaces` 패키지가 소유한다. 원본 grid digest/metadata/time, 실제 consumer role/node/instance/generation, conversion config/build 식별자와 요청 challenge를 반환한다. 이는 내부 wire contract이며 자체 contract version을 갖는다. 외부 REST·Fleet DTO·capability에는 새 권한이나 필드를 추가하지 않는다. CORE SRS ROS-101의 내부 ROS 경계 안에 있으며, 향후 외부 계약 변경은 별도 API reservation/변경 절차를 따른다.

두 응답은 원자적 동시 snapshot이나 native stability lease가 아니다. CORE가 요청 시작 시각에 묶인 유한 sampled evidence로 다룬다. parent에 결속한 두 native instance/generation·원본 지도 객체/identity·config/build tuple은 불변이다. polling 사이 reset→같은 지도 재적용이 끝나 높은 generation이 오더라도 기존 parent를 소비한다. 기존 proof 만료 뒤 같은 tuple이 돌아와도 복구하지 않는다. 같은 tuple의 만료 전 새 관측만 sampled deadline을 대체할 수 있고 parent 예산이나 과거 selected writer receipt의 deadline을 연장하지 않는다.

CORE의 기존 최종 writer가 선택과 실제 제출 경계에서 deadline/context를 비차단으로 확인한다. query/응답이나 원본 변경은 정확히 캡처한 parent에만 STOP을 요청한다. native RMW·hash·source lock·파일 작업을 최종 writer로 옮기지 않는다. REQUIRED/CLOSED source는 첫 cycle 전에 한 번 설치하며 설치 실패는 닫힌 상태다. OMX의 별도 joint/action owner를 바꾸지 않는다.

## 구조 결정과의 관계

| 결정 | 관계 |
|---|---|
| D-427 | 기존 navigation/Drive evidence/CORE bridge·factory와 `interfaces` holder를 사용한다. 새 최상위 폴더나 ROS 패키지를 만들지 않는다 |
| D-429 | native 소비자는 사실을 보고하고 CORE가 운행 admission과 최종 출력을 소유한다. Fleet는 작업/자원 원장을 계속 소유한다 |
| D-430 | native C++ 폴더는 safety root, Python 조립은 resolving safety module/anchor로 등록하고 독립 검토·trailer를 적용한다 |
| D-776 | 원본 계측/energy와 승인 Fleet 지도 revision·변환, 정지 인계 및 source 수명 검증을 대신하지 않는다 |

## Consequences

고정 SDK/native opt-in build가 지원되지 않으면 명시적으로 실패한다. 실제 같은 SHA의 `interfaces`를 먼저 생성·source하고 `navigation`을 빌드/시험하며, 성공·실패 artifact를 보존한다. 일반 standalone/composable launch는 유지하지만 초기 verified composition은 AMCL의 공유 static free-space 상태 때문에 거절한다. 검증 실패 시 pinned upstream instrumentation 대안을 다시 검토하며 무검증 우회를 넣지 않는다.

물리 정지 지연·watchdog/제동, 실제 charger/BMS/contact/extrinsics, geometry/localization, 원본 energy, 실제 HTTP/native factory와 전체 세 번의 복귀·충전·재투입·station relocation이 확인되기 전에는 운영 capability나 전체 목표를 완료 처리하지 않는다.
