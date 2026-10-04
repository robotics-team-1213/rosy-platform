# 기존 Pinky 녹화의 실제 행동 모델 비교

2026-10-04, `feat/learning-pipeline-closure`, 기준 `d47fa97a7` 이후 변경.
[계획](../plans/2026-10-04-pinky-behavior-comparison.md)의 SOURCE/HOST 연구 실행이다.

## 원본과 분리

두 train 녹화 `20260930T163811Z`(1,595프레임), `20260930T171014Z`(2,673프레임)와
독립 eval `20260930T162847Z`(888프레임)를 고정했다. 녹화 목적은 각각
`calib-rerun-pivots`, `calib-all-9dfk-2`, `calib-odom-imu-lidar`다.
명령이 expert 주행 의도를 나타낸다고 인증하지 않는다. train/eval에 두 로봇이 포함되며
카메라 identity/calibration이 미확인이라 rig 일치와 장치 간 일반화를 주장하지 않는다.

Dataset revisions는 train
`5348e98bb7ab58d5fc638fb82bf5f66574ba9087a019e9b9ce417ad9efe14dc5`,
`ec59a9d7dd1e5aa224580d4ecefb08a959f977a85dbffcac474d805ee4aa9aac`, eval
`caf2018eef21ad47cf2c651bbe9b232cd27ee6db4e57fc9c610a1d8de8a80162`다.
각 입력에서 MCAP 검증기를 직접 실행하고 학습 후 전체 파일 closure를 재검사했다.
same Dataset/Episode/session뿐 아니라 MCAP 원본 해시 중복도 거부한다.

최초 eval 후보 `20260930T172711Z`는 scan 2,986개 중 1개의 angle geometry가 바뀌어
검증 실패로 제외했다. 학습 평가 수치를 보기 전 제외했으며 기준을 완화하지 않았다.
보존된 `pinky-excluded-session-172711.json`에 두 기하와 발생 시각을 기록했다.

## 실제 실행 결과

Python 3.12 CPU, torch 2.7.1, numpy 2.2.6, OpenCV 4.12.0.88.
seed 42760, stride 4, CNN 40 steps, ridge penalty 10을 사전에 고정했다.
train 1,068프레임, eval 222프레임. eval은 이동 명령 66/정지 명령 156프레임이다.
moving은 기록된 |v| > 0.01m/s 또는 |w| > 0.05rad/s이며 실제 움직임 판정이 아니다.

| 모델 | 전체 MAE m/s | 전체 MAE rad/s | 이동 MAE m/s | 이동 MAE rad/s |
|---|---:|---:|---:|---:|
| zero 기준 | 0.005405 | 0.011712 | 0.018182 | 0.039394 |
| train 평균 기준 | 0.005428 | 0.011875 | 0.018193 | 0.039502 |
| RGB ridge | 0.005961 | 0.020714 | 0.018307 | 0.046772 |
| 작은 CNN | 0.005484 | 0.018356 | 0.018211 | 0.043778 |

두 학습 모델 모두 zero보다 오차가 크다. CNN의 정지 구간 angular 출력 절대 평균은
0.007600rad/s로 불필요한 출력도 남았다. 작은 40-step 연구의 결과이며 모델 계열
전체의 불가능성을 증명하지 않는다. 평가를 보고 steps/seed를 튜닝하지 않았다.
보정 명령을 목적 있는 주행 정답으로 사용할 수 있는지는 추가 검토가 필요하다.

산출물 `X:/DevTemp/rosy-learning-audit-20261004/pinky-behavior-comparison-seed42760-v2/`
에는 config/package/source hash, 원본 검증 3개, split/선택 index, train-only 정규화,
loss 이력, 두 실제 모델, 원본 평가 target/prediction NPZ, 보고서와 file SHA 원장이 있다.
CNN/ridge 저장 후 재로딩 추론을 직접 비교했다. 이전 v1과 그 source snapshot은 보존했다.

## 검증과 남은 조건

- native 학습 시험 7 passed: 실제 3-session MCAP→영상→학습→재로딩→보고서 포함.
- 독립 리뷰 native 7 + CI selector 33 = 40 passed. 원본 재포장 우회와 CI torch
  누락을 수정한 뒤 남은 material findings 없음.
- 독립 산출물 재독출: file 원장 11개 SHA/크기·현재 소스 hash·split 원본 disjoint,
  3 sidecar binding·선택 index·eval target·train-only 평균/std를 확인했다.
  prediction NPZ에서 전체/moving/stop 모든 오차를 재계산해 보고서와 정확히 일치했다.
  학습이나 큰 원본 검증은 중복 실행하지 않았다.
- ownership/import/module/document/folder 구조: 66 passed, 1 skip(호스트 LeRobot 없음).
- 문서/harness 83 passed, 기존 경고 26개. selector는 새 경로 추가 기대값 갱신 뒤 33 passed.
- lint 0 errors/26 기존 warnings. CI dependency/selection 소스만 확인했고 remote CI 미실행.

모든 결과는 `research_only`, `promotion=not_eligible`다. null 카메라 보정을 채워
공통 PolicyArtifact를 만들지 않았다. expert intent/pixel/owner contract/독립 과제 수용,
주행 데이터 다양성, Pilot Episode/Fleet join, 정책 승격·DEVICE/FIELD 증거는 미완료다.
로봇 연결·writer·hold 해제·장치 명령·main merge/push는 하지 않았다. 전체 목표는 active다.
