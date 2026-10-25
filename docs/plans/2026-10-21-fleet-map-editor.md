# Fleet Map Editor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. 이 계획은 인터페이스 의존성이 커서 현재 세션에서 직접 구현하는 Native 방식을 권장한다. 사용자의 계획 검토와 실행 방식 선택 전에는 제품 코드를 변경하지 않는다.

**Goal:** Fleet에서 STL 도면을 등록하고 평면의 도로·목적지·구역을 직접 편집해 템플릿·초안으로 저장하고 검증 후 운영 지도에 적용한다.

**Architecture:** 기존 `SiteMapStore`·프로필·survey 편집·활성화를 재사용한다. 원본 STL과 변환 결과는 내용 해시로 분리 보관하고 지도에는 작은 참조만 넣는다. 코드 크기 한도를 보존하기 위해 기존 source-holder 방식으로 지도 관련 코드를 묶고 공개 Python import·웹 URL을 유지한다.

**Tech Stack:** 기존 Python/FastAPI/Pydantic/SQLite, Python 표준 라이브러리 STL 파서·제한된 변환 자식 프로세스, 기존 정적 ES modules/SVG, 원격 pytest·Node wrapper·Chromium. 새 제품 의존성은 추가하지 않는다.

**Spec:** [승인된 지도 편집기 설계안](2026-10-20-fleet-map-editor-design.md).

## Global Constraints

- “첫 지원 입력은 STL로 잡는다.” ASCII·binary STL을 지원하고 다른 CAD 형식은 실제 파일을 확보한 후 별도 계획으로 다룬다.
- “큰 원본 파일과 변환 결과를 기존 작은 지도 JSON에 넣지 않는다.” 기존 draft의 2 MiB 제한을 유지한다.
- “편집 클릭·드래그·저장·템플릿 복사는 로봇 명령을 보내지 않는다.” 실행 모드도 기존 활성 지도·Fleet admission·CORE 최종 권한을 사용한다.
- “현장 교정·활성화 증거는 복사하지 않는다.” 템플릿 복사·도면 변환 변경은 검토 완료 상태를 계승하지 않는다.
- 기존 trip·대형·teach 진행 중 활성화 거절, revision CAS, 인증·권한·CSRF, 기존 지도 직렬화·해시를 보존한다. 익명·읽기 역할에 쓰기 권한을 주지 않는다.
- `AGENTS.md`, `docs/reference/pr-pipeline.md`, D-766이 Git·검증·공개 병합의 기준이다. 크기 한도·기존 실패 목록·안전 예외로 이 작업을 통과시키지 않는다.
- D-430 안전 경로를 바꾸는 커밋은 현행 절차의 독립 검토와 실제 근거를 담은 `Safety-Review:` trailer를 갖춰야 한다. 문서의 계획 승인으로 안전 검토를 대신하지 않는다.
- 모든 pytest는 커밋된 SHA로 `tools/remote/remote_pytest.py`에서 실행한다. RED 테스트도 먼저 자기 테스트만 커밋하며 그 SHA는 게시하지 않는다. GREEN 구현 커밋 뒤 동일 명령과 `test/known_failures.py`를 실행해 NEW0을 확인한다.
- 명령의 `<external-log-dir>`는 실행별로 새 저장소 밖 폴더를 사용한다(예: 현재 `$env:TEMP` 아래 task·RED/GREEN·SHA별 하위 폴더). 원격 runner가 출력한 모든 run-N.txt를 공식 classifier로 검사하고 이전 RED 로그를 덮어쓰지 않는다.

## Review Focus

1. `solid`로 시작하는 binary STL과 잘린 파일: 길이·삼각형 수로 판별하고 기존 지도 손실 없이 거절 — Task 2.
2. 잘못된 단위·뒤집힌 축·0 거리·NaN: 명시적 도면 맞춤과 알려진 거리 확인, 비유한·범위 밖 좌표 거절 — Tasks 1·2·5.
3. 저장 충돌·디스크 부족·변환 취소: 활성 지도와 기존 초안 보존, 부분 파일 제거, 재시도 가능한 안내 — Tasks 3·5.
4. 확대·회전·드래그 뒤 클릭: 화면 좌표를 정확히 역변환하고 편집 동작이 이동 요청으로 전파되지 않음 — Tasks 4·5·6.
5. 템플릿 복사·도면 교체 뒤 교정: 새 지도 식별자·미검토 상태, 기존 teach/카메라/로봇 앵커 재사용 금지 — Tasks 3·5·6.

