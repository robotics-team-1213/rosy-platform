## D-626 D-625 holder 이전 실행과 패키지·Safety 식별 보존

**Status:** Accepted (2026-10-11, 사용자 후속 실행 요청; M3–M6 source 이전, 설치·장치·현장 수용은 별도).

## Context

D-625는 구조 방향과 계획·도구 준비를 결정했다. 사용자가 후속으로 실행을 요청하여 API·Pinky/OMX 장치 구성·Nav2 holder를 실제 이전한다. 책임 추출이나 새 실행 권한을 폴더 이동으로 대신하지 않는다.

## Decision

| 기존 결정 | 이번 이전과의 관계 |
|---|---|
| D-427 | 세 part와 import 규칙을 유지한다. manifest의 현재 `path`를 갱신하고 `d427_target` 소유권 ID와 `legacy` 이력은 보존한다. |
| D-429 | concern은 역할 관점이다. 이동으로 runtime owner·host·process를 바꾸지 않는다. |
| D-430 | Safety module의 현재 경로를 새 holder로 옮기고 dotted/string anchor는 유지한다. API·OMX의 이전 커밋에 독립 리뷰와 `Safety-Review:` trailer를 포함한다. |
| D-625 | M3–M6의 package 보존 이전을 실행한다. M7–M9 책임 추출·world 소비자·예측 구현은 별도 단계다. |

이전 단위는 `middleware/core/api_web → middleware/core/api`, `middleware/apps/device/pinky → middleware/devices/pinky`, `middleware/apps/device/omx → middleware/devices/omx`, `middleware/core/navigation → middleware/control/drive/planning/nav2`다. namespace와 ROS package명, entry point, `/opt/rosy_ws`의 기존 설치 목적지를 유지한다. source 경로와 참조·packaging·manifest·현재 안내·시험을 같은 단위 커밋에서 정합시킨다. source의 미추적·ignored 파일이나 target 충돌은 지우지 않고 중단한다.

CORE 단일 process/최종 `/cmd_vel`, Nav2의 `nav_cmd_vel` 후보 출력, Pinky deadman와 기본 motion off, ArmCommandOwner·cancel/HOLD·fresh-feedback recovery를 보존한다. 보호 코드의 본문은 변경하지 않는다. 설치 위치를 기준으로 찾는 asset과 checkout root 계산을 구별하고, holder 깊이가 바뀐 root 계산만 수정한다.

기존 committed logs·Accepted ADR·dated validation은 보존한다. 이전 사실과 독립 리뷰·시험 결과는 새 로그에 append한다. 현재 실행 명령·module guide·CI/native/dev consumer는 새 경로를 쓴다. 새 `control`·`devices` holder 안내는 실행 권한을 부여하지 않는다.

## Consequences

CORE 공통 접점, 장치별 구성, Drive 경로 계획의 현재 폴더 경계가 분명해진다. Python package 내부 깊이는 책임 holder의 5단계 상한과 별개다. 이동만으로 CORE services 내부의 책임 추출이나 Arm Control/world model 구현이 완료되지 않는다.

SOURCE·원격 host 계약·Linux 설치/import 증거를 따로 기록한다. ARM64 이미지·장치 stop/readback·현장 수용·배포 활성화는 이번 source 이전의 성공으로 추정하지 않는다. 공유 main 착지·push는 저장소의 별도 실행 절차를 따른다.
