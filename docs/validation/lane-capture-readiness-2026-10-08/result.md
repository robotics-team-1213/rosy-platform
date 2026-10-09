# 차선 추종 증거 수집 준비 (2026-10-08)

기준 코드: `d447a776f` 위의 `feat/lane-capture-proof` 후보. 장치 관찰은 설치 릴리스 `2026.10.08-053`에 대한 읽기 전용 SSH 및 짧은 ROS topic 구독으로 얻었다. 장치 설정과 주행 명령은 바꾸지 않았다. 검사 스크립트와 출력은 `X:/DevTemp/lane-goal-20261008/`에만 둔다.

## 목표와 수용 기준

목표는 직선·굽이·한쪽 선 소실·벽/분기에서 같은 물리 경계를 따라가는지 재생, 감독 관찰, 실기 순서로 확인하는 것이다. 프레임별 경계 ID, 선 소실 원인, 재출현 여부를 사람이 판정하고, 불확실하면 STOP을 유지한다. 장치 주행 수용은 D-378의 R0→R1→R2 단계와 CORE 단일 `cmd_vel` 경계를 따른다.

## 현재 관찰

- 10/6 두 세션은 전진 주행 양성 예가 아니다. 10/7 두 세션은 전진했지만 기존 MCAP에는 `line/keep_debug`, TF, 승인된 카메라 보정 revision이 없다. 검수 전 초안은 정답이 아니다.
- 읽기 전용 장치 확인: 두 로봇의 CORE와 카메라 서비스가 실행 중이었다. `rosy_26`의 5초 표본에서 `line/keep_debug` 39개를 받았고 모드는 `keep`, 지면 출처는 `NOMINAL`이었다. 같은 표본의 명령 선속도·각속도 최대 절댓값은 모두 0이었다. 이 수치는 승인된 보정이나 주행 합격 증거가 아니다. `rosy_60`은 `line` 모드여서 같은 토픽 메시지가 없었고 원본 카메라 프레임은 있었다. 확인에는 `X:/DevTemp/lane-goal-20261008/sample_capture_readiness.py`를 SSH stdin으로 실행했다.
- 이번 변경은 Pilot MCAP에 네임스페이스 TF와 전역 `/tf`, `/tf_static` 구독을 추가한다. 실제 게시 여부, 프레임과 자세 시각 정합, 지도 자세, 카메라 보정 revision은 아직 확인되지 않았다. 따라서 지도 투영 라벨 게이트(D-481 §3의 6·7)는 열린 상태다.
- 검증 명령: `python -m pytest middleware/perception/test/test_pilot_recorder.py -q -rfE -p no:cacheprovider` → 39 passed; `python test/known_failures.py X:/DevTemp/lane-capture-proof/run.txt` → 0 new; `python tools/harness/rosy_harness.py lint` → 오류 0, 기존 경고 23.

## 다음 증거

1. 10/7 전진 구간에서 연속 프레임의 경계 ID·가림·재출현을 사람이 검수한다. 10/6 회전 구간은 음성/혼동 사례로 분리한다.
2. 감독자가 있는 새 R0 녹화에서는 원본 프레임, odom, `line/keep_debug`, TF와 각 토픽의 실제 메시지 수·시각 범위를 확인한다. 보정 revision이나 지도 자세가 없으면 이유를 기록하고 지도 투영 초안은 만들지 않는다.
3. 동일한 직선·굽이·한쪽 선 소실 사례로 프레임 연속 미검출과 잘못된 경계 연결을 측정한다. 재생과 R1 shadow가 통과해야 R2 hold-to-run을 검토한다. 현장 녹화 주행·배포는 단계별 사용자 승인과 운영자 입회 후 진행한다.

관련 근거: `docs/validation/lane-1007-source-proof-2026-10-08/result.md`, `docs/validation/lane-fallback-sim-2026-10-08/result.md`, `docs/validation/lane-network-projection-2026-10-08/result.md`, D-378, D-475, D-481.