## 구현 인터페이스 결정

아래 신규 이름·REST 경로·제한은 **구현 제안**이다. Task 1에서 ADR·API reference·스키마를 함께 확정한 뒤 사용하며 현재 제공되는 API라고 취급하지 않는다.

- `DrawingTransform`: `plane`=`xy|xz|yz`, `unit`=`m|cm|mm`, `source_origin`=원본 평면상의 유한 2좌표, `map_origin_m`=유한 미터 2좌표, `heading_rad`=기존 survey와 같은 [-2π, 2π]의 유한 라디안, `scale`=유한 양수. `p_map = map_origin_m + R(heading_rad) * (p_source - source_origin) * unit_m * scale`. 측정한 두 점의 거리를 `distance_m`로 맞춰 scale을 계산한다. 0 거리와 변환 후 기존 지도 좌표 한계 밖의 값은 거절한다.
- `DrawingReference`: 소문자 64자리 `asset_sha256`, `projection_sha256`. `SiteMap.drawing`은 선택 필드이며 없는 지도는 기존 bytes/hash를 보존한다. 도면 지도는 `survey.revision == projection_sha256`이어야 한다. 변환 메타데이터는 projection과 함께 보관한다.
- 승인된 설계의 도로 이름은 기존 edge ID와 구분한다. `SiteEdge.name`을 선택 문자열(1–64자·공백만인 값 거절)로 추가하고 없는 값은 직렬화에서 생략한다. UI에서 비우면 None/생략으로 저장하며 ID·도로/시설 참조를 변경하지 않는다. 기존 장소·시설 이름 필드는 재사용한다.
- 원본 16 MiB, 삼각형 200,000개, 투영 후 중복 제거 선분 50,000개, projection JSON 8 MiB, 저장소 총 1 GiB. 업로드 수신은 최대 60초, 변환은 한 번에 1개, 자식 프로세스 wall timeout 5초·메모리 256 MiB. 이 제한은 기존 88,484 bytes/1,768 triangles 샘플을 수용하며, 큰 실제 파일이 거절되면 측정 후 후속 변경으로 조정한다. 임의 단순화나 일부 도면 누락으로 통과시키지 않는다.
- 제안 경로: `POST /api/fleet/site-map/drawings`는 raw STL bytes를 받아 `{asset_sha256, format, triangle_count, bounds_3d}`를 반환한다. `POST /api/fleet/site-map/drawings/{asset_sha256}/projections`는 `DrawingTransform`을 받고 `{projection_sha256, asset_sha256, transform, bounds_m, segments}`를 반환한다. `segments`는 미터 좌표의 두 끝점을 가진 선분 목록이다.
- `GET /api/fleet/site-map/drawing-projections/{projection_sha256}`는 기존 지도 읽기 guard, `GET /api/fleet/site-map/drawings/{asset_sha256}/source`는 named operator guard를 사용한다. 쓰기는 기존 named operator·CSRF 경로를 따른다. hash 이외의 파일 경로·외부 URL은 받지 않는다.
- 제한 초과 413, 잘못된 STL/변환 422, 변환 중 429, 미설정/변환 프로세스 장애 503, 저장 공간 부족 507, 없는 해시 404. 기존 계정·revision·busy 오류 규약을 바꾸지 않는다. 새 오류 코드 문자열은 Task 1의 API 오류 표에서 고정한다.
- 원본·변환 결과는 `<tasks_db.parent>/<tasks_db.name>.site-map-assets/` 아래에 atomic rename으로 저장해 다른 DB의 보관 위치와 구분한다. `--tasks-db`가 없으면 기존 메모리 지도는 유지하고 도면 보관 API만 503으로 비활성화한다. 첫 버전에는 자동 삭제·외부 URL 가져오기·새 설정 옵션을 만들지 않는다.

