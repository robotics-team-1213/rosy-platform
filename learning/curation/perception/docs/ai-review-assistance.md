# AI 도움으로 라벨 검수 시간을 줄이는 방법

조사일: 2026-10-13. 소스 확인 범위: `fix/review-tools-eeb165` 작업 공간. 아래의 **구현됨**은 소스에 경로가 있다는 뜻이며 운영 설치·모델 추론·정답 품질을 확인했다는 뜻이 아니다. 이번 조사는 원본 업로드, 추론 작업 실행, 라벨 변경을 하지 않았다.

지금은 새 모델을 붙이기보다 **기존 초안 → 합친 결과 미리보기 → 255만 보완 → 작은 영역 수정 → 사람 승인**을 먼저 쓰는 것이 가장 작다. 사람의 저장 라벨을 보존하는 경로는 이미 있다. AI가 사람 표시를 읽어 새 후보를 만드는 전체 흐름은 후속 계약과 구현이 필요하다. [검수 작업대 계약 D-542](../../../../docs/adr/D-542-human-guided-review-workspace-ux.md), [현재 앱 안내](review-app.md)

## 지금 쓸 수 있는 도움과 추가할 도움

| 방법 | 현재 범위 | 검수자가 하는 일 | 추가로 필요한 것 |
|---|---|---|---|
| 남은 255만 AI 초안으로 보완 | **구현됨:** 후보 선택·합친 결과 미리보기·부분 병합 | 원본과 미리보기를 비교하고 `255만 초안 보완` 후 남은 곳을 수정 | 사람 revision을 입력으로 새 후보를 재생성하는 요청/작업 상태는 별도 구현 |
| 점 선택·다각형·브러시로 경계 수정 | **구현됨:** Lab 색 영역 선택, 다각형, 브러시. 점 선택은 학습 AI가 아닌 색 기반 도구 | 넓은 같은 색은 여러 점, 다른 색이 섞인 영역은 다각형, 작은 경계는 브러시 사용 | AI 클릭 분할은 기존 점 선택과 구별한 별도 후보 경로 필요 |
| AI가 의심한 사진부터 검토 | **일부 구현됨:** prelabel 점수·노출 보고·VLM 참고 의견 | 점수가 높거나 판단 보류인 사진을 먼저 확인하되 나머지도 검수 | 보고서를 작업 목록의 정렬/필터로 연결하는 기능은 제안 |
| 한 프레임의 표시를 인접 프레임에 전파 | **오프라인 일부 구현됨:** SAM3 차선 텍스트 후보와 점 시드 기반 짧은 구간 추적 | 가림·교차점·재등장 구간에서 후보를 다시 확인 | 사람의 수정 점/영역을 기존 추적기에 넣는 계약과 연결은 제안 |
| 누락 객체만 후보로 제안 | **일부 구현됨:** 객체 후보 등록·미리보기·적용 | 원본에서 실제 객체를 확인하고 기존 박스와 비교 | 사람 박스를 보호하며 누락만 선택 병합하는 흐름은 D-542의 후속 과제 |
| 서로 다른 후보가 다르게 칠한 곳을 강조 | **제안:** 같은 의미의 두 후보 간 불일치 영역 표시 | 불일치 위치와 원본을 집중 비교 | 같은 원본·클래스 의미·좌표에 묶인 후보끼리 비교; 합의도 정답으로 간주하지 않음 |

근거: [픽셀 편집·후보 UI](../review_app_web/pixels.js), [객체 후보 UI](../review_app_web/app.js), [후보 등록](../review_ingest.py), [prelabel 점수](../prelabel.py), [노출 보고](../review_quality.py), [SAM3 오프라인 생성](../sam3_road_draft.py). 위 표의 제안은 현재 버튼이나 API가 있다고 주장하지 않는다.

## 부분 보완에서 실제로 보호되는 것

