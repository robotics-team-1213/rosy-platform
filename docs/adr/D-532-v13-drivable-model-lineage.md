## D-532 주행 가능 영역 모델은 `v13-drivable` 계열로 따로 관리한다

**Status:** Accepted (2026-10-09, 사용자 결정; 이름 규칙 구현은 SOURCE, 실제 학습·접수·배포는 별도 증거).

### Context

기존 v11은 전달된 차선 분할 모델이고, v13은 현재 모델 PC의 촬영·검수 작업 공간을 가리킨다. 주행 가능 영역 `drivable`을 추가한 출력은 기존 차선 출력과 클래스 수·뜻이 다르다. 둘을 단순히 `v13`이나 같은 `lane-seg` 실험명으로 관리하면 데이터 판, 학습 계열, 실제 모델 판을 혼동하기 쉽다. `model_revision`은 store·inbox·로봇 포인터에서 쓰이는 불변 식별자이며 기존 산출물을 소급 변경할 수 없다.

### Decision

1. **계열과 판을 분리한다.** 이 촬영분의 사람 승인 데이터를 이용해 `drivable` 출력을 추가한 첫 학습 계열의 이름은 정확히 `v13-drivable`이다. 학습 실행·모델 폴더·결과 화면은 `v13-drivable-YYYYMMDD-<ONNX sha8>` 형식의 `model_revision`을 사용한다. 재학습이나 가중치가 달라지면 새 revision을 만든다. v13은 원본/검수 자료의 호칭이며 승인된 학습 데이터셋의 내용 SHA를 대신하지 않는다.
2. **다른 계열과 혼합하지 않는다.** 기존 v11 차선 모델 revision과 객체 검출 `object_det` revision은 유지한다. `v13-drivable`도 manifest의 `task: lane_seg` 슬롯에만 들어가며 새 운영 슬롯이나 새 `task`를 만들지 않는다. 실제 출력의 순서 있는 클래스·role, 입력 전처리, 데이터셋 SHA, CameraProfile revision, 부모 차선 모델 revision/해시는 manifest와 run 기록에서 각각 검증한다. 이름만으로 호환성·품질·주행 권한을 판단하지 않는다.
3. **이름은 정답을 만들지 않는다.** 모델 PC의 v13 픽셀 초안, SAM/Qwen 제안, 제외 판단, JPEG만으로는 학습 자격이 생기지 않는다. 사람 승인 마스크와 원본 출처, 255 부재, 고정 평가 세트와 분리, 최신 결정·transport authority를 D-464/D-475 절차로 검증한 뒤에만 학습한다. 모델 접수·섀도 배포와 실제 주행 사용은 D-356/D-373의 별도 단계다.
4. **기존 계약을 유지한다.** 일반 `export_cell`의 기본 `lane-seg-YYYYMMDD-<ONNX sha8>`는 유지하고, 이 계열의 학습 호출만 prefix를 `v13-drivable`로 지정한다. revision은 안전한 단일 경로 토큰이어야 하며 모델/데이터셋 폴더를 이름 변경해서 이미 봉인된 해시나 READY를 바꾸지 않는다.

### Consequences and verification

코드와 호스트 시험은 두 prefix가 각각 만들어지고 manifest loader가 새 revision을 읽는지 확인한다. 모델 PC의 현재 v13 작업 공간은 객체 승인 0장, 픽셀 승인 0장, 원본 영상 검증 대기 상태다. 이 ADR과 이름 규칙은 실제 `v13-drivable` 가중치가 만들어졌거나 학습이 시작되었다는 증거가 아니다.

**Related:** [D-356](D-356-perception-learning-loop-and-model-delivery.md), [D-373](D-373-learned-perception-on-pinky-and-capture-loop.md), [D-464](D-464-pinky-indexed-review-dataset-build.md), [D-475](D-475-human-reviewed-fixed-eval-truth.md), [D-528](D-528-v13-exposure-labelability-review.md).
