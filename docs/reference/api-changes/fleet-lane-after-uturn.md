---
surface: fleet
kind: additive
slug: fleet-lane-after-uturn
date: 2026-11-27
title: 유턴 뒤 lane 간선은 카메라 차선 추종으로 실행
history: 기존 trip의 유턴 뒤 lane에 CAMERA_LINE을 강제하고 전환 거절은 이유 있는 hold로 유지
---

기존 Fleet trip은 `turnaround` 장소에서 UTURN으로 분류되는 전환 뒤에 lane 간선이 남으면,
요청의 `drive_mode: nav2` 여부와 관계없이 유턴까지 Nav2, 이후 지도 간선별 실행을 사용한다.
lane은 CAMERA_LINE이고 free는 기존 Nav2 목표다. 정밀 정차의 lane STOP →
`line-handoff-goal`·기존 정차 확인을 유지한다. 요청 경로·필드와 CORE 계약은 추가하지 않는다.

유턴 전 경로의 마지막 stop 하나에 나가는 간선 yaw를 준다. main의 RPP
`allow_reversing: false`, `use_rotate_to_heading: true`, `rotate_to_heading_min_angle: 0.70`을
사용하며, 같은 좌표의 별도 회전 stop은 넣지 않는다(D-1009).

기존 trip `detail`의 `uturn_handoff`는 전환 인덱스와
`approaching|starting|running` 단계를 기록한다. 전환은 정지 실측·살아 있는 trip lease·카메라·
실제 lane-cue 수락·지도 자세·진입 방향·차로 안 몸체·통행권을 다시 확인한다.
확인 실패는 기존 `hold.reason: fleet_hold`와 `hold.code`·`hold.detail`·`hold.stop`에 남긴다.
카메라 거절을 Nav2로 대체하지 않는다. 뒤쪽 lane의 추가 UTURN도 기존 `LANE_UTURN` 거절을 유지한다.

cue의 명시적 거절은 즉시 hold다. timeout·5xx·연결 오류는 연속 3회 또는 첫 실패부터
2초일 때 hold하며, 수락 증거는 2초(0.5초 cue 주기의 4배) 뒤 만료된다. 새 수락 전에는
전환을 정지 상태에서 재시도하며, 주행 중 증거가 만료되면 새 지시를 보내지 않는다.
유턴 전 Nav2 거절·취소·stall도 이유를 남긴 재개 가능한 hold로 보존한다.

재개는 전환을 다시 입회한다. 이미 ARRIVED인 경로의 cancel에 ACK가 없으면,
기존 동일 wire·cancel 뒤 신선한 정지 실측으로 확인할 수 있다. PUT 결과가 모호한
`starting` 단계에는 이 예외를 적용하지 않고 두 소유자 정지 확인을 유지한다.
재시작은 기존 규칙대로 trip을 종료하며 자동 출발하지 않는다.

콘솔의 차선 거절 뒤 Nav2 자동 재요청 동작은 기존대로 유지하며, 유턴 운행은 Fleet 서버가 강제한다.
Python/웹 시험과 실물 검증은 실행하지 않았다.
