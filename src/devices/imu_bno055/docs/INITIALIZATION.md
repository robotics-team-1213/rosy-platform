# BNO055 시작 정책

리셋 유무와 관계없이 CONFIGMODE에서 `UNIT_SEL` 0x3B를 0x00으로 명시한다. 이전 실행의 단위 설정을 상속하지 않고 기존 decode 계약(가속도 m/s², 각속도 degrees/s)을 유지한다. 실패하면 fusion 시작 전에 종료한다.

기본 `reset_on_start=false`는 노드 재시작 시 SYS_TRIGGER 소프트 리셋을 보내지 않는다. 로그는 `stage=reset_skipped reason=reset_on_start_false`로 이를 표시한다. 시작 시 chip ID 0xA0 확인, CONFIGMODE 전환, boot 및 system error 확인, normal power 설정, IMUPLUS 전환, fusion 상태 대기는 계속 수행한다. 센서가 없으면 리셋하지 않고 실패한다.

명시적으로 초기화를 다시 해야 할 때만 ROS 매개변수 `--ros-args -p reset_on_start:=true`를 사용한다. 이 경로는 CONFIGMODE 이후 SYS_TRIGGER 0x3F/0x20을 쓰고, I2C 접근 없이 700ms 기다린 후 제한 시간 내 boot를 확인한다. boot/system error/fusion 대기 제한은 각각 2/3/5초이다. 이 시간은 반복 확인의 사용자 공간 제한이며 커널의 단일 I2C 호출 중단을 보장하지 않는다.

2026-09-09 장치 관측에서 처음 시작한 프로세스는 유효 샘플을 보냈으나 후속 시작에서 reset 직후 chip boot NACK가 발생했다. 이는 reset과 시간상 연관된 관측이며 원인 확정이나 기본 경로의 실장치 성공 증명은 아니다. 기본 경로에서도 후속 단계 오류는 숨기지 않고 종료하며, 센서 읽기 오류를 0 샘플로 발행하지 않는다.

`test/test_driver_faults.py`는 LD_PRELOAD 가상 버스로 기본 경로의 무리셋, 명시적 리셋 성공과 리셋 후 NACK 제한 종료, 기존 칩 부재/fusion 지연/불완전 읽기를 검증한다. 실행에는 Linux ROS 빌드 산출물 `BNO055_TEST_EXECUTABLE`이 필요하다. 가상 버스 결과와 실제 장치 수신 결과는 별도로 기록한다.

## 실제 장치 확인 — 2026-09-09

ARM64 빌드, 샘플 단위/유효성 검사, cppcheck·CMake·형식 검사, 오류 주입 10개가 통과했다. 전원을 완전히 껐다 켠 뒤 무리셋 경로에서 약 100Hz로 1,657개를 받았다. 이어 서비스를 다시 시작해도 20초간 2,001개, 최대 수신 간격 0.0204초, 마지막 연속 읽기 오류 0을 확인했다. Quaternion norm²는 0.99994–1.00006, 중력 크기는 9.60–9.71m/s²였다. 이는 해당 관측 구간의 초기화·재시작 성공 증거이며 장시간 내구성 검증을 대신하지 않는다.
