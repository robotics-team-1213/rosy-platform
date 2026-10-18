# OMX 환경 원본의 native 데이터·학습 연결 — 2026-10-17

## 구현과 소스 검사

`a1485deeb`의 첫 구현은 native 환경 원본 보존·검토·학습 연결을 추가했다.
독립 리뷰에서 기존 inspection 보고서의 분할 호환성과 fresh flag만으로 알려진 조건을 집계하는
문제를 확인했다. `7260e1563`에서 기존 보고서는 명시적인 unrecorded로 정규화하고,
실제 producer의 source stamp·sequence·age·v3 수치를 확인하도록 수정했다. 반복 프레임은
알려진 영상 조건 수를 늘리지 않는다. 비유한 수치·부분 JSONL·중복 키·시각 역행·run/profile
혼입·겹치는 창·원본/요약/coverage 불일치를 거부한다. 별도 verify도 모델 적재 전에 재검증한다.

초기 모듈 부재 RED와 후속 경계 RED2건, 영상 metadata/overflow RED7건을 확인했다.
`7260e1563` 관련82개 원격 검사가 통과했다. 원격 runner의 test PC에서 실행했으며 laptop
pytest는 실행하지 않았다. NEW0, known0, flaky0이다. log는 외부 scratch의
`environment-binding-verified/run-1.txt`에 보존했다. 이 묶음은 실제 장치 시험이 아니다.

## 실제 LeRobot·ACT 왕복: 합성 fixture

`0a9954c5f9`의 `test/test_omx_lerobot_integration.py`를 Model PC의 기존 분리된
LeRobot0.4.4 CPU 환경에서 실행해1개 통과, skip0을 확인했다. 기본 환경 경로를 사용한
첫 실행은1개 skip이었다. 실제 설치 경로를 명시해 재실행한 결과와 구분한다.

검사는 공식 LeRobot writer로 합성3episode/12frame을 만들고, 합성 환경 원본을 CLI로 seal한 뒤
실제 reader로 inspect했다. 사람 판정 필드도 synthetic-test fixture이며 실제 사람 검토가 아니다.
train/eval/test를 episode·session·cycle별로 나누고 train 통계가 eval을 포함하지 않음을 검사했다.
공식 ACT trainer2step 뒤 새 process에서 model/preprocessor/postprocessor를 다시 읽고 eval4frame을
평가했다. 원본 환경 bytes·SHA·검토·분할·학습·평가 coverage 보존과 별도 재적재를 검사했다.

외부 scratch `environment-lerobot-real/run-1.txt`에 실행 증거를 보존했다. 실행은
`tools/remote/remote_pytest.py -- <isolated-python-env> test/test_omx_lerobot_integration.py -q -rA`이며
환경 marker는 `ROSY_OMX_LEROBOT_PYTHON`이다. 계정별 실제 경로는 공개 문서에 넣지 않는다.
실제 물체·로봇 시연·환경별 성공률·실데이터 학습 증거가 아니다.

## 실제 camera-only 원본의 형식 검증

별도로 Fleet에서 기존 닫힌 camera probe의 원본 `environment.jsonl`을 읽었다.
source는 `0a9954c5f9`의 pure offline `native_environment.py`다.
Source SHA-256: `f4abb1fab447cb59d5c61a68c24e278912f97a4ff23c30b313606f70abf0f03f`.
원본82015bytes,37event를 검증했고 읽기 후 그대로였다.
Original log SHA-256: `303ca702973cc2880271f3a71709f50c2ace44eb709abd4028a619598a1834cb`.

| 역할 | 확인된 새로운 영상 조건 이벤트 | 확인 불가/중복 |
|---|---|---|
| top | UNDEREXPOSED33 | UNKNOWN4 |
| front | UNDEREXPOSED12, NORMAL20, LOW_SPATIAL_SIGNAL4 | UNKNOWN1 |

이는 변경 이벤트 집계이며 프레임 수·시간 coverage·과제 성공률이 아니다. 원본은
[이전 camera-only 실행](../omx-environment-readiness-2026-10-17/result.md)의 관측이다.
Fleet private `~/rosy-test/omx-environment-lineage-0a9954c5f9/`에 원본 사본·소스·receipt를 보존했다.
episode 창을 만들거나 실제 시연으로 변환하지 않았다. bound episode0, 실제 시연0이다.
현재 camera service나 제어 설정을 바꾸거나 팔을 움직이지 않았다.

## 남은 완료 조건

이 구현은 원본 bytes와 선언된 시간 창의 내부 일관성을 검사한다. 서명된 진위·물체 가시성·
센서 exposure 동기화·연속 readiness를 입증하지 않는다. 실제 recorder의 시간 창 발행,
환경 저하와 기존 owner HOLD/stop 연결, 강조도/역광/가림 실물 수용과 첫 실제 시연 데이터·
학습·독립 실물 평가는 남아 있다. [D-770](../../adr/D-770-fleet-omx-autonomous-imitation-pipeline.md)의
실제 데이터 완료 기준을 축소하지 않는다.
