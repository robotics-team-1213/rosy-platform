---
surface: core
kind: additive
slug: motion-admit-deadline-d1079
date: 2026-11-27
title: 이동 요청 수락 기한과 capability (D-1079)
---
D-1079: `POST /api/v1/navigation/{goal,bound-goal,line-handoff-goal,home,route,bound-route}`에 선택 `admit_within_s: float | null`을 추가한다. 유한한 `0 < s <= 10`이며 생략/null은 기존 동작이다. CORE HTTP 라우트 수신부터 단조 시계로 세며 본문·의존성·threadpool·localization·map grid·nav lock 대기를 포함한다. 실제 nav admission 직전 기한을 넘기면 기존 ERR-101 형식의 `409 MOTION_ADMIT_DEADLINE_EXCEEDED`이며 backend 목표를 보내지 않는다. 경계 시각은 허용한다. 수락 뒤 주행 수명은 기존 goal lease가 맡는다.

`GET /api/v1/system/capabilities`는 `navigation.admit_deadline: true`로 위 여섯 경로의 지원을 알리고, `navigation.generation_fence: true`로 `POST /api/v1/navigation/cancel`의 선택 본문 `{"advance_generation": true}`(기본 `false`) 지원을 알린다. `advance_generation: true`는 `nav._lock` 안에서 이미 IDLE/종료 상태여도 이동 없이 `owner_generation`을 1 올리고 응답 `owner`에 갱신된 `{boot_id, owner_generation, owner_run_id}`를 돌려주어, 라우트 진입 전 지연된 옛 `expected_owner_generation` 시작 요청을 `409 OWNER_GENERATION_CHANGED`로 차단한다. `bound-plan`은 필드를 상속하지만 이동을 시작하지 않으며 실행 요청은 별도 기한을 갖는다. lease 갱신·handover와 다른 구동 API는 이 기한의 적용 대상이 아니다. Status: Proposed인 D-1079와 독립 안전 검토·배포·실물 수용을 구분한다.
