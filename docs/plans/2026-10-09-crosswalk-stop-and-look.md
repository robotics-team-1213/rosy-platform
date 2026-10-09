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
(i) perception-person-veto (별도 ADR 뒤, 독립)
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
  - 막힘 원인 `crosswalk_blocked`를 더한다. 그 원인의 `RESUME`·`BACK_AND_RETRY`·`YIELD`는 거부한다.
  - `CROSS_CONFIRMED`(D-573 4a)를 받는다. 지금 막힘·구역 id·증거 나이(앞 카메라 프레임 기록)·`confirm_id` 한 번·ttl을 확인한다. 기다림만 풀고 몸 정지는 끄지 않는다. 해결기 역할이면 403이다. 감사 사건 두 개를 낸다.
  - 앞 카메라 미리보기에 `evidence_id`(프레임 번호)와 CORE 스탬프를 붙이고, 최근 프레임 기록을 둔다.
  - 설정 `crosswalk_confirm_max_age_s`(2 s, 상한 5 s)와 `crosswalk_confirm_ttl_s`(5 s)를 둔다.
  - 상태 필드 `line_follow.crosswalk`를 더한다.
  - 설정 키를 둔다: `crosswalk_look_s`, `crosswalk_look_min_scans`, `crosswalk_report_s`, `crosswalk_cross_speed`, `crosswalk_approach_default_m`. 기본 꺼짐(`crosswalk_gate_enabled: false`)으로 시작한다.
- **파일:**
  - `middleware/core/services/core_features/line_follow/{crosswalk_gate.py(새), manager.py, model.py}`
  - `recovery/stuck_recovery.py`, `stuck_wiring.py`
  - `gateway/core/line_follow_wiring.py`
  - `contracts/foundation/core_common/protocol/schemas.py`(`LineStuckStatus.cause`)
  - API Reference 행
- **조율:** 착지 전에 차선 유지 세션의 진행 브랜치(D-520·D-531)와 `manager.py` 겹침을 확인한다. 그 세션에 연결 줄 검토를 요청한다.
- **시험:** D-573 Validation 1·2·4·5·7(CORE 부분). 7항(오래된 증거·이름 없음·재사용·몸 정지 유지)은 먼저 실패를 남긴다. 공통 가드는 기존 `line_follow` 시험과 `test_road_behaviour.py`(바뀌지 않음)다.
- **Safety-Review:** 예. 정지 우선순위, 풀지 못함, UNKNOWN, 시간으로 풀리는 길 없음, 막힘 답 거부, `CROSS_CONFIRMED`의 한 번·묶임·몸 정지 유지를 본다.

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
  - `stuck_resolver`는 `crosswalk_blocked`를 바로 `ESCALATE`한다. 해결기는 `CROSS_CONFIRMED`를 내지 못한다.
  - Fleet 경로 `POST /api/fleet/robots/{id}/line-stuck/decision`의 `CROSS_CONFIRMED`는 `require_named_operator`(D-540 9)를 쓴다. 증거 나이를 다시 재고(`CROSS_EVIDENCE_STALE`), Rosy Cam 잘라낸 이미지를 만들고, D-541 lease 주인 토큰으로 보내고, 감사 행을 남긴다.
  - API Reference 행: 결정 값, 본문, 거절 사유, 사건.
- **파일:** `operations/fleet/fleet/traffic/{blocks.py, lane_traffic.py}`, `server/{trip_runner.py, stuck_resolver.py}`.
- **시험:** D-573 Validation 5(해결기), 6(블록 표 무작위 N대, 정체 예외).
- **Safety-Review:** 예. 허가 규칙과 운영자 확인 경로(이름, 증거 나이, lease 토큰)를 본다.

### (f) `uiux/crosswalk-console` — 주인: Fleet 화면 세션. (b) 뒤, 상태 필드는 (c) 뒤.

