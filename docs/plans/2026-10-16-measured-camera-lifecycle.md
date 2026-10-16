# 실측 카메라 교정 운영 연결 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans for native execution, or superpowers:subagent-driven-development if the user selects delegation. Track each step with the checkboxes below.

**Goal:** 기존 측정 도구에서 나온 교정 묶음을 Fleet에서 승인·저장·철회하고, 현재 촬영 session을 확인한 Vision에서만 지도 미리보기에 적용하며 실제 적용 상태를 읽는다.

**Architecture:** Fleet의 기존 승인 소유자와 DB를 확장하되 preview 목적을 기존 tracking 승인과 구분한다. Vision이 기존 inverse remap과 signed Viewer lease로 최신 원본을 처리하며, 현재 source session·revision·짧은 config lease가 맞지 않으면 적용하지 않는다.

**Tech Stack:** Python, Pydantic, SQLite, OpenCV/NumPy, FastAPI, 기존 websockets ingest, vanilla ES modules, 기존 Playwright/원격 pytest. 새 서비스나 의존성 없음.

**Spec:** [승인·적용·무효화 설계](2026-10-16-measured-camera-lifecycle-design.md). 사용자 2026-10-16 재개 요청으로 설계 검토를 통과했다. 이 계획의 검토와 실행 방법은 별도로 확인한다.

## Global Constraints

- 제품 변경은 현재 `.worktrees/camera-calibration`에서만 수행한다. main 착지·push·현장 배포는 이번 실행에 포함하지 않는다.
- 첫 단위는 미리보기 전용이다. 기존 tracking record와 `approved_revision` sighting admission에 실측 revision을 넣지 않는다.
- Fleet에는 JSON 수치·근거 식별자만 보낸다. JPEG·원본 경로·자격 정보는 전송하지 않는다.
- source·map identity/revision·렌즈·실제 JPEG 크기/회전·수신 session을 확인한다. 종횡비가 같다는 이유로 resize/crop를 허용하지 않는다.
- 초점·zoom·ISP 등 확인 불가능한 조건은 operator의 현재 session 확인으로 표시한다. 자동 계측이나 현장 정확도 증거로 보고하지 않는다.
- 모든 pytest는 커밋한 HEAD를 기존 remote runner로 실행하고 `known_failures`와 비교한다. 노트북 pytest 금지. Browser 실행에는 `ROSY_RUN_BROWSER_TESTS=1`을 명시한다.
- 실측 입력 없이 DEVICE/FIELD나 D-598 완료를 주장하지 않는다. 관련 근거는 [입력 점검](../validation/measured-camera-lifecycle-2026-10-16/evidence-inventory.md)에 있다.
- 새 ADR/API 번호는 파일·계약을 만들기 직전에 reservation 도구로 선점한다. 기존 Accepted ADR을 다시 쓰지 않는다.
- D-766 파일·단위 한도와 기존 CSP를 유지한다. 새 책임은 작고 전용인 모듈에 둔다.

## Review Focus

1. 같은 revision 문자열을 붙이고 K/D·바닥 변환을 바꾼 입력은 거절해야 한다 — Task 1의 tampering 시험.
2. 서로 다른 Fleet 인스턴스가 같은 SQLite에 쓰는 승인/철회 경합은 원자적으로 한 번만 성공해야 한다 — Task 2의 두 연결 시험.
3. 프로세스 재시작으로 connection counter가 다시 1이 되어도 과거 session 확인이 재사용되면 안 된다 — Task 4의 boot identity 시험.
4. 비동기 remap 중 철회·frame 교체·config lease 만료가 발생하면 이전 결과를 새 적용 결과로 반환하면 안 된다 — Task 4의 interleaving 시험.
5. 다른 source·화면으로 전환한 뒤 도착한 응답이 승인/적용 상태를 덮어쓰면 안 된다 — Task 5의 lifecycle/browser 시험.

## 파일과 인터페이스

