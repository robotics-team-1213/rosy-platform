## D-558 drivable 모델은 불변 revision과 함께 `v<major>.<minor>.<patch>` 버전을 붙인다

**Status:** Accepted (2026-10-09, 사용자 결정 "계속 업데이트되는 버전은 v13.x.xx 등으로 메이저·마이너 버전 차이를 두고 규칙을 병행으로 세운다").

### Context

D-532는 `v13-drivable` 계열의 학습 결과를 `v13-drivable-YYYYMMDD-<ONNX sha8>` revision으로 식별한다. revision은 store·로봇 포인터·이력에 쓰이는 불변 식별자이지만, 이름만 보고는 어떤 변경이 들어갔는지 알 수 없다. 같은 날 라벨 규칙을 바꾼 재학습과 데이터만 늘린 재학습을 구분하지 못한다. D-554의 첫 후보 뒤 9항(선 바깥 음성 띠)으로 다시 학습하면서 이 차이를 사람이 바로 읽을 수 있어야 한다.

### Decision

1. **revision과 버전을 함께 쓴다.** D-532의 revision(`v13-drivable-YYYYMMDD-<sha8>`)은 그대로 불변 식별자다. 여기에 `model_version` `v<major>.<minor>.<patch>`를 붙인다. patch는 두 자리(`00`–`99`)다. 예: `v13.1.00`. 버전은 표시·비교용이고, 로봇 포인터와 store 경로는 계속 revision을 쓴다.
2. **자리마다 뜻을 정한다.**
   - **major**: 학습 계열. 원본 자료 세대(D-532의 v13 촬영·검수 계열)나 부모 차선 모델이 바뀌면 올린다. major는 계열 이름의 숫자와 같다(`v13-drivable` → 13).
   - **minor**: 라벨·출력 규칙. 유도 규칙(D-554 항목), 클래스·role, 헤드 구조, 입력 전처리, intake 게이트 정의가 바뀌면 올리고 patch를 `00`으로 되돌린다.
   - **patch**: 같은 규칙으로 다시 학습한 것. 검수 프레임 증감, 판정자 교체, epoch·seed·학습률 같은 하이퍼파라미터 변경이다.
3. **한 버전에 revision 하나.** 버전은 다시 쓰지 않는다. 거절되거나 버린 후보도 버전을 차지한다. 기록은 저장소 원장 `learning/training/perception/model/drivable_versions.yaml`에 남긴다. 항목마다 version, revision, ONNX sha256, 자료 ref, 규칙 근거(ADR 항목), 상태(`candidate`·`shadow`·`rejected`·`retired`), 한 줄 메모를 적는다. 원장에는 IP·계정·비밀을 적지 않는다.
4. **도구가 확인한다.** drivable_head 학습 설정은 `model_version`을 받아 모델 manifest와 run 기록에 쓴다. intake는 `v13-drivable-*`에 `model_version`이 없거나 형식이 틀리거나, major가 계열 숫자와 다르거나, 원장에 같은 버전이 다른 revision으로 있으면 거절한다. `deliver.py status`와 로봇의 shadow 로그는 revision 옆에 버전을 보여 준다.
5. **이미 만든 후보에도 매긴다.** `v13-drivable-20261009-982b09a9`는 `v13.0.00`(D-554 1–8항, `rejected`: 선 경계를 무시하고 카펫 전체를 칠함)이다. 그 manifest는 고치지 않고 원장에만 적는다. D-554 9항으로 다시 학습하는 첫 후보가 `v13.1.00`이다.

### Rejected

- revision 이름에 버전을 넣기(`v13.1.00-...`): D-532 4항대로 revision은 이미 store·로봇 이력에 쓰였고 소급해 바꿀 수 없다.
- 날짜만으로 구분: 같은 날 규칙 변경과 재학습을 가리지 못한다.

**Related:** [D-532](D-532-v13-drivable-model-lineage.md), [D-554](D-554-v13-drivable-lane-derived-labels.md), [D-356](D-356-perception-learning-loop-and-model-delivery.md).
