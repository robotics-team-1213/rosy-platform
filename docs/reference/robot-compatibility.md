# 로봇 호환성과 검증 상태

기종을 추가할 때는 기체 프로파일·드라이버·배포 이미지·실물 검증을 각각 확인한다. 이 목록에 이름이 있다는 이유로 실행 가능한 기체나 수용 완료 기체가 되지는 않는다.

## 호환 목록

| 기종 | 컴퓨터·구성 | 현재 소스/프로파일 | ROSY 이미지·실물 근거 | 분류 |
| --- | --- | --- | --- | --- |
| Pinky Pro | 기존 Raspberry Pi 5 구성 | `middleware/devices/pinky`, 실행 모델 `pinky_pro` | [배포 안내](../deployment/pinky-pro-first-device-runbook.md)와 해당 모듈의 SOURCE/ARTIFACT/DEVICE/FIELD 기록을 각각 확인 | 기존 구현 대상 |
| OMX | 독립 팔 또는 기체와 조합한 구성 | `middleware/devices/omx`; joint/action owner는 어댑터 | 시뮬레이션·실물 경로와 장치별 수용 증거를 구분. 이 표가 실물 활성화를 승인하지 않음 | 기존 구현 대상 |
| Adeept RaspTank Metal / ADR034 | 우선 Raspberry Pi 4B 4GB, Ubuntu Server 24.04 arm64 + ROS 2 Jazzy 목표 | [`rasptank_metal` 설정 패키지](../../middleware/devices/rasptank/profile/AGENTS.md) 소스 준비. I/O·실행 드라이버 없음 | 공식 Ubuntu 순정 이미지와 ROSY 통합 이미지는 별개. native 설치·실기 부팅·주행·팔·정지 수용 미수행 | **무구동 소스 준비 / 실행 미지원** |
| DJI Neo 2 | 제조사 기체·조종 경로. ROSY 설치 대상 없음 | 공식 SDK 미지원 확인. ROSY 어댑터·실시간 관측 연결 없음 | [2026-10-25 공식 지원 조사와 재검토 조건](../deployment/multi-device-onboarding.md#dji-neo-2-판정). 직접 설치·SDK 제어·실물 수용 없음 | **SDK 제어 미지원 / 추적 대상** |

RaspTank의 Pi 5 장착도 제조사 지원 범위지만 ROSY의 Pi 5 조합 수용을 뜻하지 않는다. 보유 Pi의 RAM, HAT 버전, 카메라와 전원 회로를 확인한 뒤 프로파일을 고정한다. 제조사 상품 페이지와 배포 PDF의 HAT 버전 표기가 달라 실물 대조가 필요하다.

후속 범위와 검증 조건은 [RaspTank 공통 ROSY 통합 설계](../plans/2026-10-25-rasptank-multi-robot-design.md)에 기록한다. 이 설계도 실행 package·통합 이미지·실물 승인 완료를 뜻하지 않는다.

제조사 근거: [RaspTank Metal 상품](https://www.adeept.com/adeept-rasptank-metal-smart-robot-car-kit-for-raspberry-pi-5-4b-3b-3bboard-not-included-tank-tracked-robot-with-4-dof-robotic-arm-opencv_p0436_s0100.html), [공식 배포 자료](https://www.adeept.com/learn/detail-85.html), [고정 소스](https://github.com/adeept/Adeept_RaspTank_Metal/tree/e60a17a59185a86abfdd67828364185c4011bb22).

## 다른 로봇이 같은 ROSY를 쓰는 방식

다기종의 직접 설치형·외부 SDK 연결형 분류와 기종 접수표는
[다기종 배포 준비](../deployment/multi-device-onboarding.md)를 따른다.
단계별 후속 작업은 [다기종 배포 설계](../plans/2026-10-25-multi-device-deployment-design.md)에 기록한다.

[HWA-001/002/003과 CAP-003](../spec/ROSY%20CORE%20SRS.md)은 로봇별 하드웨어를 프로파일과 드라이버 어댑터로 격리하고, 기능 선언과 미지원 명령 거절을 요구한다. [D-14](../adr/D-14-.md)의 경계를 재사용한다.

- **공통 계약:** identity·인증·상태·이벤트·명령 식별/만료·결과 추적·capability 협상·관제/Pilot·업데이트/복구.
- **기체별 프로파일:** 장치 구성, 설치 패키지, 확인된 센서, 좌표계·실측 치수·보정값·속도/관절 범위.
- **기체별 어댑터:** 실제 버스·드라이버·출력 변환·관측과 정지. Pinky의 Dynamixel과 RaspTank의 DC 모터/서보 PWM을 동일한 하드웨어로 취급하지 않는다.

CORE의 [프로파일 로더](../../contracts/foundation/core_common/profile.py)는 모델 기반으로 기체 설정을 찾는다. 그러나 [CORE의 경로 선택](../../middleware/core/gateway/core/node.py)은 절대경로 profile/capability가 있으면 모델 조회를 우회하며 기존 시험도 이 동작을 보존한다. RaspTank 제품 활성화 전에는 선택 모델·설치 package·프로파일·기능 선언의 일치를 별도로 검증해야 한다. 후보 이름만 바꾸고 Pinky의 절대경로 파일이나 capability를 재사용하지 않는다. Base 최종 명령은 CORE의 단일 소유권을 유지한다. 팔·집게의 동작 owner는 기존 장치 Action/Arbiter 경계와 [D-856](../adr/D-856-application-action-boundary.md)을 따라 별도로 통합해야 한다.

[rosy.controls/1](../../contracts/foundation/core_common/protocol/controls.py)은 제어 종류·단위·제한을 공통으로 표현한다. 같은 UI를 쓴다는 것은 실제 제공하는 제어만 표시한다는 뜻이다. 검증되지 않은 주행·지도 이동·팔·집기 기능을 숨기고, 미지원 호출은 명확히 거절한다. 모델별 예외 분기를 관제 화면에 늘리는 방식으로 어댑터를 대신하지 않는다.

## RaspTank에서 아직 광고하면 안 되는 기능

- 운전 가능한 로봇 모델: `rasptank_metal`은 설정만 있는 무구동 소스 패키지다. 속도 한계 0, teleop/SLAM/이동/복귀/군집/도킹 false, 수용된 센서 없음으로 시작하며 팔·집게 제어를 광고하지 않는다. [모듈 상태](../../middleware/devices/rasptank/profile/progress.md)의 native 설치·이미지·실물 증거가 필요하다.
- 검증된 m/s 주행과 odometry: 제조사 코드의 PWM throttle은 실측 속도가 아니다. encoder·위치 추정·궤도 선회 보정 경로를 확인해야 한다.
- 관절 측정과 파지 완료: 서보에 보낸 명령이나 경과 시간은 관절·물체의 측정 근거가 아니다. 기존 gripper descriptor의 readback 의미와 맞지 않으면 광고하지 않는다.
- 지도 주행·복귀·군집·자동 집기: 센서·실행 경로·통신 실패 처리·기체 수용을 기능별로 검증해야 한다.
- 안전 제어용 차체·팔 모델: 현재 조사용 URDF는 추정 시각화 모델이며 물리 제어·충돌 안전용으로 등록할 근거가 없다.

## 이미지와 펌웨어

부품·카메라/센서 연결 조사, 내려받은 순정 이미지, SD 준비 및 도착 후 순서는
[RaspTank Pi 4 준비서](../deployment/rasptank-pi4-preparation.md)에 정리한다.

공통 운영 기반은 [D-161](../adr/D-161-ubuntu-server-native-ros-runtime.md)의 Ubuntu Server 24.04 arm64 + Jazzy + systemd다. 같은 OS 기반을 쓴다는 것이 동일한 기체 패키지·overlay·드라이버·SD 이미지를 그대로 복제한다는 뜻은 아니다.

RaspTank는 먼저 no-motion 프로파일·장치 인식부터 검증하고, 실제 HAT의 단일 writer·명령 만료·전원·독립 정지와 팔 동작을 단계적으로 확인한다. Pi 4의 부트 EEPROM은 실제 revision·현재 버전과 공식 요구사항을 확인한 뒤 판단한다. 제조사 제어 Python은 HAT에 flash하는 firmware 이미지가 아니다.

호환성 승격에는 최소한 코드·패키지 설치 closure, 이미지 서명/해시, 카드 readback·실기 부팅, 보정·독립 정지와 재시작 무구동, 기능별 실물 근거가 필요하다. 기존 Pinky 이미지에 RaspTank 이름을 추가하는 것만으로 승격하지 않는다.
