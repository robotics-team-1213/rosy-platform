## D-356 인식 학습 루프와 모델 전달 — 학습은 밖, 약속·접수·전달·섀도 추론은 안

**Status:** Proposed (2026-09-30). 설계: [2026-09-30-perception-learning-loop-design.md](../plans/2026-09-30-perception-learning-loop-design.md).
잇는 결정:

- [D-209](D-209-perception-folder-and-learned-backend.md)(Accepted): 학습 모델은 `backend_learned`이고 `perception/evidence`만 낸다. 가중치는 `src/`에 두지 않는다. 학습·채점은 `tools/perception/`, 산출물은 `data/perception/`이다.
- [D-199](D-199-camera-perception-contracts-and-backends.md)(Proposed): 모르는 `model_revision`은 닫힌다.
- [D-205](D-205-real-lane-mission-transition-order.md)(Proposed): 주행 선택은 텔레옵 재생 게이트 합격 뒤다.
- [D-137](D-137-yolo-lidar-ir.md)(Proposed): 모델 교체는 되돌릴 수 있는 세대 전환이다.
- D-186: 큰 데이터는 저장소에 넣지 않는다. D-290: 수집 전에 출처·캘리브레이션·모델 revision을 묶는다.

**Context:**

1. 외부(Colab)에서 학습한 차선 분할 모델 `0930_best_model.torchscript.pt`(LaneUNet, 입력 `1×3×240×320`, 출력 4클래스)가 생겼다. 이 모델을 읽는 코드, 추론 런타임, 로봇으로 보내는 경로가 없다.
2. 학습은 앞으로도 이 저장소 밖(Colab·GPU PC)에서 돈다. 학습 환경과 로봇 사이에 입력·출력 약속이 없다.
3. 로봇에서 카메라와 명령·관측을 함께 기록하는 도구가 없다. 로봇→PC 경로는 브라우저 수동 다운로드뿐이다.
4. 코드 릴리스(서명 페이로드)는 데이터 파일 하나를 바꾸려고 다시 만들기에 무겁다.

**Decision:**

1. **학습은 저장소 밖이다.** 저장소는 약속만 갖는다: 입력은 HF private dataset 저장소의 commit SHA, 출력은 HF private model 저장소 commit의 `model.onnx`와 `model_manifest.json`(`rosy.perception.model/1`). manifest는 파일별 sha256, 입력 전처리(색 순서·scale·mean·std), 클래스와 닫힌 role 목록(`background`, `lane_marking`, `drivable`, `stop_line`, `ignore`), 데이터셋 revision, CameraProfile revision을 적는다.
2. **로봇 추론 형식은 ONNX, 런타임은 onnxruntime(CPU)이다.** torch는 로봇에 올리지 않는다. TorchScript는 개발 PC에서 변환한다. Hailo는 같은 ONNX에서 나중에 별도 산출물로 다룬다.
3. **모델은 데이터 세대로 전달한다.** 사이트 PC가 접수(manifest·해시·ONNX 로드·재생 보고서)를 통과한 모델만 SSH로 `/var/lib/rosy/models/<revision>/`에 놓고, 포인터 파일을 원자적으로 바꾼다. 이전 포인터를 남겨 한 명령으로 되돌린다. 로봇은 인터넷의 모델 저장소에 직접 붙지 않는다.
4. **이번 결정의 로봇 추론은 섀도 전용이다.** 학습 모델 노드는 `perception/learned/shadow`에 결과를 내고, 어떤 제어 경로도 그것을 읽지 않는다. 접수 보고서는 섀도 배포 자격일 뿐 D-205 주행 선택 자격이 아니다. 활성화(`perception.backend=learned_seg`)는 D-205 P3 합격 뒤 별도 ADR이다.
5. **수집은 rosbag2 MCAP이다.** 압축 카메라, `cmd_vel`, 관측, 섀도 결과를 세션 단위로 기록하고 `session.json`에 D-290 항목을 적는다. 수거 전 세션은 할당량 때문에 지우지 않는다.

**Consequences:** 학습 코드가 어디서 돌든 manifest만 맞으면 로봇까지 간다. 섀도 결과가 쌓이면 규칙 기반과의 차이를 수집 트리거와 D-205 재생 게이트의 입력으로 쓸 수 있다. onnxruntime은 장치 이미지에 없으므로 이미지 반영(해시 고정 requirements)은 Pi 실측 뒤 별도 작업이다. 데이터와 모델이 외부 클라우드(HF private)에 올라가므로 토큰은 사이트 PC와 학습 환경에만 둔다.

**Validation:** ROS-free 모듈의 호스트 pytest, 합성 ONNX 통합 시험, 실제 `0930` 모델의 변환·접수 보고서 1회. 호스트 합격은 장치 합격이 아니다. Pi 5에서의 지연 실측이 섀도 배포의 첫 장치 증거다.