`review_masks.merge_unknown`은 **현재 마스크가 255이고 후보가 255가 아닌 위치만** 채운다. 현재 0–254 라벨을 사람이 그렸는지 AI가 그렸는지 따로 판별하지 않고 모두 보존한다. 후보에도 255인 곳은 남는다. 따라서 이전 AI 오류가 이미 0–254로 저장됐다면 부분 병합이 그 오류까지 고쳐 주지는 않는다. 잘못된 저장 영역은 사람이 직접 수정해야 한다. [병합 구현](../review_masks.py)

`merge_draft`는 현재 픽셀 version을 검사하고 적용 후 승인 상태를 대기로 둔다. `apply_draft`는 전체 교체이므로 기존 라벨 보존과 다르다. 후보 PNG·원본·클래스 바이트의 SHA 검증은 있으나, 후보가 **어느 사람 라벨 revision에서 생성됐는지**를 결속하는 전체 계약은 아직 없다. 같은 시점의 적용 충돌을 막는 version 검사와 오래된 생성 근거의 판별은 별개다. [픽셀 update·draft_preview](../review_masks.py), [등록 해시 검사](../review_ingest.py), [D-542 §7–8](../../../../docs/adr/D-542-human-guided-review-workspace-ux.md)

## AI 의견의 의미와 최신성 제한

현재 VLM은 원본과 마스크 overlay를 보고 `concern`, `no_obvious_concern`, `uncertain`을 내며 실패하면 `abstain`으로 남긴다. 전체 보고서 게시에는 작업 공간 ID·generation·전체 표본 수와 review binding이 일치해야 한다. 앱의 `current`는 해당 원본/마스크 SHA뿐 아니라 클래스 SHA·전체 클래스 정의의 해시·명시 의미·프롬프트/응답 형식 해시가 같아야 한다. binding이 없는 기존 보고서는 오래된 의견으로 표시한다. 다른 사진 변경은 `workspace_changed`로 구별하며 픽셀 revision 숫자 자체는 비교하지 않는다. [analyze·publish_feedback·read_current_feedback](../vlm_mask_feedback.py), [앱 AI 의견 표시](../review_app_web/pixels.js)

현재 프롬프트는 흰 차선 안쪽 바닥을 판단한다. 배치 분석과 단일 프레임 worker 모두 추론 전에 `road_surface/1`, `trajectory_band/1`, null 및 미지원 의미를 거절한다. `current_road_region/1`과 의미 필드가 없는 구형 입력만 기존 차선 판단을 유지한다. 구형 입력에 새 의미를 추정해서 붙이지 않으며 전체 도로면 추론은 지원하지 않는다. 클래스 의미나 프롬프트가 바뀌면 새 검사가 필요하고, 이 의견은 사람 승인이나 학습 자격을 만들지 않는다. [feedback_binding](../vlm_mask_feedback.py), [단일 프레임 worker](../review_ai_worker.py), [의미 계약 D-663](../../../../docs/adr/D-663-versioned-road-label-semantics.md)

`road_surface/1`은 보이는 도로 바닥 전체이고 `current_road_region/1`은 로봇이 속한 구획의 가시 영역이다. 둘 다 선택 경로나 주행 허가는 아니다. 일반 병합은 road_surface를 자기 차선 안으로 자르지 않지만 구형/현재 구역의 기존 차선 제한은 유지한다. 자기 도로 초안을 만드는 clipping/Qwen 도구의 입력 범위도 그대로 지킨다. [D-663](../../../../docs/adr/D-663-versioned-road-label-semantics.md), [lane_boundary_classes·merge_unknown](../review_masks.py)

## 추가 AI 방법의 우선순위

