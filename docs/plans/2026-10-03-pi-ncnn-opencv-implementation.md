# Pi NCNN/OpenCV Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Ultralytics에서 학습한 YOLO 모델을 재학습 없이 NCNN으로 변환해 라즈베리파이 물체 검출에 사용하고 기존 OpenCV/NumPy 영상 처리와 배포·롤백 계약을 유지한다.

**Architecture:** 기존 `run(float32 NCHW) -> ndarray` 경계 아래 NCNN 어댑터를 추가한다. 명시적 backend가 있는 모델 manifest로 ONNX/NCNN을 선택하며 기존 모델은 ONNX로 읽는다. 물체 검출을 먼저 적용하고 자체 차선 모델은 독립 검증 후 판단한다.

**Tech Stack:** Python, Ultralytics/PyTorch(학습·변환 PC), NCNN Python binding(ARM64 기기), OpenCV, NumPy, pytest, 기존 서명·intake·deliver 도구.

---

## 범위와 현재 상태

- 결정: [D-431](../adr/D-431-pi-ncnn-models-with-opencv.md) Accepted. D-423의 YOLO export 목표만 부분 개정한다.
- 계획 등록만 완료. 아래 작업은 모두 미착수이며 NCNN export, 기기 설치·추론·승격은 실행하지 않았다.
- 작업 순서: T0 → T1 → T2 → T3 → T4 → T5 → T6. T7은 물체 검출 완료 후 별도 실행한다.
- 현 소스 경로를 아래에 사용한다. D-427 구조 이전이 먼저 진행되면 실행자가 실제 reader와 패키지 설치 경로를 대조하고 계획 경로부터 갱신한다. 별도 복사본을 만들지 않는다.
- 전용 worktree에서 작업하고 작은 작업별 커밋을 남긴다. 스크래치·환경·로그·임시 모델·테스트 cache는 `X:/DevTemp/rosy-ncnn/<run-id>/`에 둔다. 학습 모델은 git에 넣지 않는다. 공개 증거에는 기기 주소·인증 정보를 넣지 않는다.

## T0: 실제 모델과 비교·기기 기준 고정

**Files:** 참조 `tools/perception/model/intake_gate.yaml`, `tools/perception/model/convert.py`, `src/runtime/sensing/control/sensing/perception/learned/{manifest,detector,lane_mask}.py`; 생성 `docs/validation/pi-ncnn-<YYYY-MM-DD>/README.md`(실행일의 증거 요약).

1. 대상 `.pt` hash, YOLO family/version/task, 클래스 순서, 데이터·카메라 revision, 실제 카메라 평가 프레임 목록/hash를 확보한다. 모델이나 프레임이 없으면 준비 작업을 계속하되 실제 변환·정확도 판정은 보류한다.
2. 기기의 ARM64 OS/Python/CPU/RAM, 기존 `cv2`·NumPy 버전, NCNN binding 배포 가능성을 읽기 전용으로 확인한다. 현재 모델의 ONNX 기준선을 보존한다.
3. 기존 물체 검출 입력은 H=256/W=320, BGR 카메라 → RGB, scale=1/255, mean=0/std=1, grey pad=114, `INTER_AREA`, confidence=0.25/IoU=0.5다. 대상 모델에서 이 전처리와 `[1,4+C,A]` raw-head 출력을 실제 확인한다. 지원하지 않는 family/end-to-end 출력은 이 경로에서 명시적으로 거부한다.
4. 시험 전에 raw-output atol/rtol, confidence 차이, 상자 IoU·클래스 일치, 평가셋 정확도 허용 감소, p50/p95 지연·RSS·CPU 예산, 평가 프레임 수·운전 부하를 수치로 기록한다. 실측 뒤 합격하도록 기준을 옮기지 않는다. 객체 노드의 2 Hz 상한은 처리 목표의 근거이지 deadline 보장이나 합격 증거가 아니다.
5. bench 부하 시험은 예열 후 30분, CORE·카메라·센서 병행 조건으로 계획한다. 온도·스로틀링과 출력 누락·NaN/오류도 기록한다. 주행 권한 변경 없이 검출 shadow로 시험한다.

**완료 조건:** 모델과 평가셋, 지원 출력 계약, 변환/runtime 버전 후보, 기기 시험 기준이 기록돼 다음 작업의 입력으로 재현 가능하다.

## T1: backend와 NCNN 묶음의 manifest 계약