## 파일 경계

| 책임 | 경로와 인터페이스 |
|---|---|
| 계약 | 새 `contracts/foundation/core_common/protocol/site_drawing.py`: `DrawingTransform`, `DrawingReference`; 기존 `operations/fleet/fleet/site_map.py`의 선택 drawing·도로 name 필드 |
| 기존 map/teach holder | `operations/fleet/fleet/server/sitemap/`로 `site_map_store.py`, `site_map_routes.py`, `teach_service.py`, `teach_routes.py`를 이동. `_source_layout.SERVER_HOLDERS`와 manifest `source_packages`로 기존 `fleet.server.*` import 유지 |
| STL 변환 | 새 holder의 `site_map_projection.py`: `inspect_stl(path: Path) -> dict`, `project_stl(path: Path, transform: DrawingTransform) -> dict`; `python -m fleet.server.site_map_projection` 자식 프로세스 진입점 |
| 보관·HTTP | 같은 holder의 `site_map_assets.py`: `SiteMapAssetStore(root: Path)`, `put_stl(path: Path) -> dict`, `project(asset_sha256: str, transform: DrawingTransform) -> dict`, `projection(projection_sha256: str) -> dict`, `source(asset_sha256: str) -> Path`, `validate_reference(reference: DrawingReference, survey_revision: str) -> None`; `site_map_drawing_routes.py`: `install_site_map_drawing_routes(app, *, assets, read_guard, require_named_operator)` |
| runtime 구성 | 같은 holder의 `site_map_bootstrap.py`로 CLI `_build_site_map(args, tasks_db)` 본문을 이동하고 기존 함수는 위임한다. 반환 `(site_maps, routing_config)` 유지; `SiteMapStore(..., drawing_assets=None)`에 보관 객체 주입 |
| 지도 화면 holder | `applications/fleet/web/sitemap/`로 기존 `site-map.html`, `.css`, `.js`, `site-map-survey.js`, `site-map-teach.js`, `site-map-camera.js` 이동. `console/static_routes.py`와 기존 정적 자산/패키징 시험에서 공개 URL을 유지 |
| 새 편집 기능 | UI holder의 `drawing-import.js`, `edit-history.js`, `map-editor.js`, `map-editor.css`; 기존 shared 편집 함수와 `fitView(...).toPx/toMap` 재사용 |

## Task 1: 도면 참조 계약과 이전 지도 호환성

**Files:** Create `contracts/foundation/core_common/protocol/site_drawing.py`, `operations/fleet/test/test_site_map_drawing_contract.py`; Modify `docs/reference/ROSY API & Protocol Reference.md`, `docs/spec/ROSY FLEET SRS.md`, `contracts/foundation/core_common/protocol/schemas.py`와 API reservation/bump 도구가 정렬하는 버전 핀, 새 ADR와 자신의 ADR Log 행. 구조 ADR에는 D-427·D-429·D-430 관계 표를 넣는다. Fleet 모델의 drawing 연결은 크기 분리와 함께 Task 2에서 수행한다.

**Interfaces:** 위 표의 두 Pydantic 모델. 소비자는 Tasks 2–6이다. `SiteMap.drawing` 연결과 survey revision 대조는 Tasks 2·3의 책임이다.

- [ ] RED: `test_legacy_map_dump_is_unchanged`, `test_drawing_hashes_and_transform_are_bounded`를 먼저 작성·커밋한다. 예: `assert SiteMap.model_validate(old).model_dump(by_alias=True, exclude_none=True) == old`; `DrawingReference(asset_sha256='../x', projection_sha256='0'*64)`와 `DrawingTransform(..., scale=0)`는 ValidationError.
- [ ] 원격 실행: `python tools/remote/remote_pytest.py --log-dir <external-log-dir> -- operations/fleet/test/test_site_map_drawing_contract.py -q`. 새 모델/검증이 없어 실패하는지 확인한다.
- [ ] ADR/API 번호를 작성 직전에 기존 reservation 도구로 선점한다. 위 제안의 경로·DTO·오류 표·제한을 API reference에 고정하고 두 계약 모델을 구현해 커밋한다. 이 단계에는 기존 Fleet main unit의 생산 코드를 늘리지 않는다.
- [ ] 같은 원격 명령과 Fleet의 `test_mapless_survey.py`, `test_site_map_v5.py`, CORE의 `middleware/core/gateway/test/test_protocol_version_alignment.py`를 실행한다. GREEN·NEW0, API 버전 정렬·harness lint·whitespace 확인 후 다음 Task로 간다.