1. **먼저 기존 후보와 편집 도구를 사용한다.** 오프라인 pixel label job 또는 기존 SAM3 결과를 가져와 부분 병합한다. 승인과 학습 자격을 만드는 작업은 별개다. 새 모델 의존성은 필요 없다. [pixel_label_job](../pixel_label_job.py), [앱 안내](review-app.md)
2. **AI 의견의 결속을 확인한다.** 클래스 정의·의미와 원본/마스크 SHA, 모델 digest 및 프롬프트 해시는 기록한다. 현재성의 정확한 보호 범위는 위와 같으며 사람 기준 revision 숫자나 실제 정답 품질의 검증은 별도 과제다. 전체 도로면 전용 AI 의견을 추가하려면 의미에 맞는 프롬프트와 독립 검증이 먼저 필요하다. [D-542](../../../../docs/adr/D-542-human-guided-review-workspace-ux.md), [현재 VLM](../vlm_mask_feedback.py)
3. **그 뒤 사람 점으로 후보를 보완한다.** 포함점·제외점 또는 좁은 관심영역을 오프라인 SAM3에 전달하고 결과를 미적용 후보로만 돌려준다. 현재 Lab 선택과 이름을 구별하고, 전체 교체 대신 255 보완을 기본 경로로 검토한다. Meta 공식 SAM3 예제는 텍스트/박스와 영상의 점 보정을 제공하고, CVAT도 관심영역 안의 클릭 분할을 설명한다. 이는 ROSY에 이미 연결됐다는 증거가 아니다. [Meta SAM3](https://github.com/facebookresearch/sam3), [CVAT AI 도구](https://docs.cvat.ai/docs/annotation/auto-annotation/ai-tools/)
4. **영상은 짧게 전파하고 실패 구간을 먼저 보여준다.** SAM2도 점/박스 입력 후 영상 전파를 제공하지만 ROSY에는 SAM3 경로가 있으므로 SAM2를 별도 설치할 이유는 품질/시간 비교 결과가 있을 때만 검토한다. 새 가림·경계 변화·재등장은 검토 대상으로 남기고 프레임별 후보를 자동 승인하지 않는다. [Meta SAM2 예제](https://github.com/facebookresearch/sam2), [기존 track_carpet](../sam3_road_draft.py)

prelabel의 현재 score는 confidence·정규화 entropy·차선 픽셀 부족을 더하며, 기록 error_delta는 같은 model revision일 때만 더한다. 모든 클래스 의미에 검증된 오류 확률이 아니므로 이 수치를 정답 확신으로 표시하지 않는다. 도로면 전용 우선순위는 의미에 맞춘 별도 검증이 필요하다. [score_frame](../prelabel.py)

## 실제로 빨라졌는지 확인하는 작은 시험

아래는 **시험 제안**이며 측정 결과가 아니다. 여러 capture group에서 밝기·가림·얇은 차선·교차점을 포함한 고정 표본을 고른다. 사람이 원본으로 먼저 만든 독립 정답은 AI 후보와 별도로 보관하고 학습/eval session을 섞지 않는다. 동일 사진을 두 번 본 학습 효과를 줄이려면 비슷한 난도의 두 묶음을 준비하고 검수자별 수동/보완 순서를 교차한다. [독립 고정 정답 D-475](../../../../docs/adr/D-475-human-reviewed-fixed-eval-truth.md), [CVAT 독립 GT 작업](https://docs.cvat.ai/docs/qa-analytics/auto-qa/)

사진을 연 순간부터 사람이 결정할 때까지의 총 시간(추론 대기 포함), 수정 횟수·되돌리기·실패/충돌, 최종 클래스별 IoU와 경계 오류, 장애물을 도로로 칠한 오류를 기록한다. 중앙값과 느린 사진의 시간을 함께 보고 capture group별 차이도 확인한다. 같은 AI의 자기 평가를 품질 정답으로 사용하지 않는다.

원본/클래스/마스크가 바뀐 오래된 결과, 남은 255, 모델 응답 없음, 보호 라벨의 변경 여부를 별도로 확인한다. **보호 0–254 변경 0개·자동 승인 0건**은 기능 검증 기준이고, 시간 단축·품질 개선 수용 기준은 시험 전에 정한다. 보완이 느리거나 잘못된 확신을 만들면 기존 점/다각형/브러시로 돌아간다. 호스트 테스트·브라우저 성공·사람 정답 품질·학습 수용·장치/현장 주행은 각각 다른 증거다. [D-542](../../../../docs/adr/D-542-human-guided-review-workspace-ux.md), [D-663](../../../../docs/adr/D-663-versioned-road-label-semantics.md)