**Files:** 수정 `src/runtime/sensing/control/sensing/perception/learned/manifest.py`; 시험 `src/runtime/sensing/test/test_learned_manifest.py`, `test_learned_manifest_object_det.py`; 생성 `src/runtime/sensing/test/test_learned_manifest_ncnn.py`.

1. 먼저 실패 시험을 작성한다: 기존 backend 없는 manifest는 ONNX로 해석; NCNN은 param/bin 모두 요구; unknown backend·중복/경로탈출 파일명·누락/변조·blob 이름 누락을 거부한다.
2. `python -m pytest src/runtime/sensing/test/test_learned_manifest_ncnn.py -q`로 새 계약의 실패를 확인한다.
3. 기존 `rosy.perception.model/1` reader와의 호환을 설계한다. 구현 첫 단위에서 새 schema/version과 backend 필드 정책을 확정한다. 오래된 reader가 NCNN을 잘못 수락하지 않는 시험을 포함한다. backend-specific artifacts, blob 이름, family/version, precision, 전처리·출력 계약, exporter/runtime 버전을 검증한다.
4. SHA256 검증과 서명 대상 manifest에 모든 추론 파일/필수 metadata를 넣는다. `.onnx`의 단일 파일 선택을 NCNN에서도 호출하지 않게 한다.
5. 위 세 시험 파일을 함께 실행해 새 NCNN과 기존 ONNX 계약을 통과시키고 변경 파일만 커밋한다.

**완료 조건:** 기존 ONNX 폴더가 계속 열리고 불완전·변조된 NCNN 묶음은 로더 전에 거부된다.

## T2: NCNN 추론 어댑터와 OpenCV 처리 보존

**Files:** 생성 `src/runtime/sensing/control/sensing/perception/learned/ncnn_session.py`, `src/runtime/sensing/test/test_learned_ncnn_session.py`; 수정 `learned/detector.py`, 필요시 `learned/runner.py`; 시험 `test_learned_detector.py`, `test_learned_runner.py`.

1. 실패 시험으로 입력 float32 NCHW의 shape/연속성, CHW 변환, 출력 배치축 복원, blob 선택, 유한값·출력 계약 검증을 고정한다. RGB 채널별 값이 다른 이미지와 직사각형 이미지로 색상/축/letterbox 오류를 검출한다.
2. `python -m pytest src/runtime/sensing/test/test_learned_ncnn_session.py -q`로 실패를 확인한다.
3. NCNN을 lazy import하고 CPU thread 수·GPU 비활성·계산 precision을 명시한다. `run(x)`는 이미 전처리된 입력을 받으므로 BGR 변환·1/255를 다시 적용하지 않는다. NCNN API가 반환하는 오류 코드를 검사하고 load/extract 실패를 `ManifestError`로 전달한다.
4. backend factory를 `ObjectDetModel.open()`에 연결한다. 기존 `letterbox()`, `preprocess()`, 디코딩·NMS·좌표 복원을 유지한다. family에 맞지 않는 출력은 warm-up에서 거부한다.
5. NCNN이 설치된 PC에서 실제 작은 NCNN fixture로 입력/출력 시험을 실행한다. binding 없는 환경에서 건너뛴 시험은 통합 증거로 집계하지 않는다. detector/runner 회귀를 별도 실행하고 커밋한다.

**완료 조건:** NCNN 실추론이 기존 검출 결과 형식으로 나오며 전처리가 한 번만 적용되고 기존 ONNX·차선 로더가 동작한다.

## T3: `.pt` → NCNN export와 동등성 확인

**Files:** 수정 `tools/perception/model/convert.py`, `tools/perception/test/test_model_convert.py`; 생성 `tools/perception/model/compare_backends.py`, `tools/perception/test/test_model_backend_parity.py`; 참조 `tools/perception/training/README.md`.

1. 실패 시험을 작성한다: `--backend ncnn`은 지원 Ultralytics object_det만 허용; 자체 state_dict/차선 모델은 명확히 거부; 변환이나 비교 실패 시 READY/수용 가능한 묶음을 남기지 않는다.
2. 변환 CLI에 `--backend onnx|ncnn`을 추가한다. 이전 호출의 기본은 ONNX로 유지하고 신규 Pi YOLO 절차는 명시적으로 NCNN을 지정한다. `--int8`의 기존 ONNX QDQ 경로를 NCNN에 잘못 적용하지 않게 거부한다.
3. Ultralytics의 NCNN export를 고정 입력 크기·CPU에서 실행하고 생성 param/bin 및 필수 metadata를 staging에서 수집한다. blob 이름은 변환 결과에서 확인하고 가정하지 않는다.
4. 고정 seed 탐침에 더해 T0의 실제 프레임으로 동일 전처리 PyTorch/ONNX/NCNN raw 출력과 최종 검출을 비교한다. finite·shape·클래스/상자/confidence 및 평가셋 정확도 조건을 판정해 실패하면 handover를 막는다. export 지원과 정확도 판정은 실제 대상 `.pt`로 실행한다.
5. `python -m pytest tools/perception/test/test_model_convert.py tools/perception/test/test_model_backend_parity.py -q`를 실행한다. 실제 export와 비교 실행 결과·hash를 증거 요약에 기록하고 커밋한다.

