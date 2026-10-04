# 모델 PC의 고정 평가와 READY 후보 거부 검증

2026-10-04 KST. branch `feat/learning-pipeline-closure`.
실행 source: `d78be83391dccee338c966b1b18e47e4509a9c18`의 선택 소스 archive.
archive SHA-256: `15e5a4924f397e9dcddadafdb60c3696f62d77bc386557332e9c8e3ed16b4f42`.

이 기록은 모델 PC의 실제 데이터·접수 실행과 LOCAL 코드 검증이다.
시스템 timer 설치, 로봇 모델 전달, 정책 주행, ARM64 release, DEVICE/FIELD 수용은 아니다.

## 실행 환경

- 기존 모델 PC Ubuntu 24.04, Python 3.12, PyTorch 2.11.0+cu128.
- RTX 5080 Laptop 16 GB, CUDA 사용 가능 여부 readback. 아래 intake는 CPU 추론이다.
- 기존 학습 checkout·venv와 녹화 원본은 보존했다.
- 새 실행 소스/설정/증거는 모델 PC의 `~/rosy-ml/pipeline-closure-20261004/`에 둔다.
- 로컬 scratch와 원본 결과는 `X:/DevTemp/rosy-learning-audit-20261004/`.
- 모델 PC의 `sudo -n true`는 종료 코드 1. 시스템 model-watch 유닛은 미설치 상태다.

## 고정 평가 세트

학습 데이터셋 `d379-auto-lanes@35eb8bccd7d5fc5dc42dc0498a4638df355a887d4a5562edfc416edeb4158bf7`에
들지 않은 2026-10-01 주행 세션 두 개에서 압축 영상·sidecar·LiDAR로 자동 라벨을 만들었다.

| 항목 | 관측 |
|---|---|
| 평가 세트 | `pinky-heldout-20261001` |
| 내용 SHA | `0260507375e43354aadbdded329c8b5bd21e12fcbd3c4035e97ee3745b389094` |
| frame | 126 (첫 로봇 100, 둘째 26), 제외 0 |
| 학습과 공유 세션 | 0 |
| 라벨 근거 | LiDAR 126프레임, trajectory는 일부 프레임 |
| LiDAR yaw | 180도 기본값; 승인된 lidar_mount record 없음 |
| 카메라 pitch | 세션별 LiDAR fit 12.1도 / 10.8도 |
| 원본 CameraProfile revision | 미확인/null, 임의로 채우지 않음 |

내용 해시를 다시 계산해 버전 폴더 이름과 일치함을 확인했다.
모델 PC의 기존 store에 `evalsets/<name>/<sha>/`로 추가했고 기존 학습 버전은 변경하지 않았다.
일부 overlay를 직접 읽어 LiDAR wall/floor/lane 투영과 규칙 마스크 비교를 확인했다.
이 검사는 전체 126프레임의 독립 사람 라벨 수용을 대신하지 않는다.
보정 provenance가 부족하므로 이 평가 세트를 실물 정밀도 인증으로 사용하지 않는다.

## 기존 후보의 실제 평가

모델 `lane-seg-20261003-c23527f4` (기존 3에폭 smoke 모델):

| 항목 | 관측 |
|---|---|
| replay | 380프레임, visible fraction 0.97632 |
| CPU 추론 p50 / p95 | 41.29 / 51.58 ms (기준 평가 실행) |
| 고정 평가 frame | 126 |
| lane_line IoU | 0.25607 |
| wall IoU | 0.16226 |
| floor IoU | 0.38906 |
| drivable / stop_line IoU | 0 / 0 |
| 배경 제외 mIoU | 0.10458 |
| 학습·평가 세션 비겹침 | true |

기존 val 기록의 lane IoU 0.81924가 이 평가 결과를 대표하지 못했다.
평가 하한이 null인 연구 gate에서는 이 모델도 pass였다. 이를 배포 정확도 합격으로 사용하지 않는다.

## 배포용 평가 요구와 실제 watcher 결과

추가된 `require_eval: true`는 고정 eval_set, 유효한 min_lane_marking_iou,
확인된 학습 데이터셋의 세션 비겹침과 모델/평가 클래스 role 일치를 요구한다.
연구용 기본 gate의 기존 동작은 유지한다.

시험 후보 gate는 lane IoU 0.5, 배경 제외 mIoU 0.3, regression drop 0.01을 사용했다.
이는 초기 shadow 후보 선별용 보수적 목표이며 주행 정확도/물리 안전 인증 기준이 아니다.
기존 모델을 통과시키기 위해 측정값보다 낮게 하한을 내리지 않았다.

1. 실제 `handover.package`로 기존 모델과 일치하는 READY를 생성했다.
2. 실제 `watch.py`가 해시·모델·replay·평가를 실행했다.
3. 모델의 wall role `ignore`와 평가 라벨의 `wall`이 달라 intake fail을 기록했다.
4. 후보는 `models/rejected/`로 이동했다. accepted는 0, 접수 시도는 1, 로봇 전달 루프 진입은 0.
5. 같은 설정으로 재실행했을 때 state JSON SHA가 동일하고 접수 횟수 1을 유지했다.

재실행 state SHA: `779ce0747918a216de0caf2431a3a2578d52acd037706bcab1ce67b29873be3f`.
watcher 종료 코드 0은 정상적으로 후보 거부를 처리했다는 뜻이며 모델 합격이 아니다.

## 코드 검증

- wall role 회귀 RED(`ignore` 대 `wall`) 후 관련 라벨·데이터셋 시험 83 passed, 3 skipped(Windows).
- 배포 gate 신규 7시험 RED 후 intake/watch·파일 예산 시험 137 passed, 6 skipped(Windows).
- 모델 PC 실제 torch/onnx/onnxruntime을 포함한 intake/eval/watch suite **142 passed, 0 skipped**, 기존 deprecation warning 6개.
- 선택 archive는 git metadata를 포함하지 않아 제품 report의 tool_commit은 null이다. source SHA와 archive hash를 위에서 별도로 고정했다.
- 전체 CI/전체 pytest/장치 주행은 실행하지 않았다.

## 다음 확인

수정된 wall 역할로 새 immutable 학습 데이터셋과 후보를 만들고 고정 평가를 통과시켜야 한다.
통과 후보의 accepted 이동·로봇 shadow 상태·rollback, 서비스 설치, provenance 보강은 남아 있다.
OMX 정책 학습, Pinky 행동 정책, Fleet Episode 연계 역시 이번 결과로 완료되지 않는다.