## Task 2: 제한된 STL 파서·투영과 source holder 분리

**Files:** Move 위 map/teach 4파일; Create `operations/fleet/fleet/server/sitemap/site_map_projection.py`, `site_map_bootstrap.py`, `operations/fleet/test/test_site_map_projection.py`; Modify `operations/fleet/fleet/site_map.py`, `_source_layout.py`, CLI 위임, `tools/harness/platform_parts.yaml`, `test/architecture/size_units.txt`, 측정에 따라 낮아지는 `size_ratchet.txt` 행과 source-path 소비자.

**Interfaces:** Task 1 모델을 받아 표의 `inspect_stl`·`project_stl`을 제공한다. projection hash는 원본 hash·변환기 버전·정규화한 transform·결과의 canonical JSON으로 계산한다. 사용자 원본 이름은 경로에 쓰지 않는다.

- [ ] RED: 코드에서 생성한 작은 ASCII/binary STL fixture로 `test_binary_solid_header_is_not_ascii`, `test_truncated_and_nonfinite_mesh_rejected`, `test_xy_xz_yz_units_and_origins`, `test_triangle_and_segment_budgets`를 작성·커밋한다. 예: 1,000 mm 기준선은 unit=mm·scale=1에서 `math.isclose(length, 1.0)`; 길이가 같은 m/cm fixture도 같은 미터 결과여야 한다. 저장소의 기존 STL bytes는 수정하지 않는다.
- [ ] 같은 RED 커밋에 Task 1 계약 시험 파일의 `test_optional_road_name_roundtrips_without_changing_legacy_edges`를 추가한다. 한글 이름·64자 경계·공백/65자 거절·없는 이름의 이전 dump/hash 유지와 도로 참조 보존을 단언한다.
- [ ] 원격 실행: `python tools/remote/remote_pytest.py --log-dir <external-log-dir> -- operations/fleet/test/test_site_map_projection.py operations/fleet/test/test_site_map_drawing_contract.py -q`. 예상 RED를 확인한다.
- [ ] source-holder 이동과 파서·투영을 함께 구현한다. binary는 `84 + 50 * triangle_count` 길이를 먼저 검사하고 그렇지 않은 입력은 엄격한 ASCII 문법으로 검사한다. 삼각형을 순회하며 유한 좌표·개수·선분 예산을 검사하고 선분은 정확한 끝점 쌍으로 중복 제거한다. STL은 배경일 뿐 도로·목적지를 자동 생성하지 않는다.
- [ ] 같은 GREEN 커밋에 선택 `SiteMap.drawing`과 `SiteEdge.name`을 연결하고 Task 1의 기존 지도 dump/hash 회귀를 유지한다. 두 None 필드는 dump/hash에 나타나지 않게 한다. 분리 전 Fleet main unit에 먼저 필드를 추가하는 중간 커밋을 만들지 않는다.
- [ ] `SERVER_HOLDERS += ('maps',)`에 대응하는 현행 등록 방식으로 기존 imports/설치 wheel을 유지한다. 964줄인 기존 map/teach와 실제 변환 구현을 같은 단위로 측정해 D-766 최소 1,000줄·최대 10,000줄을 만족시킨다. 채우기 코드·한도 상향은 금지한다. CLI의 기존 923줄 한도는 위임으로 줄인다.
- [ ] 같은 원격 명령에 Fleet의 `test_teach_survey.py`, `test_mapless_survey.py`, root의 `test/architecture/test_module_structure.py`, `test/test_size_limits.py`, `test/test_structure_installed_packages.py`, `test/test_io_image_closure.py`를 추가해 GREEN·NEW0을 확인한다. 각 중간 커밋도 `python tools/harness/size_range.py <task-base> HEAD`가 통과해야 한다.

