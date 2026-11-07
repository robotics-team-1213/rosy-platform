## D-989 사람 핀 없이 LED·카메라·LiDAR로 기체 지도를 현장 지도에 맞춘다 — 기본은 관찰, 로봇별로 켜면 주행 앵커

**Status:** Proposed (2026-11-07, 사용자 지시: "위치 찍는 것도 서로 통신해서 lidar로 ... 서로 위치를 잡게", "맵핑 기록과 관제가 소통", "불빛도 되고", "알고리즘을 처리"). 합성 입력 시험만 했다. 실물·현장 수용은 없다. 7항은 2026-11-07 사용자 결정 "code it so auto-locate is used for driving too, and make it switchable on and off"에 따른다. **정확도는 실물 시험 전까지 재지 않았다.**

잇는 결정: [D-257](D-257-site-lane-map-and-overhead-sightings.md)(sighting은 표시 전용), [D-375](D-375-overhead-map-registration-from-lane-paint-proposal.md), [D-395](D-395-fleet-assisted-localization.md), [D-472](D-472-rosy-cam-map-and-lamp-identity.md)·D-596(LED 식별), [D-587](D-587-ceiling-marker-sightings-anchor-map-pose.md), [D-691](D-691-cam-stream-on-request.md), [D-984](D-984-robot-localization-anchor.md).

**Context:** 2026-11-07 현장 DB에서 천장 카메라 sighting은 `rosy_40`·`rosy_41`의 10-12가 마지막이고 `rosy_42`·`rosy_45`·`rosy_46`은 없었다. 원인은 코드와 설정으로 확인했다.

1. D-587 sighting은 윗면 마커가 있고 `marker_yaw_offset_deg`를 잰 로봇만 만든다. 현장 설정에는 `rosy_40`·`rosy_41`만 있다. 세 대는 설계대로 아무것도 보내지 않는다.
2. D-691 이후 Vision 추적은 스스로 영상을 부르지 않는다. 미리보기를 읽는 사람이 없으면 프레임이 없어 LED 식별도 돌지 않는다.
3. D-472 LED 식별은 마커 없이 로봇을 가려내지만 결과(`confirmed_track_pose`)는 위치뿐이고 방향이 없다. 그 위치와 로봇의 SLAM 지도를 잇는 코드도 없었다.

필요한 부품은 대부분 이미 있다. LED 식별, 추적, LOCALIZED 로봇의 LiDAR 물체(`LocalizationStatus.unmapped_objects`), peer 판정(`service_logic.peer_observations`).

**Decision:**

1. **운영자가 세션을 연다.** `POST /api/fleet/auto-locate`(이름 있는 운영자)가 카메라가 보는 로봇마다 120초 세션을 연다. 세션 동안에만 Fleet이 config에 `stream_wanted:true`를 실어 카메라를 깨운다(D-691 개정). 확인 트랙이 없는 로봇에는 기존 D-472 경로로 LED 점멸을 요청한다. 색 제한·E-Stop·caution 거절은 그대로다. 새 부호 점멸은 만들지 않았다. 한 source에서 두 대가 같은 색을 쓰거나 두 후보가 깜빡이면 이미 `ambiguous`다.
2. **두 경로로 변환을 구한다.** `site = R·slam + t`, 축척·거울 없음.
   - `span`: 확인 트랙 위치와 로봇 지도 자세의 쌍을 0.5 m 이상 벌어지게 모아 강체 적합한다. 다른 일로 움직인 로봇에서 얻는다. 이 기능은 움직임을 명령하지 않는다.
   - `peer_heading`: 서 있는 로봇의 LiDAR 물체 중 다른 확인 로봇까지의 카메라 거리와 맞는 것(±0.12 m)이 정확히 하나면 그 방향이 site 기준 방향을 준다. 후보가 둘이면 증거가 아니고, 0.3 m 안의 peer는 쓰지 않는다. 그래서 한 자리에서도 맞출 수 있다.
