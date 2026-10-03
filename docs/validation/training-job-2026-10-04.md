# 모델 PC 재시작 가능한 학습 job 검증

2026-10-04 KST. 기존 [영상 라벨 초안](recorded-video-review-2026-10-04.md)과
[후보 비교](perception-model-comparison-2026-10-04.md)의 후속이다.
새 영상 초안을 정답으로 사용한 추가 학습은 아니다. 기존 immutable 자동 라벨
데이터로 stored dataset → GPU → ONNX → strict intake → READY를 검증했다.
harvest/catalog/검수/build의 자동 연결은 아직 별도 작업이다.

## 입력과 소스

- 학습 데이터: d379-auto-lanes-v2,
  `a302ec2d53b248c32b60a8cc8c2ce9ec40080cb1b264c1324d6205efcf9abc79`.
  5세션, 630프레임(train 548/val 82).
- 고정 평가: pinky-heldout-20261001,
  `0260507375e43354aadbdded329c8b5bd21e12fcbd3c4035e97ee3745b389094`,
  126프레임. 학습 세션과 비겹침. 기존 gate를 완화하지 않았다.
- Linux CUDA 모델 PC, torch 2.11.0+cu128, enhanced recipe,
  AdamW/weighted CE+Dice/조명 증강, 30에폭, batch 16, lr 0.0003.
- source snapshot은 d78be8339 archive와 후속 helper 복사본이다. `.git`이 없어
  intake tool_commit은 null이다. state.json에 실행한 8개 소스 SHA를 남겼다.
  최종 train_job.py SHA는
  `bfdee3b35d527713ac6c5ef6309a48e517bc73bf116ecfa8fbaa0a9f7aa3f344`,
  job_state.py SHA는
  `20381e3550f69bb2540475b47cb4b3a69979f1dd75fc479e8e788317c0d95c7b`.
- camera provenance accepted=false. 역사적 CameraProfile과 LiDAR yaw 승인은
  확인되지 않았다. 고정 평가는 기하 자동 라벨이며 사람 검수된 정답이 아니다.

## 실행 결과

명령: `python training/train_job.py <config.json> --out <job-dir>`.
설정과 raw 기록에는 실제 호스트 경로가 있어 공개하지 않았다.

| job | 관측 결과 |
|---|---|
| seed42707-base8 | GPU 학습/export 후 intake 호출의 Store 객체 인자 오류. READY 없음. 소스 수정 뒤 새 job 사용 |
| seed42707-base8-v2 | GPU 잠금 점유 중 첫 시도 거절. 잠금 해제 후 train attempt 2 성공, export attempt 1. mIoU 0.4917로 champion 하락 한도 초과, terminal rejected, READY 없음 |
| 같은 rejected job 재실행 | 즉시 거절. train attempt 2/intake attempt 1 유지. 추가 학습/접수 없음 |
| seed42705-base16 | train/export/intake/ready 각 attempt 1, outcome ready. 실제 CUDA 학습과 ONNX 평가 통과 |
| 같은 base16 job 재실행 | 각 attempt 1 유지. READY 존재와 ONNX SHA 확인. 추가 GPU 학습/접수 없음 |

통과 모델 `lane-seg-20261004-ed0f9e71`의 고정 평가:

| 항목 | 값 |
|---|---:|
| lane_line IoU | 0.724265 |
| wall IoU | 0.829824 |
| drivable IoU | 0.001485 |
| foreground mIoU(lane_line/wall/drivable) | 0.518525 |
| 비교 champion mIoU(a5516fd6) | 0.514864 |
| replay 프레임 / NaN 프레임 | 380 / 0 |
| 모델 PC intake CPU p50 / p95 | 42.24 / 51.74 ms |

지연은 모델 PC intake 수치이며 Pi 실측이 아니다. 이전 별도 2-thread 비교와
측정 조건도 동일하다고 주장하지 않는다. stop_line/crosswalk는 학습 coverage가
없으며 drivable 성능은 부족하다. 벽 개선만으로 전체 주행 성능 개선을 확정하지 않는다.

canonical inbox 폴더는 `<revision>__seed42705-base16`이며 READY를 마지막에 썼다.
ONNX SHA:
`ed0f9e71e8eb800ef8312643a2c955fcd58da8c6ae4654b2386e7e0da50994db`.
자체 고정 intake report SHA:
`25a6bf5e2a83c01c5142b7410f8184228cf5d292ee035aa2c385ad59dfc64e8b`.
이 새 후보의 watcher accepted 이동과 장치 전달은 이번 실행에서 수행하지 않았다.

## 시험과 보존

job 상태/READY 회복 신규 10시험: Windows와 모델 PC 모두 통과.
Windows 기존 handover와 합친 18시험 통과. 중단 후 재개, 파일 변조,
입력 변경, 단일 작성자, terminal reject, 부분 복사, accepted 이동,
공유 intake 보고서 변경 후 자체 증거 유지 등을 확인한다.
단위시험의 ONNX 바이트는 구조 검증 fixture이며 실제 추론 증거는 위 GPU 실행이다.
최종 job/handover/문서 배치/폴더/모듈 구조 관련 Windows 시험은 66 passed,
1 skipped. harness generate 완료, lint 0 errors/기존 26 warnings.

모델 PC `~/rosy-ml/pipeline-closure-20261004/`에 job/config/evidence를 보존했다.
raw proof bundle은 `evidence/training-job-proof.tar.gz`, SHA:
`cefeeebca6882857ed2df01517d4fd6f636a632a4b4437fc8b2d89d5194b86c4`.
로컬 사본: `X:/DevTemp/rosy-learning-audit-20261004/training-job-evidence/`.

새 job은 로봇 명령이나 watcher를 실행하지 않는다. 기존 operator hold,
shadow/active 슬롯을 바꾸지 않았다. system timer 설치, 수집부터의 자동화,
검수된 물체/신호 라벨 학습, 장치 shadow/rollback, OMX/SIM/Fleet 정책 연결과
DEVICE/FIELD 수용은 남아 있다. 전체 목표는 active다.
