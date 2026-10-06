## D-481 Fleet이 지도 자세로 차선 경로를 주행시키고, 카메라 인식과 무관하게 녹화하며, 지도 초안 라벨을 검수 대기로만 만든다

**Status:** Proposed (2026-10-06, 사용자 요청 "Fleet으로 해서 우리가 오로지 맵으로만 주행하게 하는 기능도 필요할 거 같아. Fleet과 Rosy(Cam)를 통해서. 그러면서도 영상을 녹화하고 거기에 따른 학습데이터 수집도 충분히 가능할 거 같아. ADR로 기록."). 설계 결정이다. 코드, API 참조서, 설정, 로봇 주행은 바꾸지 않는다. 오늘 이 기능을 쓸 수 있다는 뜻이 아니다. 아래 선행 게이트가 닫히기 전에는 장치에서 실행하지 않는다.

잇는 결정: D-330, D-379, D-395, D-411, D-412, D-422, D-424, D-427, D-429, D-430, D-457, D-463, D-464, D-465, D-472, D-475, D-476. 번호 충돌 주의는 「번호 충돌」 절에 있다.

### Context

- **오늘의 실기 사실(rosy_26 / 9dfk, 2026-10-06).** 차선 카메라 추종(CAMERA_LINE)이 시작되지 못했다. 로봇이 차선 위에 있지 않았고 과노출이 있었으며, 학습된 차선 모델이 바닥을 벽으로 읽었다. 학습 데이터 수집이 지금 개선하려는 바로 그 인식에 의존했다. 수집용 감독 주행 고리는 일회성 스크래치 도구로만 있다.
- **Fleet 지도 경로는 이미 있다.** `POST /api/fleet/robots/{robot_id}/route`(D-463)는 `lane_graph.yaml`의 간선 id 순서 `edges`(1~8개)를 받아 폴리라인 위 약 0.20 m 앞의 점 하나만 기존 goal 경로로 보낸다(`operations/fleet/fleet/server/lane_route_routes.py` `RouteRequest`, `operations/fleet/fleet/lane_route.py:25-28` `STEP_M`·`OFF_M`·`DONE_M`·`MAX_EDGES`). 점은 `task_service.submit_navigation`을 거치고 `Idempotency-Key`가 필요하다. 이 경로는 한 호출에 한 점이다. 지금 쓰는 "어디까지 따라갔나"는 Fleet 프로세스 메모리의 `followed` 딕셔너리다. 호출을 되풀이하는 주체와 종료 조건은 코드에 없다.
- **자세를 믿는 조건이 이미 막혀 있다.** `console.trusted_map_pose`(`operations/fleet/fleet/server/console.py:631`)는 스냅샷이 `LOCALIZED`이고 `pose_frame`이 지도일 때만 좌표를 돌려준다. 레거시(위치 블록 없음), 오도메트리, 재시작 유예는 `None`이고 응답은 `ROUTE_POSE_UNTRUSTED`다(D-463 §4). 이 경로는 AMCL, `initialpose`, ArUco, 천장 맞춤을 자세로 쓰지 않는다(D-463 §5).
- **그런데 장치에는 그 자세가 없다.** `robot/state.localization`은 장치에서 null이다. `hardware.launch.py:161`의 `enable_loc_assist` 기본값이 `false`다.
  - D-395 개정 5는 항목 1~4가 닫히기 전에는 장치에서 `enable_loc_assist`를 켜지 않고 실기 S3를 하지 않는다고 적었다(`docs/adr/D-395-fleet-assisted-localization.md:158-168`). 항목은 1 Pi 탐색 시간 실측, 2 기준 사각형 테이프 실측, 3 실제 카메라의 사각형·페인트 검출, 4 장치의 들어 올림 신호, 5 장치 기본값·릴리스, 6 실기 S3다. 장치에서 쓰려면 1~6이 모두 필요하다.
  - `lane_rules.yaml`도 사이트 이미지와 로봇에 배포되지 않았다.
  - D-463 자체도 "돌아가는 사이트 이미지에는 이 경로가 없고 실차 주행 증거는 없다"고 적었다.