**완료 조건:** 실제 학습 모델의 변환과 수치/검출 비교가 통과하고 `.pt` 재학습 없이 검증된 NCNN 묶음을 얻는다.

## T4: intake·서명·전달·rollback의 종단 연결

**Files:** 수정 `tools/perception/model/{intake,deliver,watch,sign_model}.py`, `tools/perception/rosy_ml.py`, `tools/perception/training/handover.py`, `src/runtime/sensing/control/sensing/perception/learned/{slots,status}.py` 중 backend 가정이 있는 reader만; 시험 `tools/perception/test/test_model_intake_tasks.py`, `test_model_deliver_tasks.py`, `test_rosy_ml_tasks.py`, `src/runtime/sensing/test/test_learned_slots.py`, `test_learned_signature.py`.

1. 실패 시험: NCNN param/bin 전체 전달, missing/altered file 거부, 실패 intake의 전달 거부, 잘못된 작업 슬롯 거부, failed swap의 이전 모델 유지, ONNX↔NCNN rollback, object_det 서명 검증을 작성한다.
2. 명시적 backend로 intake session을 선택하고 현재 READY/불변 store/revision·작업별 서명 규칙을 유지한다. 파일 목록과 hash를 바탕으로 전달하며 backend·runtime 불일치의 doctor 오류를 제공한다.
3. 위 `tools/perception/test` 세 파일과 `src/runtime/sensing/test` 두 파일을 별도 pytest 호출로 실행한다. SSH 대역 시험과 실제 기기 readback을 증거에서 구분한다.
4. 운영자 문서 `docs/deployment/learned-perception-operators.md`와 training README에 NCNN 변환/검증/전달 명령과 오류·복구 절차를 추가하고 커밋한다.

**완료 조건:** NCNN export 결과가 검증·서명·shadow·교체·rollback까지 기존 모델 계약과 함께 연결된다.

## T5: ARM64 의존성과 이미지/payload 설치 경로

**Files:** 수정 `deploy/robot/pinky_pro/image/learned-perception-requirements.txt`, `deploy/robot/pinky_pro/dev/install-learned-perception.sh` 및 실제 learned prefix를 설치하는 image/payload reader; 기존 `test/`의 해당 배포 계약 시험을 검색해 보강한다.

1. T0에서 확인한 OS/Python에 맞는 NCNN binding을 고정한다. wheel이 없다면 빌드 입력/옵션·출력 hash를 재현 가능하게 기록한다. export PC와 기기 설치 목록을 분리한다.
2. NCNN 전용 경로가 torch/ultralytics 또는 pip OpenCV 교체를 요구하지 않는 시험을 먼저 추가한다. 기존 `cv2`/NumPy를 우선하는 learned prefix 규칙을 보존한다. ONNX·차선·rollback에 필요한 기존 의존성은 유지한다.
3. 실제 ARM64 산출물 또는 대상 기기에서 `import cv2, numpy, ncnn`과 실제 모델 load/extract를 확인한다. import 성공만으로 추론 수용을 선언하지 않는다.
4. 이미지/payload 설치 readback에서 버전·파일 hash·backend를 확인하고 설치 실패 복구 절차를 검증한다. 로컬·ARM64 artifact·device 증거를 각각 기록하고 커밋한다.

**완료 조건:** 대상 환경에서 시스템 OpenCV와 NCNN이 공존하고 학습 PC 의존성 없이 검출 모델을 실행한다.

## T6: 라즈베리파이 실측과 물체 검출 승격

**Files:** 생성 `tools/perception/model/bench_backends.py`, `tools/perception/test/test_model_bench_backends.py`; 실행 증거 `docs/validation/pi-ncnn-<YYYY-MM-DD>/README.md`; 갱신 `src/runtime/sensing/progress.md`, `logs.md`(실제 gate가 변했을 때).

