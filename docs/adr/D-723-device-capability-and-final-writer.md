## D-723 청소와 팔과 비행체는 새 폴더 없이 장치 능력과 최종 작성자로 나눈다

**Status:** Accepted (2026-10-12). 분류 결정이다. 구현, 장치 수용, 현장 수용이 아니다. 폴더, 매니페스트, wire, RobotMode는 그대로다.

## Context

운영자가 로봇청소기처럼 다룰 때 더 해야 할 일과, 팔과 다른 로봇과 드론까지 넣어 범주를 확장하고 유지보수할 수 있게 다시 정리할 것을 물었다.

범주는 이미 정해져 있다.

- 비전 문서의 프로필 설치. Pinky 프로필은 기본 런타임과 주행, 카메라, LiDAR, 배터리, 안전, 도킹이다. OMX 프로필은 관절, 그리퍼, 조작이고 작성자가 다르다. Pinky 주행의 최종 명령은 CORE이고, OMX 팔의 최종 명령은 장치 수용을 마친 OMX 로컬 제어기다. 같이 쓰는 것은 계약이 먼저다. 공통 실행 코드는 같은 일이 두 곳에서 확인된 뒤에만 뽑는다.
- D-55. 이동 조작은 로봇 로컬 미션 능력이다. OMX/MoveIt는 팔 동작만 발행한다. 베이스 `cmd_vel`의 최종 작성자는 CORE다. OMX 능력은 장치 payload 시험 전까지 꺼져 있다. Pinky와 OMX를 합친 Asset은 v1이 아니다(D-71). `motion_profiles.yaml`의 `unknown`, `base`, `stowed_arm`, `carrying_box`, `placing`은 측정 전이다.
- D-71. D-55가 OMX를 켜기 전에는 `asset.type=mobile_base`인 Device 하나다. 합성, 패브릭, rosyctl은 CORE에 넣지 않는다.
- D-310 결정 5. 드론은 비행 스택과 최종 actuator authority 확인 전 폴더나 공통 action API를 예약하지 않는다. 그 수용은 소스 배치에 한정되고, OMX 운영 제어권과 장치 수용을 승인하지 않는다. D-310 본문의 `src/products/` 그림은 D-427 이후의 현재 배치가 아니다.
- D-12. 미션 실행기는 Fleet에 둔다. 로봇은 원자 액션과 이벤트를 제공한다.
- D-420은 Proposed다. 이 결정은 Pinky Device Action 목록을 받아들이거나 늘리지 않고, wire 필드도 만들지 않는다.
- D-721. 운영자 복귀의 목적지는 `station`과 `outing_start`다. 여섯 번째 `RobotMode`는 없다.
- 매니페스트. `rosy.device.pinky`는 `device_type: mobile_base`, `enabled: true`, `provides: [drive, battery, lidar, local_safety]`다. `rosy.device.omx`는 `device_type: manipulator`, `enabled: false`, `provides: []`다.

## Decision

1. 제품 구호는 `RobotMode`, 최상위 폴더, `device_type`, CORE 사본, 공통 action API를 만들지 않는다. 새 표면 이름도 만들지 않는다. 한 운영은 지금 소유한 표면에 둔다(D-425).

2. 바닥을 덮고 돌아오는 일은 기존 `mobile_base` 위의 Fleet 미션이다(D-12). 미션은 이미 있는 원자 동작을 잇는다. 이동은 내비게이션이나 선 따라가기이고, 끝나면 D-721의 목적지 하나다. 가르쳐 둔 도크가 있으면 `station`이고, 도크가 없으면 그 복귀는 출발하지 않는다. 외출 시작 자세가 `LOCALIZED`로 기억되어 있으면 `outing_start`이고, 도착하면 `IDLE`이다. SAF-003, SAF-005의 `RETURN_HOME`, DNC-006은 그대로다. 배터리 귀환을 청소 복귀로 다시 정의하지 않는다.

3. 청소기가 되려면 나중에, 이 범주 안에서, 다음이 더 필요하다. 맵 위에서 이미 지역화되는 범위, 그 범위를 기존 목표로 잇는 Fleet 미션, 그리고 기존 안전 정책이 배터리를 멈춘 뒤의 D-721 `station`. 브러시, 흡입, 물걸레처럼 바닥을 만지는 구동기는 Pinky에 없다. 그 구동기는 가진 Device의 `provides`에 올라오고, 그 가족의 최종 작성자가 정해진 뒤에 이름이 생긴다. 방 이름, 커버리지 기하, 미션 필드, 얼굴 모드는 이 결정에 없다.

4. 팔은 `device_type: manipulator`이고 최종 작성자가 따로 있다(D-55). OMX는 `enabled: false`이고 `provides`가 비어 있다. Pinky와 OMX의 합성은 D-71대로 미룬다. 베이스 속도의 최종 작성자는 CORE다. Pinky Pro에는 팔이 없다. 파일럿 안의 OMX 연습은 새 제품이 아니다.

5. 다른 이동 로봇은 `device_type: mobile_base`인 다른 Device와 그 어댑터다. 베이스 속도의 최종 작성자는 같은 CORE다. CORE를 제품 폴더 아래로 복사하지 않는다(D-310).

6. 드론은 비행 스택과 그 최종 actuator 작성자를 확인하기 전에는 폴더도, `device_type`도, 공통 action API도 없다(D-310 결정 5). 그때까지 이름은 비워 둔다.

7. 확장 지점은 Device 매니페스트의 `provides`와 프로필 설치 목록이다. 구동기 가족마다 최종 작성자는 하나다. 베이스 속도는 CORE, 팔은 장치 수용 뒤의 OMX 로컬 제어기, 그 밖은 작성자가 생기기 전에는 이름이 없다. 공통 실행 코드는 같은 일이 실제로 겹친 뒤에만 뽑는다.

8. 이 결정은 폴더, 매니페스트, wire, `RobotMode`, safety 태그 경로를 바꾸지 않는다.

## 기존 구조 결정과의 관계

| 결정 | 관계 |
| --- | --- |
| D-427 | 최상위 폴더를 더하지 않는다. middleware, operations, learning 배치는 그대로다. |
| D-429 | 다섯 관심사와 장치 제어 포트를 옮기지 않는다. |
| D-430 | 안전 체인과 safety 태그 경로를 바꾸지 않는다. 이 변경은 Safety-Review 대상이 아니다. |

## Consequences

유지보수는 구호마다 트리를 나누지 않는 데서 온다. 능력을 더할 때는 `provides` 한 칸이고, 구동기 가족이 새로울 때만 후속 ADR이 최종 작성자를 정한다. 커버리지 미션을 적는 후속은 범위와 순서를 정할 수 있다. 그 후속도 `RobotMode`와 cleaner `device_type`을 만들지 않는다. 바닥을 만지는 구동기와 비행 스택은 하드웨어와 최종 작성자가 있는 뒤의 일이다.

## Verification

비전 문서의 프로필과 제품 경계, 합성 로봇 문서의 제어 경계, D-55, D-71, D-310 결정 5, D-12, D-420의 Proposed 상태, D-427, D-429, D-430, D-721, Pinky와 OMX 어댑터 매니페스트를 대조했다. 코드와 시험은 없다. 장치 수용과 현장 수용은 아니다.
