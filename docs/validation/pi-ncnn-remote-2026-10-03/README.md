# D-431 원격 학습 PC 변환 및 Pi 동시 부하 재검증

2026-10-03, `verify/ncnn-remote`, 실행 소스 commit `e23b8fe26`.
[앞선 구현·재생 시험](../pi-ncnn-2026-10-03/README.md)의 후속 실행이다.
기존 원격 학습 PC를 사용했으며, 운영 모델 전환 판단은 **HOLD**다.

## 입력과 실행 환경

- 실제 입력은 `data/drive/0930_best_model.torchscript.pt`의 4종 차선 분할 모델이다.
  source SHA-256 `19050e80754720a7f4b9e4a4724d5f53a145370668d3a5850544e1ed7339c782`.
- 원격 PC의 홈·runs·다운로드·마운트 경로 검색에서는 물체 검출용 학습 YOLO
  체크포인트를 찾지 못했다. 기존 차선 ONNX smoke 출력은 YOLO를 대신하지 않는다.
- 학습 PC: Ubuntu 24.04 x86_64, Python 3.12.3, RTX 5080 Laptop 16GB.
  기존 학습 venv의 torch 2.11.0+cu128, Ultralytics 8.4.171, PNNX 20260526,
  NCNN 1.0.20260526을 사용했다. 이번 export·비교·intake는 CPU 2 threads다.
  GPU를 보유한 PC를 사용한 것이며 GPU 학습을 새로 실행한 증거는 아니다.
- intake용 ONNX Runtime 1.30.0은 원격 `/tmp`의 별도 target에 `--no-deps`로
  설치했다. 공유 venv·학습 checkout·store inbox·READY는 수정하지 않았다.
- Pi: aarch64/Python 3.12.3, 시스템 OpenCV 4.6.0·NumPy 1.26.4.
  NCNN 1.0.20260526 ARM64 wheel을 임시 target에 설치했다.
  torch·Ultralytics·pip OpenCV는 기기에 설치하지 않았다.
  NCNN Vulkan/FP16/BF16은 끄고 CPU 2 threads로 실행했다.

## 원격 PC 결과

| 시험 | 관측 |
|---|---|
| 제품 `convert.py`, 실제 영상 20프레임 | logits 최대 차이 0.00003242493, 분류 픽셀 일치율 100% |
| NCNN model revision | `lane-seg-ncnn-20261003-e3f612b32f0a` |
| 제품 `intake.py`, NCNN, 380프레임 | pass, 오류/NaN 0, p50 46.43ms, p95 53.68ms |
| 같은 원본의 FP32 ONNX, 380프레임 | pass, 오류/NaN 0, p50 40.94ms, p95 50.92ms |
| 두 intake의 lane visible fraction | 0.96316 |

intake는 원격 checkout의 녹화 영상 19개에 `--max-frames 20`을 적용했다.
이는 **영상별 최대 20프레임**이며 전체 20프레임이 아니다.
실행한 gate의 `eval_set`, `min_eval_miou`, `min_lane_marking_iou`는 null이다.
따라서 pass는 shadow 전달 자격이며, 실제 라벨 IoU·학습 모델 정확도 수용이 아니다.
복사한 도구 소스에서 실행해 intake report의 `tool_commit`은 null이고,
실행 소스 commit은 이 기록의 첫 줄로 별도 고정한다.

원본 데이터셋 revision·카메라 프로파일은 아직 미확인이다.
`unknown/colab-0930`, zero revision, `unknown-provisional`은 변환 검증용
provisional metadata이며 운영 배포 자격으로 사용하지 않는다.
프레임별 동일성·파일 hash는 [remote-export.json](remote-export.json)에 기록했다.

## Pi 30분 시험

실제 카메라 ROS Image를 구독해 제품 `LaneSegModel.open/infer`로 추론했다.
기존 CORE·camera·IO 옆에서 별도 프로세스로 실행했고, warm-up 5회를 제외한다.
motion command publisher는 없으며 주행 명령·운영 pointer·서비스 재시작을 하지 않는다.
인증 readback용 임시 administrator pairing은 생성 후 회수를 확인한다.

시험은 중단됐으며 **30분 완료 실패**다. 마지막 자원 표본은 1,337.41초
(약 22분 17초), 수신 3,236프레임·추론 2,401프레임, 누적 p95 595.41ms다.
30초 간격 45개 표본 모두 CPU 진단 ERROR였고, 표본 최고 온도 77.1°C,
RSS high-water 최대 354,373,632 bytes였다. CORE·camera·IO의 PID와 restart
counter는 최초·표본·종료 readback에서 동일했다.

별도 약 2초 `/proc/stat` 표본의 전체 4-core CPU 사용률은 99.0%다.
동일 표본의 NCNN 프로세스는 125.9%, CORE main process는 58.9%였다.
프로세스 CPU는 100%가 한 core이며 전체 CPU와 단위가 다르다.
camera·IO 값은 wrapper main PID만 측정해 자식 프로세스 부하를 대표하지 않는다.
45개 표본의 `cpu_percent`는 NCNN 프로세스의 누적 평균이며 전체 Pi CPU가 아니다.
thermal throttling, CORE 명령 지연, 실시간 출력 parity는 측정하지 않았다.

