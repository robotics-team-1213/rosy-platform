# 모델 PC GPU 재학습과 고정 평가 거절

2026-10-04 KST. 이전 기록: [고정 평가와 READY 거부](learning-pipeline-2026-10-04/result.md).
실행 소스는 동일한 `d78be83391dccee338c966b1b18e47e4509a9c18` archive다.
기존 원본·라벨·데이터셋을 덮어쓰지 않고 새 버전을 추가했다.

## 실행과 데이터

두 실험 모두 실제 모델 PC의 PyTorch 2.11.0+cu128, CUDA 12.8,
RTX 5080 Laptop에서 `cuda:0`로 실행했다. nvidia-smi에서 학습 PID와
GPU 메모리 점유를 확인했다. LaneUNet, Adam, 30에폭, lr 0.001,
batch 16, seed 42704이며 학습·검증 세션을 분리했다.
최고 검증 mIoU 에폭의 가중치를 복원한 뒤 CPU ONNX로 내보냈다.

| 실험 | 데이터 내용 SHA | train / val | 모델 revision |
|---|---|---|---|
| 원래 두 세션 재라벨 | `6f2698c14a9f1e7429965f523c93d32189b1c06f1703e667fca150fdedf49f7d` | 126 / 278 | `lane-seg-20261004-db184963` |
| LiDAR 세션 보강 | `a302ec2d53b248c32b60a8cc8c2ce9ec40080cb1b264c1324d6205efcf9abc79` | 548 / 82 | `lane-seg-20261004-72799466` |

두 버전은 `d379-auto-lanes-v2` store에 저장했다. 평가 세트
`0260507375e43354aadbdded329c8b5bd21e12fcbd3c4035e97ee3745b389094`는
변경하지 않았고 build의 exclude-eval과 intake의 disjoint=true를 확인했다.

첫 실험의 학습 마스크에는 lane/drivable만 있고 floor/wall은 검증 세션에만 있었다.
픽셀 집계로 이 문제를 확인했다. 세션 hash 분할의 비어 있는 split 보충 규칙 때문에
두 세션에서는 LiDAR 세션이 val이었다. 다른 세션을 보강한 뒤 그 세션은 train이 되었다.
보강 버전은 두 로봇의 총 5개 세션이며 train/val 모두 floor/lane/wall/drivable을 포함한다.
stop_line/crosswalk 학습 근거는 없어 해당 인식 성능을 주장하지 않는다.

LiDAR가 없는 원래 주행 세션에는 같은 로봇의 학습용 LiDAR 세션에서 새로 얻은
pitch 11.5도를 사용했다. 다른 LiDAR 세션은 각 세션 fit을 사용한다.
원본 CameraProfile null을 고치지 않았다. 별도의 provisional-camera.json과 해시를
학습 provenance로 기록했으며 accepted=false, LiDAR yaw 기본값 미검증을 명시했다.
이 해시는 승인된 장치 보정 revision을 대신하지 않는다.

## 고정 평가 결과

동일한 require_eval gate와 lane IoU 0.5 / 배경 제외 mIoU 0.3 하한을 유지했다.

| 모델 | 최고 검증 에폭 | 복원 모델 val lane IoU | 고정 평가 lane IoU | 고정 평가 mIoU | intake |
|---|---|---|---|---|---|
| 두 세션 | 4 | 0.34521 | 0.2109 | 0.1494 | fail, exit 1 |
| 세션 보강 | 28 | 0.87604 | 0.21407 | 0.22902 | fail, exit 1 |

보강 모델의 고정 평가 floor IoU 0.34496, wall 0.45484, drivable 0.01816.
126프레임의 nonfinite는 0, 클래스 role 불일치는 없었다.
검증 성능 상승이 고정 평가의 차선 성능으로 이어지지 않았다.
이 관측만으로 영상 분포 차이와 자동 라벨 차이 중 원인을 확정할 수 없다.
다음 분석은 세션별 예측·마스크·보정 근거 비교이며 에폭 증가만으로 해결됐다고 보지 않는다.
고정 세트를 반복 선별에 사용했으므로 이후 최종 수용에는 별도 독립 평가가 필요하다.

## 증거와 남은 작업

모델 PC `~/rosy-ml/pipeline-closure-20261004/`의 runs, evidence와
로컬 `X:/DevTemp/rosy-learning-audit-20261004/`에 실행 스크립트,
config/summary/epoch 로그, 픽셀 분포, intake 보고서를 보존했다.
로컬 증거 파일은 wall-v2-config.json, wall-v2-summary.json,
wall-v2-intake-report.json, wall-v2-expanded-config.json,
wall-v2-expanded-summary.json, wall-v2-expanded-intake-report.json,
train-mask-distribution.json, expanded-mask-distribution.json이다.
첫 실행 wrapper의 잘못된 데이터 로더 인자를 수정했고, 실패 디렉터리는 보존한 채
새 run ID로 재실행했다. 모든 실험은 train/eval 이후 모델 전달 없이 종료했다.

이 기록은 실제 GPU 학습·CPU 접수 거절 증거다. 서비스 timer 설치,
accepted 모델의 shadow 전달·rollback, OMX/Pinky 행동 정책, Fleet Episode 연계,
DEVICE/FIELD 수용은 여전히 미완료다. 전체 목표는 active다.