- **두 로봇은 모터 런타임이다.** 모터 런타임은 `goal_navigation`과 `return_home`을 끈다(`contracts/foundation/core_common/domain/capabilities.py:113-116`). `POST /api/v1/navigation/goal`은 `require_kept`에서 `CAPABILITY_WITHHELD`로 거절되고(`navigation.py:43`) 모터 모드에는 LiDAR·SLAM이 없다(`host.py:339`). 자세 이전에 목표를 받는 런타임이 아니다.
- **녹화의 한계.** 현재 녹화 토픽에는 `/tf`, `/tf_static`, 지도 자세가 없고 카메라 프로필 revision은 빈 문자열이다. REST만 쓰는 소유자는 600 s에 끝나고, 다른 토큰의 teleop이 받아들여지면 녹화가 멈춘다(`contracts/foundation/core_common/domain/pilot_recording.py:3-8`).
- **천장 카메라는 위치를 대 주지 못한다.** `GET /api/fleet/tracking`(D-457)은 표시 전용이고(D-457 §7) 익명 검출이다. 위치 지터는 ±5 cm이고 표본의 30~40 %가 비어 있다. 로봇 신원은 풀리지 않았다. D-472(Proposed)의 후면 LED 점멸은 `POST /api/fleet/robots/{robot_id}/identify`(`operations/fleet/fleet/server/console_routes.py:157`)가 램프만 켜고 `pending_visual_confirmation`을 돌려주는 데까지다. 영상 대조와 이름 확정은 구현되지 않았다. D-472 §7은 그 결과로 `initialpose`, 경로, `cmd_vel`을 실행하지 못하게 한다.
- **길의 모양.** 아레나 도로는 도로마다 중심선 하나인 양방향 길이고(`middleware/perception/map/map_v2_fleet/lane_rules.yaml` `two_way: true`, `lane_graph.yaml` `directions: [forward, reverse]`), 로터리만 반시계 단방향이다(`ring_s`·`ring_e`·`ring_n`·`ring_w`). 두 로봇이 같은 도로에서 마주 보고 가면 비켜 갈 폭이 없다.
- **라벨 쪽 규칙이 이미 있다.** 자동 초안은 승인이 아니다(D-465 §4·§5: 모델 출력과 자기 보고 신뢰도만으로 자동 승인·고정 평가 정답을 만들지 않고, 검증되지 않은 지도 투영으로 정답을 생성하지 않는다). 승인된 indexed PNG만 학습 데이터셋이 되고 admission은 trainer owner가 다시 검증한다(D-464 §2·§6). 고정 평가 정답은 사람이 검수한다(D-475 §1·§4, Proposed). D-379는 지도 투영 라벨을 "지도 자세 정합이 먼저"라고 미뤄 두었다(`docs/adr/D-379-learning-data-pipeline-auto-labels-local-store.md:36`, `:47`).

### Decision

1. **목적.** "지도 주행(map drive)"은 Fleet이 지시하는 모드다. 로봇은 차선 그래프 경로를 지도 자세로 따라가며, 차선 카메라 인식이 아니라 지도 자세와 LiDAR로 움직인다. 그래서 수집이 학습하려는 모델에 의존하지 않는다. 영상은 주행 내내 녹화한다. 녹화된 프레임에는 차선 그래프와 보정된 카메라로 투영한 예상 차선·주행 가능 영역 초안을 붙인다. 이 초안은 검수 대기 상태로만 가고, 승인과 평가 정답은 사람이 한다. 이 ADR은 새 주행 알고리즘을 만들지 않는다. D-463의 점 경로 한 호출을 정착된 자세 아래에서 되풀이하는 주체와 종료 조건을 정한다.