1. bench 결과가 warm-up을 제외하고 누락/오류·p50/p95·처리율을 올바르게 산출하며 기준 미충족을 실패로 반환하는 시험을 추가한다. 비교 모델·입력·runtime hash와 CPU/precision 조건을 출력한다.
2. T0의 실제 프레임으로 Pi ONNX/NCNN 정확도와 전처리 포함 지연을 비교한다. 30분 CORE·카메라·센서 병행 shadow 부하에서 RSS/CPU/온도·스로틀링·출력 오류를 기록한다. NCNN이 더 빠르다는 주장도 이 결과로만 한다.
3. 실제 전달→서명 검증→shadow readback→failed swap 보존→ONNX rollback을 시험한다. 검출 evidence와 프리뷰 렌더에서 상자·클래스·좌표가 일치하는지 확인한다.
4. T0의 모든 기준을 만족해야 object_det 승격 후보가 된다. 실패·불명은 기존 ONNX를 유지하고 원인/재시험 조건을 기록한다. 물리 주행이나 차선 활성화는 별도 기존 gate를 따른다.
5. 문서/LOCAL/ARTIFACT/DEVICE/FIELD를 분리해 결과를 기록하고 커밋한다. 데이터가 없거나 핵심 시험이 skip이면 해당 gate는 미확인이다.

**완료 조건:** 실제 기기의 기능·성능·공존·안정성·복구가 증명된 모델만 NCNN 운영 후보가 된다.

## T7: 자체 차선 모델의 독립 NCNN 가능성 평가

**Files:** 참조 `tools/perception/training/rosy_lane_model.py`, `model/export_onnx.py`, `src/runtime/sensing/control/sensing/perception/learned/{runner,lane_mask}.py`; 필요시 생성 `docs/plans/<YYYY-MM-DD>-lane-ncnn-migration.md`.

1. lane_unet의 실제 state_dict/TorchScript 모델을 지원되는 PyTorch→NCNN 변환 경로에서 시험한다. Ultralytics YOLO exporter를 적용하지 않는다.
2. `[1,C,H,W]` 출력, 픽셀별 logits/IoU, lane_marking mask·연결요소·좌표, Pi 지연/CPU/RSS를 기존 ONNX와 비교한다.
3. 기존 차선 활성화·주행 수용 기준과 롤백 증거를 만족하면 별도 이전 계획을 작성한다. 아니면 lane_seg는 ONNX를 유지한다. ONNX Runtime 전체 제거는 차선과 롤백까지 전환된 후 별도 판단한다.

**완료 조건:** 차선에 대한 지원/성능 증거와 진행 또는 보류 결정이 있고 물체 검출의 성공을 차선 수용으로 대체하지 않는다.

## 실행·검증 방법

각 구현 작업은 실패 시험 → 실패 원인 확인 → 최소 구현 → 해당 시험 및 관련 회귀 통과 → 변경 파일만 커밋 순서다. @test-driven-development, @systematic-debugging, @verification-before-completion을 적용한다. 기기 접속 시 저장소의 `rosy-device-access` 지침을 읽는다. 예시 테스트 경로 중 새 파일은 해당 작업에서 생성한 뒤 실행한다.

Windows host 시험은 ROS overlay 대신 아래 환경을 준비한다. PyTorch/Ultralytics/NCNN/ONNX 의존성이 있는 PC 환경에서 실제 변환 시험을 별도로 실행하고 빠진 의존성의 skip을 성공으로 세지 않는다.

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PYTHONPATH = (Join-Path (Get-Location) 'src/contracts/foundation')
python -m pytest tools/perception/test -q -p no:cacheprovider --basetemp=X:/DevTemp/rosy-ncnn/<run-id>/tools-tests
python -m pytest src/runtime/sensing/test -q -p no:cacheprovider --basetemp=X:/DevTemp/rosy-ncnn/<run-id>/sensing-tests
python -m pytest test/test_network_topology_contracts.py test/test_harness_contracts.py -q -p no:cacheprovider --basetemp=X:/DevTemp/rosy-ncnn/<run-id>/doc-tests
python tools/harness/rosy_harness.py generate
python tools/harness/rosy_harness.py lint
```

`<run-id>`는 실행마다 고유한 영숫자로 바꾼다. 서로 다른 suite의 임시 디렉터리를 공유하지 않는다. 위 명령은 구현 후 검증 절차이며 이번 작업의 실행 결과가 아니다. 기기 검증 전 source quick tier와 변경 배포 경로의 계약 시험도 통과시킨다. 릴리스 발행·실기 설치·활성화는 계획 등록으로 자동 실행되지 않는다.
