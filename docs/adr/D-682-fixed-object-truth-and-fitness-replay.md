# D-682 예약된 물체 정답과 고정 detector의 인지 적합성 재생

**Status:** Accepted (2026-10-12, D-659 파이프라인 구축 지시). 내부 고정 평가 계약이며 성능 수용·학습 admission·배포·주행 활성화는 별도다.

### Context

D-659의 물체 정밀도·재현율과 작은/가린 정답 지표는 기존 ObjectDetModel 프레임 어댑터에 연결했다. 기존 intake의 물체 재생은 정답 없이 오류·지연·검출 개수만 확인한다. 평가 작업 공간의 prepare는 학습용 export를 거절하고 기존 MCAP publish는 픽셀 정답만 출판한다. 학습용 export를 평가용으로 재해석하지 않고 기존 소유 경로에 물체 평가 출판과 실행을 연결한다.

### Decision

1. `review_eval_bootstrap.py`의 ready/publish에 명시적 `target`을 추가한다. 기본값 pixels는 기존 경로를 유지한다. objects는 별도 evaluation workspace, D-602 여섯 클래스셋, 예약된 MCAP 원본과 모든 프레임의 approved 물체 결정을 요구한다. 완전한 물체 검수는 frame.review의 `review_status=approved`, `complete_frame_review=true`, 명시적 boxes 목록으로 확인한다. authority의 complete_frame_review/background_reviewed는 픽셀 검수 속성이므로 물체 완료로 사용하지 않는다. 빈 boxes도 명시적 전체 화면 검수가 있어야 한다. 가림 속성은 bool 또는 미설정이며 미설정은 미확인이다. 기존 리뷰와 예약은 수정하지 않는다.
2. 원본 image bytes·크기, source와 human_review의 SHA256, authority의 object_version·object_review_sha256, 세션·capture group·MCAP identity를 결속한다. 모든 원본 bag/metadata와 정확한 decoded frame을 기존 prove_frames로 다시 검증한다. 출판 전후 authority를 다시 확인하며 예약·원본·클래스·승인이 바뀌면 출판하지 않는다. 픽셀 mask 승인은 물체 출판의 선행 조건이 아니다.
3. 고정 출판물은 기존 `rosy.perception.dataset/1`, `purpose=eval`, `task=object_det`를 사용한다. `object-classes.json`, `authority.json`, 원본 images와 manifest를 content SHA로 묶어 기존 evalsets에 출판한다. 각 frame은 frame, identity, image, image_sha256, session, capture_group, split=eval, object_version, source, review를 가진다. source/review는 원래 검수 snapshot의 원본 기록이며 각각 authority의 source_sha256/object_review_sha256에 결속한다. classes는 D-602 이름/순서만 허용하고 classes_sha256은 object-classes.json의 파일 SHA256이다. authority_sha256은 decision_sha256이다. 이 task 필드가 없는 기존 픽셀 정답과 혼용하지 않는다. 기존 데이터·person_feet·검수용 obstacle을 변경하지 않는다.
4. 후속 `rosy_ml object-fitness MODEL --store STORE --eval DIR --inputs DIR --max-age-ns N --out FILE`은 고정 평가 정답과 별도 관측 입력을 읽는다. 내부 입력 schema는 `rosy.perception.object-inputs/1`이다. model_revision, model_manifest_sha256, eval_sha256, preprocessing_sha256, training_refs, match_iou, small_area_fraction, detector_confidence, detector_nms_iou, frames를 고정한다. 각 frame은 identity, image_sha256, domain, conditions, now_ns, image_snapshot을 가진다. 평가와 관측 identity/image 집합은 정확히 같아야 한다. 정답·simulator ID/pose는 모델 입력에 넣지 않는다.
5. 후보 직접 학습 버전을 포함한 immutable training_refs를 확인하고 선언 세션/capture group/실제 이미지 해시가 겹치면 실행을 거절한다. MCAP·변환 영상의 전체 upstream 원본 계보와 검수 독립성을 이 선언 검사만으로 증명하지 않는다. 모델·평가·입력·학습 파일을 실행 전후 검증하며 이미 있는 out 파일을 덮어쓰지 않는다. 성공 exit 0은 진단 실행 완료이고 판정은 항상 HOLD다. 오류는 exit 2이며 정상 보고서를 만들지 않는다.
6. 지표/매칭/보류/실물·시뮬레이션 분리는 D-659 설계 §10을 따른다. 모델 revision·camera profile·전처리·confidence/NMS·매칭/크기 기준을 묶고 다른 결속을 합산하지 않는다. 출판과 재생은 authenticated reviewer, live freshness, 가림 검수 독립성, 학습 upstream closure, 실제 인지 성능·수용 profile·장치 capture-to-result 지연/손실을 대신하지 않는다. 인지 승인·주행 권한은 HOLD이며 CORE 최종 writer를 변경하지 않는다.

### Implementation and verification

curation의 기존 evaluation workspace·MCAP proof·store 출판을 확장하고 evaluation의 object_fitness와 기존 ObjectDetModel을 재사용한다. tools/perception의 기존 CLI에 연결한다. 새 운영 서비스·ROS field·의존성·command writer는 추가하지 않는다. 이 문서의 계약 기록은 구현/실행 완료 증거가 아니다.

시험은 픽셀 pending과 물체 approved의 구별, explicit complete negative, 미검수·제외·구형 클래스 거절, 예약/authority/source/원본/hash drift, immutable 출판, 고정 모델/전처리/threshold/정답 identity 결속, 학습 overlap, 실행 중 변경, out 덮어쓰기 거절과 로봇 설정 없는 CLI를 확인한다. 실제 독립 정답과 성능·장치 수용은 별도 실행 증거다.

**Related:** [D-659](D-659-perception-fitness-and-road-region-semantics.md), [D-602](D-602-object-detection-use-and-person-class.md), [D-666](D-666-fixed-paired-road-fitness-replay.md), [D-475](D-475-human-reviewed-fixed-eval-truth.md), [설계 §10](../plans/2026-10-11-perception-fitness-design.md).