2. **소유.**
   - **Fleet(`operations/fleet`, D-429 §1 조정 층)** 이 경로(간선 id 순서)를 정하고 목표·claim을 발행한다. 목표는 기존 `task_service.submit_navigation`을 통해서만 보낸다. D-330 §1의 단일 원자 claim과 stop generation이 그대로 적용된다. 별도 scheduler, 별도 예약 표, 별도 Mission 경로를 만들지 않는다. 지도 주행의 정지는 D-330 §2의 정지·재시작 규칙을 따른다. 정지 해제나 Fleet 재시작은 대기 중인 목표를 자동으로 다시 내보내지 않는다. 용어: claim은 Fleet이 한 로봇·한 구역을 한 번에 한 발행에만 주는 예약이고, stop generation은 정지 요청마다 오르는 번호로 그보다 낮은 발행을 막는 래치다.
   - **CORE(`middleware/core`)** 는 계속 유일한 `cmd_vel` 쓰기이고(D-2, D-430 불변식 3a) 몸 기준 근접 정지(D-422, D-424), E-stop, 안전 체인(D-430)을 그대로 둔다. Fleet의 목표는 CORE가 다시 판정한다. Fleet claim은 물리 제어권이 아니다(D-330 §1).
   - **로봇은 검증되지 않은 자세를 믿지 않는다.** 매 목표 직전 `trusted_map_pose`가 스냅샷의 `LOCALIZED`·지도 `pose_frame`을 다시 확인한다. 이 검사는 상태와 좌표계만 본다(스냅샷 나이는 보지 않으므로 열린 항목 2). 한 번이라도 untrusted이면 그 세션은 새 목표를 보내지 않고 기존 `POST /api/fleet/robots/{robot_id}/cancel`로 진행 중 목표를 취소한다. 자세가 돌아와도 자동으로 이어 가지 않고 운영자가 다시 시작한다.
   - **Rosy Cam(천장 카메라)** 은 이번 결정에서 사람이 보는 화면이다. 운영자가 어느 로봇이 어디에 있는지 보고(D-457·D-472) 필요하면 정지시킨다. 천장 검출을 목표 입력, 자세, 자동 정지 조건으로 연결하지 않는다(D-457 §7, D-472 §7). 자동 교차검증으로 쓰려면 D-457 §7의 개정이 먼저 필요하며 열린 항목이다.

3. **선행 게이트(순서대로, 앞이 닫히기 전에 뒤를 하지 않는다).** 장치 주행 게이트는 0~5, 라벨 사용 게이트는 6~7이다.

   | 게이트 | 닫는 증거 | 오늘 |
   |---|---|---|
   | 0. 장치가 하드웨어 런타임이다 | 로봇이 Nav2와 localization 백엔드를 갖춘 하드웨어 런타임으로 돌고, 그 런타임이 자체 수용을 통과한다. 모터 런타임에서는 `goal_navigation`이 꺼지고(`contracts/foundation/core_common/domain/capabilities.py:113-116`) `require_kept`가 목표를 `CAPABILITY_WITHHELD`로 거절한다(`middleware/core/api_web/core_api_web/api/v1/navigation.py:43`). 모터 모드에는 LiDAR·SLAM이 없다(`host.py:339`). | 닫히지 않음. 두 로봇 모두 모터 런타임 |
   | 1. 지도 번들 | `lane_graph.yaml`, `lane_rules.yaml`, 맵이 사이트 이미지(Fleet이 간선을 읽는 곳)와 로봇에 같은 revision으로 있다 | 닫히지 않음 |
   | 2. 검증된 지도 자세 | D-395 개정 5의 항목 1~6(실기 S3 포함)이 닫혀 `enable_loc_assist`가 켜지고 스냅샷이 `LOCALIZED`·지도 `pose_frame`을 보고한다. 또는 같은 효과의 별도 결정. 후보 대안은 알려진 주차 자리에서 `POST /api/v1/localization/initialpose`(`navigation.py:103`)로 자세를 주는 것이나, 이 경로는 `localization` 블록을 만들지 않아 지금은 D-463이 거절한다. 블록의 출처는 열린 항목 1이다. | 닫히지 않음. 가장 큰 막힘 |
   | 3. 로봇 신원 | 첫 실행은 한 대만 지도에 올리고 운영자가 이름을 확인한다. 두 대 이상은 D-472 영상 대조 또는 마커 대응(D-457 §2) 이후 | 한 대 입회로는 가능, 두 대는 닫히지 않음 |
   | 4. 갱신 hold | 해당 로봇에 hold가 걸려 있다(D-412 §4, `rosy-update-hold.ps1`, 만료 필수·최대 7일). 녹화 여유와 회수 경로 확인 | 실행 시점에 닫는다 |
   | 5. 사람이 지킨다 | 운영자가 E-stop을 손에 두고 옆에 있다. 다른 세션에 알리고 합의한 로봇만 쓴다. 속도는 `capabilities.yaml:7`의 0.20 m/s 이하이며 시작 속도는 실측 전에 정하지 않는다 | 실행 시점에 닫는다 |
   | 6. 녹화가 투영에 충분하다 | 녹화가 지도 자세, `/tf`, `/tf_static`, 카메라 프로필 revision을 싣고, 자세와 프레임의 시각 동기 오차를 측정했다 | 닫히지 않음(위 4.1의 사실) |
   | 7. 투영 오차 예산 | 투영 초안의 오차를 사람이 확인한 프레임으로 측정했고, 합격 기준을 실행 전에 평가 담당자가 적어 두었다. 기준이 없으면 초안을 만들지 않는다 | 측정된 적 없음 |

   게이트 6은 라벨 단계 앞에서 닫는다. 주행 자체는 6 없이 해도 되나 그 녹화는 투영 라벨용이 아니다.

   **오늘 불가능한 것.** 게이트 0·1·2가 닫히지 않아 장치에서 지도 주행은 시작할 수 없다. 두 로봇 모두 모터 런타임이라 목표 자체를 CORE가 거절한다. 천장 카메라만으로 로봇의 자세·신원을 정해 이 주행을 시킬 수 없다. 지금 녹화로는 지도 투영을 할 수 없다. 투영 라벨의 오차 예산은 측정된 적이 없고 지도 투영 라벨 코드는 없다.

