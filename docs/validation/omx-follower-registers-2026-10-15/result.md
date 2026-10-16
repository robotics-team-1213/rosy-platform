# OMX follower 식별과 읽기 전용 모터 확인

2026-10-15, `feat/omx-hardware-server`. 앞선 [native 준비](../omx-hardware-control-preparation-2026-10-15/result.md)의 후속이다.
사용자가 우측 follower, 기존 USB 별칭과 물리 케이블의 일치, 전원 연결 및 현장 감독을 확인했다.
실제 serial 식별자·주소는 공개하지 않는다.

## 실행과 관측

현장 private overlay의 고정 DynamixelSDK Python 소스로 PING과 READ만 수행했다.
송신 경계에서 다른 instruction을 거부하고, 포트 사용자 검사와 exclusive open을 사용했다.
모터 설정 변경, reboot, torque 변경, 이동 명령은 보내지 않았다.
6개 모터 모두 통신 및 장치 오류 0, torque 0이었다. 아래 값은 한 번 읽은 시점의 raw 값이다.

| ID | model | firmware | operating mode | position | homing offset |
|---|---|---|---|---|---|
| 11 | 1060 | 50 | 4 | 2056 | 0 |
| 12 | 1060 | 50 | 4 | 719 | 0 |
| 13 | 1060 | 50 | 4 | 3181 | 0 |
| 14 | 1200 | 53 | 4 | 3203 | 0 |
| 15 | 1200 | 53 | 4 | 3167 | 1024 |
| 16 | 1200 | 53 | 5 | 2015 | 0 |

모두 drive mode 0, position min/max 0/4095였다. 이는 측정된 기구 안전 한계가 아니다.
원문은 비공개 X: 세션 `2026-10-15--042252--inference-integration--f27cbc`의
`logs/follower-readonly-registers.txt`, 실행 스크립트는 `scratch/follower-readonly-registers.py`에 있다.

## 발견한 초기화 충돌

고정 vendor xacro는 ID 12와 13의 operating mode를 3으로 바꾸고 각각 830..3129,
1024..3140의 position limit을 쓴다. 관측 위치 719와 3181은 이 범위 밖이다.
다른 drive mode·gain·profile 설정도 초기화 시 달라진다.
`DynamixelHardware::on_init`은 `InitTorqueStates`, `InitItem`, 간접 read/write 항목 설정을 실행하며,
`InitDxlComm`의 장치 오류 처리에는 reboot도 있다. `on_activate`만 막아서는 무쓰기 시작이 아니다.

따라서 기본 vendor launch를 실행하지 않았다. 무동작 준비를 명목으로 실제 plugin을 초기화하지 않는다.
현장 측정 profile과 명시적인 설정 이행 절차, 독립 정지 시험을 준비한 뒤 서버를 연결해야 한다.
기존 현재 자세와 homing offset을 보존하며, 명목 URDF/EEPROM 범위로 안전 한계를 대체하지 않는다.

## 남은 범위

이 확인은 USB 역할 및 현재 register 상태에 한정된다. 실물 controller 서버·단일 owner 연결,
기구 한계·jaw·TCP 측정, 물리 정지/복구, Fleet/Pilot 운용과 딸기 왕복은 미완료다.
읽기 전용 도구나 테스트 통과를 제어 서버 완성으로 보고하지 않는다.
