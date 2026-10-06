## D-485 검수 앱 클래스셋(review class sets)은 불변 record로 두고 작업 공간이 하나씩 고른다

**Status:** Proposed (2026-10-06, 사용자 확인한 결정 사항을 `docs/plans/2026-10-06-review-class-sets-plan.md`에서 옮김; 구현·착지 별도).

잇는 결정: [D-423](D-423-camera-object-range-detection-and-model-slots.md)(객체 6클래스 계약은 그대로) · [D-459](D-459-pinky-persistent-label-review-application.md)(검수 앱에 모델 호출 없음) · [D-461](D-461-task-first-workspace-compositions-and-learning-ux.md)(전체 확인 체크 유지) · [D-462](D-462-incremental-pinky-pixel-review-and-current-decisions.md)(픽셀 검수 binding) · [D-464](D-464-pinky-indexed-review-dataset-build.md)(학습 export) · [D-373](D-373-learned-perception-on-pinky-and-capture-loop.md)(닫힌 lane role 목록은 그대로).

### Context

검수 앱의 객체 클래스는 D-423 6클래스(`OBJECT_CLASSES`)로 굳어 있고 화면 JS에도 이름표가 하드코딩돼 있다. 모델마다 다른 클래스 목록(예: 차선 5클래스)을 검수하려면 클래스 정의를 데이터로 내려야 한다. 근거는 `docs/assessments/2026-10-06-label-review-tool-survey.md` 5.1–5.6이다. Label Studio, Labelbox, Encord는 스키마를 불변으로 두고, CVAT은 이름으로 맞추며, Roboflow와 CVAT은 숫자 단축키를 쓴다.

### Decision

1. **클래스셋은 불변 record다.** 정체성은 task와 순서 있는 class names의 sha256이다. display, color, hotkey는 표시 정보이고 sha에 들어가지 않는다. 이 task+names 정체성은 객체 클래스셋에 적용한다. 픽셀 클래스셋은 기존 D-462의 `classes.yaml` 원본 sha 바인딩을 그대로 쓴다. 수정 API는 없다. 클래스셋을 바꾸면 새 sha의 새 클래스셋이다.
2. **작업 공간(`--state`) 하나는 객체 클래스셋 하나와 픽셀 클래스셋 하나(기존 review_masks binding, D-462)를 가진다.** 다른 모델의 클래스셋은 다른 `--state` 작업 공간에서 검수한다. 기존 작업 공간은 D-423 v1 6클래스로 소급한다. 사진×클래스셋 row는 지금 만들지 않는다.
3. **객체 클래스셋 입력은 Ultralytics `data.yaml`의 `names`(dict 또는 list)와 선택 `display`/`colors`다.** 첫 실행에 `--object-classes`로 준다. 앱은 `.pt`를 열지 않는다(pickle 실행 위험, Ultralytics AGPL-3.0). 모델 PC 도구가 `YOLO(path).names`를 `data.yaml`로 내보낸다.
4. **범위는 검수, 승인, 학습 export뿐이다.** 로봇의 `object_det` manifest의 D-423 6클래스 계약(`manifest.py:179`)과 D-373 닫힌 lane role 목록은 바꾸지 않는다. 그 변경은 별도 ADR이다.
5. **차선 5클래스 `classes.yaml`을 둔다.** `background`, `lane_left`, `lane_right`, `crosswalk`, `speed_bump`. `lane_left`/`lane_right`의 role은 `lane_marking`, `crosswalk`·`speed_bump`의 role은 `ignore`다. 후자 둘은 로봇 런타임에서 의미가 없다.
6. **화면은 서버가 내려준 클래스셋(display, color)만 쓴다.** JS 하드코딩 이름표를 지운다. 숫자키 1–9는 클래스, A는 승인(전체 확인 체크 필수 유지, D-461), X는 제외다.

### Alternatives

- **서버 플랫폼(CVAT/Label Studio/FiftyOne) 도입.** 비채택.
- **다중 사용자 역할.** 비채택.
- **앱 안 모델 호출.** D-459에 어긋나 비채택.
- **공유 ontology 전파.** 비채택. 클래스셋은 작업 공간별로 둔다.
- **GPL/AGPL 코드 복사.** 비채택. 방식만 참고한다.
- **클래스셋 수정 API.** 기존 라벨의 의미가 조용히 바뀌므로 기각. 새 sha를 만든다.

### Consequences

- 기존 작업 공간은 동작이 그대로이고 6클래스 클래스셋으로 읽힌다.
- 다른 모델 클래스셋을 검수하려면 새 `--state`가 필요하다.
- 로봇 쪽 계약은 이 ADR로 바뀌지 않는다. 다른 클래스를 로봇에 배포하려면 별도 ADR과 manifest 변경이 필요하다.
- 객체 클래스셋 sha(`object_class_set_sha256`)는 `review-contract.json`과 `/api/workspace`에 있고 `/api/decisions`에는 없다. `decision_sha256`은 authority 객체 전체의 sha라서, 넣으면 기존 작업 공간의 sha가 같은 generation에서 바뀌어 `review_authority` same-generation 검사, `review_bridge`, `review_pipeline._logical_key`가 깨진다.
- 수용: host pytest. 장치·현장 확인은 해당 없음.

**References:** `docs/plans/2026-10-06-review-class-sets-plan.md`, `docs/assessments/2026-10-06-label-review-tool-survey.md`, `learning/training/perception/dataset/review_app.py`.
