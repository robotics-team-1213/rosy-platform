---
surface: core
kind: additive
slug: named-stop-core-receipts
date: 2026-11-21
title: 이름 정차용 Nav2 실행 영수증·격자 결속 목표·차선 인계
history: Additive: CORE `POST /api/v1/navigation/bound-goal`은 승인된 격자 ID로 목표 수락을 제한한다. Fleet `road-nav2`는 이름 기반 정차에서 `expected_site_map_version`과 승인 정합을 확인한다. `dry_run: true`는 요청을 큐에 넣지 않는다. 단독 Nav2 정차는 양방향 자유 구간만 있고 차선 제어·회전 제한·횡단보도가 없는 지도에서 허용한다. 충전 관리 기체는 이 경로에 들어가지 않는다. Additive: CORE `POST /api/v1/navigation/line-handoff-goal`은 현재 주행 임대, 유지 중인 차선 STOP, 격자·부팅·소유권 세대를 동일 요청으로 확인한다. 기존 Nav2 실행 영수증을 반환한다. Additive: `POST /api/v1/navigation/handover`의 선택적 `expected_map_grid_id`를 같은 인계에서 확인한다. 일치하면 `map_grid_id`와 `idle_mode_epoch`를 반환한다. `POST /api/v1/navigation/bound-plan`으로 구동 없이 경로를 요청한다. `bound-goal`과 `line-handoff-goal`은 같은 계획 ID를 요구하고 해당 경로의 실행 조건을 재검사한다. CORE에서 실행 소유권을 발급하기 전에 요청을 거절하면 `error.detail`에 요청의 `plan_id`와 `native_admitted: false`를 반환한다. 소유권을 발급한 뒤에는 이 근거를 반환하지 않는다. `evidence.velocity.sampled_at`에 검증된 속도 측정 구간의 끝 시각을 UTC로 제공한다. `received_at`은 CORE 수신 시각이다. 시간 기준을 확인할 수 없거나 측정이 만료되면 `sampled_at`은 null이다. Fleet은 Nav2 종료 증거보다 뒤의 서로 다른 0속도 표본 두 개로 점유 해제를 검증한다.
---

