## D-464 Pinky 승인 픽셀은 원본·최신 결정·평가 분리를 검증해 immutable 데이터셋으로 만든다

**Status:** Accepted (2026-10-05, 사용자 검수 라벨·학습 반복 파이프라인 구현 및 로컬 병합 지시; 실제 정답·학습·장치 수용 별도).

### Context

D-379는 당시 사용자 요청에 따라 자동 라벨만 학습했다. 이후 사용자는 Pinky 전용 웹 픽셀 검수와 검수한 영상의 재학습을 명시적으로 요청했다. D-462의 최신 객체·픽셀 승인과 봉인된 export는 바이트/결정 증거이며 데이터셋 학습 자격을 부여하지 않는다. 기존 CVAT builder는 RGB labelmap과 별도 출처를 전제로 하므로 GUI의 indexed PNG를 그 경로에 위장해 넣을 수 없다.

이번 결정은 D-379의 자동 라벨 한정을 명시 승인된 Pinky indexed 픽셀에 대해 확장한다. 기존 자동 라벨, 고정 평가 세트 및 클래스 역할은 유지한다. 아래 구현 허용은 실제 사람 정답 확정이나 장치 수용이 아니다.

### Decision

1. **입력·책임.** developer-side `training/review_dataset.py`는 `rosy.pinky-review-export/2`와 실제 transport가 확인한 `rosy.pinky-review-current-delivery/1`을 소비한다. workspace pin, 최신 digest/generation, bounded freshness와 모든 봉인된 파일을 독립 검증한다. `verify_bundle(capture_files=True)`의 같은 검증 바이트를 decode하며 승인 뒤 경로를 다시 읽어 라벨을 대체하지 않는다. producer의 `training_dataset_qualified=false`를 바꾸지 않는다.
2. **픽셀·클래스.** 전체 프레임/배경을 명시 승인한 정확한 8bit grayscale indexed PNG만 사용한다. class index, 크기, 원본 image/mask SHA, raw YAML SHA 및 정규화 classes signature를 대조한다. `ignore_index=255`와 `crosswalk`의 실제 index/role을 구분한다. GUI의 전체 검수 승인과 일치하게 mask에 값255가 하나라도 남으면 거절한다. 제외·pending·철회, RGB/CVAT 위장 및 클래스 발명도 거절한다. 승인한 image/mask bytes는 재인코딩하지 않고 보존한다.
3. **출처 증명.** 내부 입력 파일 `rosy.pinky-review-source-proof/1`은 `source_session`, `capture_group`, `video_path`, `video_sha256`을 갖고 선택적인 `sidecar_path`/`sidecar_sha256`은 함께 존재해야 한다. 이 파일이나 verified flag만으로 출처를 인정하지 않는다. authority에 선언된 정체성과 일치하는 실제 video bytes를 캡처한 동일 immutable snapshot의 SHA를 검증하고 그 snapshot에서 정확한 video frame을 순서대로 decode해 원본 PNG decoded pixels의 동등성을 검사한다. mutable 영상 경로의 전후 해시만으로 ABA 변경을 놓치지 않는다. 경로 link/junction, 변경된 bytes, 누락된 session/group/frame, 증명되지 않은 JPEG 변환은 거절한다. 독립 증명이 성공해도 producer 역사 flag를 덮어쓰지 않고 새 검증 출처로 기록한다. 그룹 이름은 설정된 수집 경계 선언이며 카메라/시간/pose/map 보정 증명이 아니다.
4. **평가 분리·split.** 사용 중인 모든 eval content version을 실제 폴더에서 재검증하고 session/group/video/frame/image·대체 표현 SHA 교집합을 배제한다. `Store.evalsets()`의 실제 전체 inventory와 고정 gate refs를 대조해 caller가 version을 빼거나 빈 목록으로 disjoint를 만들지 못하게 한다. eval source/group inventory 결손은 UNKNOWN/HOLD이며 session 이름만으로 완전 disjoint를 주장하지 않는다. 동일 session, capture_group, 원본 video SHA 전체 또는 같은 원본 표현은 하나의 연결 component로 묶는다. 최소 두 독립 component가 있어야 train/val을 나눈다. manifest의 canonical source session을 group으로 바꾸지 않고 split key/근거를 따로 기록한다. 이 origin은 기존 자동 라벨 `TRUSTED_SOURCES`를 확장하거나 새 eval 정답을 만들지 않는다.
5. **결과·게시.** 기존 `rosy.perception.dataset/1`을 만들되 sources의 `annotation_origin`을 `human_reviewed_pinky_indexed`로 명시한다. 이는 CVAT 출처가 아니다. source/image/mask/classes/승인 revision/digest·source proof 검증 결과와 eval disjoint refs를 함께 고정한다. 기존 immutable `Store.put_dataset`으로 게시하며 승인0/적격0/HOLD에서는 dataset/manifest/request/READY를 쓰지 않는다. 스크래치는 설정된 임시 드라이브에만 둔다.
6. **학습 admission.** 구축·게시 직전과 게시 뒤 최신 authority를 다시 확인한다. 성공한 게시를 포함해 현재 builder의 모든 결과는 `training_admission=false`이며 build receipt는 바이트와 검증 출처 증거만 제공한다. 게시 중 revision이 바뀌면 immutable artifact가 남아도 false/HOLD이고 삭제·rollback 성공을 주장하지 않는다. trainer owner가 실행 직전 최신 승인·출처·eval/version·TTL을 다시 검증해 승인한 뒤에만 request를 만들 수 있다. 데이터셋 존재만으로 새 학습, READY, model intake/주행 승격을 허용하지 않는다.

### Alternatives

- CVAT RGB와 `human_reviewed_cvat`로 변환: 승인한 indexed bytes와 실제 출처가 달라지므로 채택하지 않는다.
- latest envelope approval만 보고 기존 builder 호출: 원본 출처 및 group split/eval 중복을 증명하지 못하므로 채택하지 않는다.
- 원본 PNG/영상·최신 결정·고정 평가를 독립 검사하는 직접 indexed 경로: 채택한다. 증거가 없는 기존 JPEG/영상/지도 투영은 HOLD를 유지한다.

### Consequences and validation

현재 실제 마스크 승인0과 eval source/group 정보 결손이면 새 학습 데이터는 없다. 객체 승인·synthetic fixture·CAD paint를 정답 승인으로 대신하지 않는다. host/source/격리 roundtrip, 실제 service 전달, 실제 학습 정확도, 장치/현장 수용을 각각 보고한다.

회귀는 synthetic 실제 영상+PNG+두 독립 component+content-addressed eval 폴더를 사용해 원본 byte 보존 및 immutable roundtrip을 확인한다. stale/만료/철회/type alias, 위장 이미지, 원본 SHA/frame 불일치, eval 변경/UNKNOWN/중복, component 누수와 publish interleaving을 거절한다. 실제0승인 경로는 파일 생성0으로 검증한다. live 승인·push·주행/HOLD 해제는 이번 구현 증거가 아니다.

**Related:** [D-379](D-379-learning-data-pipeline-auto-labels-local-store.md), D-462, D-356, D-373.
