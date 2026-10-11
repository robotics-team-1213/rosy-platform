# D-695 사건 실패 분류 제안과 최종 검토 분리

**Status:** Accepted (2026-10-12, source 계약)

D-681 개선 루프는 모델 오류와 관측·지도·현장 연결·장치 오류를 해당 책임으로 돌려야 한다. 모델의 분류나 파일의 content hash는 정답·운영 승인 증거가 아니다.

## Decision

기존 recording incident feedback binder에 선택적 failure analysis sidecar를 연결한다. 기존 schema /1과 모델 근거 /2는 그대로 유지한다. 선택적 분석이 있을 때만 recording feedback /3을 출력한다. 기존 Fleet export·원장·CORE API는 바꾸지 않는다.

입력 `rosy.incident.failure_analysis/1`은 정확한 subject_id/case_id와 model_feedback_digest, 1~8개 reviews를 갖는다. 각 review의 필드는 category, source, author_id, at이다. category는 judgment, observation, map, field_connection, device, unknown이다. source는 model 또는 human이며 이름 있는 작성자와 timezone 포함 시각을 요구한다. 다른 사건·변조된 근거·중복 review·추가 필드는 거절한다.

책임 제안은 각각 Decision, Perception, SiteMap, Fleet, CORE/device, unassigned로 고정한다. 이는 조직 담당자 배정이나 근본 원인 확정이 아니다. 사람 분류가 없으면 unreviewed, 사람 분류가 하나로 모이면 review_candidate, 사람 분류가 충돌하면 disputed다. 모델 의견은 사람의 검토를 대신하거나 덮어쓰지 않는다.

출력은 category·owner·source·review digest만 보존하고 작성자 이름·검토 시각 원문을 export하지 않는다. 기존 recording 원인의 review_state와 reviewed_root_cause는 유지하며 분석도 label_state UNREVIEWED다. source=human 표식 자체를 인증·독립 정답 수용으로 간주하지 않는다. 팀의 최종 검수·학습 데이터 수용은 기존 독립 경로에서 수행한다.

CLI는 기존 `--model-feedback`과 선택적 `--failure-analysis`를 함께 받는다. sidecar는 64KiB 이하만 읽고 기존 출력 파일 덮어쓰기 금지를 유지한다. inference·훈련·알림·장치 호출은 하지 않는다.

## Verification

모델 제안의 비승격, 사람 의견 충돌, 사건/hash 불일치, 잘못된 필드·작성자·시각·중복·크기, 기존 schema 호환, CLI 연결과 출력 비노출을 원격 시험한다. 합성 시험은 현장 원인·검수 정답을 증명하지 않는다.
