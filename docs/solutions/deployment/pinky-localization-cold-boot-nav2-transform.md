---
title: "Pinky 콜드부트에서 AMCL TF 이후 Nav2 시작"
date: "2026-11-23"
module: "Pinky hardware Nav2 localization"
problem_type: runtime_error
component: deployment
severity: medium
symptoms:
  - "콜드부트 후 LOCALIZED가 되어도 global_costmap이 inactive에 남고 goal_navigation이 false였다."
root_cause: logic_error
resolution_type: code_fix
tags: ["pinky", "nav2", "amcl", "tf", "lifecycle"]
---

# Pinky 콜드부트에서 AMCL TF 이후 Nav2 시작

Pinky 릴리스 `2026.11.23-230`을 `localization`으로 콜드부트했을 때 `global_costmap`에서 `Invalid frame ID "map"`이 발생했다. 이후 자세가 `LOCALIZED`로 바뀌어도 `planner_server` 뒤의 Nav2 노드가 `inactive`에 남았다. 당시에는 자세 확정 뒤 비활성 노드를 순서대로 활성화해 `goal_navigation`을 회복했다.

## 원인과 수정

AMCL은 유효한 초기 자세와 스캔을 처리해야 `map → odom` TF를 발행한다. 초기 자세가 들어올 시점은 부팅 시점에 정해져 있지 않다. 코스트맵의 TF 대기 시간이 먼저 끝나면 Navigation lifecycle manager의 시작 요청이 실패한다. 나중에 TF가 들어와도 이미 실패한 lifecycle 전이는 이어지지 않는다.

로봇의 `localization` 시작 경로에서 `map_server`와 AMCL은 먼저 시작한다. 독립 시작 노드는 실제 코스트맵 파라미터의 프레임을 읽고 두 코스트맵의 TF를 확인한 뒤 Navigation lifecycle manager에 `STARTUP`을 한 번 요청한다. CORE는 기존 lifecycle 관측과 준비 조건으로 `goal_navigation`을 판단한다.

## 재확인과 현장 복구

- ROS 2 Jazzy 실험실에서 패키지를 빌드했다. 합성 `odom → base_footprint`만 있을 때 시작 요청은 0회였다. `map → odom`을 추가하자 테스트 서비스가 `STARTUP`을 1회 받았다. 기체에서 실제 AMCL·코스트맵을 사용한 콜드부트 수용은 별도로 남아 있다.
- 새 릴리스에서 다시 발생하면 `LOCALIZED` 표기와 함께 두 코스트맵 TF, Navigation lifecycle manager의 응답, `global_costmap` lifecycle 상태를 확인한다. TF가 빠져 있으면 AMCL·odom 경로를 먼저 확인한다. TF가 정상인데 매니저가 실패했다면 원인 로그와 현재 상태를 수집한 뒤 기존 lifecycle 관리 절차로 복구한다.

부팅 중 `map_grid_id`가 사라지는 별도 문제의 관측과 복구는 [5 cm 지도 및 map_server 교훈](localization-5cm-slam-map-and-map-server-lifecycle-2026-11-23.md)에 있다.
