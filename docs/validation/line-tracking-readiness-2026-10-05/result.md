# 실기 라인트래킹 준비 상태와 재생 평가

- 날짜: 2026-10-05. 판정: **차선 유지 주행 HOLD**.
- 요청: 실기 상태 확인, 영상 재생, 그림자 비교, 짧은 제한 주행 평가.
- 수행: 인증된 SSH 읽기, ROS 구독·parameter 조회, 호스트 녹화 재생. 장치 설정 변경·서비스 재시작·모델 승격·주행 명령은 실행하지 않았다.
- 호스트 재생 source: `55bf54363` (`docs/line-tracking-readiness` 시작점). Python 3.14, NumPy 2.5.3, OpenCV 5.0.0.93.
- 두 장치 설치 release: `2026.10.05-038`, source `ca1484c5b4bceb954e79d265fdf744c86a81fb4a`. 호스트 후보와 설치 source가 다르므로 호스트 결과를 설치 장치의 동일 결과로 취급하지 않는다.

## 실기 읽기 결과

초기 상태 snapshot은 03:56 UTC, 최종 ROS 구독은 04:06 UTC에 각각 장치당 약 10초 수행했다. 구독기는 발행자를 만들지 않았다. native runtime의 ROS domain, Cyclone DDS 설정을 적용한 뒤 실제 메시지 수신을 확인했다. 첫 기본 DDS 설정 구독에서 메시지가 없었던 것은 진단 설정 문제였으며 카메라 장애로 판정하지 않았다.

| 항목 | 8kcn | 9dfk |
|---|---|---|
| 초기 상태 | IDLE, line follow OFF, UNDOCKED | IDLE, line follow OFF, UNDOCKED |
| E-Stop / calibration / swarm | 모두 false | 모두 false |
| 초기 배터리 | 100%, 충전 아님 | 92.36%, 충전 아님 |
| 최종 camera/front | 80 frames, 320×240 bgr8, stamp 증가 | 80 frames, 320×240 bgr8, stamp 증가 |
| CAMERA_LINE | 80/80 visible, 마지막 error −0.190 | 80/80 visible, 마지막 error +0.232 |
| IR_LINE | 200 samples, 미보정·visible false | 201 samples, 미보정·visible false |
| cmd_vel | 500 samples, 최대 절대 v/w 모두 0 | 500 samples, 최대 절대 v/w 모두 0 |
| 학습 모델 그림자 | 9 shadow / 10 status samples | 구독 기간 status 수신 없음, shadow 비활성 설정 |

`line/observation`에는 카메라와 IR 출처가 함께 발행된다. 마지막 payload가 미보정 IR이라고 해서 카메라가 선을 보지 못하거나 IR 모드가 활성이라고 판단할 수 없다. 출처별로 분리해 위 수치를 얻었다. `visible=true`는 검출기의 자기 판단이며 사람이 확인한 정확도나 주행 성공률이 아니다.

두 장치의 observer parameter는 `camera_lane_mode=line`, `paint_source=threshold`, `camera_ground_source=PINKY`, `allow_nominal_ground=false`, `lane_half_width_m=0.0925`, `lane_corner_turning=false`였다. 따라서 아래 호스트 `keep` 재생 후보가 실기에서 활성이라는 증거는 없다. `keep_debug` topic은 광고되었지만 메시지를 받지 못했다.

8kcn의 signed 모델 `lane-seg-20261003-6e2e5640`은 `last_error=null`, 누적 `skip_ratio=0.0041`, latency p50 238.977 ms를 보고했다. 마지막 shadow에서 learned error −0.812, rule error −0.185, delta −0.627이었다. 이는 같은 정지 장면에서의 판단 차이이며, 어느 쪽이 맞는지는 독립 정답이 없어 UNKNOWN이다. 정지 상태의 짧은 추론은 사람 운전과 비교하는 R1이나 지속 성능 수용을 대신하지 않는다. 기존 모델 hold 표식은 해제하지 않았다.

## R0 재생

입력은 기존 `data/perception/frames/real-drive-1/frames`의 148 JPG 원본 프레임이다. 세션 기록은 `20260930T124745Z`, 8kcn raw camera이며 새 주행에서 얻은 데이터가 아니다. 실행 명령:

```powershell
python tools/lane_replay.py --frames data/perception/frames/real-drive-1/frames --crop none --detectors line,between,keep --out X:/DevTemp/lane-ready-20261005/replay-real-drive-1
```

| 검출기 | 비가시 비율 | 목표-선 위 비율 | paint 위 비율 | 튐 비율 |
|---|---:|---:|---:|---:|
| line | 0.014 | 0.253 | 0.158 | 0.007 |
| between | 0.243 | 0.170 | 0.062 | 0.007 |
| keep | 0.095 | 0.172 | 0.060 | 0.014 |

역사적 직진 비교 범위인 첫 36프레임에서 `line` 평균 절대 error는 0.295611, `between`은 34개 가시 관측의 0.012735, **현재 keep은 34개 가시 관측의 0.150088**이었다. error는 검출기의 정규화된 조향 오차이며 물리 거리나 각도 단위가 아니다. [D-378](../../adr/D-378-real-drive-errors-and-autonomy-gates.md)의 평균 절대 오차 ≤0.08 관문을 현재 keep이 통과하지 못한다. 목표-선 위 비율과 튐 조건만 충족했다고 전체 R0 PASS로 표시하지 않는다. 비가시 프레임의 독립 정답, 추가 곡선·교차로 수용도 미검증이다.