3. **어긋나면 멈춘다.** 맞춘 변환의 예측과 카메라가 0.15 m(기존 `max_jump_m`)를 넘게 다르거나, 적합 잔차가 0.15 m를 넘거나, 방향이 20°를 넘게 다르거나, peer가 180° 대칭 자리에 보이면 `DEGRADED`로 고정한다. 조용히 고치지 않는다. 새 세션이나 카메라 revision·지도 변경에서만 풀린다. 뒤바뀐 식별과 revision 없이 밀린 카메라가 여기에 걸린다.
4. **모르면 UNKNOWN이다.** 트랙 0.5 s 초과, 로봇이 LOCALIZED·`map` 프레임이 아니거나 `map_id` 없음, LiDAR 물체 1 s 초과, 표본 없이 10 s면 변환을 내지 않는다.
5. **기록과 관제를 잇는다.** `GET /api/fleet/auto-locate`가 `robot_map_id`↔`site_map_id` 변환·근거·쌍 수를 보여 준다. Fleet 메모리에만 두고 재시작하면 다시 맞춘다.
6. **기본은 관찰 전용이다.** 켜지 않은 로봇의 결과는 지도 자세 중재·trip·initialpose·명령에 들어가지 않는다. 로봇에 보내는 것은 기존 LED 점멸뿐이다. 정지·속도·여유·승인 한도는 켜도 끄도 바꾸지 않고, 항법은 여전히 승인 표식이 필요하다.
7. **로봇별로 켜면 주행 앵커가 된다.** 사이트 설정 `fleet.map_pose.auto_locate_robots`(로봇 id 목록, 기본 빈 목록)에 든 로봇만 쓴다. 실행 중 전환 경로가 없으므로 설정을 고치고 Fleet을 다시 시작한다.
   - **입력:** 매초 로봇의 지도 자세에 변환을 곱한 값을 `MapPoseTracker`에 `auto_locate` 앵커로 넣는다. 기존 odom 다리·첫 앵커 2회 확인·`max_jump`를 그대로 탄다.
   - **허용 목록:** `arbitrated_pose`는 이 앵커를 숨겨 `UNKNOWN`을 낸다. `driving_pose`를 부르는 곳은 trip runner(그 pose를 쓰는 trip 단계·시작 검사·trip 교통)와 `GET /api/fleet/robots/{id}/map-pose` 읽기뿐이다. `odom_to_map`도 숨긴다. 그래서 lane compliance·대형·교차로 신호·추적 영역·stuck·teach·경로 기록·guide·충전 자세·D-546 답은 이 로봇을 자세 없음으로 본다. **lane compliance 복귀 신호도 받지 않는다.**
   - **나이:** `anchor_age_s`와 `dead_reckon_m`은 마지막 카메라 확인부터 센다. trip 시작의 2 s 검사가 그대로 뜻을 갖고, 카메라 확인 뒤 1.5 m를 넘게 가면 `DEGRADED`다.
   - **주행 조건:** `span` 적합만 쓴다. `peer_heading`은 관찰 전용이다. 기준선 1.0 m 이상, 잔차 0.05 m 이하다. 방향 최악 오차는 2×0.05/1.0 = 0.1 rad(5.7°)이고, 표본에서 d만큼 떨어진 위치 오차는 0.05 + 0.1·d이므로 d ≤ 1.0 m에서 0.15 m 안이다. 가장 가까운 표본에서 1.0 m를 벗어나면 거절한다. 이 잔차는 내부 일관성이고 카메라 절대 오차는 재지 않았다.
   - **재확인:** 켠 로봇이 앵커를 받는 동안 세션을 연장해 카메라를 켜 둔다. 확인 트랙이 없으면 점멸을 다시 요청한다. 마지막 카메라 확인 뒤 90초(잠정)에 만료한다.
   - **SLAM 재시작:** 로봇의 map←odom이 틱 사이에 0.15 m·20°를 넘게 바뀌면 고정 `DEGRADED`다. 옛 원점 근처로 다시 시작한 경우와 느린 지도 변형은 여기서 보이지 않고 카메라 재확인이 막는다.
   - **잃으면:** `DEGRADED`·`UNKNOWN`·만료, 로봇이 LOCALIZED·`map` 프레임이 아니거나 로봇 지도 변경, 승인 교정 revision 변경, 로봇 상태 없음이면 다음 틱(보통 1초 안)에 앵커를 지운다. 로봇별로 나눠 처리해 한 대의 예외가 다른 로봇을 막지 않고, 예외 난 로봇은 앵커를 지운다. 틱이 멈추거나 죽으면 읽는 시점에 3 s 뒤 `DEGRADED`다. **최악은 3 s에 trip 주기를 더한 값이다.** 켠 로봇의 trip은 `pose` 사유로 닫히고 자유 주행 구간에서도 정지를 보낸다.
   - **독립 앵커:** 신선한 sighting·핀을 대체하지 않는다. 0.15 m·20°를 넘게 어긋나면 `DEGRADED`로 내리고 막는다. 세션을 새로 열어도 풀리지 않는다. 카메라 확인 2 s 안의 표본이 신선한 독립 앵커와 맞거나, 이름 있는 운영자가 `POST /api/fleet/auto-locate/{robot_id}/lift-block`을 부를 때만 풀리고, 후자는 경고 로그에 남는다.
   - **돌려보내지 않는다:** D-744·D-759로 CORE에 보내지 않는다. D-603 정렬 뒤 대기와 D-607 `stuck_heading`도 받지 않는다.
   - **켜기:** 목록에 넣고 재시작한 뒤 운영자가 `POST /api/fleet/auto-locate`로 세션을 연다. 재시작하면 변환이 사라지므로 세션을 다시 연다.
   - **끄기:** 목록에서 빼고 재시작한다. 새 추적기에 앵커가 없어 `UNKNOWN`이고, 진행 중 trip은 `pose` 사유로 닫힌다. 다만 끈 뒤에는 `_auto_locate_on`이 거짓이므로 자유 주행 구간은 기존 규칙대로 정지를 보내지 않고 로봇 deadman에 맡긴다. 차로 구간은 정지를 보낸다.

