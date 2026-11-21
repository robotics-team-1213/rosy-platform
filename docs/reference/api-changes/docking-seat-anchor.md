---
surface: core
kind: additive
slug: docking-seat-anchor
date: 2026-11-21
title: 도킹 안착 앵커 (docking anchor)
history: Additive: GET /docking/status·StateSnapshot.docking 의 anchor(칸 안착 순간 짝), 이벤트 docking.anchor
---
`GET /api/v1/docking/status`(와 `StateSnapshot.docking`)에 선택 필드 `anchor`(객체 또는 `null`)를 더한다. 로봇이 칸에 **지금** 앉아 있다는 순간 짝이다: `{dock_id, confirmation: "lidar_reference"|"inferred", source: "docked"|"startup_probe", odom_pose: {x, y, yaw, stamp, epoch, mono_s}, boot_id, map_id, along_m, lateral_m, heading_deg, inliers, margin, at, age_s}`. Fleet 은 `odom_pose`(로봇 odom 프레임의 자세와 CORE 벽시계 stamp, epoch)를 그 칸의 현장 자세(위치와 방위)에 묶고 이후 odom 변위로 이어 간다. `confirmation` 은 항상 `"lidar_reference"` 다: 멈춘 LiDAR 스캔이 도크의 기준 스캔과 맞았다는 뜻이고 `along_m`·`lateral_m`·`heading_deg`·`inliers`·`margin`(모두 숫자) 이 그 안착 오차다. 스캔이 맞지 않으면(충전 접점만 확인된 DOCKED 포함) 앵커를 내지 않는다. DOCKED 앵커는 안착 스캔부터 DOCKED 선언까지 바퀴 오도메트리가 3 mm / 0.01 rad 안에서 서 있었을 때만 낸다. Fleet 은 상태 스냅샷의 `docking.anchor` 를 폴링해 `(dock_id, odom_pose.epoch, at)` 로 구별해 읽고, 이벤트는 로그용이다. 앵커는 `odom_pose.epoch` 가 지금 odom epoch 와 같을 때만 보인다(CORE 재시작이나 odom 불연속이면 `null`). `age_s` 는 읽는 시점 기준이다. 이벤트 `docking.anchor` 는 §8 표에 있다. 새 칸에 앉을 때마다 새로 기록되고 기존 필드·동작은 그대로다. 앵커에는 그 순간의 `StateSnapshot.map_generation`(SLAM 지도 원점 세대, 없는 CORE 에서는 `null`)이 `map_generation` 필드로 실린다. (v1.next)
