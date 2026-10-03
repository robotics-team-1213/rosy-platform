## D-431 라즈베리파이 YOLO 추론은 NCNN을 목표로 하고 OpenCV 영상 처리와 학습 모델의 의미를 유지한다

**Status:** Accepted (2026-10-03, 사용자 승인 — 전환 방향을 실행 계획에 반영). 설계 결정의 수용이며 구현·기기 설치·실기 수용은 미완료다. 기존 운영 모델은 이 문서만으로 바뀌지 않는다.

### Context

Ultralytics에서 학습한 `.pt`를 라즈베리파이에서도 같은 학습 모델로 사용할 수 있는지, NCNN으로 내보내면서 OpenCV를 유지할 수 있는지를 확인했다. 가능한 조합이다. OpenCV는 영상 수신·전처리·시각화·마스크 처리 도구이며, 이 경로의 학습은 Ultralytics/PyTorch, 모델 추론은 NCNN이 맡는다. 학습 가중치를 변환해 사용하므로 기기용 재학습은 필요하지 않지만 지원되지 않는 모델 연산이나 출력 형식은 별도 대응이 필요하다. NCNN이 라즈베리파이에 필수인 것은 아니며 성능 우위는 실제 대상 모델로 측정한다.

현재 D-423 §3.3과 `tools/perception/model/convert.py`는 `.pt`를 ONNX로 변환한다. `learned/manifest.py`의 `onnx_file()`, `runner.py`의 `_OrtSession`, `detector.py`의 `ObjectDetModel.open()`은 ONNX에 결합돼 있다. 파일 확장자나 export 인수만 바꿔서는 NCNN을 사용할 수 없다.

OpenCV는 `detector.py:letterbox()`의 크기 조정, `lane_mask.py:preprocess()`의 크기 조정 및 NumPy 색상·정규화 처리, 연결요소·마스크 확대, 카메라 프리뷰 등에서 쓰인다. 이 영상 처리 계약은 추론 엔진과 분리할 수 있다. 현재 물체 검출 출력 계약은 `[1, 4 + C, A]` raw head이며 NMS와 좌표 복원은 Rosy가 수행한다. 모든 YOLO 버전의 출력이 이 모양이라고 가정하지 않는다.

### Decision

1. **라즈베리파이용 Ultralytics YOLO `object_det`의 목표 배포 형식은 NCNN으로 한다.** 학습은 PC/Colab에서 유지하며 지원되는 모델의 `.pt`를 `YOLO(source).export(format="ncnn", imgsz=[H, W], device="cpu")`로 변환한다. 예시이며 현재 Rosy CLI가 지원하는 명령은 아니다. 도구·모델 family/version과 고정 입력 크기를 기록하고 대상 모델로 export 성공을 확인한다. 학습 원본 `.pt`와 ONNX 비교 기준선은 학습 저장소에 보관한다. 모델 파일은 git에 넣지 않는다.
2. **OpenCV와 NumPy 영상 처리는 유지한다.** 흐름은 카메라 BGR 영상 → 기존 letterbox·색상·정규화 → NCNN 어댑터 → 기존 디코딩·NMS·좌표 복원 → 검출 증거·프리뷰다. 어댑터는 기존 session의 `run(float32 NCHW) -> ndarray` 경계를 목표로 한다. NCNN의 CHW 입력·출력 이름·배치/채널 축은 어댑터가 명시적으로 맞춘다. BGR→RGB, `1/255`, mean/std, resize·padding은 한 번만 적용한다. NCNN 픽셀 변환 API를 사용할 경우 기존 전처리와 중복되지 않는 경계를 구현·시험한다. Python 코드 유지가 기본이며 C++ 전체 이전을 요구하지 않는다.
3. **같은 학습 모델과 비트 단위 동일 결과를 구분한다.** 변환은 같은 학습 가중치와 클래스 의미를 이어받는다. 연산 구현·정밀도 차이로 수치와 경계값 검출 결과는 달라질 수 있다. 같은 실제 이미지, 클래스 순서, 색상, 입력 크기, 보간법, 정규화, letterbox, confidence·IoU 설정으로 PyTorch/ONNX 기준선과 NCNN 결과를 비교한다. 어댑터의 축 변환 뒤 raw output 모양·유한값과 수치 차이, 최종 클래스·상자·confidence를 모두 확인한다. 모델 family의 end-to-end/NMS 포함 출력은 기존 raw-head 디코더에 그대로 넣지 않고 지원 여부를 명시하여 거부하거나 별도 계약으로 처리한다.
4. **배포 경로 전체를 형식에 맞게 확장한다.** manifest의 명시적 backend, 모든 `.param`·`.bin` 및 필요한 metadata의 파일명·hash, 입력·출력 blob 이름, 모델 family/version, precision, 전처리/출력 계약, exporter/runtime 버전을 기록한다. 기존 manifest는 ONNX로 읽는 호환 규칙을 정의한다. 검증·서명·intake·READY·deliver·슬롯·상태·doctor·rollback도 NCNN 묶음을 함께 취급하며 `.onnx`를 찾는 하드코딩을 해소한다. 지원되지 않는 backend나 파일 누락·변조·출력 불일치는 활성화 전에 거부한다. 실패한 교체는 이전 모델을 유지한다. D-423의 작업별 서명 규칙을 유지한다.
5. **기기는 NCNN 추론 의존성과 기존 OpenCV를 사용한다.** Ultralytics/PyTorch는 export·비교 도구이며 NCNN 기기 경로의 필수 런타임으로 설치하지 않는다. 대상 ARM64 OS/Python에 맞는 NCNN Python binding의 wheel 또는 재현 가능한 빌드와 버전을 고정한다. 기존 시스템 `cv2`/NumPy와 공존·import·실추론을 확인하며 pip 설치로 시스템 OpenCV를 교체하지 않는다. CPU 경로를 먼저 검증하고 Vulkan·FP16·INT8은 각각 별도 비교 증거 뒤 적용한다. NCNN Runtime 설정에 따른 내부 정밀도도 기록하며 fp32 파일명이 fp32 계산을 보장한다고 가정하지 않는다.
6. **자체 `lane_seg`는 별도 전환 gate를 둔다.** `lane_unet` state_dict/TorchScript는 Ultralytics YOLO가 아니므로 `YOLO(...).export()`를 일괄 적용하지 않는다. 현 ONNX 경로를 유지하면서 해당 모델용 변환·지원 연산·`[1,C,H,W]` 출력·차선 IoU/마스크·지연을 별도로 확인한다. 기기 전체 ONNX Runtime 제거는 두 작업과 롤백 모델의 전환이 검증된 뒤에만 검토한다.
7. **활성화 전에 실제 라즈베리파이 수용 증거를 확보한다.** 대상 기기·OS/Python/ARM64·runtime/model hash를 기록하고 실제 학습 모델과 고정 카메라 프레임으로 로드·추론·정확도 비교, 전처리 포함 p50/p95 지연, 지속 처리율, RSS·CPU·온도·스로틀링, CORE/센서 병행 부하, 장시간 안정성, 실패 교체·롤백을 확인한다. 호스트 intake의 400 ms p50은 기기 성능 기준이 아니다. 비교 허용치와 부하 조건·시험 시간·기기 지연/메모리 예산은 시험 전에 모델별로 고정하고 원본 증거와 함께 기록한다. 요구 처리율과 기존 수용 기준을 만족해야 승격한다. NCNN export 성공이나 호스트 pytest만으로 DEVICE/FIELD GO를 선언하지 않는다. D-137의 자문 검출, D-205의 차선 활성화 순서, CORE의 최종 명령 소유는 유지한다.