4. **데이터 경로.**
   1. **녹화.** 주행 시작 전에 기존 녹화를 켠다. 후보는 CORE `POST /api/v1/recordings`(`middleware/core/api_web/core_api_web/api/v1/recordings.py:93`, D-411)다. 지금 Fleet에는 이 녹화를 켜는 경로가 없고 새 경로가 필요하다(열린 항목 3). 사실로 적는다. 현재 `PILOT_TOPICS`(`middleware/perception/control/pilot_recording.py:36-37`)는 카메라, `cmd_vel`, `odom`, `scan`, `line/observation`, teleop 의도, keep 디버그이고 `/tf`, `/tf_static`, 지도 자세(localization)는 없다. 매니페스트의 `camera_profile_revision`은 `""`이다(`:222`). 그래서 지금의 녹화로는 지도 투영을 할 수 없다. 게이트 6이 이를 닫는다.
   2. **기존 도구 재사용.** 회수 후 기존 `bag_to_video`(MP4+sidecar), `autolabel`, 픽셀 검수 `review_ingest.import_frames`, `recording_job`을 쓴다(`learning/training/perception/dataset/`, `learning/training/perception/training/recording_job.py`). 새 학습 앱, 새 저장소를 만들지 않는다(D-427). MCAP 프레임을 원본 영상 없이 직접 받는 일은 D-475 §5(Proposed)의 `source_kind: mcap`이 닫히기 전에는 하지 않는다.
   3. **지도 투영 초안.** 차선 그래프의 도로 중심선과 폭, 보정된 카메라 외부 파라미터(URDF 공칭을 바탕으로 로봇별 보정이 다듬는다. D-397 규칙), 프레임 시각의 지도 자세로 예상 차선·주행 가능 영역을 8bit indexed 마스크 초안으로 만든다. 자세와 프레임의 시각이 맞지 않거나 자세가 untrusted인 구간은 마스크를 만들지 않고 `ignore_index=255`로 둔다(D-465 §5). 이 초안에는 기존 신뢰 출처(LiDAR 벽, 궤적)와 다른 출처 이름을 붙인다. 이름은 열린 항목이다. 프레임마다 출처 기록에 지도 revision, 보정 기록 id, 자세 출처(그 프레임의 `localization` 상태와 `pose_frame`, 자세 시각과 프레임 시각의 차)를 남긴다. 하나라도 비면 그 프레임은 초안을 만들지 않는다.
   4. **초안은 초안이다.** 투영 초안은 검수 대기 행으로만 들어간다. 자동 승인하지 않고(D-465 §4), 고정 평가 세트에는 들어가지 않으며(D-475 §1·§4: 평가 정답은 사람 검수), 사람이 승인한 indexed PNG만 D-464의 데이터셋 구축 입력이 된다. 데이터셋이 존재해도 학습 admission은 D-464 §6대로 trainer owner가 다시 판정한다. 이 ADR은 학습, 모델 intake, 로봇 활성화를 허가하지 않는다.
   5. **회수와 저장.** 회수는 로봇이 정지한 뒤 기존 harvest로 한다. 스크래치, 로그, 영상 사본은 `X:\DevTemp\`에 둔다.

5. **사람이 정지시킬 수 있는 구조를 유지한다.** 지도 주행은 새 정지 경로를 만들지 않는다. 기존 `POST /api/fleet/estop`, `POST /api/fleet/cancel-all`, 로봇별 cancel, 장치의 물리 E-stop이 그대로 유일한 정지 수단이다(D-330 §2·§3). 새 모듈은 D-463과 같이 D-430 안전 cluster 밖에 둔다(`lane_route_routes.py`의 모듈 주석). 정지 파일에 의사결정 import를 들이지 않는다.

6. **한 번에 한 대, 한 방향.** 첫 실행은 로봇 한 대다. 도로는 중심선 하나인 양방향이라 마주 보는 두 로봇은 비킬 자리가 없다. 두 대 이상은 Fleet의 교통·claim 규칙이 마주 보기를 막는다는 증거가 나온 뒤에 한다.

### 기존 결정과의 관계

| 결정 | 관계 |
|---|---|
| D-427 | 새 최상위 폴더와 새 패키지를 만들지 않는다. 경로·세션은 `operations/fleet`, 녹화는 CORE의 기존 recordings, 투영 초안과 검수 연결은 `learning/training/perception`의 기존 모듈에 둔다 |
| D-429 | Fleet은 조정 층(경로·claim·발행), CORE는 중재·안전과 장치 지역 규칙, 라벨은 learning 소유다. 이 결정은 층 표의 줄을 바꾸지 않는다 |
| D-430 | 안전 체인과 `cmd_vel` 단일 writer를 건드리지 않는다. 투영 초안과 천장 검출은 안전 판정을 대신하지 않는다(불변식 4 정신) |
| D-330 | 발행은 기존 task 경로의 단일 claim과 stop generation 아래. 재시작·정지 해제가 대기 목표를 자동 재발행하지 않는다 |
| D-463 | 점 경로를 그대로 쓴다. 이 결정은 그 호출을 되풀이하는 세션과 종료 조건을 더한다. D-463 §4·§5(정착된 자세만, 위치를 만들어 주지 않음)는 바뀌지 않는다 |
| D-395 | 개정 5의 장치 게이트가 이 기능의 첫 게이트다. `enable_loc_assist`를 이 ADR이 켜지 않는다 |
| D-472 · D-457 | 신원과 천장 검출은 표시 전용. 자동 연결은 하지 않는다 |
| D-422 · D-424 | 몸 기준 근접 정지는 CORE에 그대로 있다 |
| D-476 | 차선 추종의 연장선 bridge다. 지도 주행은 차선 추종을 켜지 않고, 켜져 있으면 CORE가 목표를 거절한다 |
| D-411 · D-412 | 녹화 API 후보, 갱신 hold 규칙 |
| D-379 · D-464 · D-465 · D-475 | 초안은 검수 대기만. 승인·평가 정답은 사람. 지도 투영은 오차 예산 측정 전 사용하지 않는다 |
| capture-goal의 D-473(미커밋) | 지도에 정착된 자세에서만 기존 goal을 보낸다는 같은 조건이다. 한 점 목표는 그 쪽, 차선 경로의 반복 주행은 이 ADR이다 |

### 번호 충돌

`feat/capture-goal` 워크트리(`.worktrees/capture-goal`)에는 커밋되지 않은 `docs/adr/D-473-learning-capture-goal.md`가 있다. 그 브랜치의 커밋 이력에는 이 파일이 없다. main의 D-473은 `D-473-fleet-console-development-connection-mode.md`이므로 두 파일이 같은 번호를 쓴다. 이 ADR은 그 문제를 고치지 않는다. 그 세션이 착지 전에 다른 번호를 고르고, 이 문서의 위 표는 그때 이름만 바꾼다. D-480은 `docs/sim2real-tiers` 브랜치가 가졌고 이 번호는 D-481이다.

### Alternatives

- **카메라 차선 수집 고리(CAMERA_LINE 감독 주행):** 가장 단순하지만 오늘 실패한 경로다. 수집이 개선 대상 인식에 의존한다. 오늘의 실패(차선 밖 시작, 과노출, 바닥을 벽으로 읽음)가 그대로 수집 실패가 된다. 주 경로로 채택하지 않는다. 지도 자세가 확보되기 전까지 다른 수집이 없다는 사실은 그대로이므로 대기 경로로 남는다.
- **원격 조종(teleop) 수집:** 자세 게이트가 필요 없고 오늘도 가능하다. 사람이 운전해야 하고, 경로 반복성과 정답 경로가 없어 지도 투영 초안의 기준이 약하다. 주 경로가 아니며 자세 게이트가 닫히기 전의 임시 수집으로 허용된다. 이 결정을 바꾸지 않는다.
- **Nav2 전역 위치(AMCL global localization):** 지도 대칭 때문에 D-393이 금지했고(D-395 Context) 이를 푸는 것이 D-395다. 이 ADR이 별도 위치 수단을 만들면 D-395와 중복된다. 채택하지 않고 D-395의 게이트를 쓴다.
- **천장 카메라를 자세 입력으로 사용:** ±5 cm 지터, 표본 30~40 % 결손, 익명 검출이라 안 된다. D-457 §7, D-472 §7이 금지한다.

### 열린 항목

1. 검증된 지도 자세의 출처. D-395 개정 5 항목 1~6(S3 포함)이 닫혀 `enable_loc_assist`가 켜지는지, 또는 사람이 준 `initialpose`를 `localization` 블록으로 인정하는 별도 결정이 있는지. 한 대 입회 실행에서 S3를 생략할 수 있는지는 D-395 쪽에서 정한다. 이 ADR은 생략하지 않는다.
2. Fleet 쪽 반복 세션: 시작·정지 요청, 상태, 종료 조건(`ROUTE_COMPLETE`, untrusted, 선 이탈, stop generation)의 이름과 위치. 새 API 경로와 필드는 이 ADR이 정하지 않으며, 만들 때 API 참조서와 생산자·소비자 시험을 같은 변경에서 한다(D-330 §5, D-18). 세부는 다음을 정해야 한다.
   - **자세 최대 나이.** `trust.classify`(`operations/fleet/fleet/localization/trust.py:61-69`)는 `localization` 블록의 상태와 `pose_frame`만 보고 스냅샷 시각을 보지 않는다. 세션은 목표마다 허용 최대 나이를 따로 정해 검사해야 한다. 수치는 열려 있다.
   - **재개 키.** `followed`는 Fleet 프로세스 메모리라 재시작하면 사라진다. 닫힌 한 바퀴는 시작점과 끝점이 같아, 재개한 세션이 곧바로 `ROUTE_COMPLETE`를 내거나 이미 돈 구간을 다시 달릴 수 있다. 재개 세션을 무엇으로 식별하는지(세션 id와 마지막으로 보낸 점의 호 길이를 영속) 정해야 하며, 정하기 전에는 재시작 뒤 자동 재개를 하지 않는다.
   - **CORE가 목표를 거절할 때.** `localized_start`(`middleware/core/api_web/core_api_web/api/v1/common.py:75`)가 LOCALIZED가 아니면 거절하고, 차선 추종이 켜져 있으면 `LINE_FOLLOW_ACTIVE`, 모터 모드면 `CAPABILITY_WITHHELD`로 거절한다. 세션은 거절을 재시도하지 않고 멈춰 사유를 운영자에게 보이며, 자동으로 다른 모드를 선택하지 않는다.
   - **배터리·충전.** 반복 주행의 최소 배터리, 바퀴 수 상한, 충전 복귀를 어디서 정하는지. 값을 정하기 전에는 한 번에 한 바퀴, 운영자가 배터리를 확인한 뒤에만 시작한다.
   - **D-476 차선 bridge.** D-476(Proposed)은 차선 추종 중 선을 잃을 때의 연장선 bridge다. 지도 주행은 차선 추종을 켜지 않고 CORE 목표 경로만 쓴다. 둘 다 켜져 있으면 CORE가 `LINE_FOLLOW_ACTIVE`로 목표를 거절한다. 지도 주행 세션은 차선 추종 모드를 선택하지 않는다.
3. 녹화 소유와 상한. `pilot_recording`은 REST만 쓰는 소유자를 600 s 상한에서 끝내고, 소유자의 `/ws/state` 연결이 끊기거나 다른 토큰의 teleop이 받아들여지면 녹화를 멈춘다(`contracts/foundation/core_common/domain/pilot_recording.py:3-8`, `:144`). Fleet이 `POST /api/v1/recordings`를 호출하는 경로와 함께, Fleet의 소유 토큰이 `/ws/state` 연결을 유지할지, 600 s보다 긴 바퀴를 몇 개 녹화로 나눌지, 이음새의 프레임을 어떻게 처리할지를 정해야 한다. 녹화 소유 토큰(`recordings.py:86-90`의 `owned`) 처리도 포함한다.
4. 녹화 구성(게이트 6). 아래 「선행 게이트」 6번의 닫는 증거를 어떻게 만들지.
5. 투영 초안의 출처 이름, 오차 예산 수치와 합격 기준, 자세와 프레임 시각 허용 오차, 카메라 외부 파라미터의 로봇별 보정 값(D-397).
6. 천장 검출을 자동 교차검증으로 쓰려는 경우 D-457 §7의 개정.
7. 같은 길의 마주 보기 규칙, 두 대 이상 운용, 시작 속도.
8. 지도 번들(`lane_graph.yaml`·`lane_rules.yaml`)의 사이트 이미지·로봇 배포 경로와 revision 확인.

### 수용과 검증

수용은 증거 종류별로 따로 적고 앞 단계가 뒤 단계를 대신하지 않는다.

1. **SOURCE(호스트):** 세션이 untrusted 자세, 선 이탈, stale, stop generation에서 새 목표를 보내지 않고 진행 중 목표를 취소하는지를 가짜 시계와 가짜 로봇으로 시험한다. `ROUTE_COMPLETE`에서 끝나는지, 재시작·정지 해제가 자동 재발행하지 않는지도 시험한다. 새 코드는 D-430 안전 cluster를 import하지 않는다.
2. **ROS-SIM:** 모델 PC(OMEN) 또는 사이트 PC의 Gazebo `map_v2_fleet`에서 한 대로 한 바퀴를 돈다(이 노트북에서는 Gazebo를 돌리지 않는다). 녹화, 회수, 투영 초안 생성까지 한 번 통과시키고, 시뮬레이션의 정확한 자세로 투영 오차의 상한을 본다. 시뮬레이션 증거는 실물 오차 예산이 아니다.
3. **DEVICE:** 3항 게이트 0~6이 닫힌 뒤 한 대, 저속, 운영자 입회로 한 번 한다. 녹화가 한 바퀴 전체를 덮었는지(시작과 끝 시각, 정지 사유, 600 s 상한과 좌석 변경으로 끊기지 않았는지)를 매니페스트로 확인한다. 투영 초안과 사람이 확인한 프레임의 차이를 잰다. 합격은 실행 전에 적은 기준으로 판정한다.
4. **데이터:** 투영 초안은 검수 앱에서 `pending`으로만 보이고 승인 0을 확인한다. 평가 세트에 들어가지 않는다.

### Consequences

차선 인식이 없는 상태에서도 지도 자세만 있으면 같은 경로를 반복 주행하며 영상을 모을 수 있게 하는 설계다. 그러나 지도 자세가 장치에 없는 한 오늘은 시작할 수 없다. 이 결정은 그 막힘을 숨기지 않고 D-395 게이트를 첫 게이트로 둔다. 투영 라벨은 초안이며 사람 검수와 오차 예산이 있어야만 학습 입력이 된다. 호스트 시험과 문서 lint는 장치 주행, 라벨 품질, 학습 개선의 증거가 아니다.
