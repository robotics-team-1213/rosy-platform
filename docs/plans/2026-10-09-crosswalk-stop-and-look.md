# 횡단보도 서고·보고·건너기 구현 계획 (D-573)

**작성:** 2026-10-09. **기준:** local main `97e5101a1`. **결정:** [D-573](../adr/D-573-crosswalk-stop-look-cross.md) (Proposed).

ADR이 수락된 뒤에 시작한다. 지켜야 할 규칙은 다음과 같다.

- 한 브랜치에 주제 하나를 둔다. 접두어는 D-372를 따른다.
- 워크트리는 `rosy-platform/.worktrees/<짧은이름>`에 만든다.
- 착지는 사용자가 말한 뒤에만 `python tools/land.py --tests auto`로 한다. 푸시도 사용자가 말한 뒤에만 한다.
- pytest·브라우저·Gazebo는 모델 PC(OMEN)에서 git-archive 스냅숏으로 돌린다. 이 노트북에서는 돌리지 않는다.
- 결과 파일은 `python test/known_failures.py`와 비교한다.
- Validation 시험은 먼저 main에서 실패하는 것을 `X:\DevTemp\crosswalk-<브랜치>\red.txt`로 남긴다. 그다음 고치고, 고친 뒤 결과를 `run.txt`로 남긴다.

## 순서와 의존

```
(b) fleet-map-zones ──┬──> (d) authority-crosswalks ──> (g) gazebo-pedestrian ──> (h) device
(c) core-gate ────────┤          ^                              ^
                      ├──> (e) traffic-zone (D-517 M2 착지 뒤) ──┘
                      └──> (f) console-ui (b, c 상태 필드 뒤)
```

- (b)와 (c)는 파일이 겹치지 않는다. 동시에 해도 된다.
- (d)는 (b)의 지도 형식과 (c)의 게이트 입력이 있어야 한다.
- (e)는 D-517 M2(CORE 통행권)가 main에 착지한 뒤에 한다.
- (h)는 브랜치가 아니다. 검증 기록(`docs/validation/d573-crosswalk-*/`)만 남긴다.

## 브랜치

### (b) `feat/crosswalk-fleet-map-zones` — 주인: Fleet 세션

- **무엇:** D-573 1항의 지도 구역이다.
  - 현장 지도에 `crosswalks[] {id, polygon, approach[], lanes[], revision}`를 둔다.
  - `lane_graph.yaml` `crosswalks[].polygon`을 가져온다.
  - `lanes[]`는 결정적으로 계산한다.
  - 대기 띠가 벽(현장 바닥 경계)과 겹치거나 차로를 덮지 않으면 거부한다.
  - 동작 변경은 없다.
- **파일:** `operations/fleet/fleet/site_map.py`와 지도 적재·검사 쪽.
- **시험:**
  - 260919 두 횡단보도를 가져오는 결정성 시험
  - 띠 거부 시험
  - `PlaceKind` 불변 시험
- **Safety-Review:** 아니오. 표시와 자료만 바꾼다.

### (c) `feat/crosswalk-core-gate` — 주인: 이 ADR 구현 세션. 연결 줄은 차선 유지 세션이 검토한다.

- **무엇:** D-573 2·3·4·6항이다.
  - 순수 모듈 `core_features/line_follow/crosswalk_gate.py`를 만든다. 상태, A 판정, UNKNOWN, 보기 창, 무장 뒤 잃음을 담는다.
  - `s_wait`는 `RobotBody`에서 유도한다.
  - `manager.py`에서 통행권 판정 자리에 `min`으로 연결한다.
  - 카메라 구역(`CrosswalkZones`)을 출처로 쓴다. odom 고정 코드는 공유하고 수명은 따로 둔다.
  - 막힘 원인 `crosswalk_blocked`를 더한다. 그 원인의 움직이는 답은 거부한다.
  - 상태 필드 `line_follow.crosswalk`를 더한다.
  - 설정 키를 둔다: `crosswalk_look_s`, `crosswalk_look_min_scans`, `crosswalk_report_s`, `crosswalk_cross_speed`, `crosswalk_approach_default_m`. 기본 꺼짐(`crosswalk_gate_enabled: false`)으로 시작한다.
- **파일:**
  - `middleware/core/services/core_features/line_follow/{crosswalk_gate.py(새), manager.py, model.py}`
  - `recovery/stuck_recovery.py`, `stuck_wiring.py`
  - `gateway/core/line_follow_wiring.py`
  - `contracts/foundation/core_common/protocol/schemas.py`(`LineStuckStatus.cause`)
  - API Reference 행
- **조율:** 착지 전에 차선 유지 세션의 진행 브랜치(D-520·D-531)와 `manager.py` 겹침을 확인한다. 그 세션에 연결 줄 검토를 요청한다.
- **시험:** D-573 Validation 1·2·4·5(CORE 부분). 공통 가드는 기존 `line_follow` 시험과 `test_road_behaviour.py`(바뀌지 않음)다.
- **Safety-Review:** 예. 정지 우선순위, 풀지 못함, UNKNOWN, 시간으로 풀리는 길 없음, 막힘 답 거부를 본다.

