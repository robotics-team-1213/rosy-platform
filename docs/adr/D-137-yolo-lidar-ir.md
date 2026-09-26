## D-137 YOLO는 자문역이다 — LiDAR/IR가 결정하고 영상은 증거만 낸다

**Status:** Proposed (2026-09-20, 미착지). D-136의 묶음 ADR. YOLO를 올리기 전에
안전 논증을 먼저 못 박는다 — 순서 없이 올리면 "영상이 잘 보이는데 로봇은 멈추지
않는" 상태가 된다.

**Context:** 트리에 semantic detection이 없다 (HSV evidence, ArUco만). YOLO를
`rosy-vision`에 올릴 자리는 그려져 있으나, 결정권 서열이 없으면 두 가지 파국이
온다. (a) 거짓음성: 깨진 영상의 "clear"가 정지를 막는다. (b) 권한 상승:
"사람을 봤다"는 박스 하나로 새 정지·회피를 만들면, 검증 안 된 모델이 사실상
두 번째 Command Manager가 된다 (AIV-001 위반 — 온보드 추론은 인지이지 지휘가
아니다).

**Decision:**

1. **서열 고정: LiDAR/IR metric > YOLO advisory.** YOLO가 "길이 비었다" 해도
   LiDAR가 막았다면 정지. YOLO가 사람을 봐도 LiDAR 근거 없이 새 정지를 만들지
   않는다. YOLO 출력은 CORE 정책 스냅샷의 advisory 입력일 뿐이다.
2. **출력은 박스가 아니라 typed evidence.** `DetectionEvidence`
   (class, bbox 정규화, conf, stamp, seq, model rev, 입력 규격/fps/지연 메타) —
   control의 `TranslationEvidence`/`TrackedEvidence`와 같은 immutable 스냅샷
   패턴. CORE는 후보별로 재평가하고 stale이면 폐기한다.
3. **모델은 generation 바인딩.** 가중치 버전·digest·입력 규격을 D-47 패턴으로
   관리. 모델이 바뀌면 evidence revision이 바뀌고, CORE가 모르는 revision은
   fail-closed. "어떤 모델이 봤다"가 증거의 일부다.
4. **트리거 게이트:** YOLO 단독으로는 영상 버스트 전송을 트리거할 수 없다.
   전송 조건은 YOLO + LiDAR/IR corroboration 또는 operator 요청. 오탐 폭주율이
   버스트를 만들지 못하게 한다.
5. **해금은 metric + 사람만.** e-stop 해제는 fresh LiDAR/IR + 명시적 operator
   action. YOLO "clear"는 필요조건도 충분조건도 아니다.

**Alternatives:** YOLO 동등권안 — LiDAR와 동등한 정지 권한. 모델 미검증 상태에서
권한을 주면 안전 논증이 모델 품질에 종속된다. YOLO 우선안 — 카메라는 가려짐·
역광·야간에 깨지고 LiDAR는 안 깨진다. 물리 순서가 반대다. 현상 유지(YOLO 없음)
— HSV/ArUco만으로는 사람·케이블 같은 비정형 장애물을 못 본다. 필요는 인정하되
서열을 먼저 둔다.

**Consequences:** `vision/detections` 토픽 단일 발행자(D-2 확장 규칙), 이중
발행은 결함으로 테스트 고정. 모델 교체는 재배포가 아니라 generation 전이로
다뤄진다 (rollback 포함). D-136의 evidence 무효 조건(신선도 >300ms, 드롭율
>30%/1s)과 합쳐져 "못 본 것"과 "없는 것"이 시퀀스로 구분된다.

**Validation / Transition:** 계약 시험 — vision 단독 정지 불가(정책 스냅샷에
advisory로만 반영), unknown revision fail-closed, 단독 버스트 트리거 불가,
해금 경로에 vision 없음. ROS-SIM에서 거짓음성 주입(깨진 영상 + LiDAR 장애물 →
정지 유지). 실행 계획:
`docs/plans/2026-09-20-yolo-advisory-sequence-plan.md`.

**References:** D-2, D-38, D-47, D-136, AIV-001
(`2026-09-05-vision-accelerator-shield-design.md`), FOR-004.

**부분 구현 기록 (2026-09-25, Proposed 유지):** SAF-006 자문역 일부가 구현됐다
(`core_features/safety/manager.py:92` `person` 자문, `person_advisory_from`, API Ref §6.1.1 `DetectionEvidence`).
단 본 ADR의 Transition(계약 시험 + ROS-SIM 거짓음성 주입 + 실행 계획)은 미완이므로 Accepted로 뒤집지 않는다.

---
