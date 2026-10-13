## D-484: 천장 카메라 필드 경계 자동 캘리브레이션 — 코너 마커 없는 측정 캘리브레이션

**Status:** Proposed (2026-10-06). `site-cameras.yaml` 소스가 `calibration_source: field_boundary`를
고르면 D-360 필드 사각형 감지와 D-375 페인트 정합이 표시 전용 제안에서 **측정 캘리브레이션 획득
경로**로 승격된다. 기본값 `corner_markers`(ArUco 4코너)는 그대로다. 로봇 ArUco 마커 관측은
유지되며 폰 앱과 `rosy-overhead/1` 전선은 바뀌지 않는다(D-425). sighting은 여전히 표시 전용
(D-257 5항)이고 `cmd_vel`·정책 증거·작업 시작은 없다.

관련: [D-257](D-257-site-lane-map-and-overhead-sightings.md)(sighting 좌표 투영),
[D-261](D-261-overhead-camera-app-skeleton.md)(Vision 수신),
[D-318](D-318-site-camera-preview-rectification.md)(미리보기 보정, 수동 모드 유지),
[D-341](D-341-overhead-console-approved-pairing.md)(카메라 페어링),
[D-360](D-360-overhead-field-auto-detection-proposal.md)(사각형 감지),
[D-375](D-375-overhead-map-registration-from-lane-paint-proposal.md)(페인트 정합),
[D-457](D-457-overhead-marker-priority-and-markerless-fallback.md)(tracking 캘리브레이션 우선순위),
D-472(지도 위 영상 표시, Proposed).

**번호:** D-483은 브랜치 `pilot-lcd-approval` 계열이 이미 써서 D-484를 썼다.

## 배경

1. 오늘날 측정 캘리브레이션은 코너 ArUco 마커 4개가 프레임 안에 전부 보여야 한다
   (`marker_homography`). 마커 4개를 현장에 인쇄·부착·유지하는 비용이 사이트마다 있다.
2. D-360은 흰 경계 사각형을 감지해 네 코너를 *제안*하고, D-375는 차선 페인트로
   이미지→맵 호모그래피를 *제안*한다. 둘 다 "어디에도 적용되지 않는다"가 계약이다.
3. Fleet 사이트 맵에는 이미 측량된 필드 사각형(`corner_world_m`, 맵 미터)이 있고 맵 id별로
   소스들이 이에 합의해야 한다. 맨 사각형에는 회전 모호성(90°씰 4가지)이 있어 마커 없이는
   어느 이미지 코너가 맵의 어느 코너인지 기하만으로 가릴 수 없다.

## 결정

1. **설정.** 소스 설정에 `calibration_source: corner_markers | field_boundary`(기본
   `corner_markers`). `field_boundary`일 때 `corner_marker_ids`는 없어야 하고
   `corner_world_m`은 필수다. Fleet `site-cameras.yaml` 검증과 Vision 검증이 같은 규칙을
   적용하고, 맵 id별 사각형 합의 규칙은 그대로다.
2. **측정 소스.** `field_boundary` 소스는 매 프레임이 아니라 주기(기본 1 Hz, 카메라는 고정)
   로 D-360 사각형 감지를 돌리고 감지된 네 코너와 `corner_world_m`의 대응으로
   `games` 호모그래피를 만든다. 로봇 ArUco 마커는 매 프레임 투영한다. 안정성 게이트:
   코너 급변(이동량이 문턱 초과)은 STALE로 보고 연속 일관 감지 후 재획득, 연속 실패는
   유예 뒤 상실(orientation도 초기화, 안전 방향은 sighting 끊김이다).
3. **회전 판정은 완전 자동.** orientation 미확정 상태에서는 D-375 페인트 정합을
   `map_worker` 프로세스(단일 flight, 무거운 정합은 절대 이벤트 루프에서)에 1회 요청한다.
   수락된 정합의 `map_to_image`로 맵 사각형 네 코너를 이미지에 투영하고 감지 코너와
   최근접 대응시킨다. 모든 거리가 문턱 안이고 대응이 순환 일대일일 때만 orientation을
   확정한다. 정합 거부·애매는 `orientation_pending` 상태와 사유로 남고 **추측하지 않는다**.
   사이트에 페인트가 없으면 orientation은 자동 확정이 안 되고(사유 표시) 마커 모드나
   페인트 설치가 답이다.
4. **프로토콜은 additive.** `SiteSightingPayload.corner_marker_ids`는 선택화되고
   `calibration_source`가 추가된다(API Ref 버전 행 추가). Fleet `accept()`는
   `calibration_source`까지 일치 검사한다. `quality`는 `null`을 유지해 정책 증거 의미가
   몰래 바뀌지 않게 한다.
5. **미리보기 자동 보정.** 미리보기 리스의 rectification에 `mode: auto`가 추가된다.
   Vision은 worker가 수용한 사각형으로 원근 보정된 프레임을 내고
   `X-Frame-Rectified: auto`로 표시한다. 감지가 없으면 원본과 사유. D-318 수동 프로파일은
   비-필드 소스와 진단용으로 그대로다.
6. **영향 없는 것.** 폰 앱(D-425 역할 그대로), `rosy-overhead/1` 전선, D-457 tracking의
   `choose()` 우선순위(마커 우선 유지; field_boundary가 tracking 캘리브레이션에도 들어가는
   것은 별도 변경), D-268 정책 증거, `cmd_vel`.

| ADR | 관계 |
|-----|------|
| D-257 | sighting 투영 경로 재사용, 좌표·개정 검사는 그대로 |
| D-318 | 수동 미리보기 보정 유지, 자동 모드 추가(디스플레이 전용 경계도 유지) |
| D-360 | 3항 "제안은 적용되지 않는다"를 `field_boundary` 소스에 한해 대체 — 감지 결과가 측정 캘리브레이션 소스가 된다 |
| D-375 | 5항을 마찬가지로 orientation 획득에 한해 대체 — 수락 게이트는 그대로 |
| D-457 | tracking의 마커 우선·승인 기록 체계는 불변, 후속 과제로 남김 |
| D-472 | 지도 위 영상 표시의 전제가 되는 캘리브레이션 자동화 |

## Validation / Transition

호스트 pytest: `operations/vision/test`(신규 `test_field_calib.py`, project/worker/ingest/
config 확장), `operations/fleet/test`(sighting 설정·수리 검증 확장),
`contracts/foundation/test`(payload additive). `python tools/harness/rosy_harness.py lint`.
호스트 통과는 장치·현장이 아니다: 실제 폰 프레임에서 orientation 확정·재획득·장시간 안정성은
`docs/validation/`에 날짜 증거로 남기고 DEVICE/FIELD 게이트를 따로 밟는다.