### (d) `feat/crosswalk-authority-hint` — 주인: 이 ADR 구현 세션. (b)·(c) 뒤.

- **무엇:** D-573 1항의 Fleet→CORE 전달이다.
  - 통행권 요청에 선택 필드 `crosswalks[]`를 둔다. `pose_stamp` 기준 거리와 진행 틀 대기 띠 상자다.
  - CORE가 이것을 odom에 고정해 게이트 출처로 쓴다.
  - 능력 `line_follow_crosswalk`를 더한다.
  - 횡단보도가 있는 지도에서 능력이 없으면 `TRIP_CROSSWALK_UNSUPPORTED`로 거절한다.
  - 카메라만 있는 구역이면 `crosswalk_unmapped` 사건을 낸다.
- **파일:** `core_common.protocol.line_authority`, CORE authority 처리, `operations/fleet/fleet/server/trip_runner.py`·`trip_ports.py`의 송신, API Reference.
- **시험:** D-573 Validation 3, 6(통행권 거리·거절).
- **Safety-Review:** 예. 자세 시각 고정, 만료, 줄지 않음과의 관계를 본다.

### (e) `feat/crosswalk-traffic-zone` — 주인: Fleet 교통 세션(D-517). D-517 M2 착지 뒤.

- **무엇:** D-573 5항과 4항의 정체 예외다.
  - `blocks.py`에서 횡단보도 구역(수용 1)을 자른다. 경계는 `s_wait`와 몸 길이 + `g(v)`다.
  - 출구 동시 허가를 한다.
  - 횡단보도 위에서 통행권이 끝나지 않게 한다.
  - `trip_runner._stalled`가 게이트 대기를 건너뛴다.
  - `stuck_resolver`는 `crosswalk_blocked`를 바로 `ESCALATE`한다.
- **파일:** `operations/fleet/fleet/traffic/{blocks.py, lane_traffic.py}`, `server/{trip_runner.py, stuck_resolver.py}`.
- **시험:** D-573 Validation 5(해결기), 6(블록 표 무작위 N대, 정체 예외).
- **Safety-Review:** 예. 허가 규칙을 본다.

### (f) `uiux/crosswalk-console` — 주인: Fleet 화면 세션. (b) 뒤, 상태 필드는 (c) 뒤.

- **무엇:** D-573 7항이다.
  - 현장 지도 편집기 "횡단보도" 층과 대기 띠 편집
  - 관제 로봇 카드 한 줄
  - 지도 다각형과 상태색
  - 예외 큐 행과 판단 창(카메라 한 장 + 점유 그림 + `기다림 계속`·`운행 끝`·`넘겨받기`)
- **시험:** 화면 계약 시험, 운영자 문구 시험, Chromium 캡처 세 폭(1920·1280·390), 디자인 검토.
- **Safety-Review:** 아니오. 판단 창에 움직이는 답이 없는지는 (c)·(e) 시험이 지킨다.

### (g) `feat/crosswalk-gazebo-pedestrian` — 주인: SIM 세션. (c)·(d) 뒤, (e)는 S8·S9에 필요.

- **무엇:**
  - map_v2_fleet 260919 월드에 보행자 모델을 둔다. LiDAR 평면 0.125 m보다 크고 정해진 경로를 오간다.
  - 먼저 gz `actor`가 시뮬 LiDAR에 보이는지 확인한다. 안 보이면 운동학으로 움직이는 충돌 상자로 대신한다.
  - S1–S9 시나리오 실행기를 만든다.
- **장소:** 모델 PC 또는 관제 PC에서만 한다.
- **증거:** `docs/validation/d573-crosswalk-sim-<날짜>/`. 판정은 보행자–몸 최소 거리, 구역 위 정지 0, 시간 초과 통과 0이다.

### (h) DEVICE/FIELD — 브랜치 없음

- 실물 한 대로 A 안·대기 띠·밖 20회를 녹화한다. 사람이 E-stop을 쥔다.
- 이어서 두 대 trip 10바퀴를 돈다.
- 사용자 승인 뒤에 한다. 증거는 `docs/validation/d573-crosswalk-device-<날짜>/`.

### 나중(별도 ADR)

- 사람(person) 클래스 또는 검출기(D-356 슬롯). D-573 10항에 따라 더하는 거부권으로만 쓴다.
- `road_behaviour` 연결(D-384 R1 이후). 게이트 상태를 `pedestrian_at_crosswalk`로 넘긴다.

## 되돌리기

- (c)는 `crosswalk_gate_enabled: false`가 기본이라 착지해도 동작이 바뀌지 않는다. 켜는 것은 현장 설정이다.
- (d)·(e)는 사이트 설정 `fleet.traffic.crosswalk: false`(기본)로 시작한다. 각 브랜치는 착지 커밋 하나를 `git revert`해서 되돌릴 수 있다.