## Task 3: 인증된 도면 보관·변환 API와 활성화 검증

**Files:** Create holder의 `site_map_assets.py`, `site_map_drawing_routes.py`, `operations/fleet/test/test_site_map_drawing_api.py`; Modify 이동된 `site_map_routes.py`, `site_map_store.py`, `site_map_bootstrap.py`.

**Interfaces:** Task 2의 worker와 위 보관 인터페이스를 제공한다. 기존 `install_site_map_routes(...)`가 도면 라우터를 설치하므로 `create_app`의 공개 signature와 939줄 한도를 늘리지 않는다. 저장·프로필·활성화는 참조 존재와 survey revision 일치를 보관 객체로 검증한다.

- [ ] RED: `test_anonymous_and_readonly_cannot_upload`, `test_chunked_upload_enforces_actual_bytes`, `test_retry_deduplicates_and_restart_preserves_source`, `test_worker_timeout_and_busy_are_bounded`, `test_cancelled_or_slow_upload_releases_slot`, `test_disk_full_preserves_map`, `test_missing_or_mismatched_reference_cannot_save_or_activate`를 작성·커밋한다. 예: 실패 전후 `assert store.active_view() == before_active` 및 `assert store.draft_view() == before_draft`.
- [ ] 원격 실행: `python tools/remote/remote_pytest.py --log-dir <external-log-dir> -- operations/fleet/test/test_site_map_drawing_api.py -q`. 예상 RED를 확인한다.
- [ ] Content-Length를 신뢰하지 않는 stream 제한·고정 해시 경로·symlink/경로 이탈 거절·atomic 저장·총량 제한을 구현해 커밋한다. worker는 event loop 밖에서 고정 module/고정 보관 파일만 열고 5초 timeout·256 MiB 메모리·동시 1개 제한을 적용한다. 실패·취소 시 worker 종료와 임시 파일 정리를 보장한다. 원본 및 성공한 projection은 재시작 후에도 읽힌다. 보관 파일은 공개 static root 밖에 두고 원본 GET은 attachment·application/octet-stream·nosniff로 반환한다.
- [ ] 도면 교체 시 `survey.reviewed=false`, review note 초기화와 새 projection revision을 요구한다. 저장은 운영 지도와 분리하고 활성화의 기존 trip/formation/teach busy guard·CAS를 보존한다. 업로드 감사에는 principal·해시·결과만 넣고 실제 파일 경로·원본 bytes를 넣지 않는다.
- [ ] 같은 명령과 `test_site_map_api.py`, `test_map_profiles.py`, `test_teach_survey.py`, `test_server_formation.py`를 원격 실행해 GREEN·NEW0을 확인한다. 크기 검사·문서 계약·안전 경로 독립 리뷰와 trailer를 현행 규칙으로 완료한다.

## Task 4: 기존 편집 연산에 실행 취소·꼭짓점 수정을 연결

**Files:** Move 표의 Console 6파일 into `applications/fleet/web/sitemap/`; Create 그 holder의 `edit-history.js`, `operations/fleet/test/web/map-editor.test.mjs`; Modify `server/console/static_routes.py`, 패키징/정적 경로 소비자, `size_units.txt`·낮아지는 ratchet 행과 `shared/site-map-edit.js`의 선택 도로 이름 보존.

**Interfaces:** `createEditHistory(initialMap)` → `{current(), apply(nextMap), undo(), redo(), reset(savedMap), canUndo(), canRedo()}`. 반환 snapshot은 호출자가 원본을 변경할 수 없게 복사한다. 최대 50 snapshot/직렬화 합계 8 MiB로 오래된 undo부터 제거하며 재접속 시 저장 revision에서 새 이력을 시작한다.

