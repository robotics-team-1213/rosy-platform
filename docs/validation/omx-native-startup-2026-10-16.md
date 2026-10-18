# OMX native 수집 시작 경로 점검

2026-10-16 · [D-770](../adr/D-770-fleet-omx-autonomous-imitation-pipeline.md)

## 실제 설치 source

Fleet PC의 기존 LeRobot Python 환경에서 `inspect.getsource`로 네 메서드를 읽었다.
객체 생성·`connect()` 호출·모터 설정 쓰기는 하지 않았다.
원문과 설치 파일 SHA256은 현장
`~/rosy-test/omx-startup-read-7f5f6c8e3/native-source.json`에 보존했다.

- `OmxFollower.connect()`는 bus 연결·선택적 보정·camera 연결 이후 `configure()`를 호출한다.
- `configure()`는 `torque_disabled()` 안에서 return delay, operating mode와 elbow PID를 쓴다.
- `torque_disabled()`는 기존 torque 상태를 복구하는 방식이 아니라 `finally`에서
  `enable_torque()`를 호출한다. 설정 도중 예외가 나도 이 경로에 들어간다.
- 따라서 이 설치본에서 `connect(calibrate=False)`도 비구동 관측용 연결이 아니다.
  보정 flag는 configure/torque의 부작용을 제거하지 않는다.

현재 카메라는 기존 producer가 소유한다. 수집기에서 `camera.connect()`까지 수행하면
별도 장치 재개방 문제가 생길 수 있으므로 수집 관측은 기존 ROS stream을 구독한다.

## 실제 읽기 전용 register

`register_probe.py`가 이미 허용하던 unicast PING과 READ(0,147)의 응답에서만
startup 관련 필드를 추가 해석했다. 전송 whitelist와 읽는 주소 범위는 같다.
모터 역할은 기존에 확인한 follower by-id 경로로 결정했다.
수정 source `7f5f6c8e3`를 별도 디렉터리에 배치하고 연속 두 snapshot을 읽었다.

| 항목 | 실제 결과 |
|---|---|
| ID / 모델 | 11~13: 1060, 14~16: 1200 |
| torque / hardware error | 여섯 모터 모두 0 / 0 |
| goal minus present position | 여섯 모터 모두 0 raw count |
| operating mode | 11~15: 4, gripper 16: 5 |
| Profile Velocity / Acceleration | 전 모터 0 / 0 |
| Bus Watchdog | 전 모터 0 |
| gripper Goal Current / Current Limit | 1750 / 1750 raw |
| 전후 설정 | 동일 |

원본은 현장 `~/rosy-test/omx-startup-read-7f5f6c8e3/result.json`이다.
goal와 present의 일치는 해당 snapshot에서 pending position 차이가 없다는 뜻이다.
토크 활성화 후 동작, mode 변경의 영향, 물리 stop/간섭 검증을 대신하지 않는다.

## 제조사 문서와 대조

[XL430-W250 control table](https://emanual.robotis.com/docs/en/dxl/x/xl430-w250/)에서
모델 번호 1060과 profile/goal/PID 주소를 확인했다. 이 모델에는 Current Limit과
Goal Current 항목이 없으므로 해당 바이트를 전류 0으로 해석하지 않고 JSON null로 보존한다.
Profile Velocity 0은 제한된 저속 설정이 아니다.

[XL330-M288 control table](https://emanual.robotis.com/docs/en/dxl/x/xl330-m288/)에서
모델 번호 1200, Current Limit/Goal Current, profile과 watchdog 주소를 확인했다.
Bus Watchdog 0은 비활성화다. gripper의 raw 1750은 문서 단위상 1750mA지만,
그 값은 측정·수용된 jaw force나 현재 과제의 허용 부하가 아니다.
watchdog은 통신 패킷 간격을 감시하므로 독립 정지 수단을 대체하지 않는다.

## 검증과 남은 단계

추가 decode 필드와 모델별 미지원 전류 필드에 각각 원격 RED→GREEN을 수행했다.
`7f5f6c8e3`의 probe·기존 hardware observer 관련 25개 시험을 통과했다.
독립 검토에서 watchdog error byte 0xFF의 의미가 -1임을 확인해 두 모델의
0/127/-1 회귀도 RED→GREEN으로 검증했다. 최종 `2e3e2e5c9` 관련 **31개 시험 통과**,
known_failures NEW 0, 독립 재검토에 남은 finding은 없다.
기존 읽기 전용 장치 점유·쓰기 packet 거절 검사를 그대로 통과했다.

자동 시연 수는 여전히 0이다. 다음 구동 구현은 다음 사항을 충족해야 한다.

1. 기존 보정·mode·PID를 보존하고, 수집 시작에서 자동 torque 활성화를 제거한다.
2. 실측한 관절/그리퍼·workspace와 독립 stop이 수용된 hardware owner에만 명령을 맡긴다.
3. 승인된 속도·가속도·출력 제한과 실제 통신 상실 동작을 검증하고 시작 위치를 재독출한다.
4. 관측과 실제 전달 명령·종단·독립 outcome을 함께 기록한 첫 자동 시연을 수집한다.

원본 register의 숫자를 임의로 낮추거나 disabled profile을 활성화하지 않았다.
