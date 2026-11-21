---
surface: fleet
kind: additive
slug: identity-verdict-yaw
date: 2026-11-21
title: Fleet LED 확인 판정의 선택 yaw
history: `POST /api/fleet/detections/identity` 본문에 선택 `yaw` 추가(Vision이 이미 보냄; 이전에는 422로 전부 거절)
---
`POST /api/fleet/detections/identity` 본문에 선택 `yaw`(지도 기준 rad, 유한값만, 없으면 null)를 받아 확인 트랙에 증거로 저장한다. Vision `led_identity.decide`는 이미 `yaw`를 보내므로, 이전 Fleet은 판정을 전부 422로 거절했다.
