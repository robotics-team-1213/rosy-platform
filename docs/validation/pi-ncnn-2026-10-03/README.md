# D-431 NCNN/OpenCV 구현 및 Pi 재생 검증

2026-10-03, `docs/d431-ncnn-opencv`에서 실행. 설계 수용과 운영 수용은 별개다.

## 찾은 입력과 판정

- 실제 학습 모델: 저장소의 `data/drive/0930_best_model.torchscript.pt`.
  SHA-256 `19050e80754720a7f4b9e4a4724d5f53a145370668d3a5850544e1ed7339c782`.
  YOLO 물체 검출 모델이 아니라 4종 차선 분할 TorchScript 모델이다.
- 실제 녹화 영상에서 20프레임을 추출했다. 최종 제품 어댑터 재생의
  프레임 hash는 [device-product-replay.json](device-product-replay.json)에 기록했다.
- 저장소·다운로드·검증 작업 폴더 검색에서 Rosy 6종 클래스의 학습 YOLO 체크포인트는 찾지 못했다.
  YOLOv8n 6종 미학습 fixture로 Ultralytics export와 NCNN 실행 경로를 시험했으며,
  그 결과를 물체 검출 정확도나 기기 수용으로 사용하지 않는다.
- 기존 기기의 차선 ONNX에는 QDQ 노드 110개가 있다. manifest의 fp32 선언과 달리
  INT8 그래프였다. 최초 INT8 대 NCNN FP32 비교와 아래 동일 원본 FP32 비교를 구분했다.
  기존 모델·서비스·pointer는 변경하지 않았다.

## 실제 결과

| 검증 | 관측 |
|---|---|
| PC TorchScript → PNNX NCNN FP32, 20프레임 | 최대 logits 차이 0.00003815, 분류 픽셀 일치율 100% |
| ARM64 동일 원본 ONNX FP32 대 NCNN FP32, 20프레임 | 최대 logits 차이 0.00004363, 분류 픽셀 일치율 100% |
| ARM64 NCNN FP32 전처리 포함 지연 | p50 461.54ms, p95 474.59ms |
| ARM64 ONNX FP32 전처리 포함 지연 | p50 239.69ms, p95 252.22ms |
| 제품 `LaneSegModel.open/infer`, warm-up 5회 후 20프레임 | 오류 0, p50 447.84ms, p95 462.60ms, 2.21Hz |
| 제품 재생 자원 관측 | CPU 146.56% (2 threads), 종료 RSS 322,777,088 bytes, 종료 온도 68.85°C |
| 기존 OpenCV/NumPy | 기기 시스템 OpenCV 4.6.0, NumPy 1.26.4 그대로 사용 |

Pi는 aarch64/Python 3.12.3이다. NCNN `1.0.20260526` ARM64 wheel을 기기의 별도
`/tmp` 검증 경로에 `--no-deps`로 설치했다. torch/Ultralytics/pip OpenCV는 기기에 설치하지 않았다.
NCNN의 Vulkan/FP16/BF16은 끄고 CPU 2 threads로 실행했다. 비교 ONNX도 CPU 2 threads다.
제품 재생의 550ms 기준은 검증 명령의 종료 판단용 값이며 현장 수용 기준이 아니다.
RSS/온도는 종료 관측이고 peak/30분 부하 시험을 대신하지 않는다.

NCNN이 이 차선 모델에서는 ONNX보다 느리므로 **차선 운영 전환은 HOLD**다.
배포용 데이터셋 revision·카메라 프로파일은 원본 정보가 확인되지 않아 provisional로만 작성했다.
출력 `[1,4,240,320]` 변환·동일성 확인은 완료했지만 실제 라벨 IoU, 물체 검출 정확도,
30분 CORE/카메라 동시 부하, 서명 배포·기기 pointer 교체·실기 rollback·FIELD는 미검증이다.

## 구현 경로

- 기존 schema `/1`은 ONNX를 유지한다. NCNN은 명시적 backend가 있는 schema `/2`에서
  param/bin·blob·family·export/runtime version·hash를 검사한다. 구형 loader는 `/2`를 거부한다.
- YOLOv8/YOLO11 raw detection과 독립 TorchScript lane exporter를 분리했다.
  출력 shape/finite·실제 프레임 logits·검출 상자 또는 차선 픽셀 일치율을 확인한다.
  비교 증거까지 hash한 bundle의 revision은 전처리·클래스 역할·provenance를 포함한다.
- intake는 hash 검증 후 NCNN 비교 증거와 task별 기준을 검사한다. 기존 서명·전송·슬롯
  reader가 manifest의 파일 목록을 사용한다. NCNN 실제 기기 교체 수용은 아직 진행하지 않았다.
- Pi 이미지/개발 설치의 learned prefix에 NCNN wheel hash를 고정했다.
  OpenCV/NumPy 우선순위와 기존 ONNX rollback 의존성을 유지했다.

## 재현

실제 클래스 역할과 추적 가능한 provenance를 확인한 뒤 PC에서 실행한다.
아래 `<...>`는 운영 입력이며 provisional 값을 배포에 사용하지 않는다.

```sh
python tools/perception/model/convert.py <trained.pt> --backend ncnn \
  --kind ultralytics --task object_det --frames <camera-frames> --out <bundle> \
  --dataset-repo <repo> --dataset-revision <40-hex> \
  --camera-profile-revision <revision> --trainer <trainer>
# lane: --kind torchscript --task lane_seg --classes <classes.yaml>
python tools/perception/rosy_ml.py doctor --backend ncnn
python tools/perception/model/bench_backends.py <bundle> --frames <camera-frames> \
  --iterations 100 --duration-s 1800 --max-p95-ms <accepted-budget> --out <report.json>
```

`bench_backends.py`는 녹화 이미지 재생 도구다. 라이브 카메라·CORE 동시 부하는 별도 실행한다.
원본 모델/영상과 상세 로그는 git에 넣지 않았다. 호스트 스크래치·export bundle·raw readback은
`X:/DevTemp/rosy-ncnn-20261003/`에 있다. 공개 기록에서 기기 주소·계정을 제외했다.
