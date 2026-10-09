# 천장 마커 번호 = 로봇 번호 현장 확인 — 2026-10-09

D-562(로봇 번호 40–49 = 천장 ArUco 번호)와 D-565(번호를 바꾼 TLS 로봇 재등록)를 현장에 적용하고 Rosy Cam으로 확인한 회차다. 장치·현장 표시 확인이며 주행 수용이 아니다.

## 한 일

| 항목 | 내용 |
|---|---|
| 스티커 | `DICT_4X4_50`, 전체 40 mm(검은 사각형 30 mm, 흰 테두리 1칸), 윗변 = 로봇 앞 |
| 8kcn | `rosy_60` → `rosy_40`(ROS_DOMAIN_ID 80). `runtime.env` 세 키와 `complete.json`의 `dds` 블록, 재부팅 |
| 9dfk | `rosy_26` → `rosy_41`(ROS_DOMAIN_ID 81). 같은 절차 |
| Fleet | 옛 번호 등록 해제(`removed` 확인) → TLS binding을 새 번호로 바꿈 → 화면 코드로 재등록(D-565 경로) |
| 사이트 카메라 설정 | `robot_markers: {rosy_40: 40, rosy_41: 41}`, `heading_edge: [0, 1]`(스티커 윗변이 앞) |
| 사이트 자동 갱신 | 기능 확인 `required_ids`를 `rosy_40`, `rosy_41`로. 옛 번호를 남겨 두면 갱신이 "functional API is missing configured IDs"로 거절된다 |

## 관찰

| 항목 | 값 |
|---|---|
| 식별 램프 대조 | 8kcn 주황(후면 램프)이 마커 40 로봇에, 9dfk 파랑이 마커 41 로봇에 켜짐 |
| 마커 40 | 기본 검출값으로 매 프레임 검출, 한 변 약 13 px(1280×720) |
| 마커 41(9dfk) | 트랙 왼쪽 끝·벽 옆에서 한 변 약 7 px, 옛 Vision에서는 거의 놓침 |
| D-565 사이트 적용 뒤 Fleet `/api/fleet/tracking` | `rosy_40` MARKER (−0.00, −0.52) m, `rosy_41` MARKER (−1.28, −0.52) m, 익명 blob 없음 |
| 로봇 공개 identity | `receiver_id` `rosy_40`, `rosy_41` |

## 배운 것

- 번호 바꾸기에는 지원 도구가 없다. 순서는 Fleet 등록 해제 → 로봇 번호 변경 → 사이트 binding·카메라·자동 갱신 확인 → 재등록이다. 등록 해제를 먼저 하지 않으면 옛 행이 `pending_logout`으로 남는다.
- TLS 필수 로봇의 `ROSY_API_TLS`만 `none`으로 바꾸면 CORE는 여전히 HTTPS로 뜨고 `wait-core-ready`가 HTTP를 기다려 재시작을 되풀이한다. 되돌렸다.
- 사이트 `heading_edge`는 스티커 방향과 맞아야 한다. `[1, 2]`면 방향이 90° 틀어진다.

## 한계

한 번의 정지 관찰이다. 움직이는 로봇의 검출률, 조명 변화, 장소 마커(D-564) 실물은 확인하지 않았다. 위치 수치는 표시용 보정(`display-only`) 기준이다.
