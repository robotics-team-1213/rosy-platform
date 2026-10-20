# 기존 Fleet PC 장치와 위치 경로 재확인

2026-10-17 KST. 사용자가 기존 Fleet PC·로봇 암·카메라 연결을 지적해 현장 경로를 다시 확인했다. 저장된 이동 로봇 주소 두 개의 접속 실패만으로 현장 장치 전체가 미연결이라고 판단할 수 없다. 충전 브랜치의 진단 시점 HEAD는 `e670b23fd`이며, 아래 장치 관측은 이미 현장에 있던 별도 산출물과 서비스를 사용했다.

## 실제 연결과 관측

| 대상 | 확인한 사실 | 범위 |
|---|---|---|
| Fleet PC | 승인된 키·고정 호스트 검증으로 SSH 접속, 기존 Fleet/Vision/proxy 컨테이너 healthy | 장치별 실행 수용과는 별도 |
| 로봇 암 | OpenRB-150 두 대와 기존 arm/leader/follower USB 별칭 확인 | 두 암 모두의 제어 수용 증거는 아님 |
| 상부·전면 카메라 | 기존 두 producer와 viewer/readiness 사용자 서비스 실행, 기존 뷰어의 두 JPEG GET 모두 200 | 장치를 다시 열거나 새 producer를 시작하지 않음 |
| 카메라 상태 | 조회 시 두 frame 모두 fresh. 상부 UNDEREXPOSED/usable=false, 전면 NORMAL/usable=true | 기존 photometric 판정이며 위치 정밀도·가시성·기구 안전 수용은 아님 |
| 지도 | 활성 `map_v2_fleet` version 5와 `ceiling_north` 설정 확인 | OMX USB preview가 같은 교정 source라는 의미는 아님 |
| 이동 로봇 위치 | 두 대의 저장된 x/y/yaw 관측이 존재하나 약 361,815~361,825초 전 자료 | 현재 접안 위치로 사용할 수 없음 |

지도·source·위치 기록은 Fleet의 기존 SQLite를 읽기 전용으로 열어 필요한 열만 조회했다. 자격 증명은 복호화하거나 출력하지 않았다. 기존 저장 주소의 이동 로봇 SSH/CORE 접속 불가 및 `needs_new_code` 상태는 앞선 별도 관측이며, 암/카메라 연결 부재의 증거로 확대하지 않는다.

## 현재 follower 관절값

기존 ROS 환경(domain 13)의 수동 구독에서 `/omx_commissioning/joint_states` 발행자는 없었다. `/joint_states`는 `joint_state_publisher`가 wheel/caster의 0 값을 발행하는 합성 모델 상태였다. 이를 실제 팔 위치로 취급하지 않았다.

이후 [기존 검증 기록](../omx-physical-feedback-2026-10-15/result.md)의 `7e83db760` 관측 도구를 재사용했다. 기존 follower 별칭에 유일하게 대응하는 by-id 포트만 선택했다. 공개 기록에는 장치 serial과 호스트 주소를 남기지 않는다.

```text
hardware_observer.py --device /dev/serial/by-id/<existing-confirmed-follower> --domain-id 13 --duration 2
```

실행 전 기존 두 도구의 SHA-256을 대조했다.

- hardware_observer.py: `4231823a939dc90b04cfe5d22d2222b27d9719aac42b40946f4f04b45fc9edd0`
- register_probe.py: `a9fd080addf0bd1ed12aa54cb873a32b7472b748e498ddd92484271cb9357110`

첫 시도는 camera 전용 환경에 `dynamixel_sdk`가 없어 포트를 열기 전에 exit 2, 0개 관측으로 끝났다. 이미 현장에 빌드된 SDK의 고정 revision `516ae8632c593d7c84afd2bdee2a2fac965305cc`와 tracked source 무변경을 확인하고, subprocess의 PYTHONPATH에만 기존 SDK를 추가했다. 패키지 설치나 서비스 설정 변경은 하지 않았다.

두 번째 실행은 **2초, 19개 관측, exit 0**이었다. 여섯 ID의 모델·torque off·hardware error 0·250ms 이내 read 조건을 통과한 sample만 기존 도구가 발행했다. 마지막 capture UTC seconds는 `1792163979.654607`이다.

| ID | model | raw position | torque | hardware error | 온도 °C |
|---|---|---|---|---|---|
| 11 | 1060 | 2068 | 0 | 0 | 37 |
| 12 | 1060 | 763 | 0 | 0 | 35 |
| 13 | 1060 | 3141 | 0 | 0 | 33 |
| 14 | 1200 | 3196 | 0 | 0 | 24 |
| 15 | 1200 | 3153 | 0 | 0 | 24 |
| 16 | 1200 | 2015 | 0 | 0 | 24 |

관측기는 종료됐으며 상시 관절 서버로 전환한 것이 아니다. PING/READ whitelist와 exclusive port를 사용했다. 설정·torque·reboot·goal 쓰기, controller 시작, 카메라 서비스 재시작은 하지 않았다. raw position/명목 rad는 TCP·jaw·영점·기구 한계 보정을 대신하지 않는다.

## 충전 목표에 적용

기존 지도·카메라·장치 reader를 재사용한다. 새로운 위치 정보를 만드는 대신 해당 source의 원본 capture/교정/boot/odom 결속과 현재성을 확인한다. 상부 카메라 시야·광학과 이동 로봇의 새 지도 관측, 실제 충전기/BMS/착좌 입력은 여전히 별도 확인 대상이다. 이번 기록은 연결과 bounded 물리 피드백을 입증하며 자동 접안·충전·이탈 수용은 입증하지 않는다. 목표는 계속 ACTIVE다.

상세 비공개 진단 기록: 저장소 밖 `C:/DevTemp/station-charge/existing-site-hardware-2026-10-17.md`. 공개 설명의 도구 동작은 [OMX 실행 안내](../../../deploy/robot/omx/README.md)를 따른다.
