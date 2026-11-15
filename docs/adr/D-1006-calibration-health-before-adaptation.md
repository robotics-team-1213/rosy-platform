## D-1006 지도·보정이 현실과 어긋난 것을 먼저 알아챈다 — 보정 건강 상태, 선택 게이트, 자동 재보정은 독립 기준이 생길 때까지 규정만

**Status:** Accepted (2026-11-09, 사용자 지시: "보정과 맵이 현실과 전혀 맞지 않는다, 맵이 바뀐 걸 인식하면 그에 맞춰 동적으로 조정"). SOURCE와 호스트 시험까지다. 현장 배포와 카메라 이동 뒤 수용은 이 기록이 하지 않는다. D-595 3항의 "경고로만"을 한 걸음 넓히되 보정을 쓰지는 않는다.

잇는 결정: [D-375](D-375-overhead-map-registration-from-lane-paint-proposal.md)(차선 페인트 맞춤 제안) · [D-457](D-457-overhead-marker-priority-and-markerless-fallback.md)(승인 기록은 표시 전용) · [D-560](D-560-rosy-cam-map-plane-fleet-draws-on-it.md) · [D-587](D-587-ceiling-marker-sightings-anchor-map-pose.md)(승인 기록이 지도 자세를 잡음) · [D-595](D-595-freeze-accepted-map-calibration.md)(수락한 보정은 고정) · [D-989](D-989-fleet-auto-locate-observation.md) · [D-1003](D-1003-nav2-free-goals-in-the-robot-map-frame.md)(현장↔기체 지도 짝 변환). 폴더 구조는 바뀌지 않으므로 D-427 3항은 해당하지 않는다. CORE가 유일한 `cmd_vel` 발행자(D-2)이고 이 기록은 어떤 움직임도 명령하지 않는다.

### Context

2026-11-09 현장 읽기:

1. `ceiling_north`의 승인 보정 `paint-a316b0628833`(11-05 승인)의 윤곽이 영상의 의자 위에 놓인다.
2. Vision의 D-375 제안은 거부됐다(점수 0.51–0.60, 보이는 면적 0.43–0.59, 동·남쪽이 잘림). 카메라는 트랙 일부만 본다.
3. 현장 지도 7개 버전은 차로 간선만 있고 `free` 간선이 없다. 기체는 자기 SLAM 지도에서 Nav2를 돌린다. D-1003이 목표를 기체 지도로 바꾼다.

코드에서 확인한 공백(`file:line`은 이 ADR 시점):

- `tracking_drift.py:46` `calibration_drift_verdict`는 **수락된** 맞춤만 근거로 쓰고, `poll_once`는 거부·응답 없음을 건너뛰며 "마지막 판정이 선다". 오늘 같은 거부 연속에서는 판정이 영원히 비어 콘솔이 아무 말도 하지 않는다.
- 거부 응답의 `rejected_fit`(점수·면적·잘린 변)은 `ingest_proposals.py`가 이미 내는데 Fleet은 읽지 않는다.
- 로봇 쪽 AMCL·스캔 일치 품질은 Fleet이 보는 값에 없다(`rg amcl_cov|scan_match` 5개 파일, 모두 Fleet 밖). 천장 sighting 대 로봇 자세 비교는 브라우저(`trackingDriftSample`)에만 있다.
- 카메라가 움직였는지(A)와 바닥·배치가 바뀌었는지(B)는 점수·면적·수락 맞춤의 어긋남만으로는 가려낼 수 없다. 둘 다 같은 잔차를 낸다. 페인트와 독립한 기준(바닥에 고정한 마커, 승인 프레임의 정적 특징, 로봇 쪽 일치)이 필요하다.

### Decision

