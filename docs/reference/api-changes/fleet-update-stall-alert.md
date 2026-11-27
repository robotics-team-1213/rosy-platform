---
surface: fleet
kind: additive
slug: fleet-update-stall-alert
date: 2026-11-28
title: 업데이터 멈춤 알림 필드
history: Additive: GET /api/fleet/updates 의 channels[].alert (age_s, 운영자만 reason)
---
`GET /api/fleet/updates` (v1.next): 감시 대상 업데이터 채널(`rosy-omx-devices-autoupdate.service`, 타이머 켜짐, 관문 `open`)이 멈췄을 때만 `channels[].alert`가 생긴다.

- `age_s`: 가드 보고 시각 기준 마지막 정상 단계(`switched`·`up_to_date`) 뒤 초. 보고의 로그 창에 정상 단계가 없으면 `null`.
- `reason`: 마지막 단계의 사유 코드(없으면 단계 이름). 운영자 권한에만 붙는다.
- 조건: `age_s`가 `ROSY_FLEET_UPDATE_ALERT_AFTER_S`(기본 3600) 이상이거나 `null`이거나, 마지막 단계가 `transient`이고 사유가 `stale`.