- **무엇:** D-573 7항이다.
  - 현장 지도 편집기 "횡단보도" 층과 대기 띠 편집
  - 관제 로봇 카드 한 줄
  - 지도 다각형과 상태색
  - 예외 큐 행과 판단 창(카메라 한 장과 나이 + 점유 그림 + `기다림 계속`·`카메라 보고 확인`·`운행 끝`·`넘겨받기`)
  - `카메라 보고 확인`: 나이가 한도를 넘으면 막고, 확인 대화상자를 두고, 카드에 "운영자 확인 통과 · {이름}"을 보인다.
  - 현장 지도 편집기 안내: "보행자 인형은 0.15 m 이상"
- **시험:** 화면 계약 시험, 운영자 문구 시험, Chromium 캡처 세 폭(1920·1280·390), 디자인 검토.
- **Safety-Review:** 버튼·대화상자·나이 막기만 예. 나머지는 디자인 검토.

### (g) `feat/crosswalk-gazebo-pedestrian` — 주인: SIM 세션. (c)·(d) 뒤, (e)는 S8·S9에 필요.

- **무엇:**
  - map_v2_fleet 260919 월드에 보행자 모델을 둔다. LiDAR 평면 0.125 m보다 크고 정해진 경로를 오간다.
  - 먼저 gz `actor`가 시뮬 LiDAR에 보이는지 확인한다. 안 보이면 운동학으로 움직이는 충돌 상자로 대신한다.
  - S1–S10 시나리오 실행기를 만든다. S10은 0.12 m 인형(못 봄, 한계 기록)과 0.15 m 인형(봄), 그리고 운영자 확인 한 번(몸 경로 상자에서 정지)이다.
- **장소:** 모델 PC 또는 관제 PC에서만 한다.
- **증거:** `docs/validation/d573-crosswalk-sim-<날짜>/`. 판정은 보행자–몸 최소 거리, 구역 위 정지 0, 시간 초과 통과 0이다.

### (h) DEVICE/FIELD — 브랜치 없음

- 실물 한 대로 A 안·대기 띠·밖 20회를 녹화한다. 사람 손·다리와 0.15 m 인형을 쓴다. 사람이 E-stop을 쥔다.
- 운영자 확인 3회를 한다. 그 가운데 1회는 몸 경로에 손을 넣어 정지를 확인한다.
- 이어서 두 대 trip 10바퀴를 돈다.
- 사용자 승인 뒤에 한다. 증거는 `docs/validation/d573-crosswalk-device-<날짜>/`.

### (i) `feat/perception-person-veto` — 주인: 인식·학습 세션. 별도 ADR(D-356 슬롯)이 수락된 뒤.

- **무엇:** 카메라 사람 모델이다. D-573 10항에 따라 "사람 있음"을 더하는 거부권으로만 쓴다. 0.15 m 미만 인형이 보이게 되는 유일한 길이다.
- **자료:**
  - D-379 라벨 규격과 D-459 검수 앱에 `person`·`figurine` 클래스를 더한다.
  - 앞 카메라 실주행 프레임을 모은다: 두 횡단보도, 인형 키 여러 개(0.15 m 미만 포함), 가림과 역광, 사람 없는 프레임.
  - Rosy Cam 위에서 본 프레임을 모은다.
  - 모델 PC에서 학습하고, intake와 섀도를 거친다(D-356).
- **CORE 연결:** 게이트의 추가 입력이다. 없거나 늦으면 영향이 없다.
- **시험:** 모델이 "없음"이라고 해도 LiDAR 점유를 풀지 않는다. 모델이 "있음"이면 LiDAR가 비어 있어도 기다린다.
- **Safety-Review:** 예. 거부권만인지 본다.

### 나중(별도 ADR)

- `road_behaviour` 연결(D-384 R1 이후). 게이트 상태를 `pedestrian_at_crosswalk`로 넘긴다.

## 되돌리기

- (c)는 `crosswalk_gate_enabled: false`가 기본이라 착지해도 동작이 바뀌지 않는다. 켜는 것은 현장 설정이다.
- (d)·(e)는 사이트 설정 `fleet.traffic.crosswalk: false`(기본)로 시작한다. 각 브랜치는 착지 커밋 하나를 `git revert`해서 되돌릴 수 있다.