**Consequences:**

- **벽과 비교하지 않는다.** 요청한 "LiDAR ↔ 현장 지도 벽" 대조는 만들지 않았다. 현장 지도(`rosy.site_map/1`)에 벽이 없고 Fleet이 스캔을 받지 않는다. 벽 도면과 스캔 전송이 생기면 한 자리 방향 근거로 더할 수 있다.
- **혼자 서 있는 로봇은 UNKNOWN이다.** 다른 확인 로봇이 LiDAR에 보이거나 0.5 m 이상 움직여야 한다.
- **로봇이 LOCALIZED여야 한다.** LiDAR 물체와 지도 자세는 그때만 나온다. 항법이 꺼진 기체는 맞출 수 없다.
- **값은 잠정이다.** 0.5 m, ±0.12 m, 0.3 m는 실측 전 값이다. 카메라 교정은 `display-only`이고 축척은 줄자 실측 전이다.
- 세션 동안 폰이 깨어 있으므로 발열이 늘 수 있다. 세션을 120초로 묶은 이유다.

**실물 시험 전에는 켜지 않는다.** 지도 자세와 odom을 한 번에 읽지 못하는 CORE 쪽 어긋남은 D-984 착지 때 고쳐진다. D-984 브랜치는 착지 전이고 범위가 커서 합치지 않았다. 추적기와 소비자 차단 자리만 같은 방식으로 썼다.

**기각:** 새 부호 점멸(D-472가 이미 식별한다), 어긋남 자동 보정(원인을 숨긴다), 추적이 늘 카메라를 깨우기(D-691이 줄인 발열이 돌아온다), `tools/calibration/slam_map_align.py` import(Fleet 배포에 없다. 같은 강체 식을 썼다).