- [ ] RED: `undo_redo_preserves_original_and_clears_redo_on_new_edit`, `history_budget_is_bounded`, `vertex_edit_preserves_road_endpoints_and_facility_links`를 작성·커밋한다. 예: `assert.deepEqual(history.undo(), before)`; 되돌린 뒤 apply하면 `assert.equal(history.canRedo(), false)`.
- [ ] 원격 실행: `python tools/remote/remote_pytest.py --log-dir <external-log-dir> -- operations/fleet/test/test_site_map_api.py::test_console_web_node_unit_tests_pass -q`. Node 미설치 skip이면 실행 증거가 아니므로 Node가 있는 시험 PC에서 확인한다.
- [ ] 6파일 이동·기존 `/console/site-map` 및 `/console/assets/site-map*.js` URL 유지·새 module 등록과 history를 같은 GREEN 커밋으로 구현한다. 1,526줄의 기존 지도 화면을 실제 UI 단위로 등록하고 이동 파일의 ratchet은 동일 blob/측정값으로 연결한다. Console main unit에 history를 먼저 늘리는 중간 커밋을 만들지 않는다. `rg`로 이동 전 6개 source 경로의 소비자를 찾아 같은 커밋에서 모두 갱신한다.
- [ ] 도로·목적지·구역 수정은 기존 `appendSurveyElement`·`editSurveyElement`·`removeSurveyElement`의 `geometry`, `from`, `to`, `yaw`, `approaches` DTO를 사용한다. 기존 도로 편집 helpers에 선택 name을 연결하고 geometry 수정이 기존 이름을 잃지 않는 Node 회귀를 추가한다. 도로 끝점이나 참조 중인 시설을 무효화하는 편집은 이유를 표시해 거절하며 silent cascade 삭제하지 않는다.
- [ ] 동일 원격 Node wrapper와 `test_mapless_survey.py`, `test_site_map_browser.py`, `test/architecture/test_module_structure.py`, `test/test_size_limits.py`가 GREEN·NEW0인지 확인한다. 모든 중간 커밋에 size-range를 확인한다. 편집 이력에는 로봇 요청·API 호출 함수를 넣지 않는다.

## Task 5: 지도 화면에서 도면 맞춤·직접 그리기·저장까지 연결

2026-10-21 사용자 보완: 특정 지역·지도·업무 도메인에 종속되지 않는 기반 기능을 우선한다. STL 변환은 순수 좌표 입력 어댑터로 유지하고, 이력과 점·선·다각형 편집은 Fleet 필드·시설 종류·현장 상수를 모르는 코드로 먼저 검증한다. `maps/geometry-edit.js`가 유한 2D 좌표와 꼭짓점 교체/삭제·화면 좌표 역변환을 맡으며, `map-editor.js`가 기존 Fleet DTO와 편집 연산을 연결한다. 지도/업무의 의미와 활성화 권한은 기존 Fleet 계층에 남긴다. 추가 도메인용 플러그인 체계나 새 서비스는 만들지 않는다.

**Files:** Create `applications/fleet/web/sitemap/drawing-import.js`, `maps/map-editor.js`, `maps/map-editor.css`, `operations/fleet/test/test_map_editor_browser.py`; Modify Task 4에서 이동된 map HTML/CSS/JS, `server/console/static_routes.py`의 새 asset 등록.

**Interfaces:** `createDrawingImport({request, map, replaceDraft, confirmDiscard})` → `{load(file), register(transform), cancel()}`; 요청 취소/세대 확인으로 뒤늦은 결과가 새 초안을 덮지 않게 한다. `createMapEditor({svg, map, view, changed, reason})` → `{sync(), cancel(), destroy()}`; `map()`·`view()`는 현재 상태, `changed(nextMap)`는 Task 4 history에 반영한다. `reason()`이 있으면 편집을 금지한다.