[2026-09-30 기록](../real-drive-2026-09-30/result.md)의 keep 0.074를 현재 결과로 재사용하지 않았다. 진단용으로 현 코드에 옛 source `662a5c6c`의 nominal profile만 주입해 다시 재생했으나, keep 평균 절대 error는 33개 가시 관측의 0.150242였다. profile 교체만으로 역사적 성능이 재현되지 않는다. 알고리즘·의존성·입력 처리 중 어떤 변화가 원인인지는 아직 UNKNOWN이다. 옛 profile을 장치에 복원하거나 후보를 임의 조정하지 않았다.

## 다음 평가 실행 조건

1. 동일 148프레임 및 첫 36프레임을 고정하고, 당시 source와 현재 source의 검출·전처리·의존성을 비교해 회귀 원인을 좁힌다. 가시성·곡선·교차로에는 사람이 확인한 정답과 추가 녹화가 필요하다.
2. 수정 후보의 관련 테스트와 D-378 R0 관문을 통과시키고, 시험 source와 실기 설치 source를 맞춘다. `between`의 작은 직진 오차 하나만으로 후보를 교체하지 않는다.
3. 현장 사람이 수동 운전하는 R1에서 프레임·사람 조향·rule/learned 판단을 함께 기록한다. 이번 정지 그림자 관측은 R1 주행 비교가 아니다.
4. R2는 [D-344](../../adr/D-344-pilot-assisted-autonomy.md)의 현장 진행 버튼과 신선한 hold lease, L1 이상 조건에서만 수행한다. 시작 위치·비상 정지·시험 시간·중단 조건을 확인한 뒤 짧은 구간부터 평가한다. 시간 만료 스크립트가 사람이 누르는 hold를 대신하지 않는다.

현장 진행 조작자가 없다는 사용자 답변과 현재 R0 실패 때문에 요청한 제한 주행은 **NOT_RUN**이다. 주행 성공률·이탈 거리·완주 시간은 측정하지 않았다. 실기 자동 라인트래킹 가능 판정, 모델 PC 처리 파이프라인 구현 완료, 배포·현장 수용을 이 기록으로 주장하지 않는다.

## 원본 증거

원본 위치는 공개 저장소 밖 `X:/DevTemp/lane-ready-20261005/`이다. private network 정보와 raw 영상은 커밋하지 않는다. 아래 SHA-256 manifest로 상태 JSON·probe·replay 입력 및 출력의 바이트를 확인한다. scratch 경로는 영구 보관을 보장하지 않으며 삭제되면 재현용 재수집이 필요하다.

| 파일 (원본 위치 기준) | SHA-256 |
|---|---|
| `observe.py` | SHA256: `5c5af3ca639df83782ba4641c9187777b7c050fb35e7757a5a8bd4cd72adb4e5` |
| `live-collect.py` | SHA256: `6a94537907801d34f03b0df96c2ba83edb8616a39f15ab23751db1e63b62450f` |
| `profile-comparison.py` | SHA256: `739211da5bcb1b3660dbcd3f9f5cfc7f69ae9d29c3ea7ee3a469fa720ed0ab1d` |
| `profile-comparison.json` | SHA256: `f98d9c745b95f5cdc17daa568738f855ede8692da4bf5377dc983a50274ca828` |
| `rosy-pinky-8kcn-readiness.json` | SHA256: `7942e13e3ff086b52dc118114a752b5e20cffa2b73352f150648618b5e1e8e13` |
| `rosy-pinky-9dfk-readiness.json` | SHA256: `02aefd4453c197d7de0a1a85bc5b5e87085633bfa97c88ec8d304d237bf4bc9a` |
| `rosy-pinky-8kcn-observe.json` | SHA256: `b134675106bef54279ec5d6440d45790f608e7339162d0af235f6f1c7109c186` |
| `rosy-pinky-9dfk-observe.json` | SHA256: `44b5b2ddaf70d8ae905628531785c0b652130b45186b91ebe4230229cac74d5b` |
| `rosy-pinky-8kcn-live.png` | SHA256: `989f5905ca937e8fa39577d91358a0690391a4a4e504b2c78ea5c683979abdd3` |
| `rosy-pinky-9dfk-live.png` | SHA256: `b1ef0863d3c4b8c22f66ebace8dd7fb894605c6fc531e6bc55f6649077cc67f2` |
| `replay-real-drive-1/frames.json` | SHA256: `bd1074850374eaef62fe0ae941283b0e9224d785bf8f807231691266d1c65b8c` |
| `replay-real-drive-1/metrics.json` | SHA256: `deb19e5335e45ecfbfe9b6104dac6f894a57c13a864797ef06d92314a413a04d` |
| `input-frame-sha256.json` | SHA256: `434435faeb90d4a1f232000359e4783562c329b87bae09b1d160d14e2f17e9db` |
