## D-1010 사이트 지도 프레임 결속: 활성 본문 검증, 목표·자세·경로의 프레임 거절

**Status:** Accepted (2026-11-10, 사용자 지시: "더 중요한 건 Fleet R 등에서 맵을 따올 때 틀리게 따오면 안 돼. 이 코드도 안전하게 수정해 줘."). Fleet 호스트 시험까지다. 기체·현장 수용은 없다.

잇는 결정: [D-488](D-488-site-map-draft-and-versions.md)(지도 초안·활성 버전), [D-494 3](D-494-site-trips.md)(MapPose), [D-546](D-546-line-return-localization-request.md) 6(a)(천장 자세 답), [D-593](D-593-operator-map-pin.md)(핀 앵커), [D-989](D-989-fleet-auto-locate-observation.md)(auto-locate), [D-1003](D-1003-nav2-free-goals-in-the-robot-map-frame.md)(free 목표의 기체 프레임 변환).

### Context

2026-11-09~10 R(`rosy-fleet-r`)의 Fleet DB와 코드를 읽은 결과다.

1. **R `site_map_versions`에는 서로 다른 `map_id`가 섞여 있다.** 버전 1–5는 `site`/`map_v2_fleet`, 6–7은 `world_261026`이다. 활성 버전이 바뀌면 좌표계가 바뀐다. 당일 임시 조사 스크립트가 `order by cast(version as int) desc limit 1`로 "가장 큰 행"을 골라 썼는데, 이런 추정은 제품에 들어오면 안 된다.
2. **본문 무결성 검사가 없었다.** `SiteMapStore`는 활성 행의 `body`를 그대로 파싱해 쓰고, 저장된 `sha256`과 다시 대조하지 않았다. Fleet 밖에서 편집된 행이 활성 지도로 시봉된다.
3. **프레임이 섞이는 네 곳(D-1003 기록 갭 1·5·6).** free 목표가 현장 좌표로 나가는 것(D-1003에서 변환으로 고침), D-546 천장 자세 답이 현장 프레임 자세를 기체 프레임 판정으로 게시하는 것, Fleet 교행 판정이 기체별 Nav2 경로를 한 격자에서 비교하는 것, 변환의 현장 쪽 자세가 활성 지도가 아닌 프레임에 앵커되어도 조용히 변환하는 것이다.
4. **추적 보정은 `use: display-only`다.** 화면 배치만을 위한 호모그래피(D-457)가 위치·주행 근거로 쓰이면 안 된다(geg6 한 바퀴에서 운영 스크립트가 이 보정으로 현장 위치를 계산했다).

### Decision

실패는 항상 닫는 방향(거절·정지·보류)이고, 조용한 프레임 변환은 하지 않는다.

1. **활성 지도는 한 정의로만 읽는다.** 활성 포인터는 "가장 최근에 활성화된 행"(AUTOINCREMENT `version` 내림차순 첫 행)으로 정의하고, 읽는 곳은 `SiteMapStore._active_row()` 하나다. 모든 읽기에서 `sha256(body)`를 저장값과 대조하고, 다르면 422 `SITE_MAP_BODY_HASH_MISMATCH`로 거절한다. 시작 시 손상을 만나면 활성 지도 없이 뜬다(지도가 필요한 기능은 전부 거절). 최신 행·정렬 추정으로 지도를 고르는 코드는 이 길 외에 없다.
2. **free 목표는 계획의 지도 버전에 묶인다.** `TripSteps._step_free`는 활성 버전이 trip 계획의 `map_version`과 다르면 목표를 보내지 않고 trip을 `map_version` 사유로 끝낸다. 지도 활성화가 진행 중 trip을 거절하므로(D-488) 정상 운영에서는 일어나지 않는, 일관성 깨짐을 잡는 방어다.
3. **변환의 현장 쪽 자세는 활성 `map_id`여야 한다.** `robot_frame_goal`은 기체가 자기 지도에서 LOCALIZED일 때, 현장 자세가 LOCALIZED이고 그 `map_id`가 활성 지도의 `map_id`와 같을 때만 변환한다. 다르면 `SiteFrameMismatch`로 거절하고 trip을 `map_frame` 사유로 끝낸다(현장 좌표를 그대로 보내는 폴백은 기체 지도 자세가 없을 때뿐, D-1003 3항 그대로).
4. **보낸 목표의 프레임을 trip에 기록한다.** `detail.goal_frame`에 활성 `map_id`·`map_version`, 기체 상태가 보고한 `robot_map_id`, 보낸 목표의 프레임(`robot`/`site`)을 남긴다. 기체는 이미 상태로 자기 `map_id`를 보고한다. 목표의 map_id·sha를 CORE가 명시적으로 에코하는 것은 API 계약 바꿈이 필요하므로 이번에 하지 않는다(아래 한계).
5. **D-546 천장 답은 같은 지도에서만 나간다.** `overhead_decision`은 현장 자세의 `map_id`와 기체 상태의 `map_id`가 둘 다 알려지고 같을 때만 답한다. 다르면 답하지 않고 사람으로 간다(기체는 위치 후보 상태라 변환할 짝이 없다).
6. **교행 판정은 프레임이 같은 기체끼리만 비교한다.** `console._goal`은 다른 기체의 선점 경로가 **알려진** 다른 `map_id`에 있으면 교차 판정을 하지 않고 나중 미션을 `MAP_FRAME_MISMATCH`로 보류한다. 다른 프레임에 선 로봇은 길을 막은 쪽에 두되(`NO_YIELD_SPACE`), 다른 프레임의 자세로 비켜설 자리를 계산하지 않는다. `map_id`를 보고하지 않는 기체는 기존 공유 `map` 프레임 계약(server/AGENTS)대로 비교를 유지한다.
7. **지도 자세 뷰에 프레임을 싣는다.** `pose_view`가 `map_id`를 포함해 trip 화면·기록이 프레임을 구분하게 한다. sighting·핀·auto-locate 앵커는 이미 활성 `map_id`로 걸러진다(D-494 3, D-989; `MapPoseTracker`).
8. **display-only 보정은 이미 근거가 못 되고, 그대로 둔다.** `tracking_calibrations` 기록은 `use: display-only`이고 Vision이 화면 배치에만 읽는다(D-457). sighting·auto-locate 경로는 이 보정을 읽지 않는다(`start_points`·`path_history`의 표시 전용 소비만 있다). 이번에 규칙을 바꾸지 않고, 이 ADR이 "틀린 지도를 가져오는 경로" 점검에서 display-only 보정이 위치 근거로 쓰이는 곳이 없음을 확인한 기록이 된다.