| 책임 | 위치 | 경계 |
|---|---|---|
| 공유 JSON 계약·digest·숫자 검증 | 새 `contracts/foundation/core_common/protocol/measured_calibration.py` | Pydantic/stdlib만 사용; ROS·OpenCV·Fleet import 없음 |
| 측정 결과의 운영 묶음 export | 새 `operations/overhead/rosy_vision/calibration_bundle.py`, 기존 `camera_calibration.py` CLI | 기존 fit/floor 출력 재사용, 원본 경로 제거 |
| preview 승인 영속 저장·CAS·감사 | 새 `operations/fleet/fleet/server/measured_calibration_store.py`, 기존 `tracking_calibration.py` | 기존 DB 경로·소유자 아래 목적별 record; 별도 서비스 없음 |
| 승인·config·readback API | 새 `operations/fleet/fleet/server/measured_calibration.py`, 기존 `tracking.py`, `tracking_routes.py` | 기존 source token/named operator 권한 재사용 |
| signed preview 요청 계약 | 기존 `core_common/protocol/vision_preview.py`, Fleet의 새 `server/vision_preview_routes.py`, 기존 `app.py` | 기존 preview 라우트를 전용 installer로 옮겨 app.py 증가를 피함 |
| Vision의 session·lease·render 상태 | 새 `operations/overhead/rosy_vision/measured_preview.py`, 기존 `ingest.py`, `track/worker.py`, `track/fleet_client.py` | 기존 latest-only 입력, `plane_image`, signed lease 사용 |
| 설치 화면 | 새 `operations/site_ui/console/measured-calibration-view.js`, 기존 `install.js`, `install.html`, 필요한 CSS·static allowlist | UI가 계산/승인을 우회하지 않음; scope/lifecycle 사용 |

기존 함수 이름과 경로는 기준 `89d3ba4d1`에서 확인했다. 구현 시 현재 매니페스트·모듈 한도를 먼저 확인한다.

## Task 1: 검증 가능한 실측 교정 묶음

**Files:** 위 공유 계약·bundle exporter, `contracts/foundation/test/test_measured_calibration.py`, `operations/overhead/test/test_calibration_bundle.py`를 새로 만들고 기존 측정 CLI를 연결한다.

**Interfaces:**
- `MeasuredCalibrationBundle`: versioned JSON 모델. source_id, map_id/map_revision, lens/floor 후보, training/validation digest 목록, survey digest, 촬영 signature/렌즈/rotation, bounds, evidence_kind를 보존한다.
- `bundle_digest(bundle: MeasuredCalibrationBundle) -> str`: digest 필드를 제외한 canonical JSON의 SHA-256.
- `validate_bundle(raw: Mapping) -> MeasuredCalibrationBundle`: extra field, bool/비유한 수, K/D 모양, 특이 행렬, source/lens revision/독립 이미지 계보 불일치와 digest 변조를 거절한다.
- `export_bundle(report: Mapping, floor: Mapping, context: Mapping) -> dict`: D-636의 출력에서 묶음을 만들고 공유 validator로 재확인한다. CLI는 새 출력 디렉터리만 허용한다.

- [x] 숫자·계보·공간 혼합·동일 digest 재사용·K/D 변조 거절과 pinhole/fisheye의 실제 기존 fit/floor 출력 왕복 시험을 작성한다. 합성 fixture는 evidence_kind를 synthetic으로 보존한다.
- [x] 시험만 커밋하고 원격 RED를 확인한다. import 누락이 아닌 기능 실패인지 기록한다.
- [x] validator와 exporter를 구현한다. 기존 `_revision`과 함께 검증할 원본 report digest 목록을 묶음에 보존하고 p95/max 수치만으로 성공을 만들지 않는다.
- [x] 원격 GREEN, 기존 `test_camera_calibration.py` 회귀를 확인하고 기능 커밋을 남긴다.

## Task 2: 같은 승인 소유자 안의 영속 preview 기록

**Files:** 새 store, 기존 `tracking_calibration.py`, 새 `operations/fleet/test/test_measured_calibration_store.py`.

**Interfaces:**
- `MeasuredCalibrationStore(path: Path | None)`를 기존 `TrackingCalibrationStore`가 `preview` 속성으로 소유한다.
- `approve(bundle, *, expected_revision: str | None, approved_by: str, approved_at: float, limits: Mapping) -> dict`.
- `get(source_id: str) -> dict | None`, `all() -> list[dict]`, `revoke(source_id, *, expected_revision, principal_id, at) -> dict`.
- 기록은 source별 단일 preview 선택, 전체 묶음·승인 한도·승인자·시각·고유 승인 revision·persistent·use를 포함한다. 감사 원장에는 승인/교체/철회를 남긴다.