1. **회차마다 센다.** 감시(`CalibrationDriftWatch`)가 거부·맞춤 없음·응답 없음 회차를 `CalibrationHealth`(`calibration_health.py`)에 넘긴다. 분류: `agree`/`disagree`(수락 맞춤, 기존 0.3 m·3° 문턱) · `mismatch`(거부, 면적 ≥ 0.40, 점수 < 0.70) · `low_coverage`(면적 < 0.20 또는 맞춤 없음) · `inconclusive`(그 사이, 크기가 다른 프레임, 비유한 값) · `no_response`(Vision 바쁨·불통, 연속 수를 올리지도 끊지도 않음).
2. **상태는 연속 회차로 바뀐다(60 s 주기).** `fresh` 3회 · `drifting` 3회 · `mismatch` 5회 · `insufficient_coverage` 3회. `drifting`·`mismatch`에서 `fresh`로 돌아가려면 5회 연속 일치가 필요하다. 180 s 동안 쓸 답이 없으면 `unknown`이다. 새 승인(리비전 변경)은 상태를 `unknown`으로 되돌리고 철회는 지운다.
3. **원인은 판정하지 않는다.** 행의 `cause`는 `undetermined`다. 이름은 관측한 것만 말한다(맞춤이 어긋남 / 맞는 맞춤이 없음 / 볼 수 없음). A/B 구분은 독립 기준이 생길 때(아래 후속 1·2) 따로 만든다.
4. **표시.** `GET /api/fleet/tracking` 출처 행의 `calibration_health`(API Ref v1.380)와 관제 지도 상태줄이 가장 무거운 상태(mismatch > drifting > insufficient_coverage) 하나를 쓴다. `insufficient_coverage`는 "카메라를 옮겨 트랙이 더 보이게 하세요"로, 나쁜 맞춤을 조용히 쓰지 않고 명시한다. 기존 `calibration_drift`는 그대로다.
5. **저널.** 모든 회차를 `calibration_health_log`(Fleet sightings DB, 최근 5000행)에 남긴다: 분류, 점수, 면적, 잘린 변, 이동·회전, 프레임 번호, 상태. 문턱(0.40/0.70/5회)은 11-09 한 사건에서 잡은 시작값이고 근거가 아니다. 며칠 치 정상 기준선과 카메라를 일부러 민 표본 하나로 맞춘다.
6. **게이트는 선택이고 기본은 꺼짐이다.** `ROSY_FLEET_CALIBRATION_GATE=1`이면 `drifting`·`mismatch` 동안 `TrackingService.approved_revision`이 `None`을 돌려주고, 그 하나를 읽는 `approved_record` sighting(D-587)과 auto-locate(D-989)가 409 `CALIBRATION_MISMATCH`로 멈춘다. 기체는 자기 AMCL로 계속 달리고 지도 자세는 마지막 앵커·오도메트리로 이어진다. 막지 않는 것: `unknown`·`insufficient_coverage`(증거 없음이 위치 추정을 끄면 안 된다), 추적 표시(`revisions()`, 운영자가 윤곽을 보고 판단해야 한다), 신원 결속. 이 게이트를 기본으로 켜는 일은 현장 관찰 뒤 별도 결정이다.
7. **자동 재보정은 이 기록에서 규정만 하고 만들지 않는다.** 설계 토론에서 독립 검토가 거부한 이유가 맞다: 부분적으로만 보이는 트랙의 맞춤은 자신 있게 틀릴 수 있고(반복 페인트 한 주기 어긋남), 같은 프레임에서 나온 3회 일치는 표본 1개이며, 바닥에 테이프를 붙이면 확신 있는 맞춤이 만들어지고, 두 후보 사이를 오가면 D-595가 막은 흔들림이 돌아온다. 자동 적용은 다음이 **모두** 있을 때만 새 ADR로 연다: (a) 페인트와 독립한 기준 — 승인 시점 프레임과 현재 프레임의 전체 영상 등록(인라이어 ≥ 60 %, 모서리 이동량 측정) 또는 D-933 인쇄 마커 — 이 이동을 A로 확인, (b) 변의 면적 한계(잘린 변이 맞춤을 구속하는지), (c) 이동 ≤ 0.5 m·회전 ≤ 5°, (d) 쿨다운 1 h·하루 2회·되돌리기(`previous_revision`)와 감사(`actor: auto`), (e) 사이트 설정 기본 꺼짐. 그때까지 보정의 쓰기는 운영자의 승인(`tracking_calibrations`)뿐이다.

### Consequences

- 오늘 같은 거부 연속이 5분 안에 `mismatch`로 보이고 `insufficient_coverage`는 카메라 이동이라는 사람의 일을 명시한다. 게이트를 켜기 전에는 어떤 소비자의 동작도 바뀌지 않는다.
- 게이트를 켜면 그 출처의 카메라 앵커가 운영자 재보정 때까지(또는 5회 일치까지) 사라진다. 콘솔 문구가 이를 말한다.
- 후속 증분(순서대로, 각각 별도 ADR·증거):
  1. Vision: 승인 프레임 대 현재 프레임 전체 영상 등록 → A(카메라 이동)와 보정량.
  2. Fleet: 로봇 AMCL 자세를 D-1003 짝 변환으로 천장 sighting과 비교(20쌍 이상의 중앙 잔차). 기체 쪽 새 필드는 불필요.
  3. B 경로: 확인된 `world_changed`에서 기체 스캔으로 사이트 지도 **초안** 버전을 만들고 운영자가 활성화하면 의존 보정마다 다시 맞추기 작업을 연다.
  4. 위 7항 조건이 갖춰진 뒤의 제한된 자동 적용.
- 사람이 해야 하는 일: 카메라를 옮겨 트랙 전체(최소 동·남쪽 변)가 보이게 하기, `mismatch`인 출처의 맵 고정 다시 하기, 문턱 조정용 기준선 표본(정상 며칠 + 카메라를 민 한 번) 확보.
- 시험: `operations/fleet/test/test_calibration_health.py`, `operations/fleet/test/web/tracking-layer.test.mjs`. 호스트 pytest는 장치·현장 수용을 대신하지 않는다.
