---
surface: cell
kind: additive
slug: omx-readiness-state-unknown
date: 2026-11-28
title: OMX readiness: 오래된 팔 상태는 알 수 없음
history: Additive: readiness arms[].state_unknown, 오래된 folded 는 null
---
`GET /readiness`(`rosy.cell-readiness.v1`)와 `GET /api/fleet/pipeline/cells/{cell_id}/readiness`(`rosy.fleet-cell-readiness.v1`)는 오래된 팔 상태를 현재 값으로 내지 않는다(v1.next).

- 각 팔에 `state_unknown`(`null` 또는 `{reason, last_observed_at}`)을 더한다. 값이 있으면 `folded` 는 `null` 이다.
- 셀 API: `folded` 는 15초 안의 `live.json`, 또는 같은 나이 안의 수동 motor-health가 접힘을 증명할 때만 값을 갖는다. `reason` 은 `board_missing`(관측기 env의 보드 by-id 링크 없음, 신선한 행보다 우선) \| `stale` \| `never_observed`. 이때 `blocking_refusals` 에 `<arm>:state_unknown` 이 들어가 `allowed_tiers_now` 에서 2가 빠지고, 실패 컨텍스트 대체 동작 fence도 대상 팔과 A/B 상대 팔의 `state_unknown` 을 거절한다.
- Fleet: `folded` 는 15초 안의 접힘 보고일 때만 값을 갖는다(부팅 기본값 포함하지 않음). `reason` 은 `stale` \| `never_observed`.