- [ ] RED: 실제 Chromium의 `test_import_register_edit_save_reopen`, `test_zoom_rotation_and_drag_never_dispatch`, `test_import_failure_and_unsaved_navigation_preserve_draft`, `test_copy_template_requires_new_site_review`를 작성·커밋한다. road/place/exclusion을 각각 그리고, 꼭짓점 이동·삭제·undo/redo·좌표 숫자 입력·템플릿 저장·재접속을 검증한다. 편집 중 `assert robot_command_requests == []`.
- [ ] 원격 실행: `$env:ROSY_RUN_BROWSER_TESTS='1'; python tools/remote/remote_pytest.py --log-dir <external-log-dir> -- operations/fleet/test/test_map_editor_browser.py -q`. 기능 부재에 의한 RED를 확인한다.
- [ ] Task 4의 공개 URL·패키징 매핑을 사용한다. 각 파일의 기존 한도는 올리지 않는다. `site-map.js`는 새 컨트롤러에 위임해 771줄 이하로 줄인다. 새 JS는 파일당 600줄 이하를 유지한다.
- [ ] 도면 맞춤 패널·SVG 참조 레이어·선/점/다각형 도구·선택 속성·undo/redo·레이어 표시를 구현·커밋한다. SVG는 검증된 숫자로 path를 생성하며 원본 문자열을 HTML/SVG로 주입하지 않는다. 기존 `fitView(..., discs)`에 도면 bounds의 보기용 점을 넘겨 빈 초안에서도 도면 전체를 맞춘다. `getScreenCTM().inverse()`와 `view().toMap`으로 확대·회전된 좌표를 역변환한다.
- [ ] 맞춤 완료 시 `drawing`의 두 해시와 `survey.revision=projection_sha256`, `origin=map_origin_m`, 같은 heading, `scale_source='measured'`, 입력한 양수 `measured_distance_m`, 운영자가 쓴 description, `reviewed=false`를 연결한다. 기존 초안의 도로·장소·구역은 도면 참조 변경만으로 이동·삭제하지 않는다. 사용자가 명시적으로 빈 지도 시작을 선택한 경우만 geometry를 비운다. 브라우저 회귀에서 참조 변경 전후 기존 geometry 보존을 단언한다.
- [ ] pointer capture/이동 임계값으로 드래그 뒤 click 전파를 막고 Enter 그리기 완료·Esc 취소·Delete·Ctrl/Cmd+Z·재실행과 숫자 입력을 제공한다. 그리는 중 undo/redo는 마지막 점에, 완료 후에는 Task 4 이력에 적용한다. 입력 필드 안의 단축키는 편집 명령으로 가로채지 않는다. 작은 화면은 공용 접이식 도구·속성으로 같은 상태를 유지한다.
- [ ] profile copy는 새 map_id·미검토 survey를 만들고 활성 버전·teach 기록·카메라 교정·로봇 위치 앵커를 계승하지 않는다. 초안 저장은 기존 PUT/CAS, 적용은 기존 명시적 확인과 activate 경로를 사용한다. 변경이 있으면 이탈·도면 교체 전에 확인하고 거절 사유를 표시한다.
- [ ] 같은 browser 명령과 Node wrapper·`test_site_map_browser.py`·`test_map_profiles.py`·`test/architecture/test_module_structure.py`를 원격 실행해 GREEN·NEW0을 확인한다. 1366/320 viewport, 좌표·단위 잘못 입력, 선택/삭제/취소 keyboard, prototype/XSS 입력, 401/403/409/413/429/503/507, 서버 재시작을 포함한다.

## Task 6: 지도 활성화·기존 이동 UI·군집 경계 회귀

**Files:** Modify `operations/fleet/test/test_map_editor_browser.py`, `test_site_map_trip.py`, `test_server_formation.py`, `test_teach_survey.py`; 제품 변경은 이 테스트가 드러낸 연결 누락에 한정한다.

**Interfaces:** 기존 활성 지도 버전·`planTrip`·`startTrip`·대형 admission을 사용한다. 새 navigation/군집 API·컨트롤러는 만들지 않는다.

