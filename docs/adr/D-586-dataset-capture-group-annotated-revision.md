## D-586 capture_group이 없는 옛 학습 자료는 메타데이터만 고친 새 revision으로 그룹을 밝힌다 (D-475 2항·D-464 4항 보충)

**Status:** Accepted (2026-10-10, 사용자 결정 "옵션 A". 모델 PC store에 annotated revision 게시 완료. 깨끗한 도구 수정(옵션 B)은 별도 결정·구현이다.)

### Context

- **옛 자료에는 그룹이 없다.** 학습 자료 `d379-auto-lanes-rosy26-v1@54db2400…`(D-379 자동 라벨, 녹화 세션 8개, 937 프레임)는 capture_group 필드가 생기기 전에 만들어졌다. 프레임 행에 `capture_group`이 없다.
- **평가 분리 확인은 그룹을 모르면 멈춘다.** D-475 2항은 평가용으로 예약한 세션과 capture group을 학습 입력에서 빼도록 했다. D-464 4항은 session·capture_group·원본 표현의 교집합을 확인하고, 그룹 정보가 빠졌으면 UNKNOWN/HOLD로 멈춘다(fail closed). 그래서 이 자료로 학습한 번들은 지금 게이트를 통과하지 못한다. fp32 챔피언 `lane-seg-20261006-62db9403`이 그렇고, 그 번들을 변환한 int8-hf 번들 `lane-seg-20261009-3831b20d`(D-585 3항)도 같은 자료를 가리키면 같은 이유로 멈춘다.
- **사실 관계는 분명하다.** manifest `sources[]`의 장치와 `started_at`/`ended_at`을 보면 8개 세션은 서로 다른 녹화이고, 평가로 예약된 세션과 겹치지 않는다. 비어 있는 것은 그 사실을 기계가 읽는 필드뿐이다.

### Decision

1. **옵션 A: 메타데이터만 고친 새 revision을 만든다.**
   - 이름은 `d379-auto-lanes-rosy26-v1-groups`다. 모든 프레임에 `capture_group: rec-<session>`을 적는다. 녹화 세션 하나가 capture group 하나다.
   - 프레임·마스크·conf 파일 2811개는 원본 revision과 바이트가 같다. 바뀌는 것은 `manifest.json`뿐이다.
   - manifest의 `annotation` 블록에 `annotation_of: d379-auto-lanes-rosy26-v1@54db240045672350bb7138abcf1608342918423ff7b67d5eccb65c951a074135`, 그룹 규칙, 결정자, 날짜, 근거를 적는다.
   - 그룹 표기는 운영자(사용자)의 주장이다. D-464 3항과 같이 수집 경계의 선언이며, 카메라·시간·자세·지도 보정의 증명이 아니다.
   - 게시는 기존 immutable `Store.put_dataset` 경로로 한다. 원본 revision `54db2400…`은 지우지도 고치지도 않는다.
2. **새 번들은 annotated revision을 학습 자료로 적는다.** int8-hf 번들 `lane-seg-20261009-3831b20d`부터 이 이름을 쓴다. 가중치는 같은 자료로 학습한 것이므로 다시 학습하지 않는다.
3. **기존 fp32 번들은 그대로 둔다.** `lane-seg-20261006-62db9403`의 manifest는 고치지 않는다. 이 번들은 지금 게이트에서 계속 HOLD다. 번들 manifest는 서명·revision과 묶여 있어서, 다시 쓰면 이력이 흐려지기 때문이다.
4. **fail-closed 규칙은 그대로다.** "그룹 모름 = UNKNOWN/HOLD"를 완화하지 않는다. 그룹을 세션 이름에서 자동으로 추정하는 기본값도 두지 않는다. 그룹을 밝히는 길은 사람이 결정하고 기록을 남긴 새 revision뿐이다.

### 게시 기록

2026-10-10 모델 PC store에서 읽기 전용으로 확인한 값이다.

- 경로: `/srv/rosy/store/datasets/d379-auto-lanes-rosy26-v1-groups/e643de1cf1f17cde3f8632d11f02717d6a54074676dde816ca6b7bc241ca7029/`
- 프레임 937개. 그룹 8개: 세션마다 하나이고 28–279 프레임이다.
- `annotation.annotation_of`가 위 원본 revision과 일치한다.
- 파일 수는 2811개에 `manifest.json`을 더한 2812개다.

### 기각·보류

- **옵션 B, 내용 주소 표기 기록(보류):** 자료 본문은 그대로 두고 `<자료 sha> → 그룹 표기`를 따로 서명된 기록으로 두는 방식이다. 같은 일을 하는 깨끗한 도구 수정이지만 store·게이트 코드를 바꿔야 한다. 다음에 같은 일이 생기면 이 방식을 먼저 검토한다.
- **옵션 C, 다시 빌드하고 다시 학습(기각):** 결과 가중치는 같은 자료에서 나오고, 시간만 많이 든다.
- **fail-closed 완화, 세션 이름으로 그룹 추정(기각):** D-464 4항이 막으려던 것이 바로 증명 없는 분리 주장이다.

### Consequences and verification

- 게이트는 annotated revision을 다른 자료와 같은 방법으로 검사한다. 새 예외 경로는 없다.
- 같은 처리가 필요한 다른 옛 자료가 생기면, 자료마다 사용자 결정과 annotated revision을 새로 남긴다. 이 ADR은 `d379-auto-lanes-rosy26-v1` 하나에만 적용한다.

**Related:** [D-475](D-475-human-reviewed-fixed-eval-truth.md)(2항 평가 예약), [D-464](D-464-pinky-indexed-review-dataset-build.md)(3·4항 출처·분리), [D-379](D-379-learning-data-pipeline-auto-labels-local-store.md), [D-585](D-585-model-driven-lane-lap-acceptance-and-device-paint-defaults.md)(int8-hf 번들).
