## D-627 CORE Drive 조립 책임의 첫 분리

**Status:** Accepted (2026-10-11, 사용자 요청: CORE의 drive 부분 우선; 소스 책임 분리와 원격 시험 범위).

## Context

D-625는 CORE 공통 운용과 장치별 Control을 구분한다. D-626의 폴더 이전은 패키지 배치만 바꾼다. 사용자는 그 작업 중 CORE 내부 drive 책임을 먼저 처리하도록 순서를 정했다. 현재 `CoreServices.build`에는 공통 서비스 구성과 도킹/군집 조립, 모드 전환 및 E-stop listener 배선이 함께 있다. line-follow 배선은 이미 별도 파일이지만 drive 조립의 위치가 드러나지 않는다.

## Decision

- `middleware/core/gateway/core/drive/`는 CORE 프로세스 안의 **Drive 조립**을 소유한다. `line_follow.py`는 기존 config/envelope/recovery 연결, `docking.py`는 기존 docking/swarm 객체 조립과 docking 모드 입장/해제를 담당한다. 별도 서비스 컨테이너나 프로세스를 만들지 않는다.
- `CoreServices`의 공개 attribute와 객체 identity를 유지한다. 공통 identity, 상태, 전력, 사건, CommandManager/SafetyManager와 전체 listener 순서는 그대로 둔다. 도킹 종료와 모드 해제의 기존 critical section, MANUAL 선점 검사, Nav2 취소 순서를 바꾸지 않는다.
- 기존 `core.line_follow_wiring`와 `core.services`의 parser import는 얇은 재-export로 호환한다. 내부 운용 caller는 새 drive 배선을 사용한다. 새 mode/API/config 필드는 없다.
- Drive 알고리즘은 현재 `core_features`의 주행/복구/기하 소유자에 남는다. Nav2 backend는 `middleware/control/drive/planning/nav2`다. CORE 조립, 알고리즘, ROS transport, 장치 bringup은 별도 책임이다. Arm 조립을 억지로 이 Drive 모듈에 넣지 않는다.
- 움직임 후보와 곡률/body 검사, E-stop 및 마지막 `/cmd_vel` publisher는 바꾸지 않는다. Safety 배선도 독립 리뷰하고 추출한 배선 파일을 Safety 추적에 추가한다.

## Verification and consequences

기존 docking 모드·종료·선점·listener isolation, line-follow geometry/recovery, goal tracker, cmd_vel cycle, port 및 Safety 행동 시험을 변경 전 SHA와 변경 후 SHA에서 원격 실행한다. 새 설치 위치에서 `find_packages`가 drive 하위 패키지를 포함하는지 실제 wheel 설치로 확인한다. 구조 lint와 기존 size verdict를 현재 파일에 맞춘다. 함수 구현 이동은 body 비교로 검토하고 callback 등록 순서는 실제 시험으로 확인한다.

이 결정은 P1–P3의 전 producer 통일, 곡률 정책 개선, 복구 budget 변경, 장치 설치나 실물 주행 수용을 완료시키지 않는다. 실패한 회귀는 이 브랜치에서 고치며 main 착지·push·장치 활성화는 별도 요청 범위다.