ROS spin thread의 `ExternalShutdownException` 이후 cleanup에서 중복
`rclpy.shutdown()`이 `RCLError`를 발생시켜 최종 summary와 logout이 누락됐다.
종료를 유발한 원인은 확인되지 않았으며 추론 안정성 통과로 해석하지 않는다.
종료 후 benchmark process가 없음을 확인하고 남은 임시 pairing token 1개를
API로 회수했다. token 목록의 해당 label 0개와 readback token logout 후
whoami 401을 확인했다. 초기 ROS mode는 EMERGENCY였고 표본에는 IDLE·MANUAL·
NAVIGATION도 나타났으나 navigation은 모두 IDLE였다. 본 시험은 mode·estop을
변경하지 않았으며 이러한 외부 상태 변화가 있었던 세션을 주행 수용으로 사용하지 않는다.
자원 표본·원본 로그/script hash·종료 확인·인증 회수 결과는 [live-load.json](live-load.json)에 있다.

CPU ERROR와 앞선 동일 원본 ONNX 대비 지연 열화 때문에 차선 NCNN 운영 전환을
계속 보류한다. 먼저 처리 주기·CPU 예산을 만족시키고, 종료 cleanup을 보강한
격리 시험으로 30분 동시 부하를 다시 완료해야 한다.

## 격리 서명 전달·실기 rollback

PC의 제품 intake pass bundle을 로컬의 일회성 Ed25519 key로 서명하고,
공개 key만 Pi 임시 trust 폴더에 전달했다. 운영 release trust에는 추가하지 않았다.
제품 `deliver.py --root /tmp/rosy-ncnn-live-20261003/deploy-models`로 FP32 ONNX,
NCNN 순서로 shadow 전달했고, 기기에서 `SignatureCheck(enforce=True)`와
`ModelSlot`으로 실제 모델을 열었다.

- 예상 NCNN revision·서명 검증: pass.
- param hash 불일치 후보 교체: 거부, 기존 NCNN 객체 유지.
- 잘못된 signature 후보 교체: 거부, 기존 NCNN 객체 유지.
- 제품 `deliver.py rollback`: 이전 FP32 ONNX revision으로 복귀, 서명·실제 load pass.
- 운영 `/var/lib/rosy/models`의 pointer·manifest hash: 전후 동일.

lane의 현재 운영 서명 규칙은 warn-only이므로 이번 시험 opener에서 강제 검증했다.
이는 **실기 임시 shadow의 전달·서명·교체 실패 보존·복구 검증**이며,
정식 release key·운영 slot 배포·object_det 서명 gate·차선 정확도 수용은 아니다.
결과는 [isolated-roundtrip.json](isolated-roundtrip.json)에 있다.
시험용 개인 서명키는 검증 후 로컬 임시 경로에서 삭제했다.

## 재현 순서

```sh
# Existing remote model-PC environment; scratch outside the shared checkout/store.
<training-python> learning/training/perception/model/convert.py <lane.pt> \
  --backend ncnn --kind torchscript --task lane_seg --classes <classes.yaml> \
  --frames <20-real-frames> --out <scratch-bundle> \
  --dataset-repo <verified-repo> --dataset-revision <verified-revision> \
  --camera-profile-revision <verified-profile> --trainer <trainer>
<training-python> learning/training/perception/model/intake.py <scratch-bundle> \
  --root <training-checkout> --out <scratch-accepted> --max-frames 20
python learning/training/perception/model/sign_model.py <accepted-revision> \
  --key <ephemeral-bench-key> --check <bench-public-keys>
python learning/training/perception/model/deliver.py push <robot-host> <revision> \
  --models <scratch-accepted> --root <isolated-device-model-root>
python learning/training/perception/model/deliver.py rollback <robot-host> \
  --root <isolated-device-model-root>
```

이번 실행의 미확인 provenance를 위 명령의 검증된 값으로 간주하지 않는다.
30분 시험용 일회성 subscriber·수집 script는 로컬 scratch에 보관하며,
중단 전 원본 script hash는 `live-load.json`에 고정한다.

## 남은 수용 조건

- 물체 검출용 학습 YOLO·클래스·평가 데이터 위치와 provenance 확인.
- 실제 라벨 정확도 및 Pi 처리 주기·CPU 예산 충족.
- 정식 ARM64 이미지/payload 설치·서명 release key·운영 slot readback.
- 실제 주행·차선 활성화·FIELD는 별도 gate다.

로컬 로그·모델·인증 없는 원본 readback은 `X:/DevTemp/rosy-ncnn-remote-20261003/`에
보관한다. 공개 기록에는 장치 주소·계정·인증 값·실제 ROS namespace를 넣지 않는다.

## 문서·계약 검증

- 문서 배치·폴더·네트워크·서명 전달/slot 계약: 81 passed, 1 skipped.
- 최종 harness·네트워크·문서 배치·폴더·release secret boundary: 177 passed,
  1 skipped. harness lint: 0 errors, 26 기존 history/staleness warnings.
- 최초 source quick tier의 생성 index 관련 2개 실패는 `generate` 후 해당 harness
  suite에서 해소했다. 나머지는 457 passed, 2 skipped였다.
- 독립 검토에서 자원 표본 집계·원본 hash·실제 roundtrip 결과·공개 기록의
  개인정보 경계와 HOLD 표현을 대조했다. 정확한 종료 시간으로 오해될 수 있는
  표현과 없는 readback hash 언급은 수정했다.

위 host 검증은 이미지/payload·정식 운영 배포·FIELD 증거를 대신하지 않는다.