- [x] SQLite 재시작, 두 store 인스턴스 동시 승인/철회, 오래된 expected_revision, DB 쓰기 실패, 훼손된 row, legacy tracking 보존을 시험한다.
- [x] 시험 커밋의 원격 RED를 확인한다.
- [x] `BEGIN IMMEDIATE` 안에서 현재 revision을 DB에서 읽고 CAS·선택 변경·감사를 처리한다. 성공 전 메모리를 바꾸지 않는다. 저장 파일을 재검증하고 위조·불완전 기록을 적용하지 않는다.
- [x] 원격 GREEN과 기존 `test_overhead_tracking_calibration.py`를 확인한다.

## Task 3: 기존 API의 목적 구분과 승인·readback

**Files:** 위 Fleet service/routes, API reference·공유 schema exports·필요한 SRS, 새 `operations/fleet/test/test_measured_calibration_api.py`, 기존 관련 API 시험.

**Interfaces:**
- POST `/api/fleet/calibrations`: 기존 body 또는 `purpose:preview`, `kind:measured`, bundle, expected_revision, 명시적 p95/max 한도의 새 body. 실측 승인에는 named operator와 measured evidence가 필요하다.
- GET/DELETE 기존 calibrations 경로: `purpose=preview`일 때만 preview 기록을 읽거나 철회한다. DELETE는 expected_revision 필수. 목적 생략은 legacy 의미를 유지한다.
- GET `/api/fleet/detections/config?include_preview=true`: 인증된 source 자신의 optional `measured_preview`만 추가한다. 기본 응답은 기존 모양을 유지한다.
- POST `/api/fleet/detections/preview-status`: source token으로 자신의 revision/session/state/reason만 보고한다. GET preview 목록은 신선도에 따라 저장·적용·미적용을 구분한다. 임의 JPEG/추가 필드는 거절한다.

- [x] 먼저 새 ADR/API 번호를 선점하고 위 계약과 D-427/429/430 관계를 기록한다. 버전 pin은 reservation 도구로 같이 옮긴다.
- [x] viewer/source token 쓰기 거절, named operator, 다른 source 읽기/보고 거절, synthetic 승인 거절, 같은 DB 원자성, legacy 응답 보존 시험을 작성한다.
- [x] 시험 커밋의 원격 RED 후 API를 구현한다. body·report 크기와 문자열 길이를 제한한다.
- [x] 원격 GREEN과 tracking/sightings/start-point 회귀로 preview revision이 sighting admission에 들어가지 않음을 확인한다.

## Task 4: Vision session 확인·제한된 config lease·실제 render

**Files:** 위 Vision 모듈과 signed lease 모델/Fleet route installer, 새 `operations/overhead/test/test_measured_preview.py`, 관련 signer·ingest·worker 시험.

**Interfaces:**
- `MeasuredPreview`가 검증된 config 수신 시각, source session, 확인한 geometry, 승인 revision, 마지막 render 상태를 소유한다. config lease는 monotonic 5초, 응답 갱신 실패는 만료를 연장하지 않는다.
- session은 receiver boot UUID와 source link identity를 결합한다. 재시작·재접속은 새 확인을 요구한다.
- 기존 direct preview에 `measured-status` view를 추가한다. signed viewer lease로 현재 session·geometry·상태 JSON을 읽고 원본은 반환하지 않는다.
- Fleet 기존 `/api/fleet/vision/lease`에 optional measured 요청을 추가한다. 명시적 촬영 조건 확인은 named operator만 서명받을 수 있고 source/session/revision/capture_signature에 결속한다. 일반 viewer는 상태/확인된 영상 읽기만 가능하다.
- Vision의 기존 frame GET은 signed measured 요청일 때만 측정 plane을 그린다. 실제 JPEG decoded 크기도 검사하고 기존 `plane_image`/valid mask를 사용한다. ingest는 source 상태 callback을 worker의 기존 source-token client로 보고한다.

