---
surface: fleet
kind: additive
slug: fleet-e2e-pipeline-dispatch
date: 2026-11-24
title: Fleet 파이프라인 E2E 배차·depart_s3·재주차 복구 계약
history: Additive: pinky_dispatch_enabled, depart_s3 출구 배차, cell robot_id 해석, repark ABORTED 대체
---
`GET /api/fleet/pipeline/cell-tasks` 와 `GET /api/fleet/pipeline/pinky-tasks` 는 D-1060 디스패처 활성 여부를 나타내는 불리언 `pinky_dispatch_enabled` 를 반환한다(v1.next).

* `POST /api/fleet/pipeline/pinky-tasks` 의 `depart_s3` 액션은 `site_rules.return_.exit_place` 를 `place_id` 와 `target_place` 로 설정하고 `unload_batch_id` 를 기록한다. 출구 장소가 없으면 `unload_releases` 를 예약하지 않고 `409 NO_EXIT_PLACE` 를 반환하며, 디스패치/트립 시작 직전 `unload_release` 를 재검증해 트립 시작 전 실패·거부·취소 시 `OPERATOR` 예약을 해제한다(v1.next).
* `POST /api/fleet/pipeline/cell-tasks` 및 `POST /api/fleet/pipeline/decision-gate`(`arm_target`)는 `robot_id` 를 명시 입력(공백·비문자열은 `422 INVALID_ROBOT_ID`) -> 셀 도킹 로봇 -> `"rosy_01"` 순으로 해석한다(v1.next).
* `POST /api/fleet/pipeline/repark/{request_id}` (`DONE`)는 완료된 재시도 태스크가 동일 `(unload_batch_id, robot_id, unload_index, repark_root)` 의 `ABORTED` 행을 대체해 `unload-release` / `continue_unload` 진행을 허용하고, 안전 조건(사람 미감지·팔 홀드 없음·실행 태스크 없음·신선한 `folded: true`) 충족 시에만 `ABORTED` 셀 상태를 복귀한다(v1.next).