### Alternatives

| 대안 | 장점 | 판단 |
|---|---|---|
| ONNX Runtime 유지 | 현재 export·배포·슬롯과 호환, 자체 차선 모델 운영 경로 보존 | 비교 기준선과 이전 기간·롤백 경로로 유지 |
| NCNN 추론 + OpenCV/NumPy 영상 처리 | ARM 지향 추론, 기존 카메라·영상 처리 재사용 | YOLO 물체 검출의 목표 경로로 선택 |
| 기기에 Ultralytics/PyTorch 전체 설치 또는 OpenCV DNN으로 통일 | 고수준 YOLO API 또는 기존 OpenCV 중심 구현 | 첫 경로는 기기 의존성이 커지고 두 번째는 NCNN 로더 전환과 다른 선택이므로 이번 전환안에 포함하지 않음 |

### Consequences

학습 모델을 재사용하고 영상 처리 코드를 유지하면서 추론 엔진을 바꿀 수 있다. 다만 export 변경만으로 완료되지 않으며 backend 어댑터·manifest·공급망·수용 gate가 필요하다. NCNN 형식 자체는 속도·정확도·무오류를 보장하지 않는다. D-423 §3.3의 YOLO 배포 형식 목표를 부분 개정하며 나머지 작업별 모델·서명·슬롯 계약은 보존한다. D-423 전체를 Superseded로 바꾸지 않는다.

### Implementation plan

[2026-10-03 Pi NCNN/OpenCV 실행 계획](../plans/2026-10-03-pi-ncnn-opencv-implementation.md)을 따른다. 물체 검출을 먼저 전환하고 자체 차선 모델은 별도 검증한다.

### Sources and verification

- [Ultralytics NCNN export](https://docs.ultralytics.com/integrations/ncnn): 지원 모델의 `.pt` export와 NCNN inference. 문서 예시의 최신 모델을 Rosy 모델 버전으로 자동 간주하지 않는다.
- [Ultralytics Raspberry Pi guide](https://docs.ultralytics.com/guides/raspberry-pi): ARM 기기의 NCNN 권장과 성능 비교; Rosy 실측을 대체하지 않는다.
- [Tencent NCNN: use ncnn with OpenCV](https://github.com/Tencent/ncnn/wiki/use-ncnn-with-opencv): OpenCV/NCNN 이미지 변환과 색상 순서. C++ 예시는 상호 운용 근거이며 Rosy Python binding 검증 완료를 의미하지 않는다.
- 현재 Rosy `convert.py`, `learned/{manifest,runner,detector,lane_mask}.py`를 2026-10-03 확인했다. 실제 학습 `.pt`의 NCNN export 및 라즈베리파이 추론은 이번 문서 작업에서 실행하지 않았다.

### 2026-10-03 실행 기록

NCNN schema /2, CPU adapter, YOLO exporter와 독립 TorchScript lane exporter, 실제 프레임 parity, intake 검사, 고정 wheel 설치 경로를 구현했다. 실제 차선 `.pt`와 ARM64 기기에서 20프레임 분류가 100% 일치했고 시스템 OpenCV 4.6.0을 유지했다. 다만 해당 차선 모델의 NCNN FP32 p95 474.59ms는 동일 원본 ONNX FP32 252.22ms보다 느렸다. T7의 변환 가능성은 확인됐지만 차선 운영 이전은 보류한다. 학습 YOLO checkpoint·장시간 동시 부하·실제 배포/rollback 수용은 미완료다. 상세 증거: [Pi NCNN 검증](../validation/pi-ncnn-2026-10-03/README.md).