- [ ] RED: `test_draft_click_never_plans_or_starts_trip`, `test_only_active_map_version_can_be_used_after_activation`, `test_running_trip_formation_or_teach_blocks_activation`, `test_new_drawing_does_not_reuse_old_camera_or_robot_frame`를 작성·커밋한다. 연결이 이미 구현돼 GREEN이면 중복 구현 없이 기존 기능 증거로 남긴다.
- [ ] 원격 실행: `$env:ROSY_RUN_BROWSER_TESTS='1'; python tools/remote/remote_pytest.py --log-dir <external-log-dir> -- operations/fleet/test/test_map_editor_browser.py operations/fleet/test/test_site_map_trip.py operations/fleet/test/test_server_formation.py operations/fleet/test/test_teach_survey.py -q`.
- [ ] 누락된 경우에만 편집/실행 모드와 활성 버전 표시를 연결해 커밋한다. 기존 주의 큐·비상 정지 접근성을 보존한다. 미검토·미교정 상태를 무시하거나 로봇을 자동 등록/이동시키지 않는다.
- [ ] 같은 원격 명령이 GREEN·NEW0인지 확인하고, simulated API/host/browser 증거와 실제 현장 교정·단독 이동·군집 주행 수용을 분리해 기록한다.

## Task 7: 검토·정상 릴리스·운영자 인수

**Files:** 해당 모듈의 own logs·생성 index, `docs/validation/fleet-map-editor-<date>/result.md`의 비식별 증거. 실제 호스트·지도·측정·설정은 gitignored private 기록으로 분리한다.

- [ ] 전체 변경을 승인된 spec과 대조하고 새 head의 독립 소스/계약 리뷰에서 지원되는 수정 요청이 없어야 한다. 모든 커밋에 size-range·harness·D-430 검사를 적용하고 정상 pre-push를 통과한다. 단위 이동 때문에 FULL로 선택되면 GitHub 전체 CI를 기다린다.
- [ ] 승인된 게시 범위에서 PR을 만들고 실제 필수·비게이팅 잡, 실제 browser 실행/skip, NEW 비교를 기록한다. 확인한 head를 squash 병합하고 main 전체 CI·후보 출처·서명을 확인한 뒤 기존 정상 updater로 설치한다. 적색 검사 우회·서명키 교체·수동 운영 DB 덮어쓰기는 하지 않는다.
- [ ] 설치된 image/source/CSS·HTTPS와 업로드→변환→편집→저장→재접속을 확인한다. 운영자의 실제 파일을 시험할 때는 먼저 새 초안/템플릿에 보관하고 기존 활성 지도를 교체하지 않는다.
- [ ] 실제 도면 기준 거리·축·원점·카메라/로봇 frame을 현장에서 확인한 뒤 운영자가 검토·활성화한다. 좌표 이동·군집 주행의 실물 수용은 사람·로봇·교정 근거가 준비된 후 별도 승인된 절차로 진행한다. 준비되지 않으면 해당 항목을 미검증으로 남기고 전체 완료라고 보고하지 않는다.

## 계획 자체의 검증과 다음 단계

2026-10-21 실행 근거: Task 1 `5e0c18fbdf` 계약/이전 지도/프로토콜/구조 원격 통과, Task 2 `1d8e942ac4` STL·설치·구조147통과, Task 3 `97edf0c472` API·보관·기존 프로필/대형92통과, Task 4 `edfa3d25fd` 기존 브라우저/Node/설치226통과, Task 5 `1ad375aef1` 새 Chromium/Node/구조/설치74통과, Task 6 `3adf7e4a92` 편집/원본 STL/실행 경계106통과. 모두 커밋 SHA의 원격 실행이며 NEW0이다. Task 7의 독립 검토·전체 CI·정상 배포와 실제 현장 수용은 이 근거에 포함하지 않는다.

이 문서는 구현 계획이며 위 기능이 존재한다는 증거가 아니다. 설계 요구는 Tasks 1–7에 배정했고 Review Focus 5개도 각각 테스트에 연결했다. 실제 CAD 형식 확대·3D 메시 편집·자동 도로 추출·실시간 공동 편집은 제외한다.

현재 Native 실행을 권장한다. 작업 간 계약·보관·편집 인터페이스가 연결돼 있어 한 세션에서 순서대로 구현하고, 공개 게시 전 독립 계약·소스 리뷰를 받는 편이 적합하다. 계획 검토 후 사용자가 Native 또는 Subagent-driven을 선택하면 해당 실행 스킬로 시작한다.
