---
module: situation
owner: SITUATION
last_verified: {commit: 3627ec21fb, date: 2026-10-28}
gates:
  SOURCE:
    state: GO
    evidence: 사실 전용 서비스의 순수 규칙·분석기 suite(operations/situation/test)가 원격 시험 PC에서
      green. 모델 추론·ROS·cmd_vel은 이 모듈에 없다(D-630·D-516).
    cmd: python tools/remote/remote_pytest.py --log-dir "$env:TEMP/rosy-situation-registered-green" -- operations/situation/test -q
  LOCAL:
    state: HOLD
    blocker: AI PC 루프백 서비스로서의 연속 운영·재시작 관찰은 별도다(현재는 Fleet 분포에 3개 순수
      파일만 설치되어 소비자가 섀도 운영).
  ROS-SIM:
    state: N/A
  ARTIFACT:
    state: HOLD
    blocker: AI PC 설치·버전 고정 산출물 검증은 별도.
  DEVICE:
    state: HOLD
    blocker: 장치 연결 경로 없음 — 활성화 시 별도.
  FIELD:
    state: HOLD
    blocker: D-516에 따라 AI PC의 현장 경로는 아직 활성화되지 않았다.
adrs: [D-630, D-652, D-577]
---