- [x] source session 재사용, 다른 lens·resolution/rotation·map, signature 미확인, source 끊김, 5초 lease 경계, config 갱신 실패, remap 중 철회/교체·만료, 오래된 frame cache 재사용을 실패 시험으로 고정한다.
- [x] 시험 커밋의 원격 RED 후 구현한다. event loop에서 수치 remap을 돌리지 않고 기존 thread 경로를 사용한다. await 뒤 session·config generation·lease를 다시 검사한다.
- [x] 성공 응답은 실제 source/session/revision을 헤더/readback에 보존한다. 원본은 변경하지 않고 불일치에서는 legacy 영상으로 자동 대체하지 않는다.
- [x] 실제 Fleet TestClient→source config→Vision ingest→direct preview→상태 report를 연결한 합성 integration과 기존 marker/preview 회귀로 원격 GREEN을 확인한다.

## Task 5: 운영자가 사용할 설치 화면

**Files:** 위 Console 전용 모듈과 설치 화면, 새 `operations/fleet/test/web/measured-calibration-view.test.mjs`, `test/test_measured_calibration_browser.py`.

**Interfaces:** `createMeasuredCalibrationView({scope, root, call, visionView})`는 현재 source, bundle import/수치 검토, 명시적 한도, 승인/철회, session 상태/촬영 조건 확인, direct measured preview를 한 흐름으로 연결한다.

- [x] 사용자 흐름 시험: bundle JSON import→source/map/오차 확인→한도 입력→named approval→session 확인→적용 readback→철회. 새 source/닫힌 화면의 늦은 응답이 기존 화면에 쓰이지 않는지도 확인한다.
- [x] 원격 browser RED 후 설치 화면의 기존 lifecycle와 UI 컴포넌트로 구현한다. 숫자 검증을 서버 권한 대신 사용하지 않는다. 승인 저장과 영상 적용을 다른 문구로 표시한다.
- [x] 데스크톱과 390px 화면에서 실제 Chromium으로 확인한다. 기존 signed preview·paint 승인과 회귀를 같이 실행하고 skipped를 통과로 처리하지 않는다.
- [x] 문서·모듈 logs/progress를 실제 확인 범위만 갱신하고 기능 커밋을 남긴다.

## Task 6: 첫 단위 검증과 D-598 후속 준비

- [x] 기준 `89d3ba4d1` 대비 affected selection을 검사한다. 공유 계약 변경으로 FULL 승격하면 그 요구를 유지하며 관련 시험만으로 전체 완료를 주장하지 않는다.
- [x] 기존 remote runner로 관련 계약·Vision·Fleet·Console/브라우저를 커밋한 revision에서 실행하고 각 로그의 NEW/known/skipped를 기록한다. 현재 외부 로그 위치는 `C:/DevTemp/camera-calibration/`이다.
- [x] 실제 producer-consumer 경로의 독립 contract review와 verification evidence review를 받아 지적을 해결한다. safety-tagged 변경은 D-430 독립 검토와 trailer를 충족한다.
- [x] [입력 점검](../validation/measured-camera-lifecycle-2026-10-16/evidence-inventory.md)의 실제 촬영·측량·D-587/593/596 현재 readback을 대조한다. 자료가 없으면 정확히 미검증으로 기록한다.
- [x] D-598에는 현재 World/Fleet 소유 경계, 오차 계수의 실제 측정, CARRIED/BRIDGED/감속 admission과 traffic 소비 계약을 후속 설계로 확정한다. 첫 단위의 통과를 D-598 완료로 바꾸지 않는다.

실행 전에 사용자가 이 계획을 검토하고 직접 구현/위임 중 하나를 고른다. 의존하는
인터페이스가 많으므로 이 세션에서 직접 구현하고 마지막에 독립 검토를 받는 방법을 권한다.
기준선 시험은 새 구현의 통과 증거가 아니며, 실측 자료가 필요한 전체 목표는 계속 유지한다.

## 실행 결과 (2026-10-17)

D-775 구현과 관련 원격 회귀를 완료했다. 검증 커밋 `a0a864b6ea`에서 3개 invocation 모두
exit 0, 20,243 passed / 1,159 skipped, NEW 0이다. 구체적인 커밋·브라우저·수정 및 판단의
비용은 [검증 기록](../validation/measured-camera-lifecycle-2026-10-16/result.md)에 적었다.

사용자는 실제 촬영·측량·odom 자료가 아직 없음을 확인하고, 그 자료가 필요한 작업을
이번 완료에서 제외하도록 지시했다. 실제 수집·현장 수용과 이에 의존하는 D-598 운영
활성화는 별도 후속이다. 전체 CI 승격 요구도 후속 통합 관문으로 유지한다.
