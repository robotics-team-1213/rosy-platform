# 학습 recipe 및 모델 폭 비교

2026-10-04 KST. 소스 `d003262b3`의 recipes.py와 trainer hook.
외부 기준: [pinky-lane-segmentation](https://github.com/now2466/pinky-lane-segmentation/tree/443f63fd4a5f6a4929775cecbda01c7b0a4557fe).
이전 [GPU 기준 학습](learning-gpu-2026-10-04.md)의 낮은 고정 평가 성능에 이어 수행했다.

## 비교 조건

동일한 6-class 데이터 `a302ec2d53b248c32b60a8cc8c2ce9ec40080cb1b264c1324d6205efcf9abc79`,
548 train / 82 val, seed 42704, batch 16, 30에폭, 동일한 최고 val 에폭 복원과 ONNX export.
모델 PC CUDA 12.8 / torch 2.11.0+cu128 / RTX 5080 Laptop에서 GPU run을 순차 실행했다.
고정 평가 126프레임 `0260507375e43354aadbdded329c8b5bd21e12fcbd3c4035e97ee3745b389094`는 유지했다.
모든 후보에서 학습·평가 세션 비겹침과 role 일치를 확인했다.

기준은 Adam lr 0.001 + CE, 개선 recipe는 AdamW lr 0.0003 / weight decay 0.0001,
weighted CE + masked foreground Dice 0.3 + 밝기/대비 증강이다.
mask geometry와 255 제외를 유지하고, 관측되지 않은 클래스의 정답을 만들지 않는다.
여러 학습 조건을 함께 바꾼 비교이므로 효과를 특정 손실이나 증강 하나의 공으로 분리하지 않는다.

## 실제 결과

| 모델 | revision | lane IoU | wall IoU | 배경 제외 mIoU | ONNX bytes | CPU p50 / p95 ms | intake |
|---|---|---|---|---|---|---|---|
| 기준 base16 | `lane-seg-20261004-72799466` | 0.21407 | 0.45484 | 0.22902 | 7,773,729 | 47.02 / 50.98 | fail |
| 개선 base16 | `lane-seg-20261004-a5516fd6` | 0.79448 | 0.74968 | 0.51486 | 7,773,729 | 41.21 / 51.22 | pass |
| 개선 base8 | `lane-seg-20261004-f21a7a97` | 0.76222 | 0.75105 | 0.50522 | 1,952,379 | 16.96 / 18.91 | pass |

require_eval의 기존 lane IoU 0.5, mIoU 0.3, champion 대비 mIoU 하락 0.01 기준을 유지했다.
base8의 champion 비교 하락은 0.00964로 0.01 경계에 가깝다.
단일 seed 결과이며 여러 seed/독립 세션에서 순위의 안정성은 미검증이다.
두 pass는 실제 intake가 후보 폴더를 복사한 결과다. canonical store의 accepted 이동,
READY watcher, 로봇 shadow 전달과 장치 실행까지 완료했다는 의미는 아니다.

CPU 값은 다른 학습/접수 작업이 끝난 뒤 3개 모델을 순차 실행해 얻었다.
동일한 고정 평가 126개 영상 프레임을 미리 읽고 모델별 5회 warm-up,
ORT CPU threads 2 / spinning false로 infer(전처리+추론+evidence)를 측정했다.
동일 구조인 두 base16의 p50 차이는 이 실행의 관측이며 학습 recipe의 속도 개선으로 해석하지 않는다.
Pi/ARM64 지연은 측정하지 않았다.

## 클래스 개선의 남은 공백

개선 base16의 drivable IoU는 0.00042, base8은 0.00241로 여전히 낮다.
lane와 wall의 선별 합격을 모든 클래스나 주행 안전의 합격으로 사용하지 않는다.
stop_line/crosswalk의 충분한 학습 정답도 없다. 신호등·물체 클래스는
[클래스 개선 설계](../plans/2026-10-04-perception-class-expansion-design.md)에 따라
box/ROI 상태 라벨과 별도 precision/recall 평가를 확보해야 한다.
기존 자동 라벨의 임시 보정·미검증 yaw 한계와 독립 현장 평가 필요는 유지한다.

현 단계 후보: 인식 정확도 비교는 base16, 연산 제약이 있는 shadow 비교는 base8.
주행 활성화나 신호에 따른 자동 명령은 이번 비교로 승인되지 않는다.

## 코드 시험과 증거

- 외부 원본 suite 17 passed. 실행 torch 2.11이며 외부 pyproject의 2.9.1 pin 환경 수용은 아니다.
- recipe 시험 5 passed: 라벨·geometry 보존, 255 loss/gradient 제외, 유한 gradient,
  정답 없는 batch/foreground 거절, 기존 trainer hook 연결.
- 기존 training_model 시험 19 passed. Windows 문서·학습 계약 57 passed / 3 skipped.
- 파일 예산 시험 1 passed; harness lint 0 errors / 기존 verification warning 26개.
- 초기 wrapper/시험 fixture 오류를 수정해 재실행했고 모델 수치를 그 오류 실행에서 얻지 않았다.

모델 PC `~/rosy-ml/pipeline-closure-20261004/runs/lighting-dice-base{16,8}-20261004-seed42704/`
및 evidence에 config/summary/epoch 로그, weights, ONNX와 intake 결과를 보존했다.
각 config는 실행 시점의 recipes.py / rosy_lane_model.py SHA-256을 기록한다.
이 파일들은 위 소스 커밋과 같은 내용이다. source_commit 필드는 실행 당시 미커밋이었다는
사실을 유지하며 사후 실행으로 꾸미지 않는다.
로컬 `X:/DevTemp/rosy-learning-audit-20261004/`의 recipe-base16/8-intake-report.json,
recipe-base16/8-config.json, model-comparison-cpu.json과 train-recipes.py,
compare-model-cpu.py가 원본 실행 증거다.

전체 CI/서비스 설치/DEVICE/FIELD 수용은 실행하지 않았다. 전체 목표는 active다.