### 한계

- CORE `/api/v1/navigation/goal`에 `map_id`·지도 sha를 싣고 기체가 상태로 에코하는 대조는 API 버전·CORE 변경이 필요하다. 지금은 기체 상태의 `map_id`와 `detail.goal_frame` 기록으로 대조한다. 후속 API 주기 후보다.
- `MAP_FRAME_MISMATCH`·다른 프레임 로봇의 `NO_YIELD_SPACE` 보류는 상대 선점이 풀리거나 사람이 지도를 맞출 때까지 풀리지 않는다. 프레임이 섞인 채 여러 대를 free 운행하는 현장은 이 설계에서 의도적으로 막힌다.
- 활성 지도 본문 검증은 SQLite 행 단위다. 활성화 이후 파일 수준 조작(DB 파일 통째 교체)은 막지 않는다.
- 격자(`console.map()`)는 여전히 "응답한 첫 로봇"의 점유격자다. 프레임이 섞인 현장에서 이 격자와 bay 계산의 조합은 이번에 고치지 않았다(6항의 거절가 그 위험의 상단을 막는다).

### 검증

- 호스트: `operations/fleet/test/test_site_map_frame_safety.py`(본문 sha 불일치 거절·정상 경로, 다른 `map_id`/없는 앵커/DEGRADED 현장 자세 거절, 버전 불일치·프레임 불일치 정지, `goal_frame` 기록, `pose_view`의 `map_id`), `test_localization_pose_request.py`(다른 `map_id` 천장 답 거절), `test_server_traffic.py`(`MAP_FRAME_MISMATCH` 보류, 다른 프레임 로봇 `NO_YIELD_SPACE`, `map_id` 없는 기체는 종전 비교), `test_trip_robot_frame_goal.py`(D-1003 회귀).

### 기각

- **활성 포인터를 별도 테이블로:** 활성화가 거부 조건(진행 중 trip)과 감사 행을 이미 가지고 있어 "마지막 활성화 행" 외의 상태가 없다. 포인터 테이블은 같은 사실을 두 번 저장한다.
- **프레임이 다르면 현장 좌표를 그대로 보내는 폴백:** 기체가 자기 지도에서 LOCALIZED라면 현장 좌표 목표는 다른 곳으로 달리라는 명령이다(D-1003 갭 1의 재발). 거절이 맞다.
- **다른 프레임 경로의 교차 판정을 건너뛰기(놓아 보내기):** "모른다고 막지 않는다"는 종전 원칙은 알 수 없는 경우(빈 경로)의 가용성 규칙이다. 프레임이 **다르다고 아는** 경우는 그 반대 경우고, 충돌 판정의 존재 이유(좁은 통로 교착)를 무시하는 방향이므로 폐기.
