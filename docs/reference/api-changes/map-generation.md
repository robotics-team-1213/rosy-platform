---
surface: core
kind: additive
slug: map-generation
date: 2026-11-21
title: 지도 세대 map_generation
history: Additive: StateSnapshot·GET /navigation/state 의 map_generation(SLAM 지도 원점이 바뀌었을 수 있을 때마다 바뀌는 영속 카운터)
---
`StateSnapshot`(`/ws/state`, 하트비트)와 `GET /api/v1/navigation/state` 에 선택 정수 `map_generation` 을 더한다. SLAM 지도 원점이 **바뀌었을 수 있을 때마다** 바뀌는 카운터다: 항법 스택(slam_toolbox, map_server)의 lifecycle 이 ACTIVE 가 될 때마다 +1(항법만 다시 시작해도 바뀐다), CORE 를 시작할 때마다 +1(rosy-navigation 이 rosy-core 를 Requires 하고, CORE 가 구독하기 전에 지나간 재시작은 이벤트가 없다). CORE 데이터 폴더의 작은 파일에 저장해 CORE 재시작 뒤에도 같은 값을 되풀이하지 않는다(파일이 없거나 깨졌으면 벽시계 초에서 시작한다). `boot_id`·`map_id`·`map_grid_id` 와 무관하다: `map_grid_id` 는 격자가 자랄 때마다 해시가 바뀌어 원점 토큰으로 쓸 수 없다. 소비자는 **다른지(≠)만** 본다: 크기·순서를 쓰지 않고, 항상 `boot_id` 와 같이 `(boot_id, map_generation)` 쌍으로 비교한다. 알아내지 못하는 것: lifecycle 전환 없는 slam_toolbox 내부 초기화·지도 교체, 루프 클로저로 map->odom 이 크게 밀리는 것, AMCL 재시작(프레임은 그대로이고 추정만 잃는다). (v1.next)
