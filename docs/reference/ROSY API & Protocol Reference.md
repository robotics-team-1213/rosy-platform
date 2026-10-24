# ROSY API & Protocol Reference

D-757 additive Account 계약: [Rosy Account protocol](rosy-account-protocol.md). 사람 신원·앱 세션 교환·자원별 접근 자격·계정 관리의 구현 대상이며 운영 활성화 증거는 별도다.

## 공유 인터페이스 계약서

**Document ID:** ROSY-API-REF-001
**Version:** v1.301
**Status:** Approved
**대상 독자:** rosy_core 개발자, rosy_fleet 개발자, 외부 SDK·AI·연동 시스템

### v1.301 이미지 도면 등록과 범용 추출 후보 (D-835)

기존 STL 입력·변환·해시는 유지한다. `POST /api/fleet/site-map/drawings`는 추가로 `Content-Type: image/png|image/jpeg` raw bytes를 받고 실제 format과 일치하는 단일 프레임 PNG/JPEG만 허용한다. 응답은 `{asset_sha256,format:png|jpeg,width_px,height_px}`다. 원본 bytes는 보존하며 EXIF 방향을 적용하고 투명 배경을 흰색에 합성한 별도 RGB PNG를 표시/추출 기준으로 사용한다. width_px/height_px는 정규화 후 크기다. SVG/HTML/외부 URL/다중 프레임은 거절한다.

기존 projection POST는 `RasterDrawingTransform`도 받는다. 필수 `source_origin_px:[x,y]`, `map_origin_m:[x,y]`, `heading_rad∈[-2π,2π]`, 양수 `meters_per_pixel`이며 모든 수는 유한하다. 원본 픽셀 원점은 정규화 자료의 좌상단, x 오른쪽/y 아래다. 등록 원점은 이미지 경계 안이어야 한다. `p_map=map_origin_m+R(heading_rad)*[px-source_x,source_y-py]*meters_per_pixel`. 이 변환은 원근을 보정하지 않는다. 기존 DrawingTransform과 혼합하거나 다른 source 종류에 적용하면 422다.

Raster projection은 기존 응답에 `kind:raster,format,width_px,height_px,render_sha256`을 추가하고 segments는 빈 배열이다. bounds_m은 변환한 네 모서리의 경계다. hash는 converter version `rosy.raster_projection/1`과 원본/렌더 hash·변환·크기를 포함한 canonical JSON으로 결속한다. `GET /api/fleet/site-map/drawing-projections/{projection_sha256}/render`는 기존 read guard 뒤에서 PNG를 제공하고 `nosniff, Cache-Control: private, no-store`를 설정한다. 원본 GET은 계속 named operator 전용 attachment다.

Raster 원본과 정규화 PNG는 각각 16 MiB 이하, 축별 8192 px 이하·전체 16,000,000 px 이하다. 업로드 60초, worker 10초/512 MiB, 동시 1개·보관 합계 1 GiB이며 기존 drawing error code를 재사용한다. STL의 5초/256 MiB 한도는 바꾸지 않는다. 지도 revision·새 map_id·검토 해제·CAS/활성화 경계는 D-825와 같다. 새 입력은 지도 저장·활성화나 로봇 명령을 발생시키지 않는다.

`POST /api/fleet/site-map/drawing-projections/{projection_sha256}/extractions`는 named operator·기존 CSRF 뒤에서 `DrawingExtractionRequest`를 받는다. `crop_px:[x0,y0,x1,y1]`는 정규화 이미지 경계 안의 양수 크기 정수 사각형, `method=lines|contours`다. 선택 settings는 extra forbid이며 `canny_low=50, canny_high=150`(0…255, low<high), `threshold=20`(1…8192), `min_line_length_px=30`(2…8192), `max_gap_px=3`(0…64), `tolerance_px=1`(0…10, 유한)이다. 정수 설정은 bool·문자열·소수를 거절한다. 입력/출력은 원본 픽셀 좌표이고 ROI offset을 복원한다. 직선은 Canny/HoughLinesP, 윤곽은 반전 Otsu/contour tree와 명시한 허용 오차의 단순화를 사용한다.

응답은 `{extraction_sha256,asset_sha256,projection_sha256,render_sha256,crop_px,method,settings,extractor_version,library_version,candidates}`다. candidate는 `{candidate_id,geometry_px,closed,is_hole}`이며 도로 의미·안전 점수를 포함하지 않는다. 빈 배열은 정상적으로 후보를 찾지 못한 경우이고 잘못된 자료/실행 실패와 구별한다. 후보 ≤2000개·합계 꼭짓점 ≤50,000개·응답 ≤8 MiB를 초과하면 413이며 일부를 몰래 버리지 않는다. 기존 drawing slot/worker/저장량을 공유한다. canonical result에서 extraction_sha256을 뺀 body의 SHA-256으로 보관하며, source/projection/settings/라이브러리 버전을 결속한다. read guard 뒤의 `GET /api/fleet/site-map/drawing-extractions/{extraction_sha256}`로 같은 결과를 읽는다. 결과 생성/읽기는 초안·활성 지도·운행 명령을 바꾸지 않는다.

`POST /api/fleet/site-map/drawing-extractions/{extraction_sha256}/validate`는 named operator·기존 CSRF 뒤에서 기존 DraftRequest의 `{map,expected_revision?}`을 최대 2 MiB·수신 10초로 검증하고 `{map}` canonical body만 반환한다. 저장·CAS·revision 발행·활성화는 하지 않는다. 도형·참조는 기존 SiteMap validator를 사용하며 drawing/survey는 추출의 source/projection과 일치해야 한다. 후보 추출 POST도 같은 2 MiB/10초 수신 한도를 사용한다. 잘못된 요청/도형은 `SITE_MAP_DRAWING_INVALID` 422다. 응답 수락 전 브라우저는 초안 identity·계정 epoch·원본/projection·요청 세대를 다시 검사한다.

선택 `SiteFacility.evidence`는 기존 RoadEvidence와 같은 `{source,status,reference_revision,note}` 형식을 쓰고, 없으면 기존 지도 body에서 생략한다. 후보의 도로/시설에는 운영자가 지정한 용도와 수정한 geometry를 저장하고 note에 `extraction:<sha256> candidate:<id>`를 남긴다. immutable 추출 원본과 저장된 geometry를 대조할 수 있으며 이는 운영자 출처 기록이지 AI 정확도 보증이 아니다. 시설 근거도 survey revision과 일치해야 하며 검토 전 활성화는 기존 `SITE_MAP_ROAD_UNREVIEWED`로 거절한다. 직접 수정·도면 교체·템플릿 복사는 시설 근거도 미검토로 돌리고, 명시적 조사 검토는 해당 근거를 함께 검토한다.

### v1.300 STL 도면 참조와 Fleet 평면 지도 편집 (D-825)

선택 `SiteMap.drawing={asset_sha256,projection_sha256}`의 두 값은 소문자 SHA-256 64자리다. 정본 DTO는 `core_common.protocol.site_drawing`이며 CORE snapshot/envelope를 확장하지 않는다. 도면 지도의 `survey.revision`은 projection 해시와 같아야 한다. 선택 `SiteEdge.name`은 ID와 분리된 1–64자 표시 이름이고 공백만인 값을 거절한다. 없는 두 선택 필드는 기존 지도 body/hash에서 생략한다. 기존 지도 JSON 제한은 2 MiB다.

| Method | Path | Guard | Body / Result |
|---|---|---|---|
| POST | `/api/fleet/site-map/drawings` | named operator + 기존 CSRF | raw STL bytes → `{asset_sha256,format,triangle_count,bounds_3d}`; format은 `binary_stl` 또는 `ascii_stl`, bounds_3d는 원본 단위의 `[min_xyz,max_xyz]` |
| POST | `/api/fleet/site-map/drawings/{asset_sha256}/projections` | named operator + 기존 CSRF | `DrawingTransform` → `{projection_sha256,asset_sha256,transform,bounds_m,segments}` |
| GET | `/api/fleet/site-map/drawing-projections/{projection_sha256}` | 기존 지도 read guard | 저장한 projection JSON; bounds_m은 `[min_xy,max_xy]`, segments는 `[[[x1,y1],[x2,y2]],…]` 미터 좌표 |
| GET | `/api/fleet/site-map/drawings/{asset_sha256}/source` | named operator | 원본 bytes; attachment, application/octet-stream, nosniff |

`DrawingTransform`은 필수 `plane=xy|xz|yz`, `unit=m|cm|mm`, 원본 평면의 `source_origin:[x,y]`, 미터 `map_origin_m:[x,y]`, `heading_rad∈[-2π,2π]`, 양수 `scale`이다. 모든 수는 유한해야 한다. 지도 좌표는 기존 ±1000 m 범위다. 평면의 좌표 순서는 각각 (x,y)/(x,z)/(y,z)이며 `p_map=map_origin_m+R(heading_rad)*(p_source-source_origin)*unit_m*scale`이다. 등록은 단위·축을 추정하지 않는다. 사용자가 두 점의 실측 거리를 확인하고 survey의 measured 근거를 기록한다.

원본 16 MiB, 삼각형 200,000개, 중복 제거 투영 선분 50,000개, projection JSON 8 MiB, DB별 보관 합계 1 GiB다. 업로드 수신은 60초, 변환은 동시 1개·wall 5초·자식 메모리 256 MiB로 제한한다. 성공한 원본/변환은 내용 해시로 영속 보관하며 자동 삭제하지 않는다. 같은 요청의 재시도는 같은 해시를 재사용한다. `--tasks-db`가 없으면 도면 보관만 비활성화하고 기존 메모리 지도는 유지한다. 파일 경로·외부 URL·임의 SVG/HTML은 입력이 아니다.

| HTTP | Code | 의미 |
|---|---|---|
| 413 | `SITE_MAP_DRAWING_LIMIT` | bytes/삼각형/선분/출력 예산 초과 |
| 422 | `SITE_MAP_DRAWING_INVALID` | 잘못된 STL·변환·참조 또는 유효하지 않은 미터 좌표 |
| 429 | `SITE_MAP_DRAWING_BUSY` | 업로드/변환 슬롯 사용 중 |
| 503 | `SITE_MAP_DRAWING_UNAVAILABLE` | 비영속 설정, worker 장애/시간 초과, 수신 기한 초과 |
| 507 | `SITE_MAP_DRAWING_STORAGE` | 저장소 예산·디스크 부족 |
| 404 | `SITE_MAP_DRAWING_NOT_FOUND` | 존재하지 않는 유효한 해시 |

도면 생성/변환은 지도 저장이나 활성화를 하지 않는다. 잘못된 참조는 저장·활성화 전에 거절한다. 교체·템플릿 복사는 검토 완료와 교정 근거를 자동 계승하지 않는다. 기존 revision/CAS·named operator·trip/formation/teach busy 거절을 유지한다. 편집/저장/복사는 이동 명령을 보내지 않는다. 활성화와 실제 주행·현장 교정 수용은 별도다.

### v1.297 Control-unit delegation and scoped cancellation (D-855)

독립·상하위·3수준 중첩 관제의 첫 범위는 유한한 navigation 후보 1개다. 정적 관제 manifest와 같은 Fleet SQLite journal, 직접 관계별 service principal이 설정된 경우에만 연다. 상위 서비스는 후보·조회·취소 요청만 보내며, 실제 장치 제출은 하위 인증 named operator와 기존 admission·claim을 거친다. production dispatch·새 실행 profile·모델 권한을 추가하지 않는다. Envelope protocol_version은 1.0이다.

공유 모델 정본은 `core_common.protocol.schemas`의 `ControlNavigationCandidate`, `ControlWorkRequest`, `ControlIngressRequest`, `ControlApproveRequest`, `ControlDelegationSnapshot`, `ControlUnitReply`, `ScopedNavigationCancelRequest`다. 추가 필드는 거절한다. ID는 영숫자로 시작하는 영숫자·`_.:-` 문자열이며 unit/robot/revision은 1~64자, delegation ID는 1~128자다. 좌표 x/y/yaw는 bool을 제외한 유한 수다.

| 경로 | 권한·요청·결과 |
|---|---|
| `GET /api/fleet/control-unit` | viewer. 자기 unit ID·구성 revision·직접 부모/자식·직접 자원. peer 주소·비밀은 반환하지 않음 |
| `GET /api/fleet/control-unit/delegations` | viewer. 최대 100개 최근 위임과 출처·stale. 서비스 전체 원장 조회는 허용하지 않음 |
| `POST /api/fleet/control-unit/delegations` | named operator. `{delegation_id,target_unit,robot_id,goal:{x,y,yaw?}}`. 발행 origin은 서버의 자기 unit으로 고정. 후보 접수 응답이며 자동 실행 승인이 아님 |
| `POST /api/fleet/control-unit/inbox` | 직접 부모의 별도 `service` principal만. 위 요청에 `{origin_id,config_revision}` 추가. origin은 부모 또는 그 조상, target은 자기 또는 자기 하위, robot 자원은 최종 target의 직접 소유여야 함 |
| `GET /api/fleet/control-unit/delegations/{origin_id}/{delegation_id}` | viewer 또는 검증된 직접 이웃 service. 직접 부모는 자기가 요청할 수 있는 origin 범위만 조회한다. 직접 자식은 이 노드가 그 자식에게 배정한 동일 identity만 읽어 승인 직전 취소·상위 연결을 재확인한다. 자식의 조회는 조상 연결까지 검사하며, 다른 자식의 작업·전체 원장·취소·승인 권한을 주지 않는다. 등록된 직접 자식에게 같은 identity로 조회·재전달 가능 |
| `POST /api/fleet/control-unit/delegations/{origin_id}/{delegation_id}/approve` | 최종 target의 named operator. `{expected_revision}`는 strict 양의 정수. 현재 revision·범위·기존 작업 admission 재검증. 승인 신원은 영속 결속하며 같은 위임을 다른 신원/작업에 바인딩하지 않음 |
| `POST /api/fleet/control-unit/delegations/{origin_id}/{delegation_id}/cancel` | local named operator 또는 위 범위의 직접 부모 service. 같은 위임의 취소 요청만 기록·전달. 미제출 후보는 취소할 수 있고, 제출 작업은 원래 task/attempt의 owner 결과를 기다림 |

단일 위임 응답은 `{unit_id,config_revision,stale,delegation}`다. `delegation`은 origin/delegation ID, 불변 request `{target_unit,robot_id,goal}`, 직접 결과 소유 `owner_unit`, 최초 config revision, status, 자체 단조 revision, owner_revision, nullable local_actor/local_task_id, cancel_requested, result, updated_at을 포함한다. result는 유한 JSON 최대64KiB다. 상태 값은 PENDING/APPROVING과 기존 REQUESTED/QUEUED/ACCEPTED/RUNNING/UNKNOWN/HOLD/COMPLETED/FAILED/CANCELED/EXPIRED다. cancel_requested는 정지 완료나 상태 전이를 뜻하지 않는다. COMPLETED는 실행 결과이며 앱의 물리 업무 완료를 대신하지 않는다.

같은 발행 관제·delegation ID·정규화 본문은 같은 기록을 반환한다. 구성 revision·재시작·전송 재시도가 identity를 바꾸지 않는다. 다른 본문·owner 결속은 409 충돌이다. 위임 binding·history와 로컬 task 생성은 기존 TaskStore admission transaction 안에서 함께 커밋한다. 인증·관계·본문·현재 안전 검사는 항상 유지하고 이전 권한을 재전달로 복원하지 않는다.

접수·조회 응답 유실은 새 key나 다른 자식에 재배정하지 않는다. 기존 기록과 같은 identity로 직접 자식을 재조회한다. stale 응답·잘못된 origin/request/owner/revision·낮은 owner_revision으로 현재 사실을 덮지 않는다. 상위 링크 단절에서는 신규 상위 위임과 다음 Action을 막고 현재 admission된 유한 Action의 기존 장치 정책만 유지한다. 재연결 대조 없이 자동 재시작·점유 해제·rearm을 하지 않는다. 오래된 구성·scope·수정된 본문·잘못된 승인 revision은 409, 권한/관계 위반은 403, 미등록 위임은 404, 미설정/DB 불가/불명 peer 응답은 503 또는 stale 읽기 결과로 보존한다. 빈 조회 목록을 장애의 성공 응답으로 만들지 않는다.

`POST /api/v1/navigation/cancel-scoped`는 operator 전용의 새 CORE 경로다. 요청은 UUID `expected_boot_id`, UUID `run_id`, 비어 있지 않은 1~128자 `correlation_id`를 모두 요구한다. 세 값이 현재 owner 실행과 맞을 때 기존 NavigationManager 잠금 안에서만 cancel을 수행한다. 결과는 `{navigation,operation}`이며 operation은 해당 실행의 native receipt다. scope 불일치·이미 다른/종단 실행이면 409 `NAVIGATION_SCOPE_CHANGED`이고 다른 목표·trip lease를 바꾸지 않는다. 잘못된 body는 기존 CORE ERR-101 규약의 400 `VALIDATION_ERROR`다. 기존 `/navigation/cancel`은 바꾸지 않는다. 구버전의 scoped 경로 404는 미지원으로 남기며 무조건 취소로 fallback하지 않는다. Fleet은 owner receipt의 boot/run/attempt 결속이 없으면 이 요청을 만들지 않고 결과 불명으로 보존한다.

scoped 취소는 결속된 navigation run만 취소하며 trip lease를 자동 종료하거나 IDLE로 전환하지 않는다. lease 수명·해제는 기존 소유자 경로에 남는다. 응답 `navigation`은 응답 시점의 현재 facade 상태여서 새 run의 상태일 수 있다. 성공 판단은 `operation`의 원래 boot/run/correlation과 TERMINAL/CANCELED에 결속하고 facade 상태를 원래 run의 결과로 해석하지 않는다. native 취소 receipt도 물리 정지 측정 증거는 아니다.

이 절은 공유 계약이며 HTTP·runtime·UI·배치 및 실물 수용은 각 구현 증거로 닫는다. schema 등록·원격 모델 시험만으로 파이프라인이 완성됐다고 주장하지 않는다.

### v1.292 Candidate trip admission (D-836)

`POST /api/fleet/trip-jobs`의 기존 `{robot_id, steps}`는 유지한다. 새 형식은 `{candidate_robot_ids, request_key, steps}`다. 두 지정 방식은 배타적이다. 후보는 고유한 등록 robot ID 1~8개, key는 공백/제어문자 없는 1~128자이며 steps의 기존 1~8개 제한·PlaceRef를 유지한다. 공유 request schema는 `core_common.protocol.schemas.TripJobRequest`/`TripJobStep`이다.

기존 named operator·TRIP simulation profile·장소 검사 후 Fleet이 후보 순서대로 기존 trip lease와 원장 robot claim을 확보한다. `TRIP_ROBOT_BUSY`만 다음 후보로 넘어가며 다른 불명/정지/capability/lease/claim 실패는 그대로 거절한다. 전체 busy는 409 `TRIP_CANDIDATES_BUSY`; 같은 principal/key를 다른 후보 순서나 steps로 재사용하면 409 `TRIP_REQUEST_CONFLICT`다. 등록되지 않은 후보가 하나라도 있으면 기존 404 `UNKNOWN_ROBOT`이다.

같은 principal/key·정규화된 본문은 기존 `{job}`을 반환하며 선택된 장치는 `job.workcell_id`와 robot resource claim으로 확인한다. 완료·HOLD·재시작 뒤 재접수도 새 실행·새 lease를 만들지 않는다. 재접수는 현재 지도·장치 등록의 신규 admission 검사보다 먼저 같은 원장을 읽는다. 인증·profile·정적 body 검사는 항상 유지한다. 단일 `robot_id` 방식에는 request-key 의미를 소급 추가하지 않는다. 내부 key namespace는 `trip-pool:`이며 앱에 DB 접근을 요구하지 않는다. 이 API는 후보 배정을 지원하며 다중 운행·자동 충전·production profile·장치 권한을 추가하지 않는다. Envelope 1.0은 유지한다.

공정 문서는 기존 `/api/fleet/cell-app/compile`·`/proposals`의 ID/digest 검사와 설치된 compiler로 처리한다. proposal/resolve는 물리 submission이 아니며 기존 admit의 named/two-person 검사와 `physical_submission: NOT_CONNECTED` 의미를 유지한다. 앱의 업무 완료와 관측 근거는 별도다.

> **거버넌스:** 본 문서는 로봇(rosy_core)과 Fleet(rosy_fleet)이 **공유하는 유일한 인터페이스 계약**이다.
> 본 문서의 변경은 양측 합의 + 문서 버전 업을 통해서만 가능하며(일방 변경 금지), 구현은 본 문서에 명시된 스키마를 임의로 확장하지 않는다.
> 구현 시 본 문서를 OpenAPI(YAML)로 기계 판독 가능하게 유지하는 것을 원칙으로 한다(계약 테스트의 원천).

**관련 문서:** ROSY-CORE-SRS-001 / ROSY-FLEET-SRS-001 / ROSY-ADR-001 / ROSY-PLN-001

### v1.290 Explicit operator navigation and language (D-821)

`AssistantMessage.locale` optionally selects `ko-KR` (default, including pre-v1.290 stored messages) or `en-US`. The locale is bound to immutable request identity and model input. Unsupported locales are 422. `AssistantStatus.execution_enabled` reports the separately configured handoff; dialogue remains `READ_ONLY` and every answer remains `action_admissible=false`.

POST `/api/fleet/assistant/messages/{request_id}/navigation` requires the current named operator and existing Origin/CSRF rules. Input `AssistantNavigation` is exactly robot_id, finite x/y within ±100000 metres, optional finite yaw within ±π (default 0). This is an explicit operator coordinate submission, never a model-generated command. The operator must own an ANSWERED CONTROL request completed within 30 seconds, with the same non-null selected robot. Current authentication and unexpired model admission plus `execution_enabled=true` are rechecked inside Task admission.

The endpoint calls the existing `IntentExecution`/navigation Task owner and returns its accepted/queued/task result. Same principal/request reuses the Task idempotency key; changed coordinates are 409. Another principal sees the same 404 as a missing request; a robot removed from the current roster is 404; expired/non-control/changed selection is 409; disabled/unadmitted execution or unavailable storage is 503; revoked authority is 403. Results use `Cache-Control: no-store`. Actual work state, cancellation and uncertain physical outcomes use the existing Task APIs and dispatch generation. No additional worker, direct robot call or automatic UNKNOWN replay is installed. This additive endpoint supersedes the D-810 no-dispatch boundary only for explicit operator submissions; model replies retain no execution authority.

### v1.289 Console operator assistant (D-810)

Additive, named operator only and read-only. Console credentials and cookie Origin/CSRF rules remain unchanged. Canonical DTOs are `AssistantMessage`, `AssistantFact`, `AssistantResult`, `AssistantStatus`, and `AssistantHistory` in `core_common.protocol.assistant`, following the existing protocol submodule pattern without growing the oversized schemas facade.

| Method/path | Input | Result |
|---|---|---|
| GET `/api/fleet/assistant/status` | none | `AssistantStatus`: available, mode=`READ_ONLY`, reason; configuration/admission missing or expired is unavailable |
| POST `/api/fleet/assistant/messages` | `AssistantMessage`: conversation_id, request_id, text, optional selected_robot_id | 202 `AssistantResult`, or 200 same request on duplicate |
| GET `/api/fleet/assistant/messages/{request_id}` | path ID | Own `AssistantResult`; other principal or absent is the same 404 |
| GET `/api/fleet/assistant/conversations/{conversation_id}` | path ID | Own `AssistantHistory`, latest 40 messages in chronological order |

IDs are `[A-Za-z0-9_-]{1,96}`. Original text is retained, 1..2000 characters, nonblank and no control characters except CR/LF/tab. selected_robot_id is optional `[A-Za-z0-9_.:-]{1,96}`; it is rechecked against current Fleet reads. Unknown body fields, including identity/source/Discord fields, are rejected. Principal comes only from authentication, and each site's existing Fleet DB defines site scope. Shared `site-console` and development principals are refused for persistent assistant conversations. Reading or submitting requires the current named operator credential.

Results contain request_id, conversation_id, original text, state (`PENDING`, `RUNNING`, `ANSWERED`, `HOLD`, `UNKNOWN`), nullable response/reason, facts (ref, text, observed_at), created_at, nullable completed_at, and action_admissible=false. These are conversation states, never execution-completion states. Model text does not establish physical facts: STATUS is rendered from verified fact references. CONTROL requests are handed off to the existing work UI; this release never dispatches a command.

Same principal/request ID and same original body returns the existing result without a second model call. Changed body is 409 `ASSISTANT_REQUEST_CHANGED`. Only one pending/running request per principal, 64 site-wide, and at most 1000 stored requests per principal; excess is 429 `ASSISTANT_LIMIT`. No implicit deletion or replay is used to free capacity. Missing/expired admission produces a durable HOLD rather than inference. In-flight restart/cancellation/transport ambiguity is UNKNOWN, never automatically retried. Unknown/foreign request is 404 `ASSISTANT_NOT_FOUND`; unavailable durable storage is 503 `ASSISTANT_STORAGE_UNAVAILABLE`. Invalid input is 422. Current snapshot age limit is five seconds; stale/unavailable observations hold the request. Recent model history is capped at four turns, 120 seconds, same principal/conversation/selection; previous STATUS facts are not reused as current observations. Every result is `Cache-Control: no-store`.
### v1.286 완료된 native 항법의 수동적 IDLE 인계 (D-772)

2026-10-17 Corrective(API-002): `mode.changed` 표의 기존 `{from, to, by}`를
`{from, to, by, run_id?, boot_id?}`로 정정한다. 기존 handover 발행 코드가 이미 보내는
선택 필드의 문서 누락이며 wire 변경이 없어 v1.286를 유지한다. `by=navigation_handover`의
실제 NAVIGATION→IDLE 전이에서 두 식별자를 보내며, 멱등 재호출은 이벤트를 추가하지 않는다.
다른 mode 변경의 필수 필드나 물리 정지·착좌 증명을 추가하는 계약이 아니다.

`POST /api/v1/navigation/handover`는 operator의 정확한 `expected_boot_id`/`run_id` UUID,
정수 `expected_owner_generation`, `correlation_id`를 요구한다. 같은 navigation lock 안에서
현재 native navigate/home의 SUCCEEDED·ARRIVED와 실제 backend transport의 quiescence,
빈 owner·admission/lease/moving/mapping 부재를 확인한다. 잠금 대기 뒤에도 calibration/trip
소유권·수동/비상·line-follow·현재 mode를 재검사하고 기존 CORE navigation candidate를
지운 뒤 NAVIGATION에서 IDLE로 조건부 전이한다. 다른 실행을 취소하거나 새 이동을 만들지 않는다.
동일한 현재 terminal proof의 IDLE 재호출만 멱등이다. 불명·불일치·대체 실행은 409이며
accepted/IDLE는 물리 정지·도착 오차·충전 자원 해제의 증거가 아니다. 새 station binding은
별도로 원본 motion의 새 정지 dwell을 요구한다. 응답은 accepted, mode, run_id, boot_id,
owner_generation이다. 기존 cancel/긴급 정지 계약은 유지한다.

Fleet의 충전 조립은 이 인계의 성공 뒤에도 동일한 완료 Task/attempt·원본 정책·dispatch
세대와 claim 부재를 다시 확인한다. Console의 이전 goal/route/goal-lease projection만
동일 객체·값·전송/정지 세대가 유지된 경우 정리한다. held·대형·대기 목표·새 전송이나
클라이언트 교체가 있으면 정리하지 않는다. 장치 상태를 IDLE로 꾸미거나 durable claim을
해제하는 경로가 아니며 새 복귀는 기존 TripRunner admission을 그대로 거친다.

### v1.285 스테이션 이안 허가와 실측 이탈 근거 (D-772)

Additive DTO: canonical `schemas.StationDeparturePermit`는 robot/station/session/attempt/
boot/battery/map/pose 버전, correlation, 선택된 work task와 전체 요청 SHA256,
정책·용량 revision, 기대 native generation 및 원본 유효기간을 결속한다.
이 DTO는 이동 명령이나 에너지 검증 자체가 아니다.
`StationDepartureReceipt`는 같은 세션·작업과 실제 native operation/generation,
odom·로컬 측정 출처·이안 프로필 revision, 원본 정지·접점·공간·절연 표본 시각을
결속한다. 접점 이탈·출력 절연·경로 여유·정지 플래그는 명시적인 true만 허용한다.
수신자는 현재 시각과 기대 scope를 재검증해야 하며 ACK나 native 성공을 이 근거로
대체할 수 없다.

`POST /api/v1/docking/station-undock`는 허가 DTO를 받고 실제 native `undock`
operation을 반환한다. 고정 Fleet principal·calibration/trip 소유권·capability·localization과
현재 충전 완료, 명시적 로컬 이안 프로필·출력 절연·무전류·후방 공간을 검증한다.
중복 시작은 거절하며 응답 유실은 새 시작의 허가가 아니다.
`PUT /api/v1/docking/station-departure`는 같은 현재 native 실행의 허가만 갱신한다.
세션/작업/정책·용량 scope는 변경할 수 없고 원래 허가가 유효해야 한다. 같은 capture의
TTL 연장과 만료 후 부활은 거절한다. accepted는 권한 갱신 ACK다.
`POST /api/v1/docking/station-departure/finish`는 StationMotionCommand의 정확한
session/correlation/boot/current native generation을 확인하고 실측 이탈 Receipt를 반환한다.
native 성공 이후의 새 접점 이탈·정지 dwell·IDLE 없이는 409다. 재호출은 원래
Receipt의 UTC/monotonic 수명 안에서만 가능하며 새 표본이 수명을 늘리지 않는다.
기존 `GET /api/v1/docking/station-target`의 nullable `departure_permit`와
`departure_receipt`는 현재 실행 허가와 실측 완료를 구분한다. 조회는 동작을 tick하거나
허가를 갱신하지 않으며 원래 UTC/monotonic 기한과 최신 로컬 facts에 수명을 제한한다.
Receipt는 WORK_AVAILABLE의 정확한 session/boot/battery/correlation/native operation에서만
노출한다. 완료 응답 유실은 이 readback으로 확인하며 새 이안 요청으로 재시도하지 않는다.
접점 재발견·움직임·대체 native 세대·기한 만료가 확인되면 같은 과거 Receipt를 되살리지 않는다.
WORK_AVAILABLE 이후의 새 `PUT station-target`은 새 session/attempt의 RETURN_RESERVED,
이전 이탈 이후 생성된 요청, 현재 IDLE·부트/배터리/지도/odom·빈 native 소유권과 새 원본
motion 표본의 정지 dwell을 확인한 뒤 binding을 교체한다. 일반 작업 중 옛 target/Receipt가
만료돼도 새 정지 근거로 다음 순환을 시작할 수 있다. 과거 Receipt/permit·착좌·operation을
새 세션으로 옮기지 않으며 설치 피드의 재생 watermark를 보존한다. 교체된 session ID의
지연 요청은 STATION_SESSION_RETIRED로 거절한다. 교체 검사 실패는 기존 WORK_AVAILABLE을
움직이거나 새 세션으로 바꾸지 않는다. 새 API나 물리 사실 업로드 경로는 추가하지 않는다.
로컬 물리 이안 사실을 업로드하는 HTTP 경로는 없다. 명시적인 `departure_profile`은
simulation 구성에서도 빈 로컬 피드로 시작하며 실측 facts 없이는 거절한다.
실기 구성과 DEVICE/FIELD 수용, 관제 자동 재투입은 별도 완료 기준이다.
기존 `POST /api/v1/docking/station-stop`도 정확한 undock native 실행을 중단한다.
CHARGED_HOLD의 terminal dock 이후에는 새 이안 correlation의 선행 중단이 세션을
닫아 지연된 시작을 막는다. 현재 boot/generation fence는 유지하며 다른 실행을
취소하지 않는다. 중단 ACK는 실제 정지·물리 이탈·자원 해제 근거가 아니다.

### 스테이션 충전 근거 계약 (D-772, v1.280)

`core_common.protocol.station_charging`의 DTO는 스테이션 설치 위치 후보/유효성,
로봇의 위치 버전 수락, 세션별 상대 관측, 실측 정지·착좌, 정상 충전 종단,
배터리 계측 근거, 에너지 정책 결정, durable 충전 세션을 구분한다.
canonical export는 `core_common.protocol.schemas`다. 계약 자체는 이동 권한이 아니다.
CORE 실행 경로는 아래의 명시적 프로필과 인증을 요구하며 실기 자동 도킹은 비활성이다.

`StationPoseRecord`는 station/map/revision/pose_revision, 목표·접근 포즈,
관측 출처·교정·유효기간·오차를 결속한다. VALID는 검증된 접근 포즈를 요구한다.
`StationObservation`은 robot/station/session/boot/odom_epoch 및 위치 버전을
base_link 상대 포즈에 결속한다. 관측 생성 시각은 유효기간보다 앞서야 하며
수신자는 주입한 현재 시각과 기대 scope를 검증한다. DTO 검증은 인증이 아니다.

D-774의 명시적 `station-vision` 설치 source는 관측 프로세스가 실행 중일 때 기존
카메라 `demand.wanted`를 요청한다. 종료 시 요청을 해제하고 연결을 닫는다.
일반 Vision/추적은 D-691의 인증 preview 읽기와 30초 유지 규칙을 따른다.
설치 프로필의 lens/marker 교정·source·원본 크기/회전을 검증하며 이 요청은
Fleet 위치 확정이나 CORE 주행·충전 권한을 부여하지 않는다. 새 wire 필드는 없다.

같은 위치 버전의 새 전역 관측은 기존 `PUT /api/v1/docking/station-target`으로
동기화한다. session/robot/boot/battery/map/attempt와 위치·접근 포즈·출처·교정은
그대로여야 하며 원래 CORE binding도 아직 유효해야 한다. 새로운 capture 없이
TTL만 늘리거나 만료/HOLD binding을 되살리는 요청은 거절한다. 기존 native
boot/generation fence와 현재 operation을 보존하며 이동을 시작하지 않는다.
현재 유효한 observation scope는 새 프레임 측정 권한이고 기존 영상·착좌·충전
완료 근거의 갱신이 아니다. ACK의 현재 시각도 전역 위치 관측 시각을 대신하지 않는다.
현재 충전 세션의 `UNDOCKING` 중에도 같은 검증을 거쳐 새 측정 범위를 제공한다.
이 범위는 유효한 동일 위치 관측을 CORE에 동기화하는 데 사용할 수 있으며,
이안 이동·충전 완료·자원 해제를 허가하지 않는다. HOLD 및 WORK_AVAILABLE에서는
새 측정 범위를 발급하지 않는다.

`BatteryEnergyEvidence`는 미측정 SOH·유효 에너지를 null로 보존한다.
전압 단독 출처는 건강도 계측값을 주장할 수 없다. `ChargeCompletionEvidence`는
충전기/BMS 정상 종단과 최신 팩 표본을 충전 session/battery에 결속한다.
단순 charging=false, 정상 전압, ACK는 만충이나 출발 허가를 입증하지 않는다.
v1.279은 `SeatingEvidence.position_sample_at`과 정상 종단의 필수
`ChargeCompletionEvidence.termination_sample_at`을 추가한다. 수신 시각으로
카메라·충전기 원본 표본의 나이를 갱신하지 않는다. 정상 종단 시각을 모르는 장치는
UNKNOWN을 보고하며, 이전 세션에서 발생한 종단을 현재 세션의 완료로 사용하지 않는다.
종단 발생 시각은 현재 접안 시도 시작 이후여야 한다. 완료 대기 중에는 최신 정상
충전기 상태·접점·팩 표본을 다시 검증하며, 정상 종단 사건 자체가 반복 발생할 필요는 없다.
기존 docking 명령은 스테이션 전용 기종의 미수락·무효 binding 또는 다른 동작 소유권과
충돌하면 409 `STATION_BINDING_REQUIRED`, `STATION_BINDING_INVALID`,
`STATION_SESSION_ACTIVE`로 거절한다. 이 검사는 모드 변경·모터 명령보다 먼저 실행한다.
공유 필드의 시각은 UTC epoch 초, 위치는 m, 각도는 rad, 에너지는 Wh다.

v1.280의 스테이션 실행 경로는 아래 계약을 따른다. 기본 비활성이며 실기 수용 전에는
명시적인 simulation 프로필만 구성한다. 사람 operator/admin 역할만으로 제어 근거를
등록할 수 없다. CORE 쓰기는 설정의 `docking.station.fleet_principals`에 등록된 고정
principal만 허용하고, 최초 binding의 principal에 세션을 결속한다. 공용 개발 토큰은
등록 여부와 무관하게 쓰기를 거절한다. 관측 source 자격증명은 Fleet에서만 사용하고
CORE에는 Fleet의 고유 robot credential로 전달한다.

| 경로 | 입력/출력과 권한 |
|---|---|
| CORE `GET /api/v1/docking/station-target` | viewer: `StationTargetStatus`. 현재 유효성·착좌/충전/완료 검증·실행 correlation과 실제 operation ID. 오래된 상태 문자열만으로 출발을 허가하지 않음 |
| CORE `PUT /api/v1/docking/station-target` | 지정 Fleet principal: `StationTargetBinding` → `StationPoseAck`. 현재 native boot/generation, session/map/pose revision, 로컬 프로필을 확인하며 이동을 시작하지 않음 |
| CORE `POST /api/v1/docking/station-observation` | binding 소유 principal: `StationObservation` → `{accepted: bool}`. 범위·촬영 시각·순번·교정 검증 실패는 기존 관측도 비움 |
| CORE `POST /api/v1/docking/station-dock` | binding 소유 principal: `StationMotionCommand` → 실제 native operation. 모드/로컬 안전/관측/현재 owner generation을 동작 직전에 검사 |
| CORE `PUT /api/v1/docking/station-return` (v1.282) | binding 소유 principal: `StationReturnPermit` → `StationTargetStatus`. 기존 trip lease의 owner·lease ID·trip ID·job_id=session ID에 결속한 복귀 허가. 수락만으로 이동하지 않음 |
| CORE `POST /api/v1/docking/station-return/finish` (v1.283) | 같은 principal: `StationMotionCommand` → `StationPoseAck`. 정확한 허가·boot/generation·lease를 재검사하고 NAVIGATION이면 terminal navigation owner/quiescence를 lock 아래 증명한 경우에만 IDLE로 인계. 이 호출은 409 `STATION_RETURN_STANDSTILL_REQUIRED`를 반환하며 RETURNING과 lease를 유지한다. 이후 새 연속 측정 정지 dwell을 확인한 호출만 BOUND로 넘김. 접안 시작·자원 해제·작업 배정을 하지 않음 |
| Fleet `GET /api/fleet/stations` | viewer: 유효성/위치 버전을 포함한 설치 원장 조회 |
| Fleet `POST /api/fleet/station-poses` | 등록 source credential: `StationPoseRecord` 후보. source/station/map/calibration 범위 검증, Fleet의 접근 검증·일관성 판정 후 버전 발행 |
| Fleet `POST /api/fleet/station-observations` | 등록 source credential: `StationObservation`. 활성 session/boot/위치 버전과 출처를 검증한 뒤 CORE로 전달; 모터 명령 권한 없음 |
| Fleet `GET /api/fleet/station-observation-scope/{robot_id}` (v1.281) | 등록 source credential: `{scope: StationObservation \| null}`. 해당 source에 등록된 로봇의 현재 충전 세션, CORE binding/ACK, 실제 odom epoch를 함께 확인한 생성 범위. pose=null, visible=false, sequence=0인 메타데이터이며 위치·착좌 근거가 아님 |

CORE의 위 네 경로와 명시적 station_ingress 구성의 Fleet 관측·후보·조회 경로를 연결했다.
source 범위 조회는 v1.281에서 연결했다. 조회 시 CORE 상태가 유효해야 하며, 새 측정 범위의
만료는 binding ACK·설치 위치·최신 odom과 source 나이 제한으로 한정한다. 이전 카메라
착좌 근거의 만료를 다음 프레임에 상속하지 않으며 기존 착좌·충전 근거를 연장하지 않는다.
활성 binding이 없으면 null이다. 카메라는 프레임 원본 시각·순번과 실제 영상
측정으로 관측을 생성하고, 처리 이후에도 현재 범위를 확인한다. 로봇 자격은 source에
전달하지 않는다. 기본 app에는 해당 구성이 없으며 전체 충전 사이클 수용은 미완료다.

v1.282의 `StationReturnPermit`은 session/robot/station/battery/boot, map/revision/pose_revision,
correlation, lease_id/trip_id, 기대 native owner generation과 원본 유효기간을 담는다.
기존 trip lease를 먼저 열고 허가를 수락한 뒤에만 진입 정렬과 trip 출력을 시작한다.
최종 출력 검사는 허가와 기존 lease의 현재 소유자·정확한 ID·원래 만료를 비차단으로 확인한다.
카메라 관측은 귀환 주행 허가를 대신하지 않는다. lease/허가 만료·교체나 로컬 scope 변경은
출력을 차단하며 같은 허가의 재전송으로 자동 재개하지 않는다. `return_ready`는 현재 주행
허가만 표시하고 착좌·충전·완료를 주장하지 않는다. 실제 trip terminal과 귀환 예산 검증은
Fleet 포트의 책임이며, finish의 로컬 정지 확인은 trip 성공 증거를 대신하지 않는다.

`StationTargetBinding`은 immutable 세션 식별, 설치 위치, 상대 관측 scope와
`expected_boot_id`/`expected_owner_generation`을 담는다. `StationMotionCommand`는
session ID, 고유 correlation, 기대 native boot/generation을 담는다. 응답 소실 시
readback의 같은 session/correlation에 있는 operation ID로 기존 native 결과를 읽으며,
UNKNOWN을 같은 명령의 재시도로 처리하지 않는다. 동작 취소/무효화 후 자원 해제는 정지·이안
증거 확인과 별개다. 이 버전은 임의 교정·배터리 수치·착좌/충전 완료 입력 API를 열지 않는다.


### v1.284 충전 접안의 세션 한정 중단 (D-772)

`POST /api/v1/docking/station-stop`은 고정 허용 Fleet principal의 `StationMotionCommand`를 받는다. 현재 session/boot/native generation을 owner lock 아래 검증하며, 접안이 수락되었다면 현재 native run과 저장된 correlation도 일치해야 한다. 아직 BOUND라면 해당 세션을 HOLD로 닫아 지연된 시작을 거부한다. 위치·카메라 근거가 만료되어도 중단할 수 있으며 다른 실행이나 RETURNING을 취소하지 않는다. 응답 `{"accepted":true}`는 권한 폐쇄 ACK이며 측정 정지·물리 이탈·자원 해제 근거가 아니다. Fleet는 기존 영속 의도를 사용하고 응답 유실 시 접안을 재전송하지 않는다.

### v1.283 충전 복귀의 terminal navigation → IDLE 인계 (D-772)

`POST /api/v1/docking/station-return/finish`는 NAVIGATION 상태에서도 제한된 정지 인계를 처리한다. 기존 principal/session/correlation/boot/위치 버전/native generation/정확한 trip lease 검증을 먼저 유지한다. Navigation owner lock 아래 현재 부트의 성공 terminal run, ARRIVED 상태와 실제 transport quiescence, 진행 중 goal/admission/moving session/mapping/goal lease·pending submission·actuating callback 부재를 증명한 경우에만 navigation 후보를 지우고 `expect=NAVIGATION`으로 IDLE 전환한다. MANUAL/E-stop은 덮어쓰지 않고 일반 navigation 취소를 호출하지 않는다.

인계 성공도 복귀 완료가 아니다. 해당 호출은 RETURNING과 lease를 유지하며 명시적인 409 `STATION_RETURN_STANDSTILL_REQUIRED`를 반환한다. 기존 정지 누적을 초기화하고, 이후 새 원본 odom 표본의 연속 정지 dwell을 확인한 호출만 `StationPoseAck`와 BOUND를 반환한다. 활성·불명 backend, 일관되지 않은 transport 또는 현재 부트/owner 근거 부족은 409 `STATION_RETURN_NAVIGATION_UNVERIFIED`이며 IDLE 전환하지 않는다. 잘못된 native generation은 모드 변경 전에 거부한다. Fleet은 정지 미충족의 명시적 부정 ACK만 대기 재검사하고, 응답 유실·그 밖의 거절은 재제출 가능한 완료로 바꾸지 않는다.


### v1.273 Stuck evidence as a raw JPEG for `Accept: image/jpeg`

Additive, documents shipped behaviour. `GET /api/fleet/robots/{robot_id}/line-stuck/evidence` answers a request
whose `Accept` starts with `image/jpeg` with the JPEG bytes (`Content-Type: image/jpeg`, `Cache-Control: no-store`)
and puts the remaining fields (`robot_id`, `stuck_id`, `sequence`, `source`, `media_type`, `age_s`, and for
`live=true` also `live`, `captured_at`) in the `X-Stuck-Evidence` header as compact JSON. Other clients keep the
JSON body with `jpeg_base64`. Errors stay JSON. This drops the base64 overhead (+33 %) from the console's 2 s poll.

### v1.271 CORE OMX policy I/O (D-800)

Additive, operator-authenticated `/api/v1/arm/*`. No new TaskKind or Fleet grant.
Unbound `CoreServices.arm_policy` returns 503 `ARM_POLICY_UNAVAILABLE`. The current
port supports an explicitly installed SIM session only.

| Method/path | Request | Response |
|---|---|---|
| `GET /api/v1/arm/policy` | none | `policy_revision`, `simulation: true`, ordered `joint_names`, `units: rad`, `camera: {name, shape}` (CHW) |
| `POST /api/v1/arm/observations` | `{policy_revision}` | opaque `observation_id`, same revision, `positions` (joint→rad), `camera: {name, shape, rgb_base64}`; bytes are interleaved RGB uint8 HWC |
| `POST /api/v1/arm/actions` | `{policy_revision, observation_id, positions}` | 202 owner decision `{accepted, state, reason, command_id, cancel_outcome}`; admission is not completion |
| `POST /api/v1/arm/stop` | none | `local_stop`, `hold_reason`, `physical_stop_verified: false` |

The first three paths require the session's installed authenticated token ID.
Stop is open to every operator. Revision: 64 lowercase hex characters; targets:
finite JSON numbers (no bool/string), 1–8 exact installed joints. Request objects
forbid extras. No client timestamp, lease or reset is accepted.
Wrong principal/failed owner authority: 403 `ARM_POLICY_FORBIDDEN`; mismatched,
consumed or replaced source: 409 `ARM_POLICY_CONFLICT`; prior goal active:
409 `ARM_POLICY_BUSY`; schema errors: 400 (CORE ERR-101). Never retry an uncertain action.
Capture time conservatively anchors action age; the owner rechecks source,
lease, stop and envelope before submission. Clients wait for a fresh observation
after completion. Observation data alone is not training ground truth.
### v1.268 운영자의 정책 승인 표시와 세션의 `policy_admin` (D-793)

Additive. 예전 방식 `site-users.yaml` 항목에 선택 필드 `policy_admin: true`(operator에만)를 더한다. 그 사람은 operator 역할을 유지하면서 `fleet.policy` 판단(§10.18)을 할 수 있다. 통합 계정(Rosy Account) 세션은 기존처럼 자원 권한으로 판단한다. `GET /api/fleet/auth/session`은 통합 계정이 아니고 `fleet.policy`가 있을 때만 `policy_admin: true`를 더 돌려준다(없으면 필드가 없다). 표시는 `deploy/site/site_users.py set-policy-admin`으로 켜고 끈다. 이 필드를 모르는 이전 Fleet은 파일을 거부하므로 Fleet을 먼저 배포한다. envelope 1.0 변경 없음.

### v1.266 학습 정책 승인 관문: 단계·승인 창·확인 요청·사고 잠금·실행 lease (D-793)

Additive. 새 Fleet 경로 묶음 `/api/fleet/workcells/{workcell_id}/policy/*`와 콘솔 화면 `/console/policy`다. 기존 경로·envelope 1.0 변경 없음. 장치 명령을 보내는 경로는 없다.

- 학습 결과는 L0으로만 등록되고 단계는 `fleet.policy`(레거시 `policy-admin`) 승인으로 하나씩 오른다. L3·LIMITED는 제안자와 다른 사람이 승인한다.
- 승인 창(shadow 8시간, 입회 시험 기본 15분·최대 30분, 제한 사용 8시간)과 실행 lease(기본 1초·최대 2초, 승인 창을 넘지 않음)를 분리한다. lease는 아직 장치에 전달되지 않는다(`device_delivery: "not_connected"`).
- 열린 확인 요청이나 사고 잠금은 새 lease를 거절한다. 사고 신고는 이름 있는 운영자 누구나, 해제는 신고자와 다른 관리자가 한다.

### v1.259 recipe/3 sku를 CELL_TRANSFER에 싣고, 팔마다 목표 술어를 두고, Cell 앱이 두 팔 Job을 미리 본다 (D-781 §2·§5, D-779 §4)

Additive. 한 팔 Job(recipe/1·/2)의 grant 바이트, digest, 미리보기 응답은 그대로다. envelope 1.0 변경 없음.

- **`cell_transfer.sku`.** `CellTransferPayload`에 선택 필드 `sku`(`^[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}$`, `item: "box"`일 때만)를 더한다. 없으면 직렬화에서 빠져 digest가 이전과 같고, 있으면 digest가 덮는다. recipe/3 Step의 팔별 입력(`placement.actions[role]`)에 `sku`가 있고, Fleet은 그것을 grant 본문에 옮긴다. recipe/3 로더는 sku를 같은 식별자 규칙으로 받는다.
- **owner의 승인된 물체 형상.** 형상 키는 `item_key`다: sku가 없으면 `item`(`box`·`slip_sheet`), 있으면 `box:<sku>`. owner는 `capability_current`·계획기·SIM 그리퍼 판정에서 이 키로 찾는다. recipe/3 검증기는 cell/3 문서에 대해 컴파일되는 레시피의 sku마다 `{grasp_width_m: width, grasp_depth_m, height_m}`를 `box:<sku>` 키로 낸다. owner가 cell/3 문서를 승인하는 길은 아직 없다(열린 항목). 그래서 실제 owner에서 recipe/3 레시피 승인은 아직 거절된다.
- **팔마다 목표 술어.** 목표 허용오차가 설정된 Fleet은 recipe/3 Job의 Step마다 `goal_predicates: {arm_role: item_at_pose 술어}`를 고정한다. 술어는 주 배정 팔과 대체 팔마다 하나씩, 그 팔 입력으로 계산되어 그 팔의 `robot_base` 좌표계에 있다. 물체 중심 높이는 sku의 `grasp_depth`·`height`로 정한다. `POST /api/fleet/cell-goal-evidence`의 술어 팔은 Step에 배정된 첫 팔이다(첫 주 배정 팔, 또는 Step을 넘겨받은 대체 팔). 그 팔에 저장된 술어로 판정한다. 대체 팔이 실행한 Step은 그 팔 술어가 있으면 받는다. 없으면 409 `CELL_GOAL_PREDICATE_MISSING`이다. 첫 주 배정 팔 좌표의 단일 `goal_predicate`로 대체 팔을 판정하지 않는다. 나머지 범위 검사(`EVIDENCE_SCOPE_MISMATCH`, `PRODUCER_SCOPE_MISMATCH`)는 그대로다.
- **Cell 앱 미리보기.** `POST /api/fleet/cell-app/compile`은 recipe/3 문서를 `compile_mixed`로 미리 본다. candidate envelope는 같다. `summary`에 `multi_arm: {arms: [{role, instance_id, workcell_id}], steps: [{index, sku, arm, alternates, zone, coupling, depends_on}]}`가 붙는다. `transfer_count`는 Step 수이고, `pallet_markers`는 팔레트마다 하나다. recipe/1·/2 응답에는 `multi_arm`이 없다. `POST /api/fleet/cell-app/proposals`는 recipe/3에서 두 팔 Job을 resolve한다. `instance_id`는 cell 팔 instance 가운데 하나여야 한다.
- **두 팔 제안 경로**는 Proposal 절의 "Multi-arm proposal path"에 적었다(recipe/3 candidate → 두 팔 submission 모양, 팔, 배치).

### v1.258 두 팔 Cell Job의 Step 목표 증거와 팔 하나 재개 (D-779 §3·§6)

Additive. 새 경로 하나와 기존 Cell 목표 증거 ingress의 두 팔 Job 판정이다. envelope 1.0과 한 팔 Job의 동작은 그대로다.

- **팔 하나 재개.** `POST /api/fleet/cell-jobs/{mission_id}/arms/{arm_role}/resume`, 이름 있는 운영자, 본문 `{expected_generation}`. 두 팔 Job에서 `HOLD`·`OFFLINE`인 팔 하나만 지금의 fence 아래에서 `READY`로 돌리고, 그 팔이 잡은 `HELD` 팔·구역 claim을 놓는다. 그 팔의 마지막 장치 결과가 성공이면 Action은 `ACTION_SUCCEEDED`로 남고 다시 보내지 않는다. 거절은 409 `CELL_JOB_RECOVERY_REFUSED`다: 한 팔 Job, 없는 팔이나 잡히지 않은 팔, 취소된 Job, 정지·권한 세대가 바뀐 경우(Job 전체 재개를 쓴다), 그 팔의 claim이 `DISPATCHING`·`UNKNOWN`인 경우(readback 먼저), 그리고 `TIGHT_PARTNER_HELD`로 잡힌 팔의 단단한 결합 짝이 아직 `HOLD`·`OFFLINE`인 경우(짝을 먼저 재개하거나 Job 전체 재개). 없는 Job은 404 `CELL_JOB_NOT_FOUND`.
- **두 팔 Job의 목표 증거.** `POST /api/fleet/cell-goal-evidence`는 두 팔 Job을 `current_step_index`가 아니라 Step 단위로 판정한다. 증거는 저장된 `item_at_pose` 술어가 컴파일된 팔(그 Step 배치의 첫 주 배정 팔)의 Action을 가리켜야 하고, producer는 Job의 cell `workcell_id`와 그 팔의 `instance_id`로 등록되어 있어야 한다. 협조 Step은 배정된 모든 팔 Action의 마지막 장치 결과가 그 시도의 `SUCCEEDED`일 때만 `GOAL_CONFIRMED`가 되며, 관측은 마지막 성공 뒤에, 첫 관측은 모든 grant 발행 뒤이자 첫 성공 전에 있어야 한다. 대체 팔이 실행한 Step은 그 팔 좌표의 술어가 아직 없어 거절한다(D-779 열린 질문, fail closed). 확인된 Step은 `depends_on`을 풀고, 모든 Step이 확인되면 Job은 `GOAL_CONFIRMED`가 된다(D-779 §1).
- **협조 Step의 재전송.** 협조 Step은 모든 팔 Action이 함께 시작할 수 있을 때만 다시 낸다. 한 팔만 성공하고 다른 팔이 재개된 협조 Step은 한 팔만 다시 보내지 않는다. 그 Step은 `HOLD`·`PAIR_PARTIALLY_SUCCEEDED`로 읽히고 취소로만 끝난다.

### v1.287 D-769 route-prior compatibility prerequisite

This additive prerequisite prepares the existing drivable-v2 SIM implementation; installing
the schema alone does not activate a disabled producer, wall clipping or physical deployment.
It supersedes the one-second wire limits in v1.246/v1.247: `AuthorityRouteGuide.max_age_s`
and the source-based `SelectedRoutePrior` lifetime accept at most three seconds. Fleet's
operational producer still sends one second; only the explicit isolated SIM runner uses
three seconds. Neither value extends the enclosing movement authority's end or TTL,
and repeated use of the same source cannot refresh its original age budget.

Both shapes add optional finite `wall_left_m` in (0,2], `wall_right_m` in [-2,0), and
`wall_ahead_m` in (0,2]. They describe map wall faces across the selected directed lane
from the robot, and their forward coverage, not observed free floor. Omission means no
map-wall evidence. CORE and the camera consumer must understand these fields before
an upgraded Fleet serializes them. Existing enabled producers use `model_dump()` and
already send the new fields as null after a schema-only upgrade. An older CORE with
`extra="forbid"` rejects the entire enclosing authority request at nested validation,
not only its guide. Upgrade CORE and the camera receiver before upgrading Fleet's schema.
The default `crosswalk_map_wall_band_m` is null, so this prerequisite does not clip scans.
D-573 revision 8 defines the downstream clipping bounds and physical calibration gate.

The corresponding product implementation makes one explicit exception to v1.246's
accepted-authority-only binding rule: a live, same-scope, newer-sequence extension rejected
as `reason="shrink"` may refresh a valid exact-pose guide. It keeps the existing movement
end and expiry unchanged. Actual shrink requests, stale/out-of-order or wrong-scope
requests do not gain that exception; source-age limits and the FREE authority gate remain.
Until that consumer implementation is installed, a rejected extension retains the old
behavior. Envelope 1.0 and final CORE command ownership are unchanged.

### v1.247 D-769 selected-route production capability

The base control descriptor adds `line_follow_route_guide` (absent/false means unsupported).
CORE advertises it only when `line_follow.route_guide_enabled` is explicitly true; the
flag defaults false and also gates active ROS guide publication. Enable it only with the
source-expiring camera inbox deployed. The isolated learned-drivable Gazebo runner opts in;
this does not activate a physical robot.
Fleet captures geometry from its selected directed plan and the unrounded localized pose
used to locate trip progress. The map id must match the active map. Before attaching it to
the existing authority request, Fleet checks the exact echoed pose stamp, map/route revision,
plan segment signature, lap trim, selected station and remaining source-age budget (<=1 s).
Holds, old poses, changed plans and shrink requests carry no guide. Stored segment endpoints
are normalized only within their existing four-decimal serialization precision.

### v1.246 D-769 route geometry attached to accepted authority

`POST /api/v1/line-follow/authority` adds optional `route_guide` (`AuthorityRouteGuide`).
It carries `map_id`, integer `map_revision`, finite `heading_here_deg`/`heading_ahead_deg`
in [-180,180], `ahead_m` in (0,2], nonnegative `s_m`/`off_route_m`, and `max_age_s` in (0,1].
Extra fields are rejected. Leg, sequence and pose come only from the enclosing authority.
CORE binds geometry only after authority acceptance, with a sequence and an exact echoed
`pose_stamp` match. It converts that sample's ROS stamp to `source_stamp_s` and caps the
prior by source age and authority TTL. Reusing a source cannot extend its previous budget.
Accepted requests without geometry, shrink requests, mode reset, expiry or unavailable
odometry expose no prior. Ignored stale requests cannot replace or refresh the current prior.
The prior selects among observed floor directions; it grants no movement or pivot authority.
CORE now publishes through its existing line-follow timer. Fleet production and explicit capability opt-in are implemented by v1.247; Gazebo acceptance remains pending.
REST remains additive; Fleet envelope protocol 1.0 is unchanged.

### v1.245 D-769 selected-route prior transport (internal, producer not enabled)

`core_common.protocol.lane_route_guide.LaneRouteGuide` defines the version 1 CORE-to-camera
message for the single CORE `line/lane_guide` publisher. The camera observer now routes
this subscription through the ordered inbox and checks each frame before keep-mode use.
Authority attachment is available through v1.246; Fleet production requires the v1.247 capability.
CORE emits an ordered clear before its first active message and after a source-clock rewind.
Publication has a separate monotonic source budget that survives publication-epoch resets;
the wire deadline is capped by the remaining budget. The receiver also applies its own
remaining-budget clock. This describes validity at publication/receipt: elapsed wall time
during transport while ROS time is paused is not encoded in the message.
Inactive line following, E-stop or unavailable authority produce clears. Unversioned diagnostic
messages are rejected by this runtime subscription; the legacy pure replay parser remains.

- Envelope: `v=1`, nonempty `publisher_epoch`, nonnegative integer publication `seq`, and
  `guide`. `guide=null` explicitly clears the cached prior. Publication sequence increases
  across active and clear messages within one CORE process; it is separate from authority sequence.
- Active guide: `leg_id`, `authority_seq`, `map_id`, immutable integer `map_revision`,
  `source_stamp_s`, `valid_until_s`, `heading_here_deg`, `heading_ahead_deg`, `ahead_m`,
  `s_m`, `off_route_m`, and `pivot_ok=false`. Extra fields are refused. All numeric geometry
  is finite; headings are degrees left-positive relative to the source body's yaw, bounded
  to [-180,180]. `ahead_m` is actual positive preview distance at most 2 m; zero preview
  produces a clear. `s_m` starts at the selected plan origin, not the current arc origin;
  `off_route_m` is nonnegative distance to that selected route.
- Source and deadline use the camera/ROS source clock, never another process's monotonic
  clock. The deadline is strictly after source and at most one source second later; CORE
  must additionally cap it at accepted authority expiry. Republishing cannot renew it.
  Producer mapping must identify the exact odometry sample used for Fleet's relative headings.
- The inbox rejects future, expired, malformed and reordered messages. A higher-sequence
  clear prevents queued lower-sequence active messages from reviving the prior. A different
  publisher epoch requires a clear before active messages; retired epochs remain rejected.
  It retains at most 64 retired epochs and refuses further switches until inbox restart.
  Camera clock rewind clears the current prior; epoch ordering is not reset by that event.

  The inbox also enforces the remaining source budget on its own monotonic clock. A repeated
  source sample cannot renew that local deadline, including across clears or expiry. Older
  source samples are refused within an epoch. The typed result retains actual `ahead_m`.
  Keep-mode direction use requires its full 0.25 m preview; shorter previews do not
  select steering direction, while fresh scalar off-route evidence still causes HOLD.

  The inbox also enforces the remaining source budget on its own monotonic clock. A repeated
  source sample cannot renew that local deadline, including across clears or expiry. Older
  source samples are refused within an epoch. The typed result retains actual `ahead_m`.
- Producer integration must clear atomically on accepted authority without a guide, shrink,
  revocation, mode/trajectory change and expiry. Rejected authority cannot install or renew
  a guide. Capability opt-in must cover the deployed consumer's deadline/invalidation
  behavior, not just request schema support. Legacy unversioned diagnostic input is not
  evidence of this capability. Direction never establishes visible floor or pivot permission.

### v1.264 두 팔 제안 경로와 팔별 목표 술어 (D-781 §2·§5)

Additive. recipe/3 Step은 팔마다 `goal_predicates`(그 팔 `robot_base`)를 저장하고, 목표 증거는 Step을 실제로 실행한 팔(첫 주 배정 팔 또는 대체 팔)의 술어로 판정한다. 그 팔 술어가 없으면 409 `CELL_GOAL_PREDICATE_MISSING`. `cell_transfer.sku`는 선택 필드이고 없으면 recipe/1·2 grant 직렬화와 digest가 이전과 같다. `POST /api/fleet/cell-app/compile`은 recipe/3를 `summary.multi_arm`으로 미리 본다. 자세한 내용은 변경 이력 v1.264 행.

### v1.263 두 팔 Cell Job의 Step 목표 증거와 팔 하나 재개 (D-779 §3·§6)

Additive. 새 경로 하나와 기존 Cell 목표 증거 ingress의 두 팔 Job 판정이다. envelope 1.0과 한 팔 Job의 동작은 그대로다.

- **팔 하나 재개.** `POST /api/fleet/cell-jobs/{mission_id}/arms/{arm_role}/resume`, 이름 있는 운영자, 본문 `{expected_generation}`. 두 팔 Job에서 `HOLD`·`OFFLINE`인 팔 하나만 지금의 fence 아래에서 `READY`로 돌리고, 그 팔이 잡은 `HELD` 팔·구역 claim을 놓는다. 그 팔의 마지막 장치 결과가 성공이면 Action은 `ACTION_SUCCEEDED`로 남고 다시 보내지 않는다. 거절은 409 `CELL_JOB_RECOVERY_REFUSED`다: 한 팔 Job, 없는 팔이나 잡히지 않은 팔, 취소된 Job, 정지·권한 세대가 바뀐 경우(Job 전체 재개를 쓴다), 그 팔의 claim이 `DISPATCHING`·`UNKNOWN`인 경우(readback 먼저), 그리고 `TIGHT_PARTNER_HELD`로 잡힌 팔의 단단한 결합 짝이 아직 `HOLD`·`OFFLINE`인 경우(짝을 먼저 재개하거나 Job 전체 재개). 없는 Job은 404 `CELL_JOB_NOT_FOUND`.
- **두 팔 Job의 목표 증거.** `POST /api/fleet/cell-goal-evidence`는 두 팔 Job을 `current_step_index`가 아니라 Step 단위로 판정한다. 증거는 저장된 `item_at_pose` 술어가 컴파일된 팔(그 Step 배치의 첫 주 배정 팔)의 Action을 가리켜야 하고, producer는 Job의 cell `workcell_id`와 그 팔의 `instance_id`로 등록되어 있어야 한다. 협조 Step은 배정된 모든 팔 Action의 마지막 장치 결과가 그 시도의 `SUCCEEDED`일 때만 `GOAL_CONFIRMED`가 되며, 관측은 마지막 성공 뒤에, 첫 관측은 모든 grant 발행 뒤이자 첫 성공 전에 있어야 한다. 대체 팔이 실행한 Step은 그 팔 좌표의 술어가 없으면 거절한다(fail closed). v1.264부터 술어는 팔마다(`goal_predicates`) 저장되고 대체 팔 Step도 그 팔 술어로 판정한다. 확인된 Step은 `depends_on`을 풀고, 모든 Step이 확인되면 Job은 `GOAL_CONFIRMED`가 된다(D-779 §1).
- **협조 Step의 재전송.** 협조 Step은 모든 팔 Action이 함께 시작할 수 있을 때만 다시 낸다. 한 팔만 성공하고 다른 팔이 재개된 협조 Step은 한 팔만 다시 보내지 않는다. 그 Step은 `HOLD`·`PAIR_PARTIALLY_SUCCEEDED`로 읽히고 취소로만 끝난다.

### v1.242 작업의 운행 단계: 한 사람이 시작하는 trip 단계 작업 (D-763 조각 7, simulation 프로필만)

Additive. 새 경로 하나와 Step 원장의 새 종류 하나다. envelope 1.0은 그대로다.

- **`POST /api/fleet/trip-jobs`.** 본문은 `{robot_id, steps: [{to, via[]}]}`이다(단계 1–8개, `via` ≤ 8, 추가 필드 금지). 이름 있는 운영자만 쓴다. `simulation` 배포 프로필이고 Step 원장(`--mission-api`)이 있을 때만 경로가 있다. 다른 프로필에서는 경로가 없고, 이미 열려 있던 `TRIP` 작업은 시작할 때 HOLD(`FLEET_PROFILE_CLOSED`)된다. 등록부 승인 값은 `one_person`이라 만든 사람이 곧 승인한 사람이다. 응답은 `{job}`(Step 원장 행, 단계 종류 `TRIP`, 상태 `READY`)이다.
- **거절.** 404 `UNKNOWN_ROBOT`. 422 `TRIP_UNKNOWN_PLACE` `{places}`. 422 `LINK_UNBOUNDED_MOTION` `{reasons, missing}`(D-763 개정 2 질문 10 (a)(b), `hold_job`). 409 `TRIP_ROBOT_BUSY`(이미 움직이거나 다른 작업이 쥔 로봇). 409 `JOB_ESTOP`(lease를 여는 동안 비상 정지가 왔다). 409 `JOB_ROBOT_REFUSED` `{message}`(다른 Task·작업이 robot claim을 쥠, 또는 dispatch 정지 래치). 오류 모양은 trip 경로와 같은 `{"detail": {"code", "detail"}}`이다.
- **실행.** 작업은 만들 때 그 로봇의 `robot` claim과 CORE trip lease(`job_id`, v1.236)를 잡고 끝까지 쥔다. 단계마다 로봇 카드와 같은 계획 경로와 시작 검사로 trip 하나를 연다. 다음 단계로는 그 trip의 `arrived`만 넘어간다. 다른 끝, 거절된 시작, lease 잃음, 비상 정지, 정지 래치는 작업을 HOLD(사유: trip의 사유나 코드, `JOB_LEASE_LOST`, `JOB_ESTOP`, `FLEET_RESTARTED`)로 두고 lease를 놓는다. claim은 `HELD`로 남는다. HOLD마다 사람 단계 문제 기록(`kind: job_hold`, `/api/fleet/ai/episodes`)이 하나 열린다.
- **읽기와 회복.** 작업은 `GET /api/fleet/work`에 `source: "cell_job"`, `action_kind: "TRIP"` 행으로, 단계 trip은 `source: "trip"` 행으로 나온다. 재개와 취소는 지금의 `POST /api/fleet/cell-jobs/{mission_id}/resume`·`/cancel`이다. 재개하면 새 lease와 새 trip이 열리고 시작 검사를 다시 거친다. `kinds`에는 아직 `TRIP`이 없다.
- **trip 사이의 넘겨받기(동작).** 차로 trip이 `arrived`로 끝나면 CORE는 그 `stop`을 쥔 채 남는다. 같은 로봇의 다음 trip은 아직 아무 지시도 보내지 않았고 그 정지가 자기 다음 장소에 있으면, 그 정지(같은 seq와 장소) 하나를 새 지시로 바꿀 수 있다. 멈춤이 보낸 정지와 다른 송신자의 지시는 바꾸지 않는다.

### v1.241 교차로·굽이 지시의 거리를 Fleet이 본 odom 표본부터 잰다 (D-767 A부)

`POST /api/v1/line-follow/junction`에 선택 최상위 필드 `pose_stamp`를 더한다(additive). 능력 `base_velocity.lane_instruction_stamp`가 참인 CORE에만 보낸다. 그 능력은 CORE 설정 `line_follow.instruction_stamp_enabled`(bool, 기본 `false`)와 같다.

| 필드 | 형식 | 뜻 |
| --- | --- | --- |
| `pose_stamp` | finite number > 0, UTC epoch 초(CORE 벽시계, 스냅숏 `odom_pose.stamp`) | 이 지시의 `expect_in_m`·`bend_in_m`을 잰 Fleet 자세가 묶인 odom 표본의 시각. 같은 주기의 `map_entry.odom_stamp_s`(v1.224)·통행권 `pose_stamp`와 같은 값이다 |

0 이하·무한·숫자 아님(JSON `true`, `"1.5"` 같은 문자열 포함)은 400 `VALIDATION_ERROR`다. 각 거리의 기준점(`expect_in_m`은 로봇의 차로 투영점, `bend_in_m`은 굽이 호 시작점까지)은 그대로이고 시간 기준만 바뀐다. 설정이 켜진 CORE는 받을 때 그 stamp로 발행된 odom 표본을 찾고(v1.234 정확한 표본, "그 시각 이전" 표본은 쓰지 않는다), 같은 표본의 교차로 주행 거리계(trail odometer, 통행권의 경로 길이와 다른 누적기) 값을 교차로 창의 기준으로, 그 뒤 달린 거리를 굽이의 처음 주행 거리로 둔다. 나이 상한은 없다: 교차로 궤적(약 5 s)이 그 표본을 가진 동안 쓴다. 거리(`expect_in_m` 또는 `bend`)가 있는 지시의 `pose_stamp`를 쓸 수 없으면 CORE는 그 지시를 409 `INSTRUCTION_STAMP_UNUSABLE`로 거절하고 지금의 지시 상태를 그대로 둔다. `error.detail`은 `{"reason": <까닭>}`이고 까닭은 `disabled`(설정 꺼짐), `ambiguous`(같은 stamp의 표본 둘), `future`(CORE 기록의 가장 새 표본보다 0.05 s 넘게 앞섬), `no_sample`(그 stamp로 발행된 표본 없음, 신선한 odom 없음), `epoch`(odom 세대·frame이 다름), `stale`(표본이 교차로 궤적에서 빠짐)이다. 거리가 없는 지시의 `pose_stamp`는 쓰지 않고 거절하지도 않는다.

상태 `line_follow.junction`에 두 필드를 더한다. `distance_basis`: `stamp` | `receipt`, 창도 굽이 거리도 없는 지시는 null. `distance_basis_reason`: `receipt`이면 `none_sent`(`pose_stamp` 없음), `stamp`이면 null.

Fleet은 능력이 참이고 자세에 odom stamp가 있는 로봇의 거리 있는 지시에 `pose_stamp`를 싣고, 그 로봇의 `bend_in_m`에서 앞당김(`fleet.trip.bend_send_s`, 읽기→전송 시간)을 빼지 않으며, `expect_tol_m`·`bend_tol_m`에서 읽기→전송과 전송 여유(0.2 s) 항을 뺀다(자세 나이·dead reckoning·드리프트 항은 남는다). `INSTRUCTION_STAMP_UNUSABLE`이면 다음 주기에 새 자세·stamp로 다시 보내고, 까닭이 `disabled`이면 그 trip은 stamp 없이 앞당김을 넣어 보낸다. 능력이 없거나 거짓인 로봇과 설정이 꺼진 CORE의 동작은 v1.240과 같다. Fleet `/api/fleet/*` 변경 없음. envelope 1.0 변경 없음.

### v1.240 제안 읽기·결정 응답·자원 claim 읽기는 Cell Job 상세 범위를, 채널 제출·승인은 이름 있는 운영자를 따른다 (D-763 조각 4 리뷰)

인증·응답 범위만 바뀐다. 스키마는 그대로다.

- **제안 읽기.** `GET /api/fleet/proposals/{proposal_id}`는 Cell Job 제안을 `GET /api/fleet/cell-jobs/{mission_id}`와 같은 범위로 읽는다. 제안자는 읽는다. Job이 `PROPOSED`가 아니면 운영자 누구나 읽는다. 남의 미판정·`PROPOSED` 제안은 이름 있는 운영자만 읽는다. 나머지는 404 `PROPOSAL_NOT_FOUND`이고, 본문은 없는 id와 같다. 제안자 아닌 독자는 `mission`에 `proposal_principal_id`가 없고, 제안자의 사건은 `actor_id: "proposer"`로 보인다. 레거시 Mission 제안은 그대로 제안자만 읽는다.
- **결정·복구 응답.** `POST /api/fleet/missions/{mission_id}/admit`·`/reject`와 `POST /api/fleet/cell-jobs/{mission_id}/reconcile`·`/resume`·`/cancel`이 돌려주는 Cell Job도 제안자 아닌 호출자에게는 같은 방식으로 가린다.
- **자원 claim 읽기.** `GET /api/fleet/resource-claims`에서 viewer는 claim마다 `resource_key`·`resource_kind`·`resource_id`·`phase`만 받는다. 운영자는 Cell Job claim(`job_status`가 null이 아님)의 행 전체를 받는다. 그 밖의 claim은 그것을 쥔 레거시 Mission의 제안자만 행 전체를 받고, 다른 사람에게는 viewer 필드로 줄어든다.
- **채널.** `POST /api/fleet/channel-requests/{request_id}/admit`·`/submit`은 이름 있는 운영자가 필요하다. 직접 Mission admit, `POST /api/fleet/robots/{robot_id}/goal`과 같다. 이름 없는 공유 토큰은 403 `OPERATOR_IDENTITY_REQUIRED`다.
- **작업이 쥔 로봇의 거절.** 다른 작업이 쥔 로봇의 trip 시작·작업 단계 lease가 받는 409 `TRIP_ROBOT_BUSY`의 detail은 그 작업의 `job_id` 대신 `{"reason": "job", "owner_kind": "mission"}`이다. 거절받는 사람이 쥔 작업의 id를 알지 못한다.
### v1.239 Fleet 통행권 아래의 교차로 무응답은 대기, 통행권 HOLDING 대기는 회전·호 시계를 세운다 (D-620 노트 2026-10-15, D-760 개정 4)

요청·응답·상태 필드 변경 없음. 동작 변경(Behavioural)이다.

- **교차로 신호(§7.3.1).** CORE가 D-517 통행권을 강제하는 동안(`authority_required`, 이 세션에 받은 통행권, 본 trip lease; 모드를 바꿀 때까지 유지) 응답이 한 번도 없는 정지 에피소드는 3초가 지나도 우측을 고르지 않고 0으로 서서 기다린다(`signal_state: waiting`, `regulation_wait`, CORE journal 한 줄). `green && may_enter:true` 2초 이내 답은 그대로 진입을 고른다. trip 밖의 감독 시험은 v1.203 그대로다.
- **회전·호 시계.** 교차로 기동의 단계 시계와 D-520 호의 기한은 통행권이 `HOLDING`(Fleet이 살아서 기다리라고 함)인 앞뒤 두 틱마다 그 시간을 전부 더한다. `NONE`·`EXPIRED` 통행권과 횡단보도 살핌·기다림·건넘 몫은 지금처럼 한 지시(호)에 `crosswalk_report_s + crosswalk_clear_s`(15 s)까지다. 그 뒤 `timeout`/`lane_arc_timeout`으로 선다.

### v1.238 규제 능력 `lane_crosswalk_gate`·`lane_junction_signal`과 trip 시작 거절 (D-763 10항 (c))

`GET /api/v1/system/capabilities`의 `controls.items[]` `base_velocity`에 선택 bool 둘을 더한다(additive). `lane_crosswalk_gate`는 CORE `line_follow.crosswalk_gate_enabled`가 켜졌을 때만, `lane_junction_signal`은 `line_follow.junction_signal_enabled`가 켜졌을 때만 `true`다. 설정 기본값은 그대로(둘 다 `false`)다.

Fleet은 trip 시작·다음 바퀴·재계획의 능력 검사(`trip_checks/trip_admission.py` `_caps_checks`)에서, lane 간선이 있는 경로가 현장 지도 횡단보도 다각형(D-573 1)에 들어가는데 로봇이 `lane_crosswalk_gate`를 `false`로 알리거나, 신호 구역(D-525 `fleet.traffic.signals`의 zone)을 지나는데 그 능력을 `false`로 알리면 422 `TRIP_REGULATION_CAPS_MISSING` `{missing: {<능력>: [횡단보도 id 또는 signal id]}}`로 거절한다. 규제 규칙이 조용히 빠진 채 달리지 않게 하기 위해서다. 필드가 없는 옛 CORE는 거절하지 않고, trip view `detail.regulation_caps_unknown {<능력>: [id]}`와 Fleet 경고 로그를 남긴 채 시작한다(모든 로봇이 v1.238 이상이 되면 거절로 좁힌다). 둘 다 지나지 않는 경로는 그대로 시작한다. 이 검사는 D-525의 `TRIP_SIGNAL_START_IN_ZONE`·`TRIP_SIGNAL_NEEDS_AUTHORITY`보다 먼저 온다.

### v1.237 작업 읽기의 trip·Cell Job 출처, 보이는 상태, 승인 대기 범위, 새 작업 종류 (D-763 조각 4, 8·9항)

`GET /api/fleet/work`(v1.208)의 출처에 `trip`과 `cell_job`을 더한다(additive). 응답 모델은 그대로 `FleetWorkOverview`/`FleetWorkSummary`(`core_common.protocol.schemas`)이고 필드가 늘었다.

- **행.** `source`가 `task`·`mission`·`trip`·`cell_job` 넷이다. trip 행: `source_id` = trip id, `action_kind` = `trip`, `status` = trip 상태 그대로(`started`·`running`·`link_wait`·`arrived`·`stopped`·`failed`·`canceled`), `device_id` = 로봇, `workcell_id` null, `reason` = trip 끝 사유, `updated_at` = trip view의 갱신 시각(UTC ISO). 열린 trip과 최근 끝난 trip이다(저장된 최근 `limit`개에 열린 trip을 더한다). Cell Job 행: `source_id` = mission id, `action_kind` = 원장 단계 종류(지금 `CELL_TRANSFER`), `status` = Cell Job 상태 그대로, `device_id` = OMX instance, `workcell_id`, `reason`, `updated_at`.
- **새 필드(모든 행).** `visible_state`: `approval_pending`(`PROPOSED`) · `in_progress` · `waiting`(열린 trip의 `wait.waiting`이 참) · `intervention`(`HOLD`, trip `stopped`·`failed`, Task `FAILED`·`UNKNOWN`·`EXPIRED`) · `ended`(`GOAL_CONFIRMED`, `COMPLETED`, `CANCELED`, trip `arrived`·`canceled`, `CANCELLED_BY_OPERATOR`로 끝난 Cell Job) · 이 읽기가 모르는 상태는 null. 읽기 투영이고 원장 상태 값은 바뀌지 않는다(D-664 5항). `wait`: trip 행만, trip 읽기의 `wait`(v1.232)에서 `reason`·`waiting`·`bound_s`·`over_bound` 넷(`since` 없음, 판정하지 않은 tick은 null). 상한을 넘은 기다림은 `in_progress`이고 `over_bound` 참이다 — 경고이지 개입이 아니다(개정 2 질문 7). `approval`: `PROPOSED` 행만, 단계 종류 등록부의 값(`two_person`·`proposer_only`·`one_person`, v1.230과 같은 판정), 등록부에 없는 종류는 null(승인 경로가 409 `APPROVAL_RULE_UNREGISTERED`).
- **상세 범위.** 행을 누르면 여는 `GET /api/fleet/cell-jobs/{mission_id}`도 같은 범위다(제안자 아닌 독자에게 `proposal_principal_id` 없음, 사건의 제안자는 `actor_id: "proposer"`). 닫힌 trip 행의 `wait`는 null이다(저장된 마지막 답을 보이지 않는다).
- **범위(서버가 정한다).** Task·trip 행은 viewer 이상 모두(trip은 `GET /api/fleet/trips`와 같다). Mission 행은 지금처럼 제안한 사람 자신의 것만(`PICK_PLACE`는 제안자만 종류). Cell Job 행: 제안한 principal 자신, `PROPOSED`가 아닌 행은 운영자(`GET /api/fleet/cell-jobs/{id}`와 같은 범위), `PROPOSED` 행은 이름 있는 운영자(D-763 개정 2 질문 6: 두 사람 승인이 필요한 요약 행은 제안하지 않은 이름 있는 운영자에게도 보인다). viewer와 이름 없는 운영자(공유 콘솔 토큰)는 남의 `PROPOSED` Cell Job 행을 보지 못한다. 행에는 제안자 신원·계획·후보·요청 본문이 없다. 상세와 본문의 범위는 그대로다.
- **응답 필드.** `cell_jobs_available`(Cell 원장 미설정이면 false, 빈 목록과 구별), `truncated_sources`에 `trip`·`cell_job`(최대 4), `rows` 최대 400행, `kinds`(아래).
- **새 작업 종류 `kinds`.** 이 현장에서 지금 실행할 수 있는 새 작업 종류이고 값은 그 종류 행의 `action_kind`다. `trip`: 활성 현장 지도에 장소가 있고, 로봇 가운데 하나가 trip 능력(`base_velocity`의 `robot_kind`·`drive_modes`·`trip_max_linear`, D-494 1)을 알린다(능력 캐시 읽기, 처음 읽는 로봇은 최대 0.05 s). `CELL_TRANSFER`: 이 배포 프로필에서 단계 원장 하달이 열려 있고(`step_action_kinds.open_kinds`, 지금 `simulation`만) 하달기가 켜져 있고 설정된 OMX instance가 있다. 열리지 않은 종류는 목록에 없다(꺼진 단추나 "준비 중"으로 보이지 않는다, D-763 9항). 시작 권한 검사는 각 시작 경로가 그대로 한다.

여러 원장 사이의 같은 시점은 보장하지 않는다. 행마다 원장 갱신 시각을 보인다. 이 경로는 읽기이며 dispatch·admission·claim을 하지 않는다. 승인·거절 자리(D-763 조각 5c)는 이 버전에 없다.
### v1.236 작업이 쥔 trip lease는 단계 사이 IDLE에서 끝나지 않는다 (D-763 조각 6, 4항)

`PUT /api/v1/trip-lease` 본문에 선택 필드 `job_id`(1–128자)를 더한다(additive). `job_id`를 실어 연 lease는 다단계 작업의 lease다. 그 작업의 단계 사이에 로봇이 IDLE이 되어도 CORE 모드 감시가 lease를 끝내지 않는다(D-541 5항의 `mode_left`가 IDLE에서는 일어나지 않는다). MANUAL·도킹으로 감, 비상 정지, 넘겨받기(`POST /trip-lease/takeover`), 만료, 주인의 해제는 지금처럼 끝낸다. 주인 아닌 토큰의 `POST /mode {IDLE}`는 멈춤이라 누구에게나 열려 있고, 그 요청이 lease를 끝낸다(작업의 lease도, 로봇이 이미 IDLE이어도; `mode_left`, `by` = 그 토큰의 라벨). 사람이 세운 로봇을 Fleet이 주인 토큰으로 다시 움직이지 않게 하기 위해서다. 단계 사이에 주인 아닌 토큰의 다른 `/mode`와 `/teleop`은 409 `TRIP_LEASED`다. renew는 `job_id`를 바꾸지 않는다. lease는 "누가 로봇을 쥐는가"에만 답한다: 통행권(`line-follow/authority`, `ttl_s` ≤ 5)과 목표 임대(`navigation/goal/lease`)는 자기 `ttl`대로 만료하고 lease renew가 늘리지 않는다. 상태 `trip_lease`에 `job_id`(작업의 lease가 아니면 `null`)가 실린다. 능력 `base_velocity.trip_lease_job: true`는 이 동작을 하는 CORE다. 옛 CORE는 `job_id`를 무시하고 IDLE에서 lease를 끝내므로 Fleet은 이 능력이 없는 로봇에 다단계 작업을 승인하지 않는다(D-763 개정 2 질문 10). 팔 단계 중 만료의 동작은 정하지 않았다(D-763 남은 질문 1).
### v1.234 odom 세대와 단조 수신 시각, odom 기록은 발행한 stamp로 찾는다 (D-758 0단계)

스냅숏 `odom_pose`에 선택 필드 둘을 더한다. 필드가 없는 스냅숏(v1.233 이하 CORE)은 그대로 읽힌다. 요청·응답·envelope 1.0 변경 없음.

| 필드 | 형식 | 뜻 |
|---|---|---|
| `odom_pose.epoch` | 정수 ≥ 0 | CORE 시작 뒤 odom 불연속 횟수. 한 표본에서 0.02 m + 0.2 m/s × 수신 간격을 넘는 이동, odom 메시지 `frame_id` 변경, ROS 헤더 시각이 뒤로 감 가운데 하나일 때만 는다. 원점을 지나 달리는 것과 line-follow 모드 변경은 세지 않는다 |
| `odom_pose.mono_s` | 유한 실수 | 같은 수신의 CORE 단조 시각(s). 로봇 사이·재시작 사이에 비교하지 않는다 |

- **CORE 조회.** `POST /line-follow/authority`의 `pose_stamp`, lane cue의 `pose_stamp`, `exit_segment.map_anchor`·`map_entry`의 `odom_stamp_s`는 그대로 스냅숏 `odom_pose.stamp`다. CORE는 그 stamp로 발행한 odom 표본을 찾고(|차| ≤ 1 µs, 같은 값이 둘이면 가장 새것), 그 표본의 나이와 순서는 line-follow 시계(장치 `time.monotonic`, `use_sim_time`에서 시뮬레이션 시각)로 잰다. 벽시계가 움직여도 같은 표본을 찾는다. 발행한 값과 맞지 않는 stamp(옛 Fleet의 계산한 값)는 v1.226과 같이 벽시계에서 그 이전 표본을 찾는다. 통행권의 `seq` 기억도 line-follow 시계로 잰다.
- **Fleet.** 지도 자세 추적기는 `epoch`가 바뀐 표본을 받으면 이동이 없어도 odom 기록과 기준을 버린다(`epoch`가 없는 로봇은 그대로 이동 크기로 판정한다). Fleet이 돌려주는 stamp는 바뀌지 않는다.

### v1.232 trip 읽기의 기다림 `wait.waiting`·`bound_s`·`over_bound` (D-763 조각 2, 8항)

`GET /api/fleet/trips`·`/api/fleet/trips/{trip_id}`의 trip view에 이미 있는 `wait {reason, since, …}`에 필드 셋을 더한다(additive). Fleet trip 정체 시계(`ledger/trip_progress.py` `_waiting`)가 판정할 때마다 그 답을 그대로 적는다. 화면의 기다림 표시와 정체 시계가 같은 판정을 쓴다(D-763 8항). `waiting`: 참이면 기다림이고 정체 시계가 가지 않는다. `bound_s`: 지금 사유의 상한 초(`link_wait`·`authority`는 trip lease `ttl_s`, `signal`은 `stall_s`, `crosswalk_look`·`crosswalk_wait`·`crosswalk_held`는 15 s; 모르는 사유는 null). `over_bound`: 규제나 `link_wait`가 지금 보고되는 동안, 이 기다림(첫 사유부터 한 번, 사유가 바뀌어도 이어짐)이 상한을 넘었다. 보고가 그치면 `waiting`·`over_bound` 모두 거짓이다. 이때부터 정체 규칙이 다시 돌고, 관제는 주의 행 `대기 상한 넘음 · <사유>`로 보인다. D-763 개정 2 질문 7: 상한을 넘은 기다림은 먼저 막힘 해결기(D-622)로 가고, 개입은 해결기가 사람에게 넘길 때만이다. `reason`은 CORE `line_follow.regulation_wait`(v1.227) 값 또는 `link_wait`(D-760 4항)이다. `stall_m`만큼 나아가면 규제 기다림은 사라진다(`wait` 키 없음). `since`는 Fleet 단조 시계라 화면이 쓰지 않는다. 세 키는 tick마다 판정할 때 한 번에 쓴다. 판정이 돌지 않은 tick(교차로 동작 중, hold, 그 앞의 종료)이 끝나면 null(모름)이다. tick 도중의 읽기는 앞 tick의 답을 본다. `GET /api/fleet/work`에는 trip 행이 아직 없다(D-763 조각 4). 옛 view는 세 키가 없다.

### v1.231 교차로 회전의 지도 출구 방향 (D-759 개정 1)

`POST /api/v1/line-follow/junction`의 `map_entry`(v1.224)를 `turn_deg`가 있는 `left`·`right`에도 싣는다. 회전 목표를 진입 yaw + `turn_deg`가 아니라 지도의 출구 차로 방향에 두기 위한 값이다. 능력 `base_velocity.lane_turn_map_entry`가 참인 CORE에만 보낸다. 그 능력은 CORE 설정 `line_follow.turn_map_entry_enabled`(bool, 기본 `false`)가 켜져 있고 `junction_turn`이 참일 때만 참이다. 설정이 꺼진 CORE는 받은 `map_entry`를 쓰지 않는다(`disabled`). 없는 지시와 설정이 꺼진 CORE의 회전은 이 필드가 없을 때와 같다.

필드와 범위는 v1.224와 같고 `yaw_rad`만 뜻이 다르다: 출구 차로가 교차로 장소에서 시작하는 방향(지도 좌표)이다. `straight`·`stop`이나 `turn_deg` 없는 `left`·`right`에 실으면 400 `VALIDATION_ERROR`다. CORE는 받은 때 굽이와 같이 그 방향을 odom으로 옮겨 둔다(`odom yaw + yaw_rad − pose_yaw_rad`). 교차로에 서서 회전을 시작할 때 그 방향이 오늘의 목표(진입 yaw + `turn_deg`)에서 15° 안이면(재획득 한도 30°의 절반) 목표를 그 방향으로 둔다. 목표가 180°를 넘어도 회전 방향은 `turn_deg`의 부호 그대로다. 회전 규칙(정지 확인, 5° 안 정착, 시간 상한), `advance_m`, 재획득은 그대로이고 재획득의 30° 비교도 그 목표를 쓴다. 쓰지 못하면 지시를 거절하지 않고 오늘의 목표를 쓰며 까닭을 `line_follow.junction.map_entry_reason`에 남긴다(`none_sent`·`disabled`·`stale`·`future`·`no_sample`·`epoch`·`carry`·`heading`, 뜻은 v1.224와 같고 `heading`은 오늘의 목표와 15° 초과, `epoch`는 받은 뒤 odom 실행이 바뀜). `map_entry_used`는 회전 목표가 지도 방향일 때만 참이다. 이제 `turn_deg`가 있는 `left`·`right`에서도 이 두 필드가 채워진다. Fleet은 능력이 참이고 이번 주기에 로봇을 찾은 지도 자세에 `odom_stamp`가 있을 때만 싣는다. SOURCE와 호스트 단위 시험까지이며 SIM·장치 수용은 하지 않았다.
### v1.230 승인 대기 작업의 거절 `POST /api/fleet/missions/{mission_id}/reject` (D-763 조각 5·5b)

새 경로(additive). 본문은 admit과 같은 `FleetWorkDecisionRequest` `{expected_generation}`(bool을 뺀 0 이상 정수, 다른 키 거절)다. 이름 있는 운영자만(viewer·공유 콘솔 토큰·자격 없는 루프백은 403 `OPERATOR_IDENTITY_REQUIRED`/`FORBIDDEN`). 누가 볼 수 있고 결정할 수 있는지는 admit과 같은 단계 종류 등록부(`step_action_kinds`) 판정이다: 두 사람 종류(`CELL_TRANSFER`, Cell Job)는 이름 있는 운영자 누구나, 제안자만 종류(레거시 `PICK_PLACE`)는 제안자만이고 다른 사람에게는 404 `MISSION_NOT_FOUND`다. 제안자가 하면 `decision: WITHDRAWN_BY_PROPOSER`, 다른 운영자가 하면 `REJECTED_BY_OPERATOR`이고 행위자는 감사 행에 남는다. 결과: Cell Job은 status `HOLD`, reason `CANCELLED_BY_OPERATOR`(취소와 같은 끝 상태 — resume·cancel·admit 모두 거절, 사건 `CELL_JOB_REJECTED`에 `decision`), 레거시 Mission은 status `CANCELED`, reason이 `decision`(사건 `MISSION_REJECTED`). claim을 잡지 않는다. 응답 `{proposal, mission, decision}`. 거절: 아직 resolve 전 409 `PROPOSAL_NOT_RESOLVED`; `PROPOSED`가 아님(이미 승인·거절됨 — 두 번째 거절도 여기) 또는 `expected_generation`이 지금 정지 세대와 다름 409 `MISSION_REJECT_REFUSED`(`message`); Cell 원장 없음 503 `CELL_JOB_JOURNAL_UNAVAILABLE`; resolve된 원장 단계의 종류가 등록부에 없음 409 `APPROVAL_RULE_UNREGISTERED`(admit도 같다). 승인 값은 resolve된 원장 단계 종류들 가운데 가장 엄한 것이다. 대화 요청에 연결된 작업을 거절하면 기존 결과 회신 경로가 요청자에게 알린다(Mission `CANCELED`, Cell Job `HOLD`). 정지 중(dispatch 꺼짐)에도 거절은 된다. admit의 승인 판정은 같은 등록부에서 오고 코드와 순서는 그대로다(`CELL_JOB_APPROVER_MUST_DIFFER_FROM_PROPOSER` 403, `PICK_PLACE` 비제안자 404). admit 본문 모델 이름이 `FleetWorkDecisionRequest`로 바뀌었고 받는 값은 같다.

### v1.227 로봇을 세운 규제 `line_follow.regulation_wait` (D-760 개정 3 9항)

`GET /api/v1/line-follow`와 상태 스냅숏 `line_follow`에 선택 필드 `regulation_wait`를 더한다(additive). 값은 `authority` | `signal` | `crosswalk_held` | `crosswalk_wait` | `crosswalk_look` | null이다. CORE 2b 도우미(`crosswalk/gate.py` `_regulation_wait`)가 기동·호 시계를 세울 때 쓰는 판정 그대로다. `authority`: 강제 중인 D-517 통행권이 `FREE`가 아니다. `signal`: D-525/D-620 교차로 신호를 기다린다(응답 없음, 적색, unknown, 만료, `may_enter` 없는 녹색). `crosswalk_held`: D-573 건너는 중 앞의 반사로 섰다. `crosswalk_wait`: 보기 창이 사람·unknown·stale로 막혔다(`state: waiting`). `crosswalk_look`: 보는 중(`state: looking`). 여럿이면 우선순위 `authority` > `signal` > `crosswalk_held` > `crosswalk_wait` > `crosswalk_look`이다. line-follow가 꺼졌거나 규제가 세우지 않으면 null이다. Fleet은 정체 판정에서 `reason` 문자열을 다시 풀지 않고 이 필드를 읽는다. 옛 CORE는 키가 없다. 다른 필드와 동작은 그대로다.

### v1.226 통행권: 5초, 명시적 줄이기, 순서, trip 임대 중 강제 (D-760 1–3항)

`POST /api/v1/line-follow/authority`(D-517 4항)의 계약을 넓힌다. 추가 필드가 없는 요청의 동작은 v1.225와 같다.

| 무엇 | v1.225 | v1.226 |
|---|---|---|
| `ttl_s` | 0 < s ≤ 2 | 0 < s ≤ 5. 재는 시계는 그대로 CORE line-follow 시계다: 장치에서는 `time.monotonic`, `use_sim_time`에서는 시뮬레이션 시각. 벽시계가 움직여도 만료는 움직이지 않는다 |
| `shrink` | 없음 | bool, 기본 `false`. `true`면 끝을 `min(쥔 끝, 요청 끝)`으로 바꾸고 `ttl_s`를 갱신한다. `until_m: 0`은 "지금 자리에서 서라"다 |
| `seq` | 없음 | 정수 ≥ 0, 선택. (로봇, `leg_id`)마다 늘어난다. CORE는 같은 `leg_id`에서 마지막으로 본 `seq` 이하의 요청을 무시한다 |

- **줄이기.** `shrink: true`인 요청의 끝이 로봇의 정지 거리 d_stop(v) 안이면 다음 틱에 `HOLDING`·`authority_end`로 선다. 줄이기는 통행권을 주지 않는다: 같은 `leg_id`·같은 odom 궤적의 만료되지 않은 통행권을 쥐고 있지 않으면(없음, 만료, 다른 `leg_id`, 다른 궤적) 응답은 200 `accepted: false`, `reason: shrink_none_held`이고 CORE는 쥐고 있던 통행권도 버린다(`NONE`, 로봇은 선다). 송신자는 이 답을 "로봇이 통행권 없이 서 있다"로 읽는다. 요청 끝이 쥔 끝보다 멀면 쥔 끝을 두고 `ttl_s`만 갱신한다. `shrink`가 없거나 `false`인 작은 끝은 v1.225와 같이 무시된다(`accepted: false`, `reason: shrink`, `ttl_s` 갱신 없음).
- **거절되면 선다.** `shrink` 요청도 409 `AUTHORITY_ODOM_STALE`·`AUTHORITY_POSE_STALE`·`AUTHORITY_POSE_FUTURE`로 거절되면 쥔 통행권을 버린다.
- **순서.** `seq`가 같은 `leg_id`에서 마지막으로 본 값 이하면 응답은 200 `accepted: false`, `reason: stale_seq`이고 쥔 끝과 `ttl_s`는 그대로다. CORE는 `seq`를 받은 때(거절 판정 전)에 기억하므로, 거절된 줄이기보다 먼저 보낸 늘리기가 늦게 닿아도 받지 않는다. 기억은 `leg_id`마다 따로이고 최대 8개다. 다른 `leg_id`의 요청은 남의 기억을 바꾸지 않으므로, 옛 구간의 늦은 요청이 닿아도 새 구간의 순서는 그대로다. 통행권이 만료하거나 line-follow 모드가 바뀌어도 남는다(CORE 프로세스가 다시 뜨면 없다). CORE는 어떤 `leg_id`를 마지막으로 본 때가 odom 기록의 가장 오래된 표본보다 앞일 때만 그 기억을 지운다. 그 뒤에 닿는 그 구간의 늦은 요청은 `pose_stamp`가 기록보다 오래돼 409 `AUTHORITY_POSE_STALE`로 거절된다(로봇은 선다). 지울 수 없는 기억이 8개인데 새 `leg_id`가 `seq`를 실어 오면 200 `accepted: false`, `reason: seq_legs_full`이다. 어떤 `leg_id`에서 `seq`를 한 번이라도 본 뒤에는 그 구간의 `seq` 없는 요청을 무시한다(200 `accepted: false`, `reason: seq_required`, 쥔 끝과 `ttl_s`는 그대로). `seq`를 본 적 없는 구간의 `seq` 없는 요청은 v1.225와 같다. 줄이기를 쓰는 송신자는 모든 요청에 `seq`를 싣는다. line-follow 가 OFF면 `seq`를 보기 전에 409 `LINE_FOLLOW_NOT_ACTIVE`다.
- **trip 임대 중 강제.** CORE의 trip lease(D-541, `PUT /api/v1/trip-lease`)가 열려 있는 동안 line-follow는 쥔 통행권이 있어야 움직인다. 없으면 명령 0, HOLD `authority_none`이고 `GET /line-follow`의 `authority.state`는 `NONE`이다. 설정 `line_follow.authority_required`가 `false`여도, 이 세션에서 통행권 요청을 받은 적이 없어도, 모드를 바꾼 뒤에도 같다. 5 Hz 타이머가 아직 끝내지 않은 만료 임대도 열린 것으로 센다. 강제는 그 line-follow 세션에 걸린다: 임대가 열린 채 모드를 골랐거나 세션 중에 임대가 열린 것을 한 번 보면, 임대가 풀리거나 만료하거나 넘어간 뒤에도 모드를 바꿀 때까지 통행권을 요구한다(첫 통행권 전에 임대가 끝나도 로봇은 움직이지 않는다). 임대를 본 적 없는 세션에는 v1.225의 조건(설정 `authority_required` 또는 이 세션에서 받은 요청)만 남는다. 임대 없는 대시보드·스크립트의 차선 주행은 바뀌지 않는다. 임대는 메모리에만 있으므로 CORE가 다시 뜨면 임대도 강제도 없고, Fleet이 임대를 다시 열 때 돌아온다.
- **우선순위는 그대로다.** 통행권 판정은 그 틱의 최종 결정을 0으로 만들 수만 있다. D-422 몸체 정지, D-491 IR 가드, E-Stop은 결정을 먼저 0으로 만들고, D-400 집행 정책은 그 뒤 명령을 다시 0으로 만들 수만 있다.
- **능력.** `base_velocity.line_follow_authority_shrink`(bool): CORE가 `shrink`·`seq`와 5 s까지의 `ttl_s`를 받는다. `base_velocity.line_follow_authority_under_lease`(bool): 이 CORE가 trip 임대 중 통행권을 강제한다. 둘 다 없으면 거짓으로 읽는다. Fleet은 `line_follow_authority_shrink`가 참인 로봇에만 2 s를 넘는 `ttl_s`·`shrink`·`seq`를 보낸다(Fleet 쪽 송신은 D-760 3단계이고 이 버전에 없다).
- **호환.** `fleet.trip_lease_required: true`이면서 `fleet.traffic.authority: false`인 현장에 이 CORE를 올리면 lane trip 로봇은 통행권을 받지 못해 `authority_none`으로 서 있다. 그런 현장은 통행권을 같이 켠다.

### v1.225 굽이 다음 교차로 선까지의 거리 (D-754)

`POST /api/v1/line-follow/junction`의 `action: bend`에 선택 필드 `next_line_in_m`을 더한다. 굽이 통과 중에 잡힌 교차로 목격을 다음 교차로로 넘길지를 지도 거리로 가리기 위한 값이다. 능력 `base_velocity.lane_bend_next_line`이 참인 CORE에만 보낸다. 없는 지시의 동작은 v1.221과 같다.

| 필드 | 형식 | 뜻 |
| --- | --- | --- |
| `next_line_in_m` | finite number, m, 0 ≤ m ≤ 2 | 굽이 장소(꼭짓점)에서 이 trip이 굽이 다음에 닿는 교차로 장소의 가로선까지 차로를 따라 잰 거리. 2는 2 m 이상이다 |

범위 밖이거나 `bend`가 아닌 지시에 있으면 400 `VALIDATION_ERROR`다. CORE는 통과 끝에서 목격의 선 지점이 꼭짓점에서 출구선을 따라 `next_line_in_m`의 허용치 안에 있을 때만 그 목격을 넘기고 `waiting`으로 선다. 허용치는 `bend_tol_m` + `line_follow.crosswalk_range_error_fraction` × 목격의 `junction_ahead_m` + 0.10 m(차로 반폭)다. 밖이면 목격을 지우고 통과는 `idle`로 끝난다. 필드가 없으면 v1.221의 규칙(D-507 보충 8·9항) 그대로다. 응답과 상태 필드는 바뀌지 않는다.

`lane_bend_next_line`의 값은 `lane_bend`와 같다. Fleet은 능력이 참일 때, 꼭짓점에서 굽이 호 끝까지 `bend_radius_m`·tan(\|turn\|/2), 남은 경로에서 처음 나오는 간선 끝 장소까지의 경로 거리, 그 장소에서 차로 방향으로 처음 만나는 칠한 선까지의 거리(없으면 0)를 더해 0–2로 잘라 보낸다. 남은 경로에 간선 끝 장소가 없으면 보내지 않는다. trip 보기 `caps`에 `lane_bend_next_line`이 더해진다. SOURCE·호스트 시험까지이고 SIM·DEVICE 수용은 열려 있다.
### v1.224 굽이 통과의 지도 진입 방향 (D-759)

`POST /api/v1/line-follow/junction`의 `action: bend`에 선택 객체 `map_entry`를 더한다. 굽이 통과의 진입 직선을 로봇이 향한 쪽이 아니라 지도의 차로 방향에 놓기 위한 값이다. 능력 `base_velocity.lane_bend_map_entry`가 참인 CORE에만 보낸다. 그 능력은 CORE 설정 `line_follow.bend_map_entry_enabled`(bool, 기본 `false`)가 켜져 있고 `lane_bend`가 참일 때만 참이다. 설정이 꺼진 CORE는 받은 `map_entry`를 쓰지 않는다(`disabled`). 없는 지시와 설정이 꺼진 CORE의 동작은 v1.223과 같다.

| 필드 | 형식 | 뜻 |
| --- | --- | --- |
| `yaw_rad` | finite number, rad, \|yaw\| ≤ 6.2832, 지도 좌표 | 굽이의 호 시작점에서 차로가 향하는 방향(진입 직선의 방향) |
| `pose_yaw_rad` | finite number, rad, \|yaw\| ≤ 6.2832, 지도 좌표 | Fleet이 본 로봇의 지도 yaw |
| `odom_stamp_s` | finite number > 0, UTC epoch 초 | 그 지도 자세가 묶인 odom 표본의 시각. `exit_segment.map_anchor.odom_stamp_s`(v1.221)와 같은 값이다 |

세 값이 모두 있어야 한다. 어기거나 `bend`가 아닌 action에 실으면 지시 전체가 400 `VALIDATION_ERROR`다. CORE는 지시를 받은 때 자기 odom 기록에서 `odom_stamp_s`의 표본을 찾아 차로 방향을 odom으로 옮겨 둔다(`odom yaw + yaw_rad − pose_yaw_rad`). 통과가 넘겨받을 때 닻의 yaw(곧게 추종하던 마지막 틱의 로봇 yaw)가 그 방향에서 30° 안이면 진입 직선을 그 방향으로, 로봇이 그때 선 자리에서 놓는다. 호와 나가는 직선도 그 방향에서 나온다. 호 시작점까지의 거리 셈(`bend_in_m`에서 받은 뒤 odom 이동 거리를 뺀 값), `bend_tol_m`·`bend_radius_m`, 앞당김 창, 중단 규칙은 v1.223과 같다. 다음 가운데 하나면 지시를 거절하지 않고 v1.223처럼 로봇 자신의 yaw를 쓴다: 설정이 꺼짐, 받은 때 `odom_stamp_s`가 2 s보다 오래됐거나 CORE 시계보다 0.05 s 넘게 앞섬, 그 시각의 odom 표본이 기록에 없음, odom epoch·frame이 그 표본과 다름, 받은 뒤 odom 경로 길이(부호 없는 합) 1.5 m 초과, 넘겨받을 때 닻의 yaw가 그 방향에서 30° 넘게 어긋남. `armed` 중의 재전송은 이미 둔 방향을 바꾸지 않고, 두지 못했던 방향만 다시 옮긴다. 횡 위치는 옮기지 않는다. 경로는 로봇이 선 자리를 지나 차로와 나란히 놓인다. Fleet 지도 yaw의 오차는 그대로 진입 직선의 방향 오차가 된다(D-759 한계 8).

`line_follow.junction`에 `map_entry_used: bool`과 `map_entry_reason: string\|null`을 더한다. `map_entry_used`는 그 통과의 닻이 지도 방향으로 놓였을 때만 참이다. `map_entry_reason`은 쓰지 않은 까닭이다: `none_sent`(지시에 없음), `disabled`(설정이 꺼짐), `stale`(2 s 초과), `future`(CORE 시계보다 앞섬), `no_sample`(그 시각의 odom 표본이 없음), `epoch`(odom epoch·frame이 다름), `carry`(경로 길이 초과), `heading`(30° 초과). 썼으면 null이고, 방향을 두었지만 아직 넘겨받지 않은 `armed`에서도 null이며, `bend`가 아닌 지시에서는 false와 null이다. Fleet은 능력이 참이고 이번 주기에 로봇을 찾은 지도 자세에 `odom_stamp`가 있을 때만 `map_entry`를 싣는다. SOURCE와 호스트 단위 시험까지이며 SIM·장치 수용은 하지 않았다.

### v1.223 집행 정책의 짧은 센서 끊김은 HOLD다 (D-400 4항)

안전 정책 모드가 `enforce`일 때의 동작과 상태 필드 하나가 바뀐다. `off`와 `shadow`의 출력은 그대로다.

- 동작: 0이 아닌 명령에 대해 정책의 근거나 답이 제때 없으면(평가기가 아직 묶이지 않음, 정책에 지금 쓸 관측이 없음, 형식이 맞는 판정이 늦었거나 근거 lease 밖) CORE는 그 틱에 명령 0을 내보내고 E-stop을 걸지 않으며 모드도 바꾸지 않는다. 유효한 판정이 다시 오면 스스로 재개한다. 끊김이 `control.sensor_adapter.stale_hold_s`(기본 2 s, (0, 5])에 닿으면 전과 같이 `safety.estop` `source: "control:<사유>"`로 래치한다. `stop` 판정, 형식이 틀리거나 요청과 맞지 않는 판정, 평가기의 다른 예외는 전과 같이 바로 래치한다.
- 답 시간 상한: 정책 답은 `/cmd_vel` 타이머 한 주기(50 Hz, 20 ms) 안에 와야 한다. 전에는 10 ms였다. 근거의 나이 조건(`observed_at ≤ now ≤ expires_at`, lease 폭 ≤ 0.5 s)은 그대로다.
- 필드: `safety_policy.hold` `{count, reason}`. `enforce`에서만 실린다(아니면 `null`). `count`는 CORE 시작 뒤 HOLD로 답한 끊김의 수, `reason`은 가장 최근 HOLD 틱의 정책 사유(`policy_failed` \| `policy_invalid`, 없었으면 빈 문자열)다. 평가기가 묶이기 전의 `policy_unavailable`은 HOLD가 되지 않는다. 지금 HOLD 중인지를 뜻하지 않는다.

### v1.222 거절된 한 틱은 교차로 기동을 버리지 않는다 (D-740 개정 3)

`GET /api/v1/line-follow`의 `reason`에 `junction_motion_unconfirmed`(HOLD)가 더해진다. 교차로 기동(접근, 회전, 전진, 굽이 통과와 그 재획득) 중에 운동 증명이 그 틱의 twist를 거절하면 CORE는 명령 0으로 서서 기동을 유지한다. 처음 거절된 때부터 `min(clearance_stale_s, 0.5 s)`를 넘겨 승인 없이 이어지면 전과 같이 `aborted`·`motion_unconfirmed`다. 요청과 응답의 필드는 바뀌지 않는다. 근거가 아예 없을 때(`turn_basis_lost`, `bend_basis_lost`)의 즉시 중단은 그대로다.

### v1.221 차로 호의 지도 고정 (D-744)

`POST /api/v1/line-follow/junction`의 `exit_segment`에 선택 객체 `map_anchor`를 더한다. 호의 원을 로봇이 선 자리가 아니라 지도에 놓기 위한 값이다. 능력 `base_velocity.lane_arc_map_anchor`가 참인 CORE에만 보낸다. 없는 지시의 동작은 v1.220과 같다.

| 필드 | 형식 | 뜻 |
| --- | --- | --- |
| `centre_x_m`, `centre_y_m` | finite number, m, 지도 좌표 | 그 구간에 맞춘 원의 중심 |
| `pose_x_m`, `pose_y_m` | finite number, m, 지도 좌표 | Fleet이 본 로봇의 지도 위치 |
| `pose_yaw_rad` | finite number, rad, \|yaw\| ≤ 6.2832 | 같은 자세의 방향 |
| `odom_stamp_s` | finite number > 0, UTC epoch 초 | 그 지도 자세가 묶인 odom 표본의 시각. CORE가 odom을 받은 때의 CORE 벽시계이고 스냅숏 `odom_pose.stamp`, `POST /line-follow/authority`의 `pose_stamp`와 같은 값이다 |

여섯 값이 모두 있어야 하고, 어기면 지시 전체가 400 `VALIDATION_ERROR`다. CORE는 지시를 받은 때 자기 odom 기록에서 `odom_stamp_s`의 표본을 찾아 그 쌍으로 원 중심을 odom으로 옮겨 두고, 호가 열릴 때 그 원을 쓴다(접선은 그때 자세에서 그 원의 접선). 다음 가운데 하나면 지시를 거절하지 않고 v1.220의 자세 기준 원을 쓴다: 받은 때 `odom_stamp_s`가 2 s보다 오래됐거나 CORE 시계보다 0.05 s 넘게 앞섬, 그 시각의 odom 표본이 기록에 없음, odom epoch·frame이 그 표본과 또는 받은 뒤에 달라짐, 받은 뒤 odom 경로 길이(부호 없는 합) 1.5 m 초과, 호가 열릴 때 로봇이 그 원에서 0.045 m 넘게 떨어짐(호를 멈추는 0.075 m보다 작다), 호가 열릴 때 방향이 그 원의 접선에서 25° 넘게 어긋남. 앞 호의 원을 물려받는 `straight`도 새 `map_anchor`가 있으면 그것을 쓴다. 다만 앞 호가 IR 한 번 보정을 썼으면 칠한 선에 맞춘 그 원을 물려받는다.

`line_follow.arc`에 `map_anchor_used: bool`과 `map_anchor_reason: string\|null`을 더한다. `map_anchor_used`는 그 호가 지도 고정 원으로 열렸을 때만 참이다. `map_anchor_reason`은 쓰지 않은 까닭이다: `none_sent`(지시에 없음), `malformed`(값이 없거나 유한한 수가 아님), `stale`(2 s 초과), `future`(CORE 시계보다 앞섬), `no_sample`(그 시각의 odom 표본이 없음), `epoch`(odom epoch·frame이 다름), `carry`(경로 길이 초과), `radial`(원에서 멂), `heading`(접선에서 어긋남), `ir_chain`(IR 보정한 앞 원을 물려받음). 썼으면 null이고, 원을 놓기 전에 멈춘 호(`lane_arc_pose_lost`)도 null이다. Fleet은 능력이 참이고 이번 주기의 지도 자세가 LOCALIZED이며 `odom_stamp`가 있을 때만 `map_anchor`를 싣는다. SOURCE와 호스트 시험까지이며 SIM·장치 수용과 구분한다.

### v1.220 CORE native outcome ports (D-732)

`POST /api/v1/safety/stop`은 본문 없는 Viewer 호출과 `{estop:true}`를 유지하고 `operations:NativeOperation[]`을 추가한다. 각 native owner(nav/home, dock/undock, follow, teleop)의 기존 잠금을 기다리지 않고 획득하여 stop 직전 current nonterminal run과 boot를 따로 캡처한다. 잠금 경합이나 캡처 실패는 전체 `operations:[]`로 남기고 기존 E-Stop latch를 먼저 적용한다. backend·transport·중첩 잠금 조회는 이 선택적 캡처에 넣지 않는다. 정지 listener 이후에도 같은 nonblocking 경계에서 캡처한 UUID만 읽는다. 첫 terminal은 그대로 반환하며 잠금 경합·lookup UNKNOWN·prune·재부팅·readback 실패에서는 원래 pending receipt를 보존한다. 다른 최신 run이나 terminal 이력을 대신 넣지 않는다. 선택적 증거 읽기는 E-Stop을 늦추지 않는다. 빈 목록은 ACK뿐이며 물리적 정지 성공이 아니다. site stop은 `robots[].result.operations`에 로봇별 목록을 그대로 유지한다.

`operations`는 owner별로 순차 캡처한 정지 직전의 best-effort snapshot이다. 캡처와 latch 사이의 동시 owner 변경을 포함하는 전체 실행 목록이나 로봇의 물리적 정지 증명이 아니다.

Fleet channel stop step의 receipt는 `stop_outcomes:[{robot_id, operation:NativeOperation, outcome?:NativeOperation, quiescence?:NativeQuiescence}]`로 각 run을 보존한다. `operation`은 원래 캡처한 식별자, `outcome`은 변경할 수 없는 첫 terminal, `quiescence`는 같은 로봇·boot·run의 새 owner readback이다. 모든 캡처 run에 exact terminal과 RPC 시작부터 step CAS까지 2초 이내의 quiescence가 있어야 step을 CANCELED로 닫는다. 빌린 claim을 해제하거나 다음 동작을 진행하지 않으며 SAFE_RELEASED나 물리적 정지를 주장하지 않는다. 누락·빈 목록·부분 site ACK는 유한한 HOLD/ACK-only로 끝낸다. native 식별자 없는 idle cancel/follow_cancel ACK도 유한한 HOLD이며, 이후 계획을 진행하지 않는다.

SOURCE 계약 검토 중이다. 배포·장치 수용과 구분한다. CORE의 기존 실행 owner와 최종 cmd_vel 권한, envelope protocol_version 1.0을 유지한다.

| 기존 명령 | 선택적 추가 본문 | 승인 응답 추가 필드 / owner |
| --- | --- | --- |
| POST `/api/v1/navigation/goal` | 기존 correlation_id/lease_ttl_s 유지 | `operation`, NavigationManager 승인 잠금에서 캡처 |
| POST `/api/v1/navigation/home` | `{correlation_id?: string(1..128), lease_ttl_s?: finite number(0,5]}`; lease는 CID 필요; 본문 생략 유지 | `operation`, 기존 goal에 kind=home으로 전달하여 단 하나의 run 생성 |
| POST `/api/v1/docking/dock` | 기존 dock + `correlation_id?: string(1..128)` | 기존 DockingStatus + captured `operation` |
| POST `/api/v1/docking/undock` | `{correlation_id?: string(1..128)}`; 본문 생략 유지 | 기존 DockingStatus + captured `operation` |
| POST `/api/v1/swarm/follow` | 기존 SwarmFollowParams + `correlation_id?: string(1..128)` | 기존 응답 + captured `operation` |
| POST `/api/v1/teleop` | 기존 linear/angular + `correlation_id?: string(1..128)` | 기존 accepted + captured `operation`; 단발 watchdog pulse이며 거리 달성은 아님 |

`operation`은 CORE 생성 UUID `run_id`, process UUID `boot_id`, kind(navigate/home/dock/undock/follow/teleop), 선택적 correlation_id, phase(SUBMITTED/RUNNING/TERMINAL), result(null/SUCCEEDED/FAILED/CANCELED/PREEMPTED/EXPIRED), reason(null 또는 최대64자 고정 uppercase machine code)를 갖는다. SUBMITTED/RUNNING은 result=null, TERMINAL은 result 필수다. admission 거절은 기존 오류이며 operation을 생성하지 않는다. CID 재사용도 새 native run이다. CID는 admission·멱등·retry 권한이 아니다. API는 잠금 밖 최신 상태를 재조회하여 원래 RPC receipt를 만들지 않는다.

GET `/api/v1/navigation/state`, `/api/v1/docking/status`, `/api/v1/swarm/state` 및 새 viewer GET `/api/v1/teleop/state`에 선택적 UUID query `run_id`를 추가한다. query가 없으면 현재 또는 가장 최근 operation, 있으면 정확히 일치하는 current/최근32 terminal만 반환한다. `lookup:FOUND|UNKNOWN`과 `operation`을 추가하며 missing/pruned/reboot identity는 UNKNOWN/null이다. 최신 다른 run으로 대체하지 않는다. 기존 snapshot 필드를 유지한다. 기존 event/audit 포트는 같은 run_id/boot_id를 포함한 종결 이벤트를 전달한다. 감사 보존은 기존30일/no per-event fsync와 FleetCoreEventStore 규칙을 따른다. 영구 실행 복원·자동 재발행은 하지 않는다.

readback `quiescence`는 `boot_id`, `owner_run_id:null|UUID`, `requested_run_id:UUID`, `observed_at:UTC`, boolean `admitting`, `pending_submission`, `actuating_callback`, `lease_active`, `quiescent`를 갖는다. 실제 native owner와 transport generation의 잠금 경계에서 읽으며 요청 run이 동일 boot의 retained terminal, 현재 owner 없음, 네 실행 가능성 모두 false일 때만 quiescent=true다. 조회 identity나 자료가 없으면 null이다. 일반 IDLE·0 velocity·만료된 lease 시각만으로 증명하지 않는다. Fleet의 exact robot/boot/run/claim generation CAS에만 사용한다. SAFE_RELEASED는 완료나 후속 이동 권한이 아니다.

proof에 단조 증가 `owner_generation`과 `transport_generation`을 포함한다. 승인·취소·종결·lease 변경과 backend pending/handle/callback 변경이 generation을 증가시킨다. 각 잠금의 전후 generation이 변하지 않은 관측만 proof로 반환한다. Fleet의 RPC 시작부터 local SAFE_RELEASE CAS까지 monotonic 최대2초로 제한한다. remote owner와 Fleet DB의 원자적 transaction을 주장하지 않는다. 이후 새 motion은 새 readback·원문·현재 권한·CORE gate를 다시 검증한다.

위 명령의 선택적 `expected_owner_generation: nonnegative integer`는 `expected_boot_id: UUID`와 함께만 사용할 수 있다. 기존 owner의 실제 승인 잠금 또는 Mode commit 안에서 side effect 전에 비교하여 불일치면409 `OWNER_GENERATION_CHANGED`다. fields가 없으면 legacy admission 동작을 유지한다. Fleet는 SAFE_RELEASE 이후 새 motion에 최신 native CAS를 사용하고 다른 owner/mode/lease 배타 gate도 유지한다. proof나 종결 receipt 자체가 motion grant가 되지 않는다.

readback의 항상 존재하는 `owner` 객체는 현재 `boot_id:UUID`, `owner_generation:nonnegative integer`, `owner_run_id:null|UUID`를 반환한다. lookup UNKNOWN/empty first boot에도 제공하되 unknown run의 quiescence를 증명하지 않는다. expected epoch 검증부터 mode 전환·제출까지 실제 승인 구간에 결속하고 기존 실제 잠금 순서(docking owner→mode, mode listener는 lock 밖)를 보존한다. mode 변경 전 owner 잠금에서 CAS와 admitting reservation을 확정하고 mode 전환은 owner lock 밖에서 수행하며 실제 제출 구간에서 같은 reservation을 다시 검증한다. 경쟁 취소는 reservation을 철회해 제출을 막는다. 처음 CAS가 불일치한 요청은 mode를 바꾸지 않는다.

native terminal은 첫 확정 이후 불변이다. backend 거절 FAILED/BACKEND_REJECTED, 알려진 backend 오류 FAILED/BACKEND_ERROR, lease 만료 EXPIRED/LEASE_EXPIRED, 명시적 취소 CANCELED/CANCELED, 안전 취소 CANCELED/SAFETY_STOP, stuck FAILED/STUCK으로 구분한다. 제출·결과 exception의 전달 여부가 불명이면 nonterminal/result=null, reason=BACKEND_RESULT_UNKNOWN을 유지한다. UNKNOWN은 lookup/evidence 분류이며 phase가 아니다. 검증된 owner 실패만 BACKEND_ERROR로 종결하고 통신 불명을 성공·실패로 바꾸지 않는다. navigation callback은 actual backend generation에 캡처한 identity를 사용한다. 도킹·undock 성공과 취소는 별개이며 충전 관측이 terminal을 다시 쓰지 않는다. follow hold는 RUNNING, re-follow 이전 run은 PREEMPTED다. 별도 현재 권한의 cancel/stop은 실제 닫은 이전 run receipt를 반환하며 concurrent 새 run으로 대체하지 않는다. watchdog 종료는 teleop EXPIRED이며 물리 거리 성과가 아니다. 원래 grant 만료·철회 뒤에도 terminal을 읽어 원장에 확정할 수 있지만 새 명령은 발행할 수 없다. 기존 manager 반환형·keyword 없는 executor·auth/capability/localization/calibration/readiness/mode/CORE writer/E-stop 해제 금지 계약을 유지한다.

### v1.219 경로 사실 묶음 (D-726)

`POST /api/fleet/robots/{robot_id}/trip`과 `POST /api/fleet/robots/{robot_id}/route`의 200 응답에 `context`를 더한다. `role`은 `fact`다. 이 객체는 명령이 아니고 `command`·`decision`이나 WAIT/YIELD/RESUME/ABORT/MANUAL을 담지 않는다. AI나 다른 시스템은 이 사실을 읽고 후보를 돌려 줄 수 있다. Fleet이 계획하고 CORE가 움직인다.

`planner`는 이 답을 만든 계획기다. `supplied`는 호출자가 채운 값이다. `holds`는 그 계획기가 잡은 결과다. `planners`의 각 항목은 `id`, `live`(Fleet이 그 계획기를 돌리는지), `motion`, `give`(받는 필드), `note`다.

- `lane_graph`: live, `line_follow`, give `to`·`via`·`arrive_yaw`·`speed_cap`·`blocked_edges`·`extra_cost`, note `plan_only`. 계획만 반환한다.
- `lane_step`: live, `short_point`, give `edges`, note `one_point_goal`. 저장된 차로를 따라 짧은 점 하나다.
- `nav2`: live false, `open_floor`, give `x`·`y`·`yaw`, note `not_this_runtime`.
- `grid`: live false, `occupancy`, give `goal`, note `not_this_runtime`.

trip의 선택 `blocked_edges`(차로 id, 최대 32, 중복 없음)와 `extra_cost`(차로 id → 0 이상 유한 초, 최대 32)는 그 계획에 들어간다. 없는 차로 id는 422 `TRIP_UNKNOWN_EDGE`와 `detail.edge`다. 막힌 차로 옆에 다른 차로가 있으면 그 경로를 반환하고, 남은 차로가 없으면 기존 422 `TRIP_NO_ROUTE`다. 재계획은 이 차단을 교통 차단과 합치고 비용을 유지한다. 빈 값은 오늘과 같은 경로다. `context`는 실행 plan 안에 넣지 않고 plan 옆에 기록한다.

`/route`의 다음 점은 보통 0.20 m다. 그 현이 공칭 차체를 가져온 차로 밖으로 내보내면 0.12 m까지 줄이며, 0.10 m 장치 목표 공보다는 길다. 남은 거리가 0.12 m 이하면 끝을 유지한다. 링의 0.20 m 현은 차체 여유 안이라 줄이지 않는다. 이 단축은 점 목표만 해당하고 차로 운행의 선 추종이나 링 주행 수용을 바꾸지 않는다. `holds`는 `complete`, `step_m`, `chord_m`, `body_clear_m`, `body_inside`, `s_m`이다. envelope 1.0과 CORE API는 유지한다.

### v1.219 Discord 읽기 전용 숙고 결과 (D-720)

선택 private broker 설정과 기존 기명 Discord 접수·회신이 구성된 경우 `GET /api/fleet/channel-requests/{request_id}/deliberation`은 원문 소유 operator에게 `ChannelModelResult`를 반환한다. 설정 부재·작업 부재는 404, 원문 계정·채널 소유권 변경은 403이다. 필드는 request_id, state(PENDING/RUNNING/ANSWERED/HOLD/UNKNOWN/SUPERSEDED), profile_set_hash, input_hash, created_at, deadline, completed_at, result, action_admissible(false)다. result는 bound 모델 ID·판단·비용 증빙 또는 보류 사유이며 실행·목표 수용이 아니다. 원문을 CORE 사건으로 승격하지 않고 fleet_status/READ_ONLY_QUERY 및 channel 범위 읽기 tool만 허용한다. 영속 호출 예약·UNKNOWN 재호출 금지·현재 관측/계정/profile 재검증·결과와 Discord outbox 원자 기록을 지킨다. 최초 활성화 이전 요청은 재생하지 않는다. 보호된 숙고 모델·비용·host 증빙 없이는 HOLD이며 GLM 최초 1회 spent marker는 배포·rollback에도 유지한다.

### v1.218 CORE 조건부 막힘 답 (D-718)

선택 상태 필드 `line_follow.stuck.conditional_back`은 이 CORE의 조건부 BACK 지원 여부다. 신형 CORE는 true, 이전 데이터의 누락은 false다. 조건을 사용하는 Fleet HttpRobotClient는 먼저 GET `/api/v1/line-follow`에서 명시적 true를 확인하며 없거나 false이면 POST하지 않는다. 지원 여부는 안전·운영 수용·현재 사건 조건 검증을 면제하지 않는다.

POST `/api/v1/line-follow/stuck/decision`의 BACK_AND_RETRY에 선택 `expected_stuck: {phase: "ASKING", attempts: nonnegative strict integer}`를 받는다. 두 필드는 필수이고 추가 키·다른 phase·bool/문자열/음수 attempts는 400 VALIDATION_ERROR다. 다른 decision에 조건을 붙이면 400 VALIDATION_ERROR다. CORE는 stuck_id와 현재 phase/attempts를 기존 manager lock 아래에서 검증하며 조건 불일치는 409 STUCK_DECISION_REFUSED(`stuck_precondition_failed`)로 거절한다. 거절은 타이머·시도 수·현재 복구를 바꾸지 않는다. 기존 조건 없는 요청과 WAIT/ABORT는 유지한다. 조건 일치는 기존 안전/권한 검사를 면제하지 않으며 모델 운영 수용도 아니다. envelope protocol_version은 1.0 유지다.

### v1.217 Fleet 관측 capture 기록 범위 (D-699)

`GET /api/fleet/observations`의 기존 응답과 cursor를 유지한다. 새 source에서 저장한 `observation.capture`는 선택 `{run_id: UUID hex, sequence: positive integer, monotonic_at: finite number, robot_ids: sorted unique IDs}`다. 이전 행은 이 필드가 없다. 같은 append snapshot은 동일 capture를 가지며 실패·빈 roster 다음 성공의 sequence gap과 저장소 인스턴스 재시작을 구분한다. roster는 최대 1,024행이고 기존 64KiB payload·retention 한도를 유지한다. 저장 시도 metadata이므로 console snapshot 이전 실패·CORE 명령·모델 호출·재발 없음·독립 정답을 입증하지 않는다. 운영 활성화·현장 수용은 별도다.

### v1.215 병렬 계약 통합

D-686/D-689의 초기 비밀번호 변경·본인 프로필과 D-671/D-680/D-687/D-693의 Discord 접수·검토·기존 작업 및 사건 연결을 함께 적용한다. 병렬 브랜치의 v1.210/v1.211 기록은 당시 계약 증거로 보존한다. 현재 보호된 Console 요청은 초기 쿠키의 PASSWORD_CHANGE_REQUIRED 제한과 비밀번호 변경 후 세션 무효화 규칙을 따른다. Discord transport 인증은 기명 접수만 담당하며 Console 실행 승인 자격을 대신하지 않는다. Robot API/envelope 버전과 CORE 최종 명령 권한은 유지한다.

### v1.212 Rosy Cam은 요청이 있는 동안만 보낸다 (D-691)

`rosy-overhead/1` 하향 `demand`는 `{"type":"demand","wanted":bool}`이다. 유효한 Vision preview lease로 `frame`, `field-proposal`, `map-proposal`을 읽으면 그 source를 30초(`stream_hold_s`) 동안 송출하게 한다. 프레임이 없거나 오래됐거나 429여도 요청이다. 401은 요청이 아니다. 폰은 소켓을 유지한 채 `wanted:false`에서 센서와 JPEG를 멈춘다. 열 상태가 SEVERE 이상이거나, 열 상태를 모를 때 배터리 45°C 이상이면 요청보다 먼저 같은 정지를 하고, LIGHT 이하 또는 배터리 41°C 이하에서 다시 따른다. 이전 앱은 `demand`를 무시하고 계속 보낸다. 자세한 결정은 D-691이다.

### v1.211 본인 기본 프로필 (D-689)

GET `/api/fleet/auth/profile` returns `login`, `principal_id`, `email` (null for non-email principals), `role`, `display_name` for a valid completed cookie login only. PATCH accepts exactly `display_name`: trim whitespace, 1..80 characters, reject control characters. ID, email and role are read-only. Success is 200 with the same profile shape and no-store. Profiles persist in existing SQLite bound to login+principal and survive password rotation and restart. Reassigned principals do not inherit names. Initial cookies remain 403 PASSWORD_CHANGE_REQUIRED; Bearer/development credentials are 403 COOKIE_SESSION_REQUIRED. No arbitrary account selection is accepted.

POST `/api/fleet/auth/change-password` additionally accepts normal cookies with exactly `current_password` and `password`. The current password must match; a mismatch is 422 CURRENT_PASSWORD_INCORRECT without revoking the session. A new password is 8..1024 characters and differs from ID and the current password. Initial cookies still accept only `password`. Existing same-origin CSRF, source binding, atomic replacement cookie, prior-session revocation, rate/capacity limit and rollback behavior apply. Invalid input is 422 INVALID_REQUEST; stale or raced sessions are 401 UNAUTHORIZED; unavailable DB is 503 SESSION_STORAGE_UNAVAILABLE. UI renders names as text, re-reads saved state and clears password inputs after each submission. Robot API/envelope versions are unchanged.

### v1.210 첫 로그인 비밀번호 변경 (D-686)

초기 비밀번호가 로그인 ID와 같은 계정은 서버가 scrypt로 확인하여 제한된 쿠키를 발급한다. GET `/api/fleet/auth/session`은 `password_change_required` boolean을 추가한다. 초기 쿠키에서 이 필드는 true이고, 변경된 쿠키 및 기존 Bearer/development 자격에서는 false다. 제한된 쿠키는 session 조회·logout·change-password만 사용할 수 있고 다른 보호된 Fleet API 읽기·쓰기는 403 `PASSWORD_CHANGE_REQUIRED`다. 기존 Bearer·기계 자격과 CORE 권한은 유지한다.

POST `/api/fleet/auth/change-password`는 같은 출처의 유효한 초기 쿠키만 받는다. 본문은 `password` 문자열 하나만 받으며 8~1024자이고 ID와 달라야 한다. principal·role 및 추가 필드는 받지 않는다. 성공은 204, `Cache-Control: no-store`와 새 HttpOnly/Secure/SameSite=Strict 쿠키다. 기존 remember 선택을 유지하고 해당 계정의 이전 세션을 무효화한다. UI는 새 session 조회에서 제한 해제를 확인한 뒤 업무로 돌아간다. 새 scrypt 해시는 기존 tasks SQLite에 원본 YAML의 principal·role·초기 해시 지문과 결합해 저장한다. 재시작 후 유지되며 YAML 계정 제거·자격/역할 변경 뒤에는 적용하지 않는다.

CSRF 실패는403 `CSRF_REJECTED`, 초기 쿠키가 아닌 자격은403 `PASSWORD_CHANGE_NOT_REQUIRED`, 잘못된 본문은422 `INVALID_REQUEST`, 만료·변경 경합은401 `UNAUTHORIZED`, scrypt 작업 포화는429 `RATE_LIMITED`(Retry-After 1), 세션 DB 실패는503 `SESSION_STORAGE_UNAVAILABLE`다. 감사 원장 실패는 기존503 `AUDIT_STORAGE_UNAVAILABLE`이다. DB 오류는 변경 성공으로 표시하지 않는다. 이전 비밀번호의 검증 결과로 변경 이후 세션을 발급하지 않는다. 사람 로그인 계정이 없으면 change-password도404다. Robot API/envelope 버전은 유지한다.

### v1.208 D-664 · 공통 작업 읽기 (`GET /api/fleet/work`)

`FleetWorkOverview` / `FleetWorkSummary`는 `core_common.protocol.schemas`의 additive 읽기 계약이다. 기존 Task/Mission 상태와 실행 API를 변경하지 않는다. viewer 이상이 조회하며 주행 Task는 기존 Task read 권한, Mission은 기존 Mission read와 동일한 principal 소유 범위 및 RESOLVED proposal을 요구한다. 다른 사용자의 Mission은 운영자에게도 이 목록으로 노출하지 않는다. v1.237(D-763 조각 4)부터 trip·Cell Job 출처와 그 범위는 v1.237 절을 따른다.

`limit`은 정수 1–100, 기본 50이며 **원장별** 최근 행 수다. 응답은 `observed_at`(조회 UTC 시각), `tasks_available`, `missions_available`, `truncated_sources`(`task`/`mission`), `rows`(최대 200행)다. `observed_at`은 장치 센서의 관측 시각이 아니다. 원장 미설정은 available=false이며 빈 목록과 구별한다. 행은 `updated_at` 내림차순, source/source_id 내림차순으로 정렬한다. 전체 원장 스냅숏의 원자성 또는 두 원장 사이의 동일 시점은 보장하지 않는다.

각 행: `source`(`task`/`mission`), `source_id`, `action_kind`(기존 navigate/PICK_PLACE), `status`(원장 상태 그대로), `device_id`(Task robot_id / Mission instance_id), `workcell_id`(Mission 공간; Task null), `reason`(없으면 null), `updated_at`(원장 UTC 갱신 시각). identity는 `(source, source_id)`이며 두 원장이 같은 ID를 가질 수 있다. plan/candidate/request/receipt/credential은 목록에 포함하지 않는다. 개별 상세는 기존 `/api/fleet/tasks/{id}` 또는 `/api/fleet/missions/{id}`로 조회한다.

인증 없음 401, 권한 부족 403, 잘못된 limit 422. 이 경로는 read projection이며 dispatch/admission/claim/fence/state transition을 수행하지 않는다. 조회 실패·세션 변경·권한 상실 시 UI는 이전 목록·상세를 지우고 미확인으로 표시한다. `ACTION_SUCCEEDED`는 목표 확인 대기이며 `GOAL_CONFIRMED`와 구별한다. 이 추가는 다장치 Mission 실행이나 복합 Asset API를 제공하지 않는다.

### v1.205 Fleet 지도 프로필 (D-631)

이름 있는 지도 프로필 조회·revision 비교 저장을 추가한다. 활성 지도·초안·교정 승인·로봇 명령의 기존 계약은 유지한다. 상세 계약은 문서 끝의 D-631 절이다.

### v1.204 Fleet 현재 영상과 복구 방향 (D-623)

- 기존 `GET /api/fleet/robots/{robot_id}/line-stuck/evidence?stuck_id=`에 선택 query `live: bool = false`를 추가한다. 기본 사건 사진 보존 동작은 그대로다. `live=true`는 열린 사건에만 현재 RAW front JPEG를 읽고 `{robot_id, stuck_id, sequence, source, media_type, jpeg_base64, live:true, captured_at:number|null, age_s}`를 반환한다. CORE 촬영 시각이 있으면 그 시각으로, 없으면 CORE `age_ms`와 요청 경과 시간으로 나이를 재며 3초를 넘거나 나이를 확인하지 못하면 기존 404 `STUCK_PREVIEW_UNAVAILABLE`이다. 닫힌/교체된 사건은 404 `STUCK_NOT_OPEN`. viewer+ 권한과 로봇 credential 경계는 동일하다. JPEG는 현재 요청에서만 반환하고 원본 사건 사진을 덮어쓰거나 디스크에 저장하지 않는다. D-136 T1의 단일 사진 제한은 이 인증된 열린 사건 조회만 예외로 한다.
- `/api/fleet/state`의 열린 `line_stuck` 행과 `/api/fleet/line-stuck`의 pending 행에 선택 `heading_review`를 넣는다. `status:heading_compared`일 때만 `{turn_deg, pose_stamp, edge_id, map_version, turn_spot}`가 있다. 미확인 상태(`pose_untrusted`, `lane_sample_untrusted`, `observer_unavailable`)에는 회전각이 없다. AI case의 `context.heading_review`도 같은 의미다. 방향 재평가이며 실행 허가는 아니다.
- 차선 경계의 실제 변화 판정은 D-468의 자세 정렬 후 경계 기하 비교를 따른다. 프레임 sequence 증가, JPEG hash 차이, 모델 confidence, D-595 보정 jitter는 경계 변화나 새 이동 명령의 근거가 아니다. 이동 결정 단어/CORE 실행 계약은 변경하지 않는다.
- CORE `line_follow.stuck.inquiry`는 선택 object/null이며 현재 `situation-inquiry-v1` 문맥을 담는다. `lane_boundary`는 `{state:unknown|baseline|confirming|confirmed, revision:integer>=0, epoch:integer, source_stamp_ns:integer|null, geometry_id?:string, reason?:string}`이다. 신선한 D-468 경계가 자세 정렬 후 기존 경계와 다르고 서로 다른 촬영 시각 세 개에서 일치할 때만 revision이 증가한다. 새 epoch/geometry는 baseline이며 변화로 세지 않는다. Fleet은 최신 상태 inquiry를 최초 사건 inquiry보다 우선한다. AI는 같은 stuck의 첫 문의 후에는 confirmed revision 변경에서만 재문의한다. 경계 상태가 없는 기존 장치도 첫 문의만 가능하며 자동 재문의는 하지 않는다. 이 상태는 기하 관측의 변화이고 명령·허가가 아니다.

---

### v1.209 지도 없는 조사 좌표와 도로 시설 (D-655)

- `POST /api/fleet/site-map/activate`는 진행 중 trip, 대형 ARMING/RUNNING/HOLDING, 진행 중 teach 기록에서 기존 409 `SITE_MAP_ROUTE_ACTIVE`를 반환한다. 초안·프로필 저장은 가능하고 멈춘 teach의 pending 검토만으로 활성화를 막지 않는다. busy 검사와 활성 버전 저장은 같은 이벤트 루프의 await 없는 구간이다. 거절은 지도·기록·대형·로봇을 변경하지 않으며 운용 종료 뒤에도 별도 활성화와 기존 draft revision 검사가 필요하다.
- 카메라 차선 추출 결과의 간선은 camera/observed 근거를 가진다. calibration JSON의 선택 survey는 기존 SurveyReference와 같고, 생성 결과의 review는 false로 초기화한다. survey가 없으면 reference_revision은 calibration JSON의 SHA256 지문으로 생성한 식별자다. 간선 note는 교정 지문과 CLI 원본 프레임 SHA256을 보존한다. 검토 전 활성화는 기존 ROAD_UNREVIEWED/SURVEY_UNREVIEWED 가드로 거절한다.
- 화면의 관측 누적은 기존 draft PUT/CAS/named operator만 사용한다. 대상과 입력의 map_id 및 reviewed/review_note를 제외한 전체 survey 기준이 같아야 한다. 기존 시설·규칙·간선을 유지하고 새 관측의 ID는 분류 안에서 재배정한다. 동일 기하·운행 속성의 기존 차로는 중복 추가하지 않는다. 신규 관측 장소가 기존 장소의 0.05 m 이내면 연결이 모호하므로 자동 접합하지 않고 검토를 요구한다. 입력 시설/횡단보도/회전 규칙은 이 차선 누적 경로에서 거절하며 기존 편집 경로를 사용한다.
- 동일 차로의 다른 관측 note는 기존 근거에 덧붙이고 검토를 무효화한다. 같은 파일의 재누적은 idempotent이며 note 합계 1000자 초과는 거절한다. 검토와 도로/장소 교정은 원본 관측 지문을 유지한다. survey가 없는 카메라 초안도 도로 근거 검토가 가능하며 운행 속성·marker geometry 수정 뒤 operator/observed로 재검토한다.
- 연결 후보는 같은 좌표계의 신규 관측 장소와 기존 장소가 0.05 m 이내인 경우만 제시한다. 후보의 이름·좌표·거리를 지도 밖에서 표시하고 관측 장소마다 운영자가 기존 장소를 선택해야 접합한다. 선택하지 않은 가까운 장소·다른 프레임·범위 밖 연결·존재하지 않는 ID는 거절한다. 접합 결과의 간선은 inferred이며 원본 지문과 관측 ID→기존 ID 연결 근거를 note에 남긴다. 기존 장소와 기존 간선은 움직이지 않는다. 실제 연결과 통행 의미를 검토해 reviewed로 저장하기 전에는 활성화할 수 없다. 이 후보는 명령·운행 pose·관측되지 않은 연결 자동 완성을 만들지 않는다.
- 일반 teach의 시작·샘플·확정과 pose/마커 장소 추가는 활성 지도와 대상 초안의 map_id·전체 survey 기준을 비교한다. 다른 기준은 409 `TEACH_MAP_CHANGED`로 거절한다. 일반 기록 시작과 pose 장소 저장은 위치 조회 전 map_id·전체 survey 기준·활성 버전을 고정하고 조회 후 비교한다. 조회 중 활성화되면 같은 map_id여도 거절하며 이전 위치를 새 지도에 저장하지 않는다. 기록 시작의 활성 버전이 바뀌면 기록은 `map_changed`로 종료되고 이전 기록 확정은 거절된다. 기록 종료는 로봇 정지 명령이 아니다. 일반 recording/pending도 시작 시 고정한 `map_id`와, 조사 기준이 있으면 `survey_reference`를 반환하며 화면은 일치하는 좌표계에서만 선을 표시한다.
- 거절된 odom(시각 역행·동일 시각의 다른 위치 포함)은 조사 기록의 연속성 토큰을 변경한다. 운행 pose의 기존 앵커와 odom epoch는 이를 이유로 초기화하지 않는다. 기존 정상 teach로 같은 조사 지도에 도로를 확정할 때도 odometry observed 근거를 추가하고 조사 검토를 무효화한다. pose/마커 장소 편집도 조사 검토를 무효화하며 마커로 바뀐 간선은 operator observed로 재검토한다.
- 장소·간선·시설의 ID 유일성은 각 분류 안에서 적용한다. 기존 프로필의 분류 간 같은 ID를 허용하며 편집·삭제는 분류와 ID를 함께 식별한다. 기존 `schemas.HostStatusEvidence` 이름·본문은 유지하고 구현 소유만 기존 `protocol.evidence`로 이동한다.
- 기존 `rosy.site_map/1`에 선택 `survey`와 `facilities`, edge의 선택 `evidence`를 추가한다. 기계 계약은 `core_common.protocol.site_survey`이며 `core_common.protocol.schemas`에서 재노출한다. 없는 필드는 기존 지도 body와 해시에 추가하지 않는다.
- `survey`: `{revision, origin:[x,y], heading_rad, scale_source:odometry|measured, measured_distance_m?:number|null, description, reviewed:false, review_note:string}`. 좌표는 m, 방향은 rad이며 유한 값이다. 원점 좌표는 ±1000 m, 방향은 ±2π, revision은 영문·숫자·밑줄·점·하이픈 1–64자다. description은 비공백 1–1000자다. 실측 축척에는 양의 `measured_distance_m`(≤2000), reviewed=true에는 비공백 review_note(≤1000)가 필요하다. odometry 축척은 측량 정확도나 운행 위치 승인 증거가 아니다.
- edge `evidence`: `{source:camera|odometry|operator,status:observed|inferred|reviewed,reference_revision,note}`. note 기본 빈 문자열, reviewed에는 비공백 note(≤1000) 필수. 조사 기준이 있으면 reference_revision이 일치해야 한다.
- `facilities`는 최대 500개 `{id,name,kind:traffic_signal|stop_line|landmark|exclusion,geometry:[[x,y]],approaches:[{edge_id,forward,stop_s_m?}],signal_id?,signal_kind?:physical|virtual}`다. 신호등/landmark는 한 점, 정지선은 서로 다른 두 점, 금지 구역은 퇴화·자기 교차 없는 3–32점 다각형이다. geometry 좌표는 ±1000 m의 유한 값이다. id는 revision과 같은 형식, name은 비공백 최대 64자. approaches 최대 64개, 존재하는 차로와 허용 방향만 참조하고 동일 차로·방향 중복 불가, stop_s_m은 0 이상 차로 길이 이하. 신호등은 signal_id·signal_kind·제어 approaches 필수이고 나머지 시설에는 device 필드를 넣지 않는다. 시설 기하는 장치 등록·신호 제어 활성화가 아니다.
- 기존 초안·프로필 요청의 크기·revision·named operator·감사 계약은 유지한다. 활성화 및 최초 import는 미검토 survey를 422 `SITE_MAP_SURVEY_UNREVIEWED`, observed/inferred road evidence를 422 `SITE_MAP_ROAD_UNREVIEWED`로 거절한다. 메타데이터는 World의 운행 MapPose나 CORE 명령을 바꾸지 않는다.
- 금지 구역에 닿거나 차로 반폭 이내로 접근하는 주행 간선이 있으면 활성화/최초 import는 422 `SITE_MAP_EXCLUSION_OVERLAP`이다. 금지 영역을 그림으로만 표시한 채 경로 계획이 통과하도록 두지 않는다. 간선 기하를 수정하거나 차로 초안에서 제거한 뒤 다시 검토한다.
- 기존 teach의 map-pose 기록 중 UNKNOWN/DEGRADED 또는 dead_reckon_m >0.5로 유효 좌표가 끊기면 기록을 끝낸다. stop/result의 reason은 `pose_lost`이며, 직전까지 유효한 선만 pending에 남는다(최소 길이 미만은 폐기). 이후 재관측 좌표를 같은 선으로 자동 잇지 않는다. 이는 기록 중단이며 로봇 정지 명령이나 위치 승인으로 사용하지 않는다.
- `POST /api/fleet/teach/start`에 선택 mode `map`(기본값)/`survey`를 추가한다. map은 기존 요청을 유지하며 조사 필드를 받지 않는다. survey는 저장된 초안의 `map_id`, `reference_revision`(조사 revision 형식), `expected_revision`과 신선한 상대 odom을 요구한다. 현재 로봇 위치를 survey.origin, 현재 방향을 survey.heading_rad에 놓는 상대 변환으로 선을 기록한다. 로봇을 설명에 명시한 실제 시작점·방향에 놓고 시작해야 한다. 운행 MapPose나 map pin은 생성하지 않는다.
- survey 시작은 초안 없음/조사 없음 422 `TEACH_SURVEY_REQUIRED`, revision 불일치 409 `SITE_MAP_DRAFT_CHANGED`, map_id/조사 기준 불일치 409 `TEACH_SURVEY_CHANGED`, odom 없음·stale·읽기 실패 422 `TEACH_ODOM_UNAVAILABLE`을 반환한다. 유효하지 않은 mode/필드 조합은 422 `TEACH_MODE_INVALID`이다. 기존 named operator·roster·한 사이트 한 기록·busy·감사·pending 10분 계약을 유지한다.
- survey recording/result에는 mode, map_id, reference_revision을 추가하며 recording의 draft_revision은 시작 시점의 저장 revision이다. 내부 odom anchor/epoch는 공개 응답에 넣지 않는다. 기록 중 초안 수정은 `survey_changed`, odom 단절은 `odom_lost`, odom epoch 변경은 `odom_reset`으로 유효 앞부분만 남기고 끝낸다. confirm은 시작 기준과 현재 초안의 동일성을 확인하고 기존 expected_revision CAS로 저장하며 새 간선을 source=odometry/status=observed로 기록하고 survey 검토를 무효화한다. 기준이 바뀌면 409 `TEACH_SURVEY_CHANGED`로 기록을 유지하고 저장을 거절한다.
- survey recording/result의 `survey_reference`는 시작 기준 snapshot(reviewed/review_note 제외)이다. UI는 동일 map_id와 기준 snapshot에만 조사 선을 겹치고 현재 초안 기준이 다르면 confirm을 차단한다. 공개 응답의 points는 기존처럼 배열의 배열이다. 시작점 확인은 각 시작마다 필요하며 로봇·기록 방식·저장 revision 변경 시 UI 확인을 초기화한다.

# 1. 버저닝 및 폐기 정책

### D-531 경로 문맥 발행 (v1.166, 기본 꺼짐)

`line_follow.route_context_enabled: true`인 CORE는 `line/route_context`에
`std_msgs/String` JSON을 RELIABLE, KEEP_LAST 1, VOLATILE로 발행한다.
활성 문맥은 5 Hz로 갱신하며 지시 변경 시 바로 발행한다. 지시 완료·만료,
모드 변경, odom 소실·epoch 변경, E-Stop 시 `{ "v": 1, "seq": null }`로 비운다.
활성 메시지는 `{v: 1, seq, place_id, map_id, kind, stamp_s, valid_until_s}`와
선택 필드 `ahead_m: [lo, hi]`, `bend_phase`, `lane_turn_deg`, `curvature_1pm`을 갖는다.
`kind`는 `junction|bend|ring`; 시각은 ROS clock 기준이고 유효 기간은 최대 1초다.
`bend_phase`는 `kind: bend`일 때만 `bending|reacquiring`으로 나타낸다.
이 단계에서는 이미 굽이에 들어왔으므로 CORE는 접근 거리 `ahead_m` 대신 이 필드를 보낸다.
`exit_segment`가 지시에 있어도 실제 호 주행이 시작되기 전에는 `junction`이다.
`ahead_m`의 각 값은 −0.5~2.0 m, `|lane_turn_deg|`는 360° 이하,
ring의 `|curvature_1pm|`는 0.5~5.0 1/m이다. 경로 문맥은 인식 보조 증거이며
주행 명령이 아니다. CORE만 최종 `cmd_vel`을 발행한다.

켜진 경우 `GET /api/v1/line-follow`와 상태 스냅숏의 `line_follow`에는
`route_context`(현재 발행 중인 문맥 또는 null)와 `route_context_published_at_s`
(마지막 발행 ROS 시각 또는 null)가 추가된다. `rosy.controls/1`의
`base_velocity.route_context: true`는 설정이 켜졌음을 뜻하며 주행 가능성이나
현장 수용을 뜻하지 않는다. 인식의 `line/observation`과 `line/keep_debug`가
선택 필드 `route_context_seq`를 실으면 CORE는 현재 발행 문맥의 `seq`와
다른 프레임을 거절한다. 필드가 없거나 null이면 기존 인식 경로와 같다.
거절한 카메라 프레임은 `invalid_observation`으로 무효화해 즉시 HOLD하고,
그 프레임의 교차로 감지도 받지 않는다.

기본값은 false이며 이때 토픽과 능력 필드는 없다. 인식 소비자와 경계 판정은
별도 단계로 검증한다(D-531 P2/P3).

### D-556 한쪽 경계 odom 충돌 (v1.221)

내부 `line/observation`의 CAMERA_LINE `quality`는 `visible=false`, `confidence=0`일 때만
`{valid:false, reason:"odom_side_conflict"}`를 추가로 허용한다. CORE는 이 사유를 도색 공백으로
취급하지 않고 HOLD한다. D-476 bridge와 D-468 로컬 복구는 이 사유로 시작하지 않는다.
이때 `GET /api/v1/line-follow`의 `reason`은 `camera_odom_side_conflict`이고, `lost_after_s`가 지나면
저조도와 같이 `nav.lane_lost`의 `reason`에도 같은 값이 실린다. 생산자는 인식 노드의
`lane_odom_veto_enabled`(기본 false)가 켜졌을 때만 이 사유를 낸다(D-556 Proposed, SOURCE 후보).
내부 String 토픽의 값 확장이며 REST 경로·스키마와 envelope 1.0은 바뀌지 않는다.

### D-468 추가 차선 경계 증거 (v1.106)

내부 `line/observation`의 CAMERA_LINE 증거는 optional `containment`를 포함할 수 있다.
원본 영상 `stamp`와 1us 이내로 일치하는 `stamp`, `geometry_id`,
`ground_source`(NOMINAL/CALIBRATED/GAZEBO/ISAAC), optional `uncertainty_m`와
`boundaries`(0~2개)를 보낸다. 각 경계는 `side`(left/right), `slope`,
`intercept_m`, 실제 관측 구간 `observed_x_min_m`/`observed_x_max_m`를 갖는다.
좌표는 base footprint 기준 x 전방/y 좌측, 직선 y=slope*x+intercept_m이다.
경계는 칠한 선의 중심이 아니라 차로 쪽(안쪽) 가장자리, 곧 달릴 수 있는 끝이다(생산자가
칠 폭의 절반 `lane_paint_half_width_m`만큼 안쪽으로 옮긴다).
CALIBRATED는 실제 승인된 calibration이 있을 때만 사용한다. unknown uncertainty는
null이며 임의의 안전 여유로 대체하지 않는다. 누락/단일 경계로 전체 차체 containment를
증명할 수 없고 관측 구간 밖으로 무제한 외삽하지 않는다. 명령 필드는 없다.
기존 관측 메시지와 공개 mode/route는 보존한다. 이 계약의 추가는 자동 복구 활성화나
장치/현장 수용을 뜻하지 않는다.

v1.210(D-692): ISAAC은 native Isaac 영상의 시뮬레이션 출처이며 NOMINAL 실물 관측이나
GAZEBO 검출기 오차를 대신하지 않는다. 검증된 projection/detection 오차 범위가 없으면
`uncertainty_m`와 `crosswalk_uncertainty_m`는 null을 유지한다. 해당 관측은 안전한 경계나
횡단보도 통과를 증명하지 않는다. envelope `protocol_version`은 1.0을 유지한다.

D-491(v1.115): `containment`는 optional `crosswalk`(`near_m`, `far_m`)를 더 가질 수 있다. D-573 6 개정(v1.194): optional `crosswalk_uncertainty_m`(m, 0–1) — 횡단보도 가까운·먼 끝의 앞뒤 최악 한도(영상 시각 몸 좌표). 검출기가 돈 모든 프레임에 둔다(찾았든 못 찾았든). 없으면 검출기가 돌지 않은 것이고 CORE 횡단보도 보고는 `unknown` 이다.
같은 영상 시각에 카메라가 본 차로와 나란한 줄무늬 횡단보도의 가까운 끝과 먼 끝이며,
base footprint 기준 전방 거리(m, 0~1, near < far)다. CORE는 지면 표시와 상관없이
`uncertainty_m`이 있고 0.015 m 이하일 때만(D-468과 같다) 이 구간을 영상 시각의 odom 자세에 고정해 IR 차선 감시의
휴식 구간으로 쓴다(D-491 개정 2026-10-07). 불확실도 없음·odom 끊김이면 구간이 없고 감시는 그대로다.
명령 필드는 없다.

### API-001 경로 버저닝

모든 REST API는 버전을 포함한다.

```text
/api/v1/...
```

Breaking Change 발생 시 `/api/v2/...`로 분리한다.

### API-002 변경 분류

| 분류 | 예 | 정책 |
|---|---|---|
| Additive | 신규 엔드포인트, 응답에 신규 선택 필드 추가 | 버전 유지, 버전 노트 기록 |
| Breaking | 필드 제거/이름 변경, 의미 변경, 필수화 | 신규 major 버전 |
| Corrective | 문서가 틀리게 적혀 있던 것을 구현과 맞춤 (payload 키명, 심각도, 발신자) | 버전 유지, 버전 노트에 **양쪽 값을 모두** 기록 |

소비자는 알 수 없는 응답 필드를 무시해야 한다(Must Ignore 원칙).

Corrective 는 Additive 의 종류가 아니다. 문서대로 짜놓은 소비자는 이미 깨져 있었고, 정정은
그것을 알려 주는 것이다 — 그래서 어느 쪽으로 고쳤는지(문서를 고쳤는지 코드를 고쳤는지)와
틀리게 적혀 있던 값이 무엇이었는지를 모두 적는다. 버전 노트에 `A(≠B)` 로 쓴 것이 그것이다.

### API-003 폐기(Deprecation) 정책

- 폐기 예정 엔드포인트는 응답 헤더 `Deprecation: true` + `Sunset: <date>`와 버전 노트로 사전 공지한다.
- 폐기까지 최소 **2개 마이너 릴리스 또는 6개월** 유지한다.
- Fleet은 로봇 `api_versions`(Capability)를 확인하여 버전별 호출 경로를 선택할 수 있어야 한다.

> **상태 (v1.16)**: `Deprecation`/`Sunset` 헤더는 아직 구현되지 않았다 — 폐기 대상이
> 생기는 첫 시점에 구현과 함께 유효해진다. 현재 폐기 예정 엔드포인트는 없다.

### API-004 원천 일관성

본 문서와 구현 OpenAPI 간 불일치 발견 시 본 문서를 우선하고, 수정은 합의 후 양측에 동시 반영한다. 계약 테스트(Implementation Plan §테스트)가 불일치를 회귀 차단한다.

---

# 2. 인증 및 권한

### AUTH-101 토큰

- `Authorization: Bearer <token>` (REST). 쿠키는 쓰지 않는다.
- WebSocket: 연결 뒤 첫 메시지 `{"type": "auth", "token": "<token>"}` (v1.19). 2 s 안에 오지 않거나 틀리면 4401.
  첫 메시지를 기다리는 소켓은 출발지 호스트마다 4 개, 전체 64 개까지이고(2 s 안에 첫 메시지), 넘으면 수락 전에 닫는다(Starlette는 수락 전 close를 HTTP 403으로 보낸다). 열린 소켓은 30 s 마다 토큰을 다시 보고,
  회수·로그아웃·만료됐으면 4401 로 닫는다.
  `?token=<token>` 쿼리도 한 릴리스 동안 받는다(v1.19 기준 폐기 예정 — URL 은 프록시·기록에 남는다).
- 토큰은 sha256 다이제스트로만 저장한다. 레코드에는 `source`(`card` \| `manual` \| `pair-physical` \| `pair-admin` \| `legacy`)와
  `expires_at`(없으면 만료 없음)이 있다. 만료된 토큰은 401 이고, 다음 저장 때 목록에서 지워진다(D-193).
- 장치 기본값에는 토큰이 없다. 장치 모드(`ROSY_DEPLOYMENT=device`)의 CORE 는 평문 레거시 항목과 공용 개발 토큰
  `rosy-dev-*` 를 어디서 오든 거부하고 `auth.credentials_refused` 를 낸다. 토큰이 0 개여도 API 는 뜨고 모든 인증 요청은 401 이다.
  예외(D-548): root 가 만든 `/etc/rosy/dev-mode` 가 있으면 그 로봇만 세 공용 개발 토큰을 받고 기동 때 `auth.development_mode` 를 낸다. 파일을 지우면 즉시 401 이다. 이때도 공용 개발 토큰은 `/api/v1/host/ssh*`·`/api/v1/auth/enrollment-codes` 전부와 `/api/v1/host/*`·`/api/v1/system/tokens*`·`/api/v1/system/dds*` 쓰기에 403 `FORBIDDEN` 이다.
- 로그인 코드(D-193): 로봇 화면·콘솔의 8자 일회용 코드를 `POST /api/v1/auth/pair` 로 이 브라우저 전용 만료 토큰으로 바꾼다(§5.1).
- Fleet 접속용 로봇 토큰은 사용자 토큰과 분리한다(페어링, §7).

### AUTH-102 권한

| Role | 조회 | 제어 | 관리 |
|---|---|---|---|
| Viewer | 상태·맵·센서·이벤트 | — | — |
| Operator | 조회 | Navigation·Teleop·Stop·Mission | — |
| Administrator | 조회 | 제어 | 설정·ROS·네트워크·Robot ID·Update·페어링·토큰 |

예외: `POST /api/v1/safety/stop`은 모든 Role 허용(E-Stop은 누구나).

**토큰 capability (v1.72, D-395 P2-5).** 역할 위에 이름 붙은 쓰기 권한을 둔다. 경로는 "operator 이상" 대신 필요한 capability 를 말한다. 지금은 역할에서 정해진다(`core_api_web.api.grants`).

| capability | 뜻 | Viewer | Operator | Administrator |
|---|---|---|---|---|
| `NAVIGATE` | 사람이 로봇 위치·목표를 정한다 (`localization/initialpose`, `source: human` 결정) | — | ✓ | ✓ |
| `LOCALIZE_ASSIST` | Fleet 위치 확정 서비스가 후보를 읽고 결정·의심을 보낸다 (§5.3, §7.9) | — | ✓ | ✓ |
| `STUCK_DECIDE` | 열린 막힘에 답한다 (`POST /line-follow/stuck/decision`, D-438, v1.91). 역할 `stuck_resolver`(순위 viewer, 이 권한만 가짐)는 Fleet 판단기 전용이다. `stuck_resolver` 가 `MANUAL` 을 고르면 403 `FORBIDDEN` "MANUAL is a human decision (D-438)" 이고 막힘은 열려 있다 | — | ✓ | ✓ |

Fleet 의 로봇 토큰은 operator 토큰이다(`robots.yaml` 의 `token`, 또는 operator 가 아니면 거부하는 D-361 등록). 그래서 `LOCALIZE_ASSIST` 를 가진다. 없으면 403 `FORBIDDEN`, `detail: {capability}`.

### AUTH-103 브라우저 직접 접속 없음 — CORS 미제공 (v1.16 additive)

이 API 는 CORS 헤더를 제공하지 않는다. 소비자는 ① 로봇 로컬 대시보드(동일
출신 정적 자산), ② 서버 간 클라이언트(Fleet·Games), ③ 브라우저라면 자기
출신에서 프록시 하는 웹 앱만 해당한다. 브라우저가 로봇 API 를 직접 fetch
하는 구성은 계약 밖이며 `same-origin` 정책에서 조용히 실패한다.

---

# 3. 에러 응답 표준

### ERR-101 형식

```json
{
  "error": {
    "code": "CAPABILITY_NOT_SUPPORTED",
    "message": "docking is not supported on this robot",
    "detail": { "capability": "docking" }
  }
}
```

### ERR-102 에러 코드 카탈로그

| code | HTTP | 의미 | 발신 |
|---|---|---|---|
| `VALIDATION_ERROR` | 400 | 요청 스키마 위반 | 로봇/Fleet |
| `ROBOT_MUST_BE_STOPPED` | 409 | staged 주행 정책 적용 전에 IDLE/EMERGENCY, 0 속도, line-follow OFF 조건이 충족되지 않음 | 로봇 |
| `UNAUTHORIZED` | 401 | 토큰 없음/무효 | 로봇/Fleet |
| `FORBIDDEN` | 403 | 권한 부족. D-760 9항: 목표를 보낸 토큰이 아닌 토큰의 `POST /navigation/goal/lease` | 로봇/Fleet |
| `NOT_FOUND` | 404 | 리소스 없음 | 로봇/Fleet |
| `MODE_CONFLICT` | 409 | 현재 모드에서 수행 불가 (예: MANUAL 중 NAV goal) | 로봇 |
| `EMERGENCY_ACTIVE` | 409 | E-Stop 활성 상태 | 로봇 |
| `NAVIGATION_ACTIVE` | 409 | 이미 진행 중 (재정의 필요 시 cancel 먼저) | 로봇 |
| `WAYPOINT_EXISTS` | 409 | Waypoint 이름 충돌 | 로봇/Fleet |
| `CAPABILITY_NOT_SUPPORTED` | 501 | 로봇이 미지원하는 기능 (CAP-003) | 로봇 |
| `CAPABILITY_WITHHELD` | 409 | 로봇이 지원하지만 현재 런타임이 보류한 기능. `detail: {capability, reason}`의 이유는 `GET /system/capabilities`의 `withheld.reasons`와 같다. 미지원 판정(501)이 우선한다 | 로봇 |
| `MAP_MISMATCH` | 409 | Goal의 map_id 불일치 (MAP-002) | 로봇 |
| `MAPPING_ACTIVE` | 409 | 매핑 세션 중 명령 거부 (NAV-005) | 로봇 |
| `ROTATE_CLEARANCE` · `MOTION_BUSY` · `ODOMETRY_STALE` | 409 | D-603 (v1.194) `POST /motion/rotate_to` 거부: 회전 반경 안 반사·LiDAR 증거 부족·신선한 LiDAR 없음(`detail {nearest_m, need_m}`, 몸체를 알면 base_footprint 기준 `rotation_radius + rotate_margin_m`, 모르면 LiDAR 기준 `rotate_clearance_m`), 다른 미션·IDLE 아닌 모드(MANUAL·NAVIGATION·DOCKING)·line-follow·도킹·swarm·Nav2 목표가 바퀴를 쥐고 있음, 0.5 s 안의 odometry 없음 | 로봇 |
| `OPERATOR_NAME_REQUIRED` | 403 | D-603 (v1.194) `POST /motion/rotate_to`: trip lease 주인이 아닌 호출이 `operator_name`을 비워 보냄 | 로봇 |
| `DOCKING_ACTIVE` | 409 | 도킹/언도킹이 주행을 쥐고 있다 (DNC-003, §8.1 DOCKING > NAVIGATION) | 로봇 |
| `NOT_LOCALIZED` | 409 | D-395 로봇이 `LOCALIZED` 가 아니거나 `pose_frame` 이 `odom` 이어서(Fleet 신뢰 규칙과 같다) 자율 주행 시작을 거부함: `navigation/goal`·`home`(`/do` 포함), `line-follow/mode`(OFF 제외), `docking/dock`, `swarm/follow`. 검사와 시작은 `LOCALIZED` 이탈 정지와 같은 잠금 안에서 순서가 정해진다. 내부 시작도 같다: 저배터리 자동 도킹은 대기로 남았다가 `LOCALIZED` 로 돌아오면 이어 가고, SAF-005 `RETURN_HOME` 은 보낼 수 없는 귀환으로 보아 e-stop 으로 올린다. `detail: {state, pose_frame, reason}`. `localization` 이 `null` 인 로봇(D-395 이전)에는 적용하지 않는다 (v1.72) | 로봇 |
| `STALE_REQUEST` | 409 | `POST /localization/decision` 의 `request_id` 가 로봇의 열린 요청이 아님을 CORE 가 이미 안다. 열린 요청이 없을 때 `candidate` 결정도 같다 (v1.72) | 로봇 |
| `NO_CANDIDATES` | 404 | `GET /localization/candidates` — 로봇이 `CANDIDATES` 가 아니거나 열린 요청의 보고가 아직 없음 (v1.72) | 로봇 |
| `NO_REQUEST` | 404 | `GET /localization/request` — 로봇이 연 위치 요청이 없거나 `ttl_s` 가 지남 (v1.163) | 로봇 |
| `localized` · `busy` · `estop` · `path_not_clear` · `calibration_lease` · `unsupported` | 409 | `POST /localization/mission` 거부(D-395 P2-7, v1.73, 계약 §2 의 소문자 코드): 로봇이 이미 `LOCALIZED`; 미션·MANUAL·NAVIGATION·도킹·line-follow·swarm·Nav2 목표가 바퀴를 쥐고 있거나 로봇의 3 s 주입 검사가 도는 중(`reason: checking`); e-stop; 신선한 LiDAR 가 없거나 정면 부채꼴(±20°)이 0.25 m 보다 가까움(`nudge_forward`·`lane_to_stopline`); 다른 토큰의 보정 lease; 아직 없는 종류(`to_square`, 후속) | 로봇 |
| `CALIBRATION_ACTIVE` | 409 | 다른 토큰이 보정 세션 lease 를 쥐고 있어 구동 쓰기를 거부함: `teleop`, `/mode`(IDLE 제외), `line-follow/mode`(OFF 제외)·`hold`, `navigation/goal`·`home`, `docking/dock`·`undock`, `swarm/follow`. 멈추기만 하는 것(`safety/stop`, `/mode` IDLE, line-follow OFF, 각종 cancel)은 막지 않는다. `detail: {session}` 은 `GET /calibration/session` 의 세션과 같다. `POST /calibration/session` 이 이미 세션이 있을 때도 같은 코드 (D-321 부록, v1.68). D-395 경로 `POST /localization/decision`·`suspect` 에서는 같은 코드를 **423** 으로 낸다(v1.72, 계약 `docs/plans/2026-10-01-d395-phase2-interfaces.md` §2) | 로봇 |
| `TRIP_LEASED` | 409 | D-541 (v1.157): Fleet trip lease 가 살아 있어 **주인 아닌 토큰**의 구동·모드 쓰기를 거부함. `require_calibration_owner` 를 지나는 모든 쓰기다: `teleop`, `/mode`(IDLE 제외), `line-follow/mode`(OFF 제외)·`hold`·`junction`·`authority`, 막힘 결정 중 움직이는 답(RESUME·BACK_AND_RETRY·MANUAL·YIELD; `stuck_resolver` 토큰도 주인이 아니다), `navigation/goal`·`home`, `localization/initialpose`, `slam/start`·`stop`·`reset`, `docking/dock`·`undock`, `swarm/follow`, `PUT /safety/limits`, `POST /power/mode`, host install·rollback·reboot(`override_calibration` 없이), `/api/v1/do` 의 같은 동사, `POST /localization/mission`. D-395 경로 `POST /localization/decision`·`suspect` 에서는 `CALIBRATION_ACTIVE` 와 같이 **423** 으로 낸다. `POST /calibration/session` 은 lease 가 있으면 토큰과 관계없이 이 코드다. `PUT /trip-lease` 는 다른 `lease_id`(같은 토큰이어도)나 다른 토큰일 때 이 코드다. `detail: {lease_id, trip_id, holder, operator_name, since, expires_in_s}`. 멈춤(`safety/stop`, `/mode` IDLE, `navigation/cancel`, line-follow OFF, `swarm/cancel`, docking cancel, 막힘 WAIT·ABORT)은 막지 않는다 | 로봇 |
| `GOAL_LEASE_NOT_ACTIVE` | 409 | D-550 10 (v1.160): `POST /navigation/goal/lease` 의 `correlation_id` 가 활성 임대 목표가 아님(취소·도착·실패·만료·교체, 또는 임대 없이 연 목표). 갱신은 목표를 되살리지 않는다 | 로봇 |
| `FLEET_GOAL_ACTIVE` | 409 | D-555 (v1.163): `PUT`/`DELETE /api/v1/fleet/link` 를 Fleet 목표(`nav.fleet_goal()`)가 진행 중일 때 부름. relink 가 링크를 끊어 SAF-003 을 무장시키지 않도록 목표가 끝난 뒤 다시 한다 | 로봇 |
| `FLEET_LINK_CONFIG_INVALID` | 409 | D-555 (v1.163): 기동 때 잘못된 `fleet.heartbeat_reply_timeout_s` 또는 SAF-003 시간을 기본값으로 대신한 CORE 에 `PUT /api/v1/fleet/link`. 설정을 고치고 CORE 를 다시 띄운다 | 로봇 |
| `MANUAL_MODE` | 409 | D-541 2 (v1.157): `PUT /trip-lease` 를 MANUAL 모드 로봇에 엶(`manual_active` 와 관계없이). 먼저 IDLE 로 둔다 | 로봇 |
| `LINE_FOLLOW_NOT_HELD` | 409 | `POST /line-follow/hold` 인데 운전자 확인(`hold_s`) 세션이 없음 (v1.63) | 로봇 |
| `LINE_FOLLOW_NOT_ACTIVE` | 409 | `POST /line-follow/junction`·`POST /line-follow/authority`(v1.143) 인데 line-follow 가 꺼져 있음 (D-494, v1.114) | 로봇 |
| `JUNCTION_ALREADY_DONE` | 409 | `POST /line-follow/junction` 인데 같은 `place_id`·`action` 지시가 이미 실행됨(재획득 완료·직진 통과·회전 뒤 중단). 다른 `place_id` 지시로만 풀림(모드 변경으로는 풀리지 않음) (D-495, v1.114) | 로봇 |
| `JUNCTION_CAMERA_ONLY` | 409 | `POST /line-follow/junction` 인데 line-follow 가 `IR_LINE` — 교차로 감지는 CAMERA_LINE keep 에만 있음 (D-495, v1.114) | 로봇 |
| `AUTHORITY_ODOM_STALE` | 409 | `POST /line-follow/authority` 인데 받는 순간 신선한 odom(0.3 s)이 없어 주행 거리를 잴 수 없음. 쥐고 있던 통행권도 버리고 선다 (D-517 4, v1.143) | 로봇 |
| `AUTHORITY_POSE_STALE` | 409 | `POST /line-follow/authority` 의 `pose_stamp` 가 CORE odom 기록(이 line-follow 세션의 같은 odom 궤적, 최대 200개 표본)보다 오래됨. 쥐고 있던 통행권도 버리고 선다 (D-517 4, v1.143) | 로봇 |
| `AUTHORITY_POSE_FUTURE` | 409 | `POST /line-follow/authority` 의 `pose_stamp` 가 CORE 의 가장 새 odom 표본보다 0.05 s 넘게 앞섬(시계 불일치). 쥐고 있던 통행권도 버리고 선다 (D-517 4, v1.143) | 로봇 |
| `JUNCTION_ODOM_STALE` | 409 | `POST /line-follow/junction` 에 기대 창(`expect_in_m`·`expect_tol_m`)이 있는데 받는 순간 신선한 odom(0.3 s)이 없어 기대 점을 둘 수 없음 (D-507, v1.127) | 로봇 |
| `LANE_ARC_UNAVAILABLE` | 409 | `POST /line-follow/junction` 에 `exit_segment` 가 있는데 능력 `lane_arc` 가 거짓(`line_follow.arc_enabled` 꺼짐, 현장 바닥 선언 `site_floor_map_id` 없음, 또는 `ir_guard_speed_scale` 0) (D-520, v1.145, v1.154) | 로봇 |
| `JUNCTION_ARC_RUNNING` | 409 | `POST /line-follow/junction` 의 `action: bend` 인데 D-520 호(`line_follow.arc.state: running`)가 달리는 중 — 호가 그 차로를 달리므로 굽이 지시를 받지 않는다. Fleet 은 호가 도는 동안 굽이를 보내지 않는다 (D-520, v1.145) | 로봇 |
| `STUCK_ID_MISMATCH` | 409 | `POST /line-follow/stuck/decision` 의 `stuck_id` 가 지금 열린 막힘이 아님(늦은 답·이미 닫힌 막힘·막힘 없음). 늦은 답이 다음 막힘에 쓰이지 않게 한다 (D-407, v1.74) | 로봇 |
| `STUCK_DECISION_REFUSED` | 409 | 막힘 답을 지금 실행할 수 없음 — `RESUME`: 경로 띠 안 물체가 `obstacle_stop_m` 안이거나 scan 이 `clearance_stale_s` 보다 오래되었거나 LiDAR 정지를 쓰는데 scan 이 없음; `BACK_AND_RETRY`: BACKING/SETTLING (back_active, D-717); 로컬 복구 꺼짐·시도 소진·뒤 여유 부족·LiDAR 사각·몸 기하 미설정·scan stale; `YIELD`: 구간이 없거나 유한하지 않음·거리 밖(0.05–2.0 m)·회전이 π 를 넘음·회전 여유 없음(`turn_blocked`)·보정 중·몸 기하 미설정·scan 없음·scan stale·선속도 한도 0. 앞에 동료가 있는 것만으로는 거절하지 않는다. 메시지에 사유 (D-407, v1.74; YIELD 는 D-453, v1.95) | 로봇 |
| `LINE_FOLLOW_ACTIVE` | 409 | 라인 추종이 켜져 있어 도킹/언도킹을 시작하지 않음 — `line-follow/mode` 를 `OFF` 로 먼저 (v1.18) | 로봇 |
| `IR_FALLBACK_NOT_READY` | 409 | 카메라 고장 상태, IR 라인 증거 최신성, 보정 revision, 또는 센서 안전 정책을 만족하지 못함 | 로봇 |
| `NO_ODOMETRY` | 409 | 오도메트리가 없어 언도킹 후진 거리를 잴 수 없음 (v1.18) | 로봇 |
| `RECORDING_BUSY` | 409 | Pilot 로봇 녹화가 진행 중이거나 manifest 해시를 끝내는 중(`stopping`) — 동시 녹화는 1개, 그동안 시작·수신 불가 (D-411, v1.83) | 로봇 |
| `RECORDING_NOT_ACTIVE` | 409 | 정지할 녹화가 없음 (`POST /recordings/active/stop`, D-411, v1.83) | 로봇 |
| `ROBOT_MOVING` | 409 | 녹화 수신은 정지 중에만: 살아 있는 MANUAL 입력 없음·NAVIGATION/DOCKING 아님·line-follow OFF·신선한 0 속도(또는 E-Stop; 0 은 인코더 틱 잡음 바닥 선 0.005 m/s·각 ≈0.0265 rad/s 이하, D-411 부록 17). MANUAL 모드 자체는 막지 않는다 (D-411, D-136 §6, v1.83) | 로봇 |
| `RECORDING_NOT_FOUND` | 404 | 없는 녹화 id, 안전하지 않은 id, manifest 없음·무효, manifest 와 다른 크기·폴더 밖·일반 파일 아닌 멤버 (D-411, v1.83) | 로봇 |
| `RECORDING_QUOTA_FULL` | 507 | 받지 않은(fetched 아님) 녹화로 전용 쿼터의 예비분까지 찼다 — 받아 가면 정리 대상이 된다 (D-411, v1.83) | 로봇 |
| `RECORDING_DISK_FULL` | 507 | 녹화 디스크의 빈 공간이 512 MiB 이하라 시작을 거부함 (D-411, v1.83) | 로봇 |
| `RECORDER_UNAVAILABLE` | 503 | 카메라 유닛 녹화기의 상태가 없거나 3 s 넘게 낡음, 서비스 무응답, 저장 디렉터리 없음·쓰기 불가, rosbag2 기동 실패 (D-411, v1.83) | 로봇 |
| `ROBOT_OFFLINE` | 503 | 대상 로봇 미접속 | Fleet |
| `HW_PROBE_UNAVAILABLE` | 503 | 장치 점검 요청 파일을 쓰지 못함 (`POST /host/hardware/refresh`, D-247) | 로봇 |
| `HW_TEST_COOLDOWN` | 429 | 부저·램프 시험을 10초 안에 다시 요청함 (`POST /host/hardware/test`, D-247 6, v1.23) | 로봇 |
| `HW_TEST_UNAVAILABLE` | 503 | 부저·램프 시험 요청 파일을 쓰지 못함 (`POST /host/hardware/test`, v1.23) | 로봇 |
| `HW_CONFIRM_UNAVAILABLE` | 503 | 들림·보임 기록을 쓰지 못함 (`POST /host/hardware/confirm`, v1.23) | 로봇 |
| `HW_CONFIRM_NO_TEST` | 409 | 그 장치를 `done`으로 5분 안에 끝낸 시험이 없는데 들림·보임을 답함 — 시험 없음·`busy`·`unavailable`·`failed`·다른 장치·5분 초과 (`POST /host/hardware/confirm`, v1.23) | 로봇 |
| `SSH_INVALID` | 422 | D-418 공개키(허용 종류·한 줄·base64)·라벨(`^[a-z0-9][a-z0-9._:-]{0,47}$`)·`expires_days`(1..365)·`minutes`(1..60)가 계약과 맞지 않음. `detail.fields`. root 도우미도 같은 규칙으로 다시 검사한다 (`/host/ssh/...`, v1.89) | 로봇 |
| `SSH_LABEL_EXISTS` · `SSH_KEY_EXISTS` · `SSH_KEYS_FULL` | 409 | D-418 같은 라벨이나 같은 공개키가 이미 있음, 또는 관리 키가 이미 32개 (`POST /host/ssh/keys`, v1.89) | 로봇 |
| `SSH_KEY_NOT_FOUND` | 404 | D-418 그 라벨의 관리 키가 없음 (`DELETE /host/ssh/keys/{label}`, v1.89) | 로봇 |
| `SSH_ACCESS_UNAVAILABLE` | 503 | D-418 root `rosy-ssh-access`가 10 s 안에 답하지 않았거나(요청은 거둬들인다), 요청 파일을 못 썼거나, 적용에 실패함(`chpasswd`·`sshd -t`·만료 타이머·파일 쓰기 실패, `keys.json` 손상 — 비밀번호는 켜지지 않은 채로 되돌린다) (`/host/ssh/...`, v1.89) | 로봇 |
| `COMMAND_TIMEOUT` | 504 | 명령 추적 타임아웃 (PRT-004) | Fleet |
| `PAIRING_INVALID` | 401 | 페어링 토큰 무효/만료 | Fleet |
| D-535 연결 이유 코드 (`ROBOT_UNREACHABLE` · `TLS_REQUIRED` · `TLS_NAME_MISMATCH` · `CA_UNKNOWN` · `CORE_NOT_READY` · `API_VERSION_TOO_OLD` · `PAIRING_UNAVAILABLE` · `PAIRING_REQUIRED` · `IDENTITY_CHANGED` · `LAN_REQUIRED` · `APPROVAL_PENDING` · `APPROVAL_CODE_WRONG` · `CONSOLE_APPROVAL_REQUIRED` · `APPROVAL_TIMEOUT` · `APPROVAL_CANCELLED` · `APPROVAL_EXPIRED` · `APPROVAL_DENIED` · `APPROVAL_REVOKED` · `RATE_LIMITED` · `SESSION_TAKEN` · `UNEXPECTED_RESPONSE`) | 경로의 기존 상태 그대로 | 연결·승인·세션이 안 된 이유. `/api/v1/auth/peer-pairing/*`·`/api/v1/auth/connection` 거절의 `error.code`이고, `error.message`(운영자 문장)와 `error.detail.action`(할 일)·`detail.retry`(`auto`\|`person`)를 싣는다. 기존 `detail` 필드는 본문 맨 위에 그대로 있다. 로봇에 닿지 못한 실패(이름·TCP·TLS)와 옛 로봇의 답은 클라이언트가 같은 코드로 분류한다. 기계 원천 `test/fixtures/protocol/connect-reasons.v1.json` = `core_common.protocol.connect_reason` (D-535, v1.155) | 로봇/클라이언트 |
| `IDEMPOTENCY_CONFLICT` | 409 | 동일 key·다른 내용 | Fleet |
| `INTERNAL_ERROR` | 500 | 내부 오류 | 로봇/Fleet |

---

# 4. 공용 데이터 모델

### 공용 Enum

| Enum | 값 |
|---|---|
| `mode` | `IDLE`, `MANUAL`, `NAVIGATION`, `DOCKING`, `EMERGENCY` |
| `navigation_state` | `IDLE`, `PLANNING`, `NAVIGATING`, `ARRIVED`, `CANCELED`, `FAILED`, `BLOCKED` |
| `health` | `OK`, `WARNING`, `ERROR`, `UNKNOWN` |
| `severity` | `info`, `warning`, `error`, `critical` |
| `command_priority` | 1=EMERGENCY, 2=SAFETY, 3=MANUAL, 4=DOCKING, 5=NAVIGATION, 6=FLEET, 7=IDLE |
| `fleet_policy` | `STOP`, `HOLD`, `RETURN_HOME`, `CONTINUE` |
| `dock_state` | `UNDOCKED`, `DOCKING`, `DOCKED`, `CHARGING`, `UNDOCKING`, `DOCK_FAILED` (v1.5 additive, DNC-004) |
| `line_follow_mode` | `OFF`, `IR_LINE`, `CAMERA_LINE` (v1.10 additive, D-143) |

**대소문자 표 (v1.16 additive)**: 위 표에서 UPPER 그룹(모드·내비·도킹·전원)은
`UPPER_SNAKE`, lower 그룹(심각도·배터리·프레즌스·군집 역할·참조 소스)은
`lower_snake`다. 두 관례가 공존하는 것은 역사적 사실이고 이 표가 계약이다 —
신규 enum 은 자기 그룹의 관례를 따르고, 소비자는 대소문자를 그대로 비교한다.
(ROS `power/mode` 토픽은 예외로 소문자 값을 실으며 JSON 과 다르다.)
`safety_policy.mode`·`mode_effective`·`safety.shadow_verdict.verdict` 는 소문자이고
config `control.sensor_adapter.mode` 와 같은 문자열이다(D-400). 일반 문자열이며 enum 검증을
하지 않으므로 값을 더하는 것은 additive 다.

### 좌표·계측

```json
{ "pose": { "x": 1.82, "y": 3.21, "yaw": 0.73 },
  "velocity": { "linear": 0.12, "angular": 0.0 },
  "battery": { "percent": 81, "voltage": 11.9 } }
```

`yaw`는 radian. 타임스탬프는 UTC ISO 8601.

`battery.percent` 와 `battery.voltage` 는 `number | null` 이다. `null` 은 아직 읽은 값이 없다는
뜻이다(CORE-only 처럼 배터리 출처가 없는 런타임 포함). 결측은 0% 가 아니다 — 소비자는 `null` 을
0 으로 바꿔 경보를 내지 않는다(D-82 Law 0, v1.18).

---

# 5. Robot REST API 카탈로그

로봇(rosy_core)이 제공하는 엔드포인트. Base: `http://<robot-host>:8080`

## 5.1 System

| Method | Path | Role | 요구사항 |
|---|---|---|---|
| GET | `/api/v1/system/info` | Viewer | IDN-003. `caller_role`(v1.18 additive) — 이 요청 토큰의 역할(`viewer`\|`operator`\|`administrator`). 대시보드는 이것으로 관리 패널을 가르고, 권한 밖 경로를 찔러 보지 않는다. `robot_name` 은 오버레이에 이름이 없고 기본값(`Rosy 01`)뿐이면 프로비저닝 신원(`ROSY_DEVICE_NAME`, 없으면 `Rosy NN` ← `ROSY_ROBOT_NUMBER`)에서 온다. `device_uid`(v1.150 additive)는 프로비저닝 UID이며 없으면 null. `serial_number`는 설정값이 없고 UID가 있을 때 Pi `/proc/cpuinfo`의 Serial을 읽으며, 못 읽으면 null이다. 두 값은 등록 일관성 확인용이며 물리 차체 위치 증거가 아니다 |
| PUT | `/api/v1/system/info` | Admin | IDN-003 (payload: `{robot_id?, robot_name?}`) — 로컬 오버레이에 영속 |
| GET | `/api/v1/system/capabilities` | Viewer | CAP-001. 지킬 수 있는 것만 광고한다(D-32) — §9.1 `withheld`, `runtime`(v1.21), `controls`(v1.87, D-411): `rosy.controls/1` `{schema, items[]}` — Pinky는 adapter `provides`의 `drive`(manifest가 없으면 `teleop`)에서 `base_velocity` 하나. 스키마 정본 `core_common.protocol.controls`. `line_follow`(v1.195, D-604, line-follow 서비스가 있을 때만): `{camera: {available, age_ms, source}}` — 차선 카메라(앞 카메라) 상태. `GET /vision/front/status`와 같은 저장소의 `available`·`age_ms`, `source`는 `DEVICE`·`GAZEBO`(미리보기 라벨 `GAZEBO`)·`NONE`(프레임 없음) |
| GET | `/api/v1/system/runtime` | Viewer | ROS-102 — 호스트 OS/CPU/RAM/디스크/온도 + 읽기 전용 ROS 그래프 스냅샷 |
| GET | `/api/v1/system/tokens` | Admin | SEC-101 — `{id, role, label, created_at, legacy, expires_at, source, current, last_used_at}`. `current` 는 호출자 자신의 토큰, `last_used_at` 은 CORE 가 켜진 뒤 마지막 인증 시각(메모리, 없으면 null). 만료된 토큰은 빠진다. 토큰에서 유도된 값은 싣지 않는다 |
| POST | `/api/v1/system/tokens` | Admin | SEC-101 (payload: `{role, label?, token?}`) — `token` 을 비우면 서버가 생성해 응답에 **단 한 번** 싣는다. 직접 정하면 16자 이상. 응답은 `Cache-Control: no-store`. 만료가 있는 호출자(페어링 세션)는 403 — 만료 없는 토큰을 만들 수 없다(D-193 보안 리뷰) |
| DELETE | `/api/v1/system/tokens/{id}` | Admin | SEC-101 — 호출자 자신의 토큰(400)과 만료 없는 마지막 administrator(409) 는 거부. 만료가 있는 administrator 는 세지 않는다(D-193). 만료가 있는 호출자가 만료 없는 administrator 를 지우려 하면 403 |
| PATCH | `/api/v1/system/tokens/{id}` | Admin | SEC-101 (payload: `{label}`, 64자 이하) — 이름표만 바꾼다. 응답은 목록 항목 한 개. 없거나 만료된 id 는 404 (v1.19) |
| POST | `/api/v1/auth/pair` | 없음 | D-193 (payload: `{code, label?}`, 본문 1 KiB 이하, 넘으면 413) — 로그인 코드 `ABCD-EFGH`(하이픈·대소문자 무시) → `201 {id, token, role, label, source, expires_at}`, `Cache-Control: no-store`. 원문 토큰은 이때 한 번만 싣는다. 출발지는 RFC 1918·루프백만(그 밖 403), IP 마다 60 s 5회·전체 60 s 30회(넘으면 429 + `Retry-After`). 형식이 아닌 코드는 400, 틀리거나 만료·사용된 코드와 발급된 코드가 없는 경우는 모두 같은 401 이다. 한 코드에 틀린 시도가 5회 쌓이면 코드를 폐기하고, 그 5번째 요청의 401 만 `error.detail = {"burned": true}` 를 싣는다(대시보드가 새 코드를 받으라고 안내한다) 토큰 수명은 `auth.pairing.token_lifetime_hours`(기본 operator·viewer 168 h, administrator 24 h, 설정해도 168 h 를 넘지 않는다) — 만료 없는 토큰은 나오지 않는다 |
| GET | `/api/v1/auth/whoami` | Viewer | D-193 — `{id, role, label, source, created_at, expires_at}`. 대시보드가 역할을 추측하지 않고 묻는다 |
| GET | `/api/v1/ui/surfaces/{surface}` | Viewer+ | D-263/D-265/D-283 — 역할별 화면 매니페스트. `console`/`setup`/`device`; 해당 화면 최소 역할보다 낮으면 403, 인증 실패 401, 미등록 화면 404. 응답은 현재 역할이 열 수 있는 기반 화면 목록과 현재 화면의 CAP-001·inventory 필터 패널, 구조 revision이다. console act 패널은 선택형 `action_group` (`drive`, `docking`, `line_follow`)을 담을 수 있으며, capability가 없거나 `not_provided` inventory인 panel과 그룹은 응답에서 생략한다. 메뉴는 패널 수와 독립이다. REST 응답 모델 `UiSurfaceManifest`; Fleet envelope `protocol_version`은 1.0 유지 |
| POST | `/api/v1/auth/logout` | Viewer | D-193 — 호출자 자신의 `pair-*` 토큰을 지운다(204). 다른 출처의 토큰은 409 — 설정 화면에서 회수한다 |
| POST | `/api/v1/auth/enrollment-codes` | Admin | D-193 (payload: `{role}`, 기본 `operator`) — 다른 기기용 로그인 코드 `201 {code, code_id, role, expires_in_s}`, 5분, CORE 메모리에만. 역할은 호출자 이하(넘으면 403). 이 코드로 받은 토큰의 출처는 `pair-admin` 이고 만료는 발급자 토큰의 만료를 넘지 않는다. 발급자 토큰이 회수·만료되면 코드도 무효다 |

## 5.2 Robot 상태·센서

| Method | Path | Role | 요구사항 |
|---|---|---|---|
| GET | `/api/v1/robot/state` | Viewer | CORE-001 — payload는 §6.1과 동일 |
| GET | `/api/v1/robot/pose` | Viewer | §12 센서 |
| GET | `/api/v1/robot/battery` | Viewer | §12 |
| GET | `/api/v1/robot/velocity` | Viewer | §12 |
| GET | `/api/v1/sensors` | Viewer | §12 |
| GET | `/api/v1/sensors/{lidar\|imu\|ultrasonic\|battery\|encoder\|motor}` | Viewer | §12. 표본이 없으면 404 `NOT_FOUND`. 예외로 `battery` 는 404 를 내지 않는다(D-502, v1.120): 200 `{voltage, received_at, source, evidence, sample_age_s, stale_after_s}`. `evidence` 는 `missing`\|`fresh`\|`stale`(`GET /power/health` 의 `battery` 와 같은 판정, 5 s), 표본이 없으면 `voltage`·`received_at`·`source` 는 `null`. 배터리 모니터가 없는 런타임은 `evidence: missing`, `stale_after_s: null`. 제품 그래프의 표본은 `battery/voltage` 에서 오며 `source: "battery/voltage"` 다(D-192 4). 벤치의 `batt_state` 표본은 기존 필드 `percentage`·`power_supply_status`·`location` 을 더 싣는다. 두 토픽이 함께 돌면 마지막으로 온 표본이 이기므로 이 세 필드는 나타났다 사라진다 — 소비자는 있을 때만 읽는다 |
| GET | `/api/v1/power` | Viewer | PWR-001 (절전 모드·프레즌스·샘플링 주기) |
| GET | `/api/v1/power/health` | Viewer | 전원 정책·절전 blockers·wake 제약·배터리 age/신선도/충전 확인·health 조회. 읽기 전용이며 깨우지 않음 |
| POST | `/api/v1/power/wake` | Operator | PWR-004 (원격 웨이크 — 정보 화면 표시) |
| POST | `/api/v1/power/mode` | Operator | PWR-001 (payload: `{mode: ACTIVE\|IDLE\|STANDBY}`) |

`GET /sensors`·`GET /sensors/{type}` 의 숫자 값 가운데 유한하지 않은 값(`inf`·`-inf`·NaN)은 JSON 에 없으므로 `null` 로 나간다. LiDAR `ranges` 의 반환 없는 빔(+inf)과 NaN 이 `null` 이며, 값이 있는 빔과 구분된다(`robot_body.scan_view` 와 같이 반환 없음 = 알 수 없는 구간). 필드 이름·형식은 그대로이고 CORE 내부 표본은 inf 를 유지한다.

`GET /power/health` 응답은 공유 `core_common.protocol.power_health.PowerHealthResponse` 계약이다. `power`는 기존 `PowerStatus`, `health`는 진단 요약이며 조회가 idle timer나 wake를 변경하지 않는다.

| 영역 | 필드와 해석 |
|------|-------------|
| `battery` | `evidence`: missing/fresh/stale; `sample_age_s`, `stale_after_s`(5초), `level`, `percent`, `filtered_voltage`. 낡은 전압·잔량은 마지막 관측값이며 현재 측정으로 사용하지 않는다. |
| 충전·종료 | `charging_state`: confirmed/unconfirmed. 전압과 충전 확인이 모두 5초 이내일 때만 confirmed; `charging_evidence_age_s`와 `charging_latched`는 마지막 확인의 age와 기존 정책 latch를 구분한다. `shutdown_armed`는 정책 조건, `shutdown_request_written`는 sentinel 기록이며 실제 OS 종료 완료가 아니다. |
| 잔여 시간 | `remaining_runtime_s`는 null, `remaining_runtime_reason`는 current_and_capacity_not_measured. 전류·용량 측정 없이 시간을 추정하지 않는다. |
| `policy` | `sleep_blockers`: power_policy_disabled/robot_mode_not_idle/information_hold; `deepest_available_mode`는 ACTIVE 또는 STANDBY 정책 상한(`deepest_mode_basis=policy_target`). 물리 절전 인증이나 POST 권한·보정 lease 허용을 뜻하지 않는다. `idle_after_s`, `standby_after_s`는 정상 설정(기본 600/1800초), `effective_idle_after_s`, `effective_standby_after_s`는 현재 적용 기준이다. warning은 60/300초, critical/deep은 30/120초 기본이며 정상 기준과 min을 취한다. `battery_alert` 포함. |
| 깨우기 | `wake_sources`는 api/proximity/contact/activity/battery_level_change 정책 처리기(`wake_sources_basis=policy_supported_not_hardware_verified`). contact는 초음파 거리 임계값이며 별도 접촉 스위치 확인이 아니다. `api_wake_requires_running_os=true`, `os_halt_remote_wake=not_verified`. |
| LiDAR | `lidar_standby_stop_enabled`는 설정이며 `lidar_state_basis=policy_intent`. 실제 모터 정지 증거와 구분한다. |
| 권고 | `recommendation`: 배터리 missing/stale이면 restore_battery_telemetry; fresh 경고이면 charge_and_conserve; fresh 정상은 normal_idle_policy. 권고는 자동 운전·종료 명령이 아니다. |

## 5.3 Navigation·SLAM

| Method | Path | Role | 요구사항 |
|---|---|---|---|
| POST | `/api/v1/navigation/goal` | Operator | NAV-001 (`{x,y,yaw}` 또는 `{waypoint}`; 선택적 `correlation_id`는 Fleet dispatch 시도 ID와 실행 이벤트를 잇는 추적 메타데이터). 기능 보류 시 모드 전이 전에 409 `CAPABILITY_WITHHELD`. D-395 로봇이 `LOCALIZED` 가 아니면 409 `NOT_LOCALIZED` (v1.72) |
| POST | `/api/v1/navigation/goal/lease` | Operator | D-550 10 (v1.160, Safety-Review). Fleet 목표 임대 갱신 `{correlation_id (1–128자), ttl_s (0 < s ≤ 5, 유한)}` → `{renewed: true, correlation_id, ttl_s}`. `POST /navigation/goal` 선택 필드 `lease_ttl_s`(0 < s ≤ 5, 유한, `correlation_id` 필요; 어기면 모드 전이 전에 400 `VALIDATION_ERROR`)로 연 임대를 늘린다. 활성이 아니거나(취소·도착·실패·만료·교체된) 임대 없이 연 `correlation_id`는 409 `GOAL_LEASE_NOT_ACTIVE`이고 목표를 되살리지 않는다. 그 목표(`POST /navigation/goal`·`/navigation/home`)를 보낸 토큰이 아닌 토큰의 갱신은 403 `FORBIDDEN`이다(D-760 9항): 임대와 목표는 그대로이고 목표는 제 만료 시각에 끝난다. 활성 여부를 먼저 보므로 끝난 목표는 어느 토큰이든 409다. 비교는 토큰 id다: 공유 개발 토큰(D-548 `rosy-dev-operator`)은 쓰는 모두가 한 id라 서로의 임대를 갱신할 수 있다. 계정 세션이 갱신 중에 새 토큰으로 바뀌면 그 뒤의 갱신은 403이고 로봇은 임대 만료에 선다(Fleet은 403에서 그 임대를 놓는다). 만료하면 5 Hz 전원 타이머가 SAF-003 STOP과 같은 취소 경로로 목표를 취소한다(`nav.canceled` source `goal_lease`). 만료는 `fleet_loss_policy`와 관계없이 STOP이다: 임대가 먼저 끝나면 SAF-003은 지킬 목표가 없어 `safety.fleet_lost`를 내지 않는다(D-550 10). `ttl_s`는 CORE 단조 시계. 능력 `controls` `base_velocity.goal_lease: true`(목표 주행이 있을 때)일 때만 Fleet이 쓴다. `lease_ttl_s`가 없는 목표는 지금과 같다 |
| POST | `/api/v1/navigation/cancel` | Operator | NAV-002 |
| POST | `/api/v1/navigation/home` | Operator | NAV-003. 기능 보류 시 409 `CAPABILITY_WITHHELD`. D-395 로봇이 `LOCALIZED` 가 아니면 409 `NOT_LOCALIZED` (v1.72) |
| GET | `/api/v1/navigation/state` | Viewer | NAV-004. `mapping_active: bool`은 CORE가 수락한 맵핑 세션 상태다. SLAM Toolbox의 실제 실행·지도 갱신 성공을 증명하지 않는다. |
| GET | `/api/v1/navigation/path` | Viewer | MAP-003. `{poses}`; 경로 메시지를 받은 뒤에는 `map_id`(그때 로봇 지도 ID 또는 null), `frame_id`(`nav_msgs/Path.header.frame_id` 또는 null), `age_s`(CORE 수신 뒤 경과 초, 서버 monotonic 시계)를 함께 반환한다. 최초 수신 전은 `{poses: []}`. 이 응답은 마지막 수신 계획이며 현재 목표와의 동일성은 증명하지 않는다. |
| GET | `/api/v1/line-follow/perception` | Viewer | 저장된 `paint_source`(threshold / denoise / learned), `camera_lane_mode`, 서명·해시 확인 `model_ready`와 `model_revision`. 별도 `applied_paint_source`는 실제 최신 keeper 프레임의 threshold / denoise / learned / denoise_fallback 또는 null; `applied_source_age_s`는 monotonic 수신 나이(2초 이내), `applied_model_revision`은 실제 사용한 learned mask의 producer revision(없으면 null). stale·malformed·설정 불일치·재시작 전 증거는 null. 운전 모드와 독립이며 물체 검출이나 주행 허가가 아니다. |
| PUT | `/api/v1/line-follow/perception` | Administrator | `{paint_source: threshold\|denoise\|learned}`만 허용. IDLE·line-follow OFF·보정 비활성, Host Agent가 fresh 정지 및 active mission 부재를 재확인. 기존 기하 보존, learned는 고정 signed model pointer 검증, camera만 재시작·실패 복구. `applied: true`는 설정/서비스 적용이며 live 추론이나 실제 주행 성공이 아니다. |
| GET | `/api/v1/line-follow` | Viewer | D-143 — 선택 모드, 상태, 증거 신뢰도·나이, 최종 선속도·각속도와 사유. `clearance_m`(정면 LiDAR 최소 거리, 없으면 null)과 정지 사유 `obstacle_ahead`·`obstacle_sensor_stale`·`driver_released` (D-344, v1.63). IR 이탈 감시(`line_follow.ir_guard_enabled`)가 켜지면 추종 사유 `lane_edge_left`·`lane_edge_right`(경계 반대로 비킴)와 정지 사유 `lane_departure`·`lane_guard_stale` (D-344 §12, v1.63). 감시가 알려진 횡단보도 구간(D-491)에서 쉬면 추종 사유 `ir_guard_crosswalk` (v1.115). 공칭 지면(`ground: NOMINAL`) 카메라 증거는 `hold_s` 세션이 없으면 `nominal_ground_requires_driver` 로 멈춘다 (D-364 §3, v1.63). 정지 사유 `limit_level_too_low`(수동 한도 L1 미만)·`angular_limit_zero`(각속도 한도를 읽을 수 없음) (D-344 §13, feat/device-prep, v1.64). 몸 기준 정지(D-422, v1.84: `obstacle_mode: path` + 로봇 패키지 URDF 몸 기하)에서는 `body_gap_m`(의도한 차선 호를 따라 몸 윤곽이 닿기까지의 거리, 없으면 null)·`stop_gap_m`(그 속도의 정지 간격)·`clearance_source`(`lidar`·`memory`(LiDAR `range_min` 아래로 사라져 기억한 반환)·`ultrasonic`·`odometry_lost`(바퀴 값 적분 실패 — 다음 스캔까지 정지), 아무것도 없으면 null)가 오고 `clearance_m` 은 `body_gap_m` 과 같은 몸 간격이다. 그 밖에는 세 필드 모두 null. 선택 필드 `lane_return_containment`(D-507 7, v1.133, 개정 v1.134): D-468(`recovery_local_enabled`)이 추종 중일 때 `contained`(차로 안이 증명됨) 또는 `unknown`(증명 못 함 — D-468은 멈추지도 움직이지도 않고 추종은 `recovery_local_enabled: false` 와 같다), 그 밖에는 null. D-468 이탈(`lane_return_*`)은 양의 증거가 있을 때만 열린다: (1) 신선한 `ready` 차로에서 몸이 경계를 넘음(`margin + uncertainty_m < 0`), (2) 추종 중 자세 불연속(odom 점프) 또는 연속성 epoch 변경, (3) 증명된 차로 안이지만 체크포인트 차로가 아님. 차로가 보이지 않은 채 D-476 bridge 가 끝나면 D-468은 역추적하지 않고 손실 경로(LOST)로 간다. D-517 4 (v1.143): CORE 가 통행권을 강제하는 동안에만 `authority {state: FREE\|HOLDING\|EXPIRED\|NONE, authority_id, leg_id, remaining_m, expires_in_s, reason}` 가 붙는다(`POST /line-follow/authority`). 강제하지 않으면 이 키가 없고 응답은 이전과 같다. 이 응답에만 있고 상태 스냅숏 `line_follow` 에는 없다 D-573 6 (v1.179, 개정 v1.194): `crosswalk` 는 게이트 설정과 무관하게 늘 있다. 게이트(`line_follow.crosswalk_gate_enabled`, 기본 false)가 무장한 구역 안이면 `{state: armed|approaching|looking|waiting|crossing, zone_id, source: camera, reason: person_present|look_unknown|sensor_stale|zone_lost|null, waiting_s, look_progress}`. 그 밖에는 (v1.194) `{state: inside}`(이 odom epoch의 D-491 카메라 구역이 몸 또는 D-407 후진 범위의 반지름 `hypot(max(body_front_x_m, recovery_back_m − body_rear_x_m), body_half_width_m)` 안), `{state: ahead}`(같은 길에서 구역이 아직 앞), `{state: unknown, reason: pose_stale|perception_stale|not_watched|camera_crosswalk_unadmittable|zone_unplaced}`(CORE가 알 수 없음: 최근 카메라 프레임의 `containment.crosswalk_uncertainty_m` 이 없거나 `line_follow.crosswalk_max_uncertainty_m` 초과면 `camera_crosswalk_unadmittable`, odom 자세 0.3 s 초과, 그 모드의 카메라 관측이 `stale_after_s` 초과·모드 OFF, 이 epoch에 경계와 한도 안 불확실도를 가진 카메라 프레임이 없었거나, 끊김 없는 그런 프레임 구간 안에서 몸 뒤끝 + `recovery_back_m` 이 카메라가 본 가장 가까운 땅까지 아직 오지 못했거나, 마지막 그런 프레임 뒤 그 프레임의 가장 가까운 땅보다 멀리 움직임·URDF 몸 모름, 구역을 odom에 아직 놓지 못했거나 한 epoch에 64개 초과), 아니면 null(몸과 후진 범위가 카메라가 본 땅 위이고 어느 구역에도 닿지 않음). `inside`·`ahead`·`unknown` 의 `zone_id`·`waiting_s`·`look_progress` 는 null, `source` 는 `camera`. 키가 없으면 이전 CORE 다. Fleet D-577 R3 는 null 에서만 열리고, `unknown`·키 없음은 R5 `crosswalk_unknown`, 그 밖은 R5 `crosswalk`. Fleet은 현장 지도 `crosswalks[]` 를 기준으로도 본다: 신뢰 지도 자세가 다각형에서 0.29 m 안이면 R5 `crosswalk`, 지도에 횡단보도가 있는데 신뢰 지도 자세가 없거나 출처 없는 `UNKNOWN` 이면 R5 `crosswalk_unknown`. 게이트가 세우면 `state: HOLD`, `reason` `crosswalk_looking`·`crosswalk_person_present`·`crosswalk_look_unknown`·`crosswalk_sensor_stale`·`crosswalk_zone_lost`. D-760 개정 3 9항 (v1.227): `regulation_wait` 는 그 틱에 로봇을 세운 규제 `authority|signal|crosswalk_held|crosswalk_wait|crosswalk_look` 또는 null(꺼짐·규제 없음), 우선순위는 그 순서이고 상태 스냅숏 `line_follow` 에도 있다. |
| PUT | `/api/v1/line-follow/mode` | Operator | D-143 — `{mode: OFF\|IR_LINE\|CAMERA_LINE, hold_s?}`. 소스는 상호 배타적이며 변경 즉시 이전 증거와 명령을 폐기. 도킹/언도킹 중에는 409 `DOCKING_ACTIVE` (v1.18). 요구 능력은 구동(`mobility.move`)이다 — Nav2 가 없는 `motor` 런타임에서도 켜진다(D-344 §7, v1.63). `hold_s`(0 < s ≤ 2)를 주면 운전자 확인 세션이다: `POST /line-follow/hold` 가 그 안에 계속 와야 하고, 끊기면 CORE 가 스스로 OFF(`reason: driver_released`)로 내리고 바퀴 명령을 지운다(D-344 §8, v1.63). OFF 가 아닌 모드는 D-395 로봇이 `LOCALIZED` 가 아니면 409 `NOT_LOCALIZED` (v1.72) |
| POST | `/api/v1/line-follow/hold` | Operator | D-344 §8 — 운전자가 "진행"을 누르고 있다. 활성 `hold_s` 세션의 만료를 `hold_s` 만큼 미룬다. 세션이 없으면 409 `LINE_FOLLOW_NOT_HELD` (v1.63) |
| POST | `/api/v1/line-follow/junction` | Operator | D-494 4항 (v1.114) — 다음 교차로 하나에 대한 지시 `{action: straight\|left\|right\|stop, place_id, stop_after_m?, expires_s, turn_deg?, advance_m?}`. `expires_s` 0 < s ≤ 30, `stop_after_m` 0 ≤ m ≤ 2 이고 `stop` 에만 쓴다(아니면 400 `VALIDATION_ERROR`). 지시는 하나만 보관하고 새 지시가 바꾼다. 응답 `{accepted, junction_seq, state}`. 회전 동작 중에 온 새 지시는 그 동작을 `aborted` 로 멈추고 자신은 받지 않는다(`accepted: false`). 모드를 바꾸지 않는다. line-follow 가 OFF 면 409 `LINE_FOLLOW_NOT_ACTIVE`, `IR_LINE` 이면 409 `JUNCTION_CAMERA_ONLY`(IR 에는 교차로 감지가 없다, D-495 검토 M4). "seat" 는 D-460 의 기존 어휘라 다른 구동 경로처럼 수동 조종 해제(409 `MODE_CONFLICT`)와 보정 lease(409 `CALIBRATION_ACTIVE`)를 지킨다. 회전 동작 중 같은 지시(`place_id`·`action`·`turn_deg`·`advance_m`)의 재전송은 지금 seq·상태를 돌려주는 무동작이다. 이미 실행된 지시의 반복은 409 `JUNCTION_ALREADY_DONE` 이다. 한 교차로 정지 안의 모든 회전은 그 교차로를 처음 본 순간의 진입 yaw + `turn_deg` 를 겨눈다(중단 뒤 재전송이 방향을 더하지 않는다). CORE 는 자기 차선 명령을 그대로 두거나 0 으로 만들 뿐이다. 오늘 인식은 분기 후보를 주지 않으므로(D-494 구현 부록 2026-10-07) `turn_deg` 없는 `left`·`right` 는 받자마자 `unresolved` 이고 HOLD `junction_unresolved` 다. D-495: `turn_deg`(부호 있는 각도, `left` 는 +, `right` 는 −, 0 < \|θ\| ≤ 150)와 `advance_m`(0–0.30, 기본 0.10, `turn_deg` 와만)가 있으면 `armed` 이고, 교차로가 감지되면 CORE 매니저가 정지 확인(odom \|v\| < 0.01 m/s·\|ω\| < 0.05 rad/s 0.2 s, 사유 `junction_stopping`) → 제자리 회전(`turning`, odom yaw 닫힌 고리, 각속도 ≤ 수동 한도, `\|오차\| ≤ max(5°, ω·junction_turn_lead_s)` 에서 멈춘 뒤 ±5° 안 0.3 s 머무름과 odom 정지 확인, 한도 \|θ\|/ω_min + 2 s) → 직진(`advancing`, `advance_m`, 속도 ≤ trip 최고 속도의 절반, 한도 `advance_m`/속도 + 2 s) → 차선 다시 잡기(`reacquiring`, 0.20 m 또는 5 s 안에 연속 `junction_reacquire_frames`(기본 3)장의 신뢰도 기준 이상 visible 프레임, containment 방향이 있으면 돌린 방향 ±30° 안, 못 잡으면 `unresolved`)를 한다. 회전·전진 중 상태는 `RECOVERING` 에 사유 `junction_stopping`·`junction_turning`·`junction_advancing` 이다. odom 낡음·점프, 모드 변경·E-Stop, 보정 lease, D-422 근접 정지, 동작 확인 실패·미바인딩, D-498 현장 근거로 시작한 회전에서 그 근거를 잃음(`turn_basis_lost`, v1.118), 정지 확인 실패, 교차로 전에 시작된 차선 손실(`lane_lost_before_junction`), 시간 초과, 다른 새 지시는 즉시 0 명령과 `aborted`(HOLD `junction_aborted`, `junction.reason` 에 이유)다. `aborted` 는 다음 지시나 모드 변경까지 이어진다. `straight` 는 `armed` 이고 D-476 bridge 방향 힌트를 채운다. `stop` 은 측정한 odom 으로 `stop_after_m` 뒤 또는 교차로 감지 중 먼저 오는 쪽에서 HOLD `junction_stop` 이며(odom 이 없으면 바로) 다음 지시나 모드 변경까지 이어진다. 교차로 감지는 keep 모드 keeper 의 교차로 HOLD 사유(`line/keep_debug` `reason`: `junction_transverse`·`junction_fork`, `lane_corner_turning` 이 켜졌을 때만 — D-495부터 로봇 기본값 켜짐)뿐이다. 감지됐는데 지시가 없거나 `armed` 지시가 만료됐으면 HOLD `junction_waiting` 이고 다음 지시까지 잠근다. 상태는 `GET /line-follow` 와 스냅숏 `line_follow.junction {pending_action, place_id, state: idle\|armed\|executing\|waiting\|unresolved\|turning\|advancing\|reacquiring\|aborted, seq, turn_deg, reason}`. D-507 2–4항 (v1.127, `junction_pivot` 능력이 참인 로봇에만 보낸다): 선택 필드 `map_id`(`^[A-Za-z0-9_.-]{1,64}$`, 지시를 계산한 지도. 기대 창 누락 시 감지를 거절하는 표지이며, 현장 바닥 선언(D-507 9항)과 운동 허가 시 대조한다), `expect_in_m`(0 < m ≤ 2, 보낼 때 로봇 자세에서 장소까지 차로를 따른 거리), `expect_tol_m`(0 < m ≤ 0.30, 장소 위치 오차), `pivot_past_line_m`(−0.30 ≤ m ≤ 0.30, v1.135부터 부호 있음: 감지된 가로선에서 회전 축(장소 점)까지, 장소가 선 너머면 양수, 선 앞이면 음수(회전교차로 입구·T자에서 keeper가 재는 먼 쪽 경계), `straight` 또는 `turn_deg` 가 있는 `left`·`right`. `straight` 에서는 기대 창에만 쓰고 접근하지 않는다). `expect_in_m` 과 `expect_tol_m` 은 함께 보낸다. 범위·짝이 틀리면 400 `VALIDATION_ERROR` 다. 기대 창 필드가 있는데 지시를 받는 순간 신선한 odom(0.3 s)이 없으면 409 `JUNCTION_ODOM_STALE` 이다. map_id도 기대 창도 없는 옛 지시는 오늘 동작 그대로다. map_id가 있는데 기대 창이 빠진 straight·회전 지시는 가로선 감지 시 HOLD junction_unexpected이고 지시는 armed로 남는다(D-507 3항 보충, 2026-10-08); Fleet은 trip을 중단한다. 모서리 정지(v1.148, lap SIM A): 기대 창이 있는 지도 지시가 `armed` 이고 감지가 없을 때, `line/keep_debug` `strategy` 가 `corner_left`·`corner_right`(최근 2 s 안 한 프레임)이고 기대 가로선이 0.45 m + `expect_tol_m` 안이면 keeper 의 모서리 회전 대신 HOLD `junction_corner_hold` 다(지시는 `armed`, 창을 측정할 수 없으면 HOLD). 2 s 동안 모서리 프레임이 없으면 풀린다. 이 정지 중에 지시가 만료되면 풀지 않고 새 지시나 모드 변경까지 HOLD `junction_corner_hold` 로 남는다(fail closed). Fleet 은 자기 지시에서 이 사유를 보면 trip 을 바로 끝낸다. 모서리 방향 범위(v1.152, lap SIM 2): 지시와 어긋나는 모서리만 정지한다. `left`·`right` 는 반대쪽 모서리(`left` 에 `corner_right`, `right` 에 `corner_left`)만, `straight` 는 선택 필드 `lane_turn_deg`(지도 차로가 로봇에서 장소까지 도는 부호 있는 방향 변화, 도, 왼쪽 +, −360 ≤ θ ≤ 360, `straight` 이고 기대 창이 있을 때만, 아니면 400 `VALIDATION_ERROR`)가 그 모서리 쪽으로 20° 이상이 아닐 때만 정지한다(왼쪽으로 도는 회전교차로 둘레의 `corner_left` 는 차로다). `lane_turn_deg` 가 없으면 모든 모서리에서 정지한다(옛 Fleet, 이 필드를 모르는 옛 CORE 는 무시하고 v1.148 그대로). Fleet 은 기대 창을 보내는 `straight` 에 늘 싣는다. stop은 이 창을 쓰지 않는다. 기대 창(v1.139부터 주행 거리, 2026-10-08 사용자 결정): 기대 값은 차로를 따른 거리 `expect_in_m − pivot_past_line_m`(`junction_fork` 감지면 `expect_in_m`, 필드가 없으면 0을 뺀다)이다. 받은 순간의 odom 전진 거리 누적값(매 걸음을 앞 자세의 yaw 에 투영한 부호 있는 합)을 기록하고, 감지마다 측정값 = 받은 뒤 감지 때 odom 자세까지 전진 거리 + `line/keep_debug` `junction_ahead_m` 이다. 받은 뒤 전진 거리가 봉우리에서 0.01 m 넘게 내려가면(후진) 창 밖이다. `straight`·회전 지시는 \|측정 − 기대\| ≤ `expect_tol_m` 일 때만 쓰인다. 곧은 접근에서는 v1.139 이전의 곧게 내다본 점 비교와 같은 값이고, 굽은 접근(회전교차로)에서도 쓸 수 있다. 창 밖이거나 측정할 수 없으면(`junction_ahead_m` 없음, odom 끊김·epoch·frame 변경) HOLD `junction_unexpected`, 상태 `unexpected` 이고 지시는 `armed` 로 남는다(감지가 사라지거나 창 안의 감지가 오면 `unexpected` 가 풀린다). `stop` 지시는 창을 쓰지 않는다. 회전 축 접근: 회전 지시에 `pivot_past_line_m` 이 있고 가장 최근 감지가 `junction_ahead_m` 을 실었으면, 정지 확인 뒤 `approaching`(사유 `junction_approaching`)으로 그 감지(같은 odom 궤적에 고정, 나이 무관)의 가로선 점에서 진입 yaw 방향으로 `pivot_past_line_m`(`junction_fork` 면 0) 더 간 점까지 진입 yaw 를 붙잡고 직진한다. 그 점이 로봇 자리이거나 뒤면 접근 거리 0으로 그 자리에서 회전하고 뒤로 가지 않는다. 속도는 `advancing` 과 같고, 한도는 거리/속도 + 2 s, 중단 규칙·운동 근거·D-422 검사도 `advancing` 과 같다. 도착 뒤 정지 확인을 다시 하고 회전한다(목표는 그대로 진입 yaw + `turn_deg`). IR 가드가 켜진 현장 근거에서 접근과 `straight` 통과 중의 IR `centre` 는 측정 가로선 띠 안에서만 허용한다: 띠는 감지 자세 + `junction_ahead_m` 에 odom 으로 고정하고 진입 방향으로 [선 − 테이프 폭/2 − e, 선 + 테이프 폭/2 + e](선은 측정한 테이프 중심, 테이프 폭 0.025 m, v1.135), 옆으로는 ±(반폭 + e)다. 반폭은 지시의 `pivot_past_line_m` 이 양수일 때 그 값, 아니면(없거나 0 이하) D-491 통로 반폭 0.10 m 다. e = `crosswalk_range_error_fraction`·`junction_ahead_m` + `crosswalk_odom_error_fraction`·min(감지 뒤 odom 이동, `junction_ahead_m` + 테이프 폭)이며, IR 줄은 자세 + `ir_row_x_m` 이다. IR 줄이 먼 끝을 지나거나 감지 뒤 이동이 `junction_ahead_m` + 테이프 폭/2 + e 를 넘으면 띠는 끝나고, 모드 변경·정지·다음 지시에서도 끝난다. 띠 밖의 `centre` 는 지금처럼 중단(`turn_basis_lost`, 통과 중이면 `lane_departure`)이고, odom 궤적이 바뀌면 띠가 사라진다. 회전 중에는 띠를 쓰지 않는다. `junction.pivot_basis` 는 접근했으면 `map`, 멈춘 자리에서 돌면 `stop_point`, 회전 전에는 null 이다. 상태 목록에 `approaching`·`unexpected` 를 더한다. D-507 보충 (v1.142, `lane_bend` 능력이 참인 로봇에만 보낸다): `action: bend` 는 지도의 굽이 장소 하나를 odom 호로 지나는 지시다. 필수 `turn_deg`(부호 있는 회전, 왼쪽 +, 0 < \|θ\| ≤ 90), `map_id`, `bend_in_m`(0 < m ≤ 2, 보낼 때 로봇 자세에서 호 시작점까지 차로를 따른 거리), `bend_tol_m`(0 < m ≤ 0.30, 그 거리의 오차), `bend_radius_m`(0 < m ≤ 0.5, 중심선 호 반지름); `expect_in_m`·`expect_tol_m`·`pivot_past_line_m`·`advance_m`·`stop_after_m` 는 함께 둘 수 없고, 세 `bend_*` 필드는 다른 action 에 둘 수 없다(400 `VALIDATION_ERROR`). D-754 (v1.225, `lane_bend_next_line` 능력이 참인 로봇에만 보낸다): `bend` 의 선택 필드 `next_line_in_m`(0 ≤ m ≤ 2, 꼭짓점에서 다음 교차로 가로선까지 차로를 따른 거리, 2 는 그 이상)이 있으면 통과가 넘겨줄 목격을 그 거리로 가린다(허용치 밖이면 넘기지 않고 `idle`). 다른 action 에 두면 400. 받는 순간 신선한 odom 이 없으면 409 `JUNCTION_ODOM_STALE`. 상태: `armed`(카메라 추종 그대로, 받은 뒤 odom 이동 거리를 센다. 같은 `place_id`·`turn_deg` 의 재전송은 만료만 늘리고 잰 거리를 지킨다. D-476 bridge 힌트는 모름 그대로, 이동 거리는 진행 방향 부호 투영이라 뒤로 간 거리는 뺀다) → 호 시작점 `bend_tol_m` + 0.25 m 앞부터 카메라가 곧은 확신 추종(`TRACKING`/`tracking`, \|error\| ≤ `bridge_arm_max_error`)을 멈춘 첫 틱(카메라 자신의 HOLD·손실·큰 오차·교차로 감지. 장애물·IR·한도·LOST HOLD는 그대로 HOLD이고 지시는 `armed`, 닻이 없으면 호 시작점까지 지금의 HOLD)이나 호 시작점 `bend_tol_m` 앞에서 `bending`(사유 `junction_bending`: 마지막 곧은 확신 틱의 odom 자세에서 그 방향 직선, 반지름 `bend_radius_m` 호, 나가는 직선을 `bridge_lookahead_m` pure pursuit 로, 속도 ≤ trip 최고 속도의 절반, 각속도 상한을 넘으면 같은 호로 감속) → 호 끝에서 `reacquiring`(사유 `junction_reacquiring`, 나가는 직선을 계속 좇으며 D-495 재획득 또는 나가는 방향 ±30° 안의 교차로 감지로 끝) → `idle`. 그 앞 구간 밖의 교차로 감지는 HOLD `junction_unexpected`(지시는 `armed`). 이유 있는 0 명령 `aborted`: `no_anchor`(곧은 확신 틱이 없거나 0.25 m 넘게 뒤), `lane_lost_before_bend`, `odom`, `distance`(실측 odom × `bridge_distance_scale` 이 남은 호 경로 + `bridge_lookahead_m` 초과), `timeout`(직선/속도 + 호/호 속도 + 2 s), `stuck`(D-407), `bend_basis_lost`(운동 근거 상실), `motion_unconfirmed`(v1.222: 거절이 0.5 s 넘게 이어질 때, 그 전에는 HOLD `junction_motion_unconfirmed`로 기동 유지. D-507 6 운동 허가 종류 `bend` 거절: 현장 근거는 IR `clear` 만), `off_path`(경로에서 옆으로 0.06 m 초과 또는 추적점이 뒤), 기존 중단 규칙(모드·보정·stuck·사유). 그 twist 의 D-422 몸 sweep 이 재출발 간격 이하이거나 스캔이 `clearance_stale_s` 보다 낡은 틱은 0 명령 HOLD `junction_bend_blocked` 이고 통과는 이어진다(시간 상한 안). 재획득을 0.20 m·5 s 안에 못 하면 `unresolved`(HOLD). 뒤로 가지 않는다. 상태 목록에 `bending` 을 더한다. D-759 (v1.224, `lane_bend_map_entry` 능력이 참인 로봇에만 보낸다): `bend` 의 선택 객체 `map_entry {yaw_rad, pose_yaw_rad, odom_stamp_s}`(호 시작점에서 차로가 향하는 지도 방향과 지도 yaw·odom 시각 쌍)가 있으면 CORE 는 통과의 진입 직선을 그 방향에 놓고, 풀지 못하면 로봇 자신의 yaw 를 쓴다(맨 위 v1.224 절). 결과는 `junction.map_entry_used`·`map_entry_reason` 이다. D-520 1–2항 (v1.145, `lane_arc` 능력이 참인 로봇에만 보낸다): 선택 객체 `exit_segment {curvature_1pm, length_m, outer_line_offset_m, end_place_id}` — 이 장소의 회전(또는 앞 호 끝의 `straight`) 뒤 들어갈 차로가 반지름 1/\|κ\| 의 원호이고 `end_place_id` 까지 `length_m` 이라는 뜻이다. `curvature_1pm` 은 부호 있는 1/m(왼쪽·반시계 +, 0.5 ≤ \|κ\| ≤ 5), `length_m` 0 < m ≤ 1.0, `outer_line_offset_m` 0.05–0.20(차로 중심선에서 곡선 바깥 칠한 선 중심까지, 지도의 선 간격에서 옴), `end_place_id` 1–128자. v1.221(D-744): 선택 객체 `exit_segment.map_anchor {centre_x_m, centre_y_m, pose_x_m, pose_y_m, pose_yaw_rad, odom_stamp_s}`(지도 좌표의 원 중심과 지도 자세·odom 시각 쌍, 능력 `lane_arc_map_anchor` 로봇에만)가 있으면 CORE 는 호의 원을 그 지도 원에 놓고, 풀지 못하면 자세 기준 원을 쓴다(맨 위 v1.221 절). `map_id` 가 없거나, `stop` 이거나, `turn_deg` 없는 `left`·`right` 에 오면 지시 전체가 400 `VALIDATION_ERROR` 다. CORE 의 `line_follow.arc_enabled` 가 꺼져 있으면 409 `LANE_ARC_UNAVAILABLE` 이다. `exit_segment` 가 있으면 `advance_m` 은 무시한다(기본 0.10 도 쓰지 않는다). 들어감: (a) `exit_segment` 가 있는 `left`·`right` 가 `turning` 을 마쳤고 `pivot_basis` 가 `map` 또는 `segment_end` 면 그 지시는 `advancing`·`reacquiring` 없이 그 자리에서 끝나고(상태 `idle`, 같은 `place_id`·`action` 반복은 `JUNCTION_ALREADY_DONE`) 새 호 기록이 열린다. (b) 앞 호 끝에서 `end_place_id` 의 `straight` 가 `exit_segment` 를 실었으면 그 지시도 끝나고 다음 호가 곧바로 열린다. `pivot_basis: stop_point` 면 호를 열지 않고 전진 없이(0 m) 재획득한다. 호 주행: v = min(`cruise_speed`, `max_linear`, 수동 선속도 한도), ω = `arc_curvature_gain`·v·κ + v·c (v1.154, D-520 개정 2026-10-09: c 는 호를 열 때 odom 에 놓은 지도 원(회전 뒤면 회전 목표 yaw 를 접선으로 하고 지금 자리를 지나는 원, 같은 세대의 이어지는 `straight` 면 앞 호의 원)으로의 반지름·방향 보정, \|c\| ≤ 1.5 1/m, IR 보정 중 0; 보정 밖에서 원과의 odom 거리가 0.075 m 를 넘으면 HOLD `lane_arc_edge`; 첫 IR `left`·`right` 판정은 원을 그 쪽 칠한 선 기준으로 옮긴다), \|ω\| 가 live 각속도 한도를 넘으면 같은 곡률로 v 를 줄인다. 상태 `RECOVERING`, 사유 `lane_arc`(IR 보정 중 `lane_arc_correcting`). 길이는 매 걸음을 앞 자세 yaw 에 투영한 odom 의 부호 있는 합이고 `length_m` 에 닿으면 끝난다. 시간 한도 `length_m`/v + 2 s(IR 보정이 열리면 그 보정 한도만큼 늘어남. D-760 개정 2 6항: 통행권이 `FREE`가 아니거나 D-573 횡단보도 게이트가 `looking`·`waiting`이거나 건너는 중 앞 물체로 서 있는 시간은 이 한도와 보정 한도에 세지 않고, 건너는 중(`crosswalk_cross_speed`)에는 호 속도보다 느린 몫만 세지 않는다. 한 틱 간격은 `stale_after_s`까지만 센다. 한 호에 `crosswalk_report_s` + `crosswalk_clear_s`(15 s)까지만 더한다 — D-507 13항의 기동 단계 시계와 같은 규칙이고, 기동도 같은 계산을 쓴다). 호 주행 중에는 keeper 사유(`no_boundary`·`flipping`·교차로·`line_not_visible`·`low_confidence`·영상 품질)로 서지 않고 손실 시계가 돌지 않으며(끝나면 새로 시작), D-476 bridge·D-468 이탈 판정·D-407 막힘·keeper 교차로 감지를 쓰지 않는다. 호 중의 지시 칸은 비어 있고, 그 사이에 온 지시는 모두 `armed` 로 받아 호를 끊지 않는다. 끝에서: `end_place_id` 의 `armed`(만료 전) 지시가 있으면 그 지시의 회전 축은 이 끝 자리다(`pivot_basis: segment_end`, 기대 창·접근 없음) — `left`·`right` 는 정지 확인 뒤 회전(나가는 차로가 또 호면 (a)), `straight` 는 `exit_segment` 가 있으면 (b), 없으면 오늘의 `straight` 처럼 `executing` 으로 지나간다, `stop` 은 HOLD `junction_stop`, `turn_deg` 없는 `left`·`right` 는 `unresolved`. 지시가 없으면 오늘의 추종으로 돌아가고 이벤트 `nav.lane_arc_end_unarmed` 를 낸다. 다른 장소의 `armed` 지시는 `aborted`(`reason: arc_mismatch`, HOLD 아님)가 되고 지시 없는 끝과 같다. 장소와 무관하게 `armed` `stop` 은 HOLD `junction_stop` 이다. 호가 도는 동안 `action: bend` 는 409 `JUNCTION_ARC_RUNNING` 이고, 호 끝의 `armed` `bend` 는 다른 장소 지시처럼 `aborted`·`arc_mismatch` 다. 운동 허가는 매 틱 `motion_admitted(kind arc)`(IR `clear` 만)와 그 틱 호 twist 의 D-422 몸 sweep 이다. 후진은 없다. IR 한 번 보정(호 하나에 한 번): 호 시작 뒤 odom 0.03 m 안에서는 `left`·`right` 를 허가하고 보정을 열지 않는다(`centre` 는 멈춤); 유예 뒤 처음 판정이 유예 중 본 쪽과 같으면 `lane_arc_edge` 로 선다. 그 밖에 처음 `left`·`right` 가 보정을 연다: 속도 v·`ir_guard_speed_scale`, `away` 는 선 반대쪽으로 ω = g·v_c·κ ∓ v_c·`bridge_arm_max_curvature`(선이 왼쪽이면 음) 로 odom 0.12 m 간 뒤 확신 있는 `clear`(신선·교정된 IR 이 `visible: false`)여야 하고, `level` 은 반대 편향으로 odom yaw 가 호 기준 ψ₀ + κ·s 에 닿으면 끝난다(상한 0.18 m). 허가는 `away` 에서 그 쪽 또는 `clear`, `level`·보정 뒤에는 `clear` 만이다. 멈춤(HOLD, 호 기록 `stopped`, 다시 열지 않음, 다음 모드 변경까지): `lane_arc_edge`(`centre`, 보정 중 반대쪽 판정, `away` 끝이 확신 있는 `clear` 아님, `level` 중 판정 재등장, `level` 상한, 보정 뒤 두 번째 판정, 보정 중 구간 끝, 보정 한도 (0.12 + 0.18)/v_c + 2 s 초과), `obstacle_ahead`(D-422 sweep 미달), `lane_arc_pose_lost`(odom 이 `stale_after_s` 보다 낡음·끊김·epoch/frame 변경), `lane_arc_motion_unconfirmed`(스캔이 `clearance_stale_s` 보다 낡음, IR `stale`, 운동 허가 거절), `lane_arc_timeout`, `lane_arc_blind`(보정 없이 간 거리가 `arc_blind_max_m` 초과; step 1 은 호 전체), `lane_arc_entry`(step 2 예약), 그리고 오늘의 `angular_limit_zero`·`limit_level_too_low`·`linear_limit_zero`·`calibration_active`, 모드 변경·E-stop·운전자 hold. 상태는 `line_follow.arc {arc_seq, from_place_id, end_place_id, curvature_1pm, length_m, travelled_m, state: running\|ended\|stopped, reason, ir_correction: {side, phase: away\|level\|done, away_m, level_m, used}, map_anchor_used, map_anchor_reason}`(이 프로세스의 마지막 호, 없으면 null; `map_anchor_used`·`map_anchor_reason` 은 v1.221 D-744, 지도 고정 원으로 열린 호만 참이고 아니면 까닭을 적는다). `reason` 은 끝이면 `segment_end`, 지시 없는 끝(다른 장소 지시 포함)이면 `lane_arc_end_unarmed`(Fleet 이 이 값으로 판정한다), 멈춤이면 그 사유다. D-491: 호를 열 자리에서 알려진 횡단보도 구역(CORE 가 영상으로 odom 에 고정한 구역)이 호 앞 `crosswalk_zone_max_m` 안에 걸치면 CORE 는 `exit_segment` 를 버리고 오늘처럼 동작한다(회전 뒤 `advance_m` 0.10 전진·재획득, 이어지는 `straight` 는 오늘의 통과). 그 지시의 `junction.reason` 은 `arc_crosswalk` 다. Fleet 은 `from_place_id` 가 보낸 장소와 같고 `arc_seq` 가 새로우면 그 지시를 `carried` 로 본다. `junction.pivot_basis` 값에 `segment_end` 를 더한다 |
| POST | `/api/v1/line-follow/authority` | Operator | D-517 4항 (M2, v1.143) — Fleet 이동 통행권 `{authority_id (1–128자), leg_id (1–128자), pose_stamp (> 0), until_m (0–10), ttl_s (0 < s ≤ 5; v1.225까지 ≤ 2), shrink? (bool, v1.226), seq? (정수 ≥ 0, v1.226)}`. 범위 밖·누락은 400 `VALIDATION_ERROR`. seat 는 `/junction` 과 같다(수동 조종 해제 409 `MODE_CONFLICT`, 보정 lease 409 `CALIBRATION_ACTIVE`). `until_m` 은 그 자세의 로봇 **앞 끝**(base + 몸 `front_x_m`)에서 통행권 끝까지의 거리다. CORE 는 base odom 주행 거리를 빼므로 앞 끝이 통행권 안에 남는다. `pose_stamp` 는 Fleet 이 계산에 쓴 자세의 CORE odom 시각으로, 스냅숏 `odom_pose.stamp` 와 같은 CORE 벽시계(UTC epoch 초)다. CORE 는 odom 표본마다 같은 벽시계 시각과 누적 경로 길이를 기록하고, `pose_stamp` 이전(같거나 이전)의 가장 새 표본부터 지금까지 odom 경로 길이(부호 없음: 후진도 남은 거리를 줄인다)를 `until_m` 에서 빼서 남은 거리를 낸다. 남은 거리가 D-422/D-424 몸체 정지 거리 d_stop(v)(`derived_stop_gap_m`, v = `max_linear`, line follow 가 낼 수 있는 가장 빠른 속도(D-468 복귀 포함, `cruise_speed` ≤ `max_linear`)) 이하가 되면 선다(`HOLDING`, 사유 `authority_end`). 다시 가려면 남은 거리가 d_stop(v) + `obstacle_resume_hysteresis_m` 보다 커야 한다. `ttl_s` 는 CORE line-follow 시계(`hold_s` 와 같은 시계)로 재고, 그 안에 새 통행권이 없으면 선다(`EXPIRED`, `authority_expired`). 통행권은 줄지 않는다: 같은 `leg_id` 이고 같은 odom 궤적이며 아직 만료되지 않은 통행권보다 끝이 0.02 m 넘게 짧으면 무시하고(응답 `accepted: false`, `reason: shrink`, 로그) 만료도 늦추지 않는다. 0.02 m 안에서 짧으면 쥔 끝을 그대로 두고 만료만 늦춘다(Fleet 지도 자세 잡음). 다른 `leg_id`, 만료 뒤, 또는 odom 궤적이 바뀐 뒤에는 새 통행권이 그대로 대신한다. 응답 `{accepted, reason, authority}`(`authority` 는 아래 상태). 거절: line-follow OFF 409 `LINE_FOLLOW_NOT_ACTIVE`, 409 `AUTHORITY_ODOM_STALE`·`AUTHORITY_POSE_STALE`·`AUTHORITY_POSE_FUTURE` — 이 셋은 쥐고 있던 통행권도 버려서 로봇이 선다. 통행권 강제는 설정 `line_follow.authority_required: true` 이거나, 이 line-follow 세션에서 통행권 요청을 한 번이라도 받은 뒤(trip 구간이 선언함)에만 켜지고, 모드 변경·E-Stop 이 끝낸다. 꺼져 있으면 동작은 오늘과 같다. 켜져 있으면 유효한 통행권 없이는 선다(`NONE`, `authority_none`). odom 이 0.3 s 넘게 끊기거나 궤적이 바뀌면 선다(`HOLDING`, `authority_odom_stale`). 통행권 판정은 그 틱의 결정을 0 으로 만들 수만 있다: D-422 몸체 정지, D-491 IR 가드, E-Stop 은 먼저 결정을 0 으로 만들므로 언제나 앞선다. 통행권 때문에 0 이 된 틱의 상태는 HOLD 와 위 사유다. D-760 (v1.226, 맨 위 v1.226 절): `shrink: true` 는 끝을 `min(쥔 끝, 요청 끝)` 으로 바꾸고 `ttl_s` 를 갱신한다(`until_m: 0` 은 지금 자리 정지). `seq` 가 같은 `leg_id` 에서 마지막으로 본 값 이하면 `accepted: false`, `reason: stale_seq` 이고 쥔 끝과 `ttl_s` 는 그대로다(`seq` 를 본 구간의 `seq` 없는 요청은 `seq_required`, 기억 8개가 찼으면 `seq_legs_full`). 쥔 통행권이 없는 `shrink` 는 통행권을 주지 않는다(`accepted: false`, `reason: shrink_none_held`, `NONE`). CORE trip lease 가 열려 있는 동안에는 설정·세션과 무관하게 통행권이 강제된다(없으면 `NONE`, `authority_none`) |
| POST | `/api/v1/line-follow/advice` | Operator | D-551 (v1.156, 표시만). D-525 신호 참고 `{advice_id (1–128자), leg_id (1–128자), seq (≥ 0), fleet_epoch (1–64자), pose_stamp (> 0, CORE가 준 odom 시각을 그대로 되돌림), ttl_s (0 < s ≤ 2), map_version?, route_rev?, signal: {signal_id, approach, stop_m (음수면 정지선 안), lamp: green\|yellow\|red, left_s?, green_in_s?, exact, may_enter} \| null}`. 응답 `{accepted, reason}`. 허가가 아니다: 차선 판정·통행권·교차로 판정이 읽지 않고 움직임을 만들지 않는다(차선 매니저 밖 저장소, import 검사 시험). 수동 조종 해제·보정 lease 를 요구하지 않고 line-follow 가 꺼져 있어도 받는다. 저장소는 하나이고, 만료 전·같은 `leg_id`·같은 `fleet_epoch` 항목보다 `(pose_stamp, seq)`가 같거나 오래되면 `accepted: false`, `reason: stale` 이다. 만료(CORE 단조 시계 `ttl_s`), 다른 구간, 다른 `fleet_epoch` 뒤에는 새 것을 받는다. `signal: null` 은 표시를 지운다. 틀린 본문은 400 `VALIDATION_ERROR`. 노출은 `GET /line-follow` 선택 키 `advice`(만료 전·신호가 있을 때만), 로봇 상태 스냅숏에는 넣지 않는다. 능력 `controls` `line_follow_advice`. 모르는 신호는 Fleet 이 `signal: null` 로 보낸다. odom 기록 대조(자세 409)와 속도 상한은 D-551 다음 단계(Safety-Review) |
| POST | `/api/v1/line-follow/lane-cue` | Operator (D-555 3 현장 등록 자리; 라벨은 인증이 아님) | D-511 개정 1·2 (v1.200, D-430 Safety-Review). Fleet 차로 신호 `LaneCueRequest`; 필드와 동작은 11장 v1.200. 정지를 풀지 않는다 |
| POST | `/api/v1/line-follow/stuck/decision` | `STUCK_DECIDE` (operator·administrator·`stuck_resolver`, D-438 v1.91) | D-407 §2 / D-453 — `{stuck_id, decision: WAIT\|RESUME\|BACK_AND_RETRY\|MANUAL\|ABORT\|YIELD}`. `YIELD` 는 선택 필드 `yield_m`·`yield_turn_rad` 가 둘 다 있어야 하고, 다른 결정에 그 필드가 있으면 400 `VALIDATION_ERROR`. 한 답은 한 구간이다. CORE 는 회전을 확인한 뒤 그 거리만 앞으로 기어 가고, 끝나면 `YIELDED` 로 서며 차선 추종을 재개하지 않는다. 다음 `YIELD` 가 다음 구간이다. 열린 막힘(`GET /line-follow` 의 `stuck`)에 대한 관제 답. `WAIT` 그대로 HOLD·로컬 복구 안 함; `RESUME` 앞물체 정지를 한 번 풀어 `obstacle_stop_m` 까지 접근 허용·LOST 해제 후 차선 추종 재개; `BACK_AND_RETRY` 짧은 후진과 재판단을 즉시(로컬 복구가 켜져 있어야 함); `MANUAL` 차선 추종 OFF + MANUAL(D-342 한도); `ABORT` 차선 추종 OFF + IDLE. 응답은 line-follow 상태 + `outcome`(`hold\|back\|resume\|manual\|idle\|yield`). `RESUME`·`BACK_AND_RETRY`·`MANUAL`·`YIELD` 는 보정 lease 를, `RESUME`·`BACK_AND_RETRY`·`YIELD` 는 E-Stop 을 지킨다. `MANUAL`·`ABORT` 의 모드 전이는 `POST /mode` 와 같다(`MANUAL` 은 navigation·swarm 취소, `mode.changed`). 409 `STUCK_ID_MISMATCH`·`STUCK_DECISION_REFUSED`·`CALIBRATION_ACTIVE`·`EMERGENCY_ACTIVE`. 운용자 Fleet 경로의 다섯 단어와 추가 필드 422 는 그대로다 (v1.74, YIELD 는 v1.95) D-573 4 (v1.179): `cause: crosswalk_blocked` 에는 `WAIT`·`MANUAL`·`ABORT` 만 받는다. `RESUME`·`BACK_AND_RETRY`·`YIELD` 는 409 `STUCK_DECISION_REFUSED`(`crosswalk_gate`). D-607 8 (v1.199): `REALIGN` + `realign {kind: PIVOT\|KTURN, angle_rad (부호 있음, + 왼쪽, \|값\| ≤ π/2), back_m?, back_radius_m?, fwd_radius_m?, pose_stamp (CORE 벽시계 odom 시각, lane cue·D-517 권한과 같음), attempt: 1\|2, turn_spot? (기본 false), basis? (감사·표시만)}`. `realign` 은 `REALIGN` 에만(아니면 400). `line_follow.stuck_realign_enabled`(기본 false)일 때만 `stuck.decisions` 에 `REALIGN` 이 있고 능력 `controls.items[].stuck_realign: ["PIVOT","KTURN"]` 을 알린다. `PIVOT` 은 `turn_spot: true`(지도 회전 자리)일 때만이고, IR 가운데 면제는 그때만이다. `KTURN` 은 0 < `back_m` ≤ 0.08, `back_radius_m` ≥ 0.05, `fwd_radius_m` ≥ 0.02: 반지름 `back_radius_m` 뒤 호로 odom `back_m` 만큼, 이어 반지름 `fwd_radius_m` 앞 호로 목표까지. 목표는 `pose_stamp` 시점 odom yaw + `angle_rad`(부호 고정, 끝 10°, 예산 \|각\|+30°, 시간 한도). 속도 ≤ `recovery_back_speed`, \|ω\| ≤ 0.3 rad/s. 시작 전과 매 틱: 스캔 신선, URDF 몸, 보정 없음, D-573 게이트 비무장, 제자리 회전은 회전 반지름 밖 여유 ≥ 0.010+0.02 m와 8구역 목격, 뒤 호는 BACK_AND_RETRY 뒤 확인(뒤 띠 0.06 m·사각·지나온 길), 앞 호와 제자리 회전은 실제 명령의 D-422 몸 정지, IR 감시(stale·가운데 정지). 하나라도 깨지면 0, `nav.line_stuck_local_result` `aborted` + 막힘은 사람·Fleet 답 대기(`local_aborted`). 끝나면 `recovery_settle_s` 뒤 차선 증거 + 앞 여유면 `recovered`(RESUME), 아니면 Fleet 답 대기(`realign_done`); 로컬 후진으로 넘어가지 않는다. 막힘마다 두 번(빠른 재막힘은 같은 막힘). 진행 중 단계 `REALIGNING`·`REALIGN_SETTLING`, 상태 `RECOVERING` 사유 `stuck_realign`, 응답 `outcome: realign`. `REALIGN` 은 보정·trip lease(409 `TRIP_LEASED`)와 E-Stop 을 지키고, E-Stop·모드 변경은 진행 중 조작을 끝내며 다시 시작하지 않는다. 진행 중 `BACK_AND_RETRY`·`YIELD`·`REALIGN` 은 `realign_active`. 거절 `why`: `realign_unset`·`realign_angle`·`realign_kind`(꺼짐·모르는 종류·회전 자리 아닌 `PIVOT`)·`realign_attempts_exhausted`·`realign_active`·`pose_stamp_unknown`·`turn_blocked`·`turn_unseen`·`rear_blocked`·`rear_blind`·`no_scan`·`scan_stale`·`body_geometry_unset`·`calibration_active`·`crosswalk_gate`·`local_recovery_disabled`(+ 기존 `linear_limit_zero`·`object_within_stop_distance`). |
| GET | `/api/v1/traffic` | Viewer | D-151 — 교통 인식 증거, 정책 판정, active/staged 설정과 simulation signal capability readback |
| POST | `/api/v1/traffic/policy/stage` | Operator | D-151 — 정책 모드·revision·거리·dwell·신뢰도 기준을 검증해 검토본으로 저장. 활성 정책은 바꾸지 않음 |
| POST | `/api/v1/traffic/policy/apply` | Operator | D-151 — IDLE/EMERGENCY이고 line-follow가 꺼져 있으며, fresh 0 속도 또는 E-stop으로 정지가 증명된 경우에만 staged 정책을 원자 적용 |
| PUT | `/api/v1/traffic/simulation/signal` | Operator | D-151 — 명시적 simulation capability에서만 `{colour: RED\|YELLOW\|GREEN}` 허용. 실제 장치에서는 501 |
| GET | `/api/v1/vision/models` | Viewer | D-423: 로봇 학습 모델 상태(작업별, 읽기 전용) `{tasks:[{task,slot,model_revision,last_error,frames_inferred,latency_ms_p50,signed,age_s,stale}]}` (`signed`: 노드가 서명을 확인했으면 true/false, 아니면 null; lane_seg 는 경고만이라 false 일 수 있다). `lane_seg`/`shadow` 는 `perception/learned/status`, `object_det`/`active` 는 `perception/learned/object_det/status` 에서 온다. CORE 는 포인터 파일을 읽지 못하므로 노드가 없는 슬롯은 빠진다. `no-store`. 교체(promote/rollback)는 운영자 CLI(`rosy_ml`)만 — CORE 쓰기 API 없음 |
| GET | `/api/v1/vision/front/status` | Viewer | 최신 front camera preview의 available/stale, source, frame, 크기, overlay, sequence 메타데이터. 원본 영상은 상태 WebSocket에 싣지 않음 |
| GET | `/api/v1/vision/front/frame` | Viewer | D-152 fresh 최신 JPEG 한 장. `Cache-Control: no-store`, `Content-Encoding: identity`; 없거나 stale이면 404 `CAMERA_FRAME_UNAVAILABLE` |
| GET | `/api/v1/vision/front/stream` | Operator | D-368 (v1.102) 운전자 전용 MJPEG 스트림. `multipart/x-mixed-replace; boundary=frame`, `?overlay=`(기본 true, `false`면 raw pair). 파트 헤더 `X-Rosy-Camera-{Sequence,Source,Captured-At}`. 조종 소유권은 가장 최근 수락된 teleop 토큰(D-460, 임대 없음): 운전자 아님 409 `CAMERA_STREAM_NOT_DRIVER`, 동시 하나만 409 `CAMERA_STREAM_BUSY`, 다른 토큰의 teleop 수락으로 열린 스트림이 끝난다. 인증은 헤더만(D-193). 관전자·관제 화면은 기존 0.4 s 폴링을 그대로 쓴다 |
| POST | `/api/v1/vision/front/evidence` | Operator | 카메라 화면에서 만든 JPEG 스크린샷 또는 WebM/MP4 녹화를 로봇 SD에 저장. 길이 접두 JSON 메타데이터 뒤에 바이너리 미디어를 전송; 성공 시 `VisionEvidenceRecord`(201) |
| GET | `/api/v1/vision/front/evidence` | Operator | 저장된 카메라 증거의 최신 목록(`VisionEvidenceList`, 최대 50건) |
| GET | `/api/v1/vision/front/evidence/{id}` | Operator | 저장 미디어 다운로드. 24자리 불투명 id만 허용; 없으면 404 |
| POST | `/api/v1/localization/initialpose` | Operator (`NAVIGATE`) | 초기 자세 `{x, y, yaw}`, 응답 `{accepted: true}` 그대로. D-395 로봇(`localization` 이 null 아님)에서는 `/initialpose` 를 직접 쓰지 않고 `LocalizationDecision(source: human, pose)` 로 `localization/decision` 에 보내, 로봇의 3 s 검증을 거친다. `request_id` 는 열린 요청이 있으면 그것, 없으면 `human-<ms>`. D-395 이전 로봇은 예전처럼 `/initialpose` 를 쓴다 (v1.72) |
| GET | `/api/v1/localization/candidates` | `LOCALIZE_ASSIST` | D-395 P2-4 — 최신 `CandidateReport`(§7.9, `robot_id` 는 CORE 신원). `CANDIDATES` 가 아니거나 열린 요청의 보고가 없으면 404 `NO_CANDIDATES` (v1.72) |
| GET | `/api/v1/localization/request` | `LOCALIZE_ASSIST` | D-546 5 (v1.163, 제안) — lane_return 이 위치 증거가 없어 못 갈 때(`pose_stale` 이 1 s 이상, 또는 `fleet_required`) CORE 가 여는 "내 위치를 알려 달라" 요청 하나. `{request_id, robot_id, reason: pose_stale\|fleet_required, created_at(CORE 벽시계 초), age_s, ttl_s(기본 30), evidence {phase, odom_pose {x, y, yaw, frame, stamp_ns, age_s}\|null, lane {visible, confidence, error, quality_reason, stamp}\|null}}`. 같은 사유면 `request_id`·`created_at` 이 유지되고 증거만 갱신된다. 요청이 없거나 `ttl_s` 가 지났으면 404 `NO_REQUEST`(다음 틱에 새 `request_id` 로 다시 열린다). 답은 기존 `POST /localization/decision` 이다(`request_id` 를 그대로 싣고 `source: overhead\|candidate`, `ttl_s`). 로봇의 3 s 스캔 확인이 통과해 `localization.result` `accepted` 가 오고 그 `request_id` 가 열린 요청의 것이며 Fleet 이 보낸 결정일 때만 요청이 닫히고(사람의 initialpose·homing 결과는 닫지 않는다) `fleet` 단계의 lane_return 이 D-407 RESUME 으로 차선 확인을 다시 연다. 요청 중 로봇은 HOLD 로 기다린다 |
| POST | `/api/v1/localization/decision` | `LOCALIZE_ASSIST` (+`NAVIGATE` for `source: human`) | D-395 P2-4 — 본문 `LocalizationDecision`(§7.9). 로봇에 보냈으면 202 `{request_id}`. 열린 요청이 아니면 409 `STALE_REQUEST`, 보정 lease 중 비소유자는 423 `CALIBRATION_ACTIVE`, 스키마 위반 400, D-395 이전 로봇은 501. `source: human` 이면 `localization.initialpose` 를 낸다 (v1.72) |
| POST | `/api/v1/localization/suspect` | `LOCALIZE_ASSIST` | D-395 P2-4 — `{reason}`(1–64자, 예: `fleet_monitor`)를 로봇 `localization/suspect` 로. 202 `{accepted: true}`, lease 중 423, D-395 이전 로봇 501 (v1.72) |
| POST | `/api/v1/localization/mission` | `LOCALIZE_ASSIST` | D-395 P2-7 — `{kind, max_distance_m, max_time_s, target}`. CORE 가 스스로 아주 느리게 움직인다(Fleet 은 바퀴를 몰지 않는다, D-2·D-369). 로봇이 `LOCALIZED` 가 아닐 때만. `kind`: `rotate_in_place`(오도메트리로 최대 한 바퀴, 0.3 rad/s, `max_distance_m` 무시, 전체 스캔에 0.20 m 안 반사가 있으면 `path_not_clear`), `nudge_forward`(오도메트리로 0 < `max_distance_m` ≤ 0.10 m, 0.03 m/s, 정면 0.25 m 안에 물체가 들어오거나 정면 ±20° 를 잴 수 없으면 — 유효 빔 5 개 미만, 또는 inf·NaN·`range_min` 미만 빔이 30 % 초과, self-mask 반사는 빼고 — 거부·끝), `lane_to_stopline`(카메라 line-follow 를 이 미션에 한해 `LOCALIZED` 관문 없이 켜고 0.04 m/s 로 제한, 정지선 0.12 m 안·거리·시간에서 끝, 0 < `max_distance_m` ≤ 1.0), `to_square`(409 `unsupported`: map 프레임 없이 사각형까지 가는 차선 경로가 아직 없다, 후속). `0 < max_time_s ≤ 120`. 움직임은 NAVIGATION 모드의 nav 슬롯으로 들어가 50 Hz 최종 중재(`select_output`: e-stop·readiness·속도 제한·제어 정책)를 그대로 거친다. 202 는 `GET` 과 같은 본문(`state: running`). 끝: `done`·`stop_line`·`localized`(→ `state: done`), `timeout`·`obstacle`·`obstacle_sensor_stale`(모든 종류, LiDAR 0.5 s 끊김)·`odometry_stale`·`lane_lost`·`estop`·`cancelled`(모드가 NAVIGATION 을 떠남: MANUAL·IDLE·line-follow OFF)·`error`(→ `aborted`). 끝나면 바퀴 명령을 지우고 IDLE 로 돌아가며, ROS `localization/mission` `{kind, state, reason}` 으로 로봇 sensing 노드가 바로 다시 탐색한다. 거부 409 코드는 §ERR-102, 범위 위반 400, D-395 이전 로봇 501, 구동 능력 없음 501, readiness HOLD 503 (v1.73) |
| GET | `/api/v1/localization/mission` | Viewer | D-395 P2-7 — `{kind, state, reason}`; `state`: `idle`(아직 없음, `kind`·`reason` 은 `null`) \| `running`(+ `elapsed_s`, `travelled_m`, `turned_rad`) \| `done` \| `aborted` (v1.73) |
| POST | `/api/v1/motion/rotate_to` | Operator: trip lease 주인(D-541), lease가 없으면 `operator_name`을 적은 운영자 | D-603 (v1.194) — `{delta_deg? (|·| ≤ 180), yaw_odom? (rad, odom), tol_deg = 5 (1–20), max_rate_dps = 20 (≤ 30), timeout_s = 10 (≤ 15), operator_name}`, `delta_deg`·`yaw_odom` 중 하나만. CORE가 제자리에서 자기 odom yaw로 닫힌 고리 회전을 한다(비례 감속, 최저 `localization_mission.rotate_to_min_angular` 0.15 rad/s, 최고 `max_rate_dps`). NAVIGATION 모드의 nav 슬롯으로 들어가 `select_output`(E-Stop·readiness·Safety clip·D-400 정책)을 거친다. `LOCALIZED`와 상관없이 받고, `LOCALIZED`가 되어도 끝나지 않는다. 거부: lease 주인 아님 409 `TRIP_LEASED`, 보정 lease 409 `CALIBRATION_ACTIVE`, 이름 없음 403 `OPERATOR_NAME_REQUIRED`, 매핑 409 `MAPPING_ACTIVE`, E-Stop 409 `EMERGENCY_ACTIVE`, 409 `MOTION_BUSY`·`ODOMETRY_STALE`·`ROTATE_CLEARANCE`, 범위 400, readiness HOLD 503, 구동 능력 없음 501. 202 본문은 `GET`과 같다. 끝: `done`(오차 ≤ `tol_deg`) 또는 `timeout`·`overturn`(odom 회전 합이 요청 + `rotate_to_overturn_deg` 30° 초과)·`obstacle`(회전 중 `rotate_in_place`와 같은 몸체 검사)·`obstacle_sensor_stale`·`odometry_stale`·`estop`·`cancelled`(NAVIGATION을 떠남, `DELETE`)·`error` → `aborted`. 끝나면 바퀴 명령을 지우고 IDLE. 사건 `motion.rotate_to`(요청), `localization.mission`(`kind: rotate_to` 시작·끝) |
| GET | `/api/v1/motion/rotate_to` | Viewer | D-603 (v1.194) — `{kind: rotate_to, state: running\|done\|aborted\|idle, reason, err_deg (running), final_err_deg (끝), elapsed_s, turned_rad}`; 마지막 미션이 회전이 아니면 `state: idle` |
| DELETE | `/api/v1/motion/rotate_to` | Operator | D-603 (v1.194) — 도는 회전을 멈춘다(`cancelled`). 멈춤이므로 lease와 상관없이 받는다. 다른 미션은 건드리지 않는다. 본문은 `GET`과 같다 |
| POST | `/api/v1/slam/start` | Operator | NAV-005 — 추종 세션이 주행을 쥐고 있으면 409 `NAVIGATION_ACTIVE` |
| POST | `/api/v1/slam/stop` | Operator | NAV-005 |
| POST | `/api/v1/slam/save` | Operator | NAV-005 (응답에 `map_id`) |
| POST | `/api/v1/slam/reset` | Operator | NAV-005. **미구현** — 어느 런타임에도 slam_toolbox 리셋이 없어 항상 `501 CAPABILITY_NOT_SUPPORTED`. 맵핑 세션이 없으면 `400 VALIDATION_ERROR` (D-32) |

## 5.4 Map·Waypoint

| Method | Path | Role | 요구사항 |
|---|---|---|---|
| GET | `/api/v1/map` | Viewer | MAP-003 (응답의 `map_id`는 해당 점유 지도 스냅숏을 수신할 때 묶인 ID. 이후 로봇 상태의 `map_id`가 바뀌어도 이전 격자에 새 ID를 붙이지 않음) |
| GET | `/api/v1/map/costmap?scope=global\|local` | Viewer | MAP-003 |
| GET | `/api/v1/waypoints` | Viewer | WPT-002 |
| POST | `/api/v1/waypoints` | Operator | WPT-002 |
| PUT | `/api/v1/waypoints/{name}` | Operator | WPT-002 |
| DELETE | `/api/v1/waypoints/{name}` | Operator | WPT-002 |

## 5.5 제어·안전

| Method | Path | Role | 요구사항 |
|---|---|---|---|
| POST | `/api/v1/teleop` | Operator | §11. 기능 보류 시 409 `CAPABILITY_WITHHELD`. 다른 토큰의 보정 세션 중 409 `CALIBRATION_ACTIVE` (v1.68) — owner 의 teleop 은 D-342 한도 안에서 그대로 동작 |
| POST | `/api/v1/mode` | Operator | `{mode: MANUAL\|NAVIGATION\|IDLE}`. 다른 토큰의 보정 세션 중 MANUAL·NAVIGATION 은 409 `CALIBRATION_ACTIVE`, IDLE 은 멈춤이라 허용 (v1.68). EMERGENCY 에서는 어느 목표든 409 `MODE_CONFLICT` — EMERGENCY 를 떠나는 길은 Admin `POST /safety/release` 하나다 (SAF-001, v1.196) |
| POST | `/api/v1/swarm/follow` | Operator | SWM-002 `{target_robot_id, distance, lateral, max_speed, stream_timeout_ms, source, members, mode}`. `mode: offset(기본)\|trail` (D-559, v1.170): `trail` 은 리더가 실제로 지나간 자취를 `distance`(자취 위 경로 거리) 뒤에서 CORE 가 직접 조향해 따라간다 — Nav2 목표를 내지 않고, 그 동안 Nav2 twist 는 버린다. `trail` 에서 `lateral` ≠ 0 은 400 `VALIDATION_ERROR`. 응답의 `mode` 가 `trail` 이 아니면 그 로봇은 trail 을 모른다(옛 CORE 는 필드를 버리고 offset 으로 따라간다). 첫 리더 표본이 1.5 m 넘게 떨어져 있으면 follow 를 끝내고 `swarm.aborted`(`reason: trail_join_too_far`)를 낸다. `source: fleet(기본)\|peer(예약, D-21 — 요청하면 501)`. `members` 는 대형 명단을 `robots.yaml` 순서로 — 비어 있으면 리더 승계를 하지 않고, 있으면 리더 상실 시 `swarm.succession` 을 낸 뒤 follow 를 끝낸다. `max_speed` 는 SAF-004 상한을 넘으면 400 이고, 추종 구간 동안 실제 상한으로 적용된다 — Nav2 가 무엇을 내보내든 `cmd_vel` 은 이 값으로 클리핑된다(D-31). 적용 중인 값은 `GET /safety/state` 의 `limits.session_linear` 에 보인다. 미지원 로봇은 501 `CAPABILITY_NOT_SUPPORTED` (SWM-005/CAP-003), 도킹/언도킹 중에는 409 `DOCKING_ACTIVE`, 맵핑 세션 중에는 409 `MAPPING_ACTIVE`, E-Stop 중에는 409 `EMERGENCY_ACTIVE`. 추종 중 `POST /navigation/cancel` 이나 MANUAL 전환은 대형을 끝내고 `swarm.aborted` 를 낸다 |
| POST | `/api/v1/swarm/cancel` | Operator | SWM-002 |
| GET | `/api/v1/swarm/state` | Viewer | SWM-006 — `{role, formation, active, holding, target_robot_id, source, max_speed, map_mismatch, mode, trail, stream_age_s}`. `mode`·`trail` 은 D-559 (v1.170): `trail` 은 trail 모드에서 자취가 생긴 뒤 `{leader_s, progress, hold_reason, anchor}`(`anchor` 는 D-581 v1.176: Fleet 천장 기준 odom 자취면 `fleet`, 아니면 null)(경로 거리 m; `hold_reason` 은 아래 `swarm.hold` 의 trail 사유, `stream_lost`, `map_mismatch`, `waiting_for_leader` 또는 null), 아니면 null. `map_mismatch` 는 거부 중인 리더의 `map_id` 다. 상태 스냅샷의 `swarm` 필드는 그중 `role`·`formation`·`active` 다 |
| GET | `/api/v1/calibration/session` | Viewer | D-321 부록 (v1.68) — `{session: Session\|null}`. `Session` = `{id, kind, label, owner: {id, role, label}, started_at, ttl_s, elapsed_s, remaining_s}`. `owner.id` 는 `GET /auth/whoami` 의 `id` 와 같은 불투명 토큰 id |
| POST | `/api/v1/calibration/session` | Operator | `{kind, label?, ttl_s?}` → 201 `{session}`. 모드가 IDLE·MANUAL 이 아니거나 navigation·도킹·line-follow·swarm 이 돌고 있으면 409 `MODE_CONFLICT`. `kind` 는 `^[a-z][a-z0-9_]{0,31}$`(알려진 값 `drive`·`camera`·`imu`·`ir`·`lidar`·`odometry`), `label` ≤ 80자(비면 `kind`), `ttl_s` 5–300(기본 30). 호출 토큰이 owner 가 된다. 세션은 로봇당 하나 — 이미 있으면(같은 토큰이어도) 409 `CALIBRATION_ACTIVE` + `detail.session` |
| POST | `/api/v1/calibration/session/{id}/heartbeat` | Operator | owner 만. `ttl_s` 를 다시 채운 `{session}`. 다른 토큰 403 `FORBIDDEN`, 없거나 만료된 id 404 `NOT_FOUND`. `ttl_s` 안에 heartbeat 가 없으면 세션은 만료되고 `calibration.session_expired` 가 한 번 발행된다 |
| DELETE | `/api/v1/calibration/session/{id}` | Operator | owner 또는 Admin(걸린 lease 강제 해제). 끝난 `{session}`. 그 밖의 토큰 403, 없는 id 404 |
| PUT | `/api/v1/trip-lease` | Operator | D-541 1–2 (v1.157) — `{lease_id (^[A-Za-z0-9_.:-]{1,64}$), trip_id (1–128자), holder (Fleet 사이트, 1–64자), operator_name (trip 을 시작한 이름 있는 운영자, 1–64자), ttl_s (1–10, 기본 5), job_id? (1–128자, v1.236: 작업의 lease, 단계 사이 IDLE에서 끝나지 않는다)}` → 200 `{trip_lease, renewed}`. `trip_lease` = `{lease_id, trip_id, holder, operator_name, since, expires_in_s, job_id}`. lease 가 없으면 열고(호출 토큰이 주인), 같은 토큰·같은 `lease_id` 면 만료를 `ttl_s` 로 다시 채운다(renew, `renewed: true`). 다른 `lease_id`(같은 토큰이어도) 또는 다른 토큰 409 `TRIP_LEASED`. 열 때만 거절: 보정 세션이 있음 409 `CALIBRATION_ACTIVE`(보정과 trip lease 는 서로 배타. **같은 토큰의 보정 세션도 막는다** — D-541 2항의 "다른 토큰"보다 엄격한 fail-closed 선택), E-stop 409 `EMERGENCY_ACTIVE`, MANUAL 모드 409 `MANUAL_MODE`, DOCKING 모드 409 `MODE_CONFLICT`(도킹이 바퀴를 쥐고 있다). 이미 끝난 `lease_id` 로 부르면(넘겨받기·만료·주인 아닌 멈춤·release 뒤의 renew) 다시 열지 않고 404 `NOT_FOUND` + `detail.ended {lease_id, reason, by}` 다(D-541 7: 잃은 lease 는 되살리지 않는다; CORE 는 끝난 id 를 최근 1024개 기억한다). 새 `lease_id` 는 보통대로 연다. 값 밖 400 `VALIDATION_ERROR`. 상태는 메모리에만 있다(CORE 재시작이면 lease 없음). `ttl_s` 안에 renew 가 없으면 CORE 5 Hz 타이머가 lease 를 끝내고(`expired`) line-follow 를 끄고 내비게이션을 취소해 IDLE 로 둔다. 만료를 타이머가 처리하기 전까지(≤ 0.2 s) 지난 lease 도 주인 아닌 쓰기를 막는다 |
| DELETE | `/api/v1/trip-lease/{lease_id}` | Operator | D-541 1 (v1.157) — 주인 토큰의 정상 끝(`released`). 로봇을 멈추지 않는다(Fleet 이 먼저 `stop`/취소를 보낸다). 200 `{trip_lease_ended}`. 다른 토큰 403 `FORBIDDEN`. 없거나 끝난 lease 404 `NOT_FOUND`, 바로 앞에 끝난 그 lease 면 `detail.ended {lease_id, reason, by}` — Fleet renew 가 404 를 받았을 때 끝 이유를 읽는 자리다 |
| POST | `/api/v1/trip-lease/takeover` | Operator | D-541 4 (v1.157) — `{lease_id, reason? (≤ 200자)}`. 주인 아닌 토큰의 명시적 넘겨받기: 같은 처리 안에서 lease 를 끝내고(`taken_over`, `by` = 넘겨받은 토큰의 라벨, 없으면 역할) line-follow 를 끄고 내비게이션을 취소해 IDLE 로 둔다. 200 `{trip_lease_ended, mode}`. MANUAL 은 그다음 `POST /mode` 로 따로 요청한다. 주인이 부르면 400(주인은 `DELETE`), 다른·끝난 `lease_id` 404(`detail.ended` 는 DELETE 와 같다), Viewer 403 |
| GET | `/api/v1/fleet/link` | Viewer | D-555 (v1.163) — `{configured, provisioned, expected_hostname, hub_url, enabled, connected, fleet_goal_active, arm_state, arm_deadline_s}`. `arm_state`: `armed`(WELCOME 받음, 또는 relink 없음) \| `pending`(relink 뒤 첫 WELCOME 대기, `arm_deadline_s` 남은 초) \| `grace_expired`(35 s 안에 WELCOME 없음 — SAF-003 이 끊긴 링크로 센다). 허브 페어링 토큰은 어떤 응답에도 싣지 않는다 |
| PUT | `/api/v1/fleet/link` | Admin 또는 사이트 등록 토큰 | D-555 3 (v1.163) — CORE 자신의 TLS 리스너(`https` + `network.tls`)로 온 요청만; 아니면 403 `TLS_REQUIRED`. Fleet 목표(`navigation/goal` + `correlation_id`)가 진행 중이면 409 `FLEET_GOAL_ACTIVE`. 기동 때 잘못된 Fleet·SAF-003 설정을 기본값으로 대신했으면 409 `FLEET_LINK_CONFIG_INVALID`. 새 링크는 허브의 첫 WELCOME 또는 relink 뒤 35 s(`FLEET_LINK_ARM_GRACE_S`) 중 먼저 오는 때부터 SAF-003 `fleet_link.configured` 다. 호출자는 관리자, 또는 화면 코드(`pair-physical`·`pair-admin`)로 받은 운영자 토큰 중 라벨이 `site:` 로 시작하는 것(Fleet 등록 토큰. 라벨은 인증이 아니다). 공용 개발 토큰과 그 밖은 403 `FORBIDDEN`. `{pairing_token (32–256자, [A-Za-z0-9_-]), expected_hostname (<name>.local), ca_pem (PEM 인증서, ≤ 16 KiB)}` → 비밀 덮어쓰기 `~/.rosy/fleet-link.yaml`(`ROSY_FLEET_LINK`, 0600)과 CA `fleet-link-ca.pem` 을 쓰고 FleetAgent 만 다시 시작한다(발견 프로필, D-452). 이 파일의 `fleet` 링크 키가 모든 층 위에 온다. 200 은 GET 과 같다. 틀린 본문 400 `VALIDATION_ERROR`(입력을 되돌리지 않도록 필드 detail 없음). 사건 `fleet.link_provisioned`. 능력: `GET /system/capabilities` 최상위 `fleet_link_provisioning: true` |
| DELETE | `/api/v1/fleet/link` | PUT 과 같음 | D-555 6 (v1.163) — Fleet 목표 중이면 409 `FLEET_GOAL_ACTIVE`. 비밀 파일과 CA 를 지우고 아래 층(덮어쓰기 파일을 뺀 `load_config`)의 링크(있으면)로 FleetAgent 를 다시 시작한다. 200 `{…GET, removed}`. 사건 `fleet.link_cleared` |
| POST | `/api/v1/safety/stop` | Viewer↑ | SAF-001 (누구나). 보정 세션 중에도 막지 않는다 |
| POST | `/api/v1/safety/release` | Admin | SAF-001. 어떤 경로의 래치든(API, control 정책, SAF-005 `battery_policy`·`battery_deep`) E-Stop 은 모드 EMERGENCY 와 함께 걸리므로 이 경로로 풀린다. EMERGENCY 도 아니고 래치도 없으면 409 `MODE_CONFLICT`. 래치가 IDLE 에 남은 경우(v1.196 이전 CORE)도 이 경로로 풀린다 (v1.196). 배터리 래치는 전압이 회복되어도 스스로 풀리지 않는다. 해제는 배터리 정책을 끄지 않으며 Deep 이 이어지면 다음 표본에서 다시 래치한다. 어떤 출처의 E-Stop 이든 배터리 자동 복귀(도크 복귀·`RETURN_HOME`)를 배터리 단계가 OK 로 돌아올 때까지(복귀 히스테리시스 포함) 끄고, 해제는 래치 중 무장된 복귀를 지우며, 그 사이 Critical 통과는 다시 래치한다 — 해제 뒤 로봇은 새 명령 없이 움직이지 않는다(D-502, v1.120) |
| GET | `/api/v1/safety/state` | Viewer | SAF-001. `battery` 는 정책 `{warning_percent, critical_percent, deep_percent, critical_policy}` 와 지금의 근거 `{evidence, sample_age_s, level, percent}`(D-502, v1.120 additive) — `evidence` 는 `missing`\|`fresh`\|`stale`, `level` 은 `ok`\|`warning`\|`critical`\|`deep`, 표본이 없으면 `sample_age_s`·`percent` 는 `null`. `source: battery_policy`\|`battery_deep` 래치를 풀기 전에 관리자는 `evidence: fresh` 와 `level` 을 본다. `fleet_loss_policy` 와 선택 필드 `fleet_link` (SAF-003, D-419, v1.86) `{configured, connected, lost, timeout_s, applied, correlation_id, disconnected_s, held_goal}` — `configured` 는 FleetAgent 가 돌고 있는가(승인된 `pairing_token` + 주소), `lost` 는 이번 단절에서 정책을 적용했는가, `applied` 는 실제로 한 것(`STOP`·`HOLD`·`RETURN_HOME`·`CONTINUE`·`NONE`), `held_goal` 은 `HOLD` 가 보관한 `{correlation_id, x, y, yaw}`(재접속 이벤트 뒤 비움). 서비스가 없으면 `null` |
| PUT | `/api/v1/safety/limits` | Admin | SAF-004 — `{manual_linear?, manual_angular?}` 는 프로필 최대값으로 clamp. SAF-005 배터리 임계값 `{battery_warning_percent?, battery_critical_percent?, battery_deep_percent?, battery_critical_policy?}` 과 `{fleet_loss_policy?}` 도 같은 경로로 받는다. 임계값은 `0 < deep < critical < warning <= 100` 을 만족해야 한다. `fleet_loss_policy` 는 `STOP`·`HOLD`·`RETURN_HOME`·`CONTINUE`(`CONTINUE_CURRENT_NAVIGATION` 은 `CONTINUE` 로 저장), 그 밖은 400. `RETURN_HOME` 을 받으면 응답에 선택 필드 `warning`(문자열) — 사이트 Fleet 이 죽으면 이 정책의 로봇이 Fleet 교통정리 없이 동시에 home 으로 간다 — 을 싣고 로그에 경고를 남긴다(거절하지 않음). 판정 시간 `safety.fleet_loss_timeout_s`(기본 5.0, 4–60 s, `1 + fleet.heartbeat_reply_timeout_s + 1` 이상)와 하트비트 답 시한 `fleet.heartbeat_reply_timeout_s`(기본 2.0, 0.5–10 s)는 설정 파일 전용이고, Fleet 링크가 설정된 로봇에서 어기면 CORE 가 기동하지 않는다(Fleet 없는 로봇은 경고 후 기본값) (D-419) |

## 5.6 이벤트·진단·관리

| Method | Path | Role | 요구사항 |
|---|---|---|---|
| GET | `/api/v1/events?since_seq=N&types=...` | Viewer | EVT-003 |
| GET | `/api/v1/diagnostics` | Viewer | DIAG-001 — `{health, components}`. `health` 는 최악값 롤업, 수집 전이면 `UNKNOWN` |
| GET | `/api/v1/diagnostics/{component}` | Viewer | DIAG-001 — 모르는 이름은 404. `/metrics` 의 `rosy_diagnostics_health` 와 같은 출처다 |
| GET | `/api/v1/logs/audit` | Admin | LOG-001 — `{events, log}`. `log` 은 `{writable, write_failures, write_failures_total, prune_failures, prune_skipped, serialize_failures, last_write_error, last_prune_error, last_skip_reason, last_serialize_error, dir_sync_failures, last_dir_sync_error}`: 기록이 멈추어 있으면 짧은 목록과 구분되지 않으므로, 이 로그를 믿어도 되는지 함께 답한다. `write_failures` 는 **연속** 실패(지금 쓸 수 있는가), `write_failures_total` 은 부팅 이후 누적이라 되돌아가지 않는다. `prune_failures` 는 기록이 아니라 보존 정리가 실패한 횟수다 — 기록은 남고 있으나 파일이 30 일보다 길게 자라는 중이라 경보 기준이 다르다. `serialize_failures` 는 이벤트 `data` 가 JSON 이 될 수 없어 그 값을 `repr` 로 바꿔 남긴 횟수다(기록은 남았다 — 발행한 쪽의 결함). `dir_sync_failures` 는 정리의 바꿔 끼우기는 끝났는데 그 뒤 디렉터리 fsync 가 실패한 횟수다(정리 실패가 아니다 — 정전이 이름 바꾸기를 되돌려도 옛 파일이 남는다). 사유는 채널별로 나누어 남기며(하나로 두면 정리 실패가 디스크 부족이라는 사유를 덮어쓴다) 성공했다고 지우지 않는다. 스키마로도 JSON 으로도 읽을 수 없는 줄은 삭제하지 않고 감사 로그 옆 `audit.jsonl.quarantine` 으로 바이트 그대로 옮긴다 |
| GET | `/metrics` | 내부/모니터링 | OBS-101 (Prometheus 형식, 토큰 면제는 배포 정책). `rosy_audit_write_failures_consecutive` 가 0 이 아니면 LOG-001 감사 기록이 남지 않고 있다 |
| GET | `/api/v1/ros/nodes\|topics\|services` | Admin | **미구현** — ROS-102. 그래프 스냅샷은 `/api/v1/system/runtime` 이 제공한다 |
| POST | `/api/v1/ros/publish` | Admin + 설정 ON | **미구현** — ROS-102. D-2(단일 퍼블리셔)와 충돌하므로 구현 시 별도 ADR 필요 |
| POST | `/api/v1/docking/dock` | Operator | DNC-003 (미지원 시 501). body: `{"dock": "dock_1"}` — 도크가 1개면 생략 가능. 409: `DOCKING_ACTIVE`(이미 진행 중), `LINE_FOLLOW_ACTIVE`, `MODE_CONFLICT`(DOCKING 모드를 쥘 수 없음 — MANUAL 등), `EMERGENCY_ACTIVE` |
| POST | `/api/v1/docking/undock` | Operator | DNC-003. 409: `NOT_DOCKED`, `LINE_FOLLOW_ACTIVE`, `NO_ODOMETRY`, `MODE_CONFLICT`, `EMERGENCY_ACTIVE` |
| POST | `/api/v1/docking/cancel` | Operator | DNC-003 |
| GET | `/api/v1/docking/status` | Viewer | DNC-003 — **capability 무관 항상 200**, `supported` 포함 |
| GET | `/api/v1/docking/docks` | Viewer | DNC-005 |
| GET | `/api/v1/docking/types` | Viewer | DNC-005 도크 유형·검출기 설정 목록 조회 |
| POST | `/api/v1/docking/types` | Admin | DNC-005 도크 기종 등록. v1.18 선택 필드(생략 시 기존 충전 도크 동작): `tag_id`, `tag_size_m`, `staging`(기본 true), `approach`(`bearing` 기본 \| `pose`), `settle`(`agent` 기본 \| `pose`), `tag_offset_m`, `acquire_creep_m`, `backoff_m`, `undock_turn_rad` — 주차형 도크 (docs/plans/2026-09-23-lane-network-parking-design.md) |
| POST | `/api/v1/docking/docks` | Admin | DNC-005 도크 개체 등록 |
| DELETE | `/api/v1/docking/docks/{id}` | Admin | DNC-005 |
| POST | `/api/v1/docking/docks/{id}/teach` | Operator | DNC-005 teach-by-docking |

## 5.7 Host (Host Agent 릴레이)

CORE 는 이 경로의 호스트 작업을 직접 실행하지 않고 unix 소켓으로 Host Agent 에 넘긴다(`docs/reference/rosy-host-agent-contract.md`). 네트워크·릴리스 조회에서 에이전트가 없으면 HTTP 200과 `available:false`, 사유, `evidence.evidence:"disconnected"`를 돌려준다.
파괴적 명령은 `{confirmed: true}` 와 `idempotency_key` 를 받는다.

v1.42: `GET /api/v1/host/network`와 `/release`는 기존 `{available,ok?,code,detail,recovery,data}`에 `evidence:{evidence,observed_at,age_s,stale_after_s,reason}`을 추가한다. `evidence`는 `fresh`·`delayed`·`disconnected`·`unavailable` 중 하나이며 CORE가 Host Agent의 해당 조회 완료 UTC `observed_at`을 검증해 판정한다. `age_s`는 CORE 응답 시각에서 원본 시각을 뺀 초, 임계는 15초다. 원본 시각이 없거나 잘못됐거나 미래이면 `unavailable`이며 `data:null`이다. 소켓 미연결·타임아웃은 `disconnected`, 유효하지만 15초 초과한 조회는 `delayed`다. `available`은 소켓 응답 여부를 뜻하므로 `available:true`여도 증거가 `unavailable`일 수 있다. 화면은 `fresh`일 때만 네트워크·릴리스 작업을 허용한다. 이 증거는 상태 조회 완료 시각이며 POST 적용 readback이나 물리 결과가 아니다.

| Method | Path | Role | 요구사항 |
|---|---|---|---|
| GET | `/api/v1/host/network` | Viewer | NET-001 — 현재 모드와 도달성. SSID 는 싣되 PSK 는 절대 싣지 않는다 |
| POST | `/api/v1/host/network/apply` | Admin | NET-001 (payload: `{profile_id, confirmed, idempotency_key?}`) — 등록된 NetworkManager 프로파일로 전환. PSK 는 호스트에 남고 CORE 에 들어오지 않는다 |
| GET | `/api/v1/host/release` | Viewer | OPS — current/previous/staged 와 마지막 실패 사유 |
| POST | `/api/v1/host/release/install` | Admin | OPS — 서명 검증된 릴리스 설치 |
| POST | `/api/v1/host/release/rollback` | Admin | OPS — previous 로 복귀 |
| POST | `/api/v1/host/release/clear-hold` | Admin | OPS — RECOVERY HOLD 해제 |
| GET | `/api/v1/host/commissioning` | Viewer | HWA-001 — runtime mode 와 hardware 재승인 사유. v1.22 `motion_reason`: 로봇이 왜 못 움직이는지 한 문장(D-247 7, 권한 문구와 구별). hardware 모드는 `""` |
| GET | `/api/v1/host/hardware` | Viewer | D-247 — 보드 장치 관측. Host Agent가 아니라 root `rosy-hw-probe`가 쓴 `/run/rosy-boot/hardware.json`을 엄격히 읽는다. `{available, schema:1, measured_at, age_s, stale(600 s 초과), boot_id, devices:[{id, label, bus, state, evidence, product, held_by?, source?}], detail}`. `state` ∈ `ok`·`no_response`·`bus_missing`·`driver_missing`·`needs_human`·`not_measured`. `held_by` 행은 CORE가 토픽 신선도로 판정해 덮고 `source:"topic"`을 단다. 결과가 없으면 200 `{available:false, detail:"장치 점검 결과가 아직 없습니다", devices:[]}`. v1.23: `test`(마지막 부저·램프 시험 `{request_id, action, state ∈ done·busy·unavailable·failed, detail, finished_at}` 또는 `null`), 그리고 `needs_human`인 `buzzer`·`lamp` 행은 기록된 답으로 덮는다 — 들림·보임이면 `ok`·근거 `사람 확인: <이름> <시각>`, 아니면 `no_response`·`사람 확인: 들리지 않음/보이지 않음 · …`, 둘 다 `source:"human"`. 다른 상태의 행은 덮지 않는다 |
| GET | `/api/v1/host/status-summary` | Viewer | D-260 5 (v1.25) — 운용 화면 요약줄. 부팅 표시와 같은 규칙표(`core_common.robot_state`)를 `/run/rosy-boot/boot-status.json`(엄격히 읽음; 없으면 CORE가 응답 중이므로 `CORE_READY`로 보고 `boot.available:false`), `GET /host/hardware`와 같은 덮기를 거친 장치 행, 배터리(채널이 fresh일 때만)와 SAF-005 경고 임계, runtime mode에 적용한다. `{state ∈ booting·failed·caution·ready_held·ready, label(부팅 중·실패·주의·준비됨 — 못 움직임·준비됨), reason, state_line, motion_reason, runtime_mode, boot:{available, stage}, devices:{available, stale, ok, total, problems:[{id, label, state, product}]}, battery:{percent, voltage, warning_percent, low}, temperature_c, todos:[{id, text, device?}]}`. 우선순위 실패 > 주의 > 준비됨 — 못 움직임 > 준비됨, CORE_READY 전은 부팅 중. 할 일은 급한 순서 |
| POST | `/api/v1/host/hardware/refresh` | Admin | D-247 — `/run/rosy/hw-probe.request`를 써서 `rosy-hw-probe.path`가 probe를 다시 돌리게 한다. 10초 안의 재요청은 `{accepted:false}`. 요청 파일을 못 쓰면 503 `HW_PROBE_UNAVAILABLE` |
| POST | `/api/v1/host/hardware/test` | Admin | D-247 6 (v1.23, payload: `{device: "buzzer"\|"lamp"}`, 다른 키 거부) — `/run/rosy/hw-test.request` `{action, request_id, requested_at, by}`를 써서 root `rosy-hw-test`가 부저를 150 ms×3 울리거나 램프를 빨강·초록·파랑 1 s씩 켜게 한다. subprocess 없음. 200 `{accepted:true, request_id, device, detail}`. 10초 안 재요청은 429 `HW_TEST_COOLDOWN`, 요청 파일을 못 쓰면 503 `HW_TEST_UNAVAILABLE`. 결과는 `GET /host/hardware`의 `test` |
| POST | `/api/v1/host/lamp/identify` | Operator | D-472 (v1.129), `{color?:"blue"\|"amber"}`. v1.185(D-596): 쿼리 `?quiet=true`면 같은 점멸을 호출음(두 번 삑) 없이 한다(rosy-hw-test·rosy-face 동작 `identify_<색>_quiet`, 다음 로봇 payload부터). `color`를 빼면 이 로봇의 설정 색 (CORE 설정 `lamp_identify.color`, 없으면 D-472 4항 기본 `rosy_26` blue·`rosy_60` amber(주황)); 둘 다 없으면 409 `IDENTIFY_COLOR_UNSET`. CORE는 식별 요청만 기록하고(`requested_at` ms) 후면 램프는 `rosy-face`만 구동한다: 1 s 켬→1 s 끔→1 s 켬, 3.5 s에 강제 종료. 요청부터 끝까지 6 s 이내: `rosy-hw-test`는 1.5 s, `rosy-face`는 1 s보다 오래된 식별 요청을 버린다. 정상 패턴(ready·manual·navigating·docking·illumination) 위에서만 켠다 — 움직이는 로봇 포함(addendum 5항). E-Stop·EMERGENCY·고장·주의·booting·blocked 또는 CORE 인계가 없으면 즉시 `failed`로 거절하고, 점멸 중 그렇게 되면 끊고 상태 패턴으로 돌아간다. 바퀴·모드·E-Stop·localization은 바꾸지 않는다. 200 `{accepted:true, request_id, color, state:"pending_visual_confirmation"}`는 영상상 식별 성공을 뜻하지 않는다. 결과는 `GET /host/hardware`의 `test`. v1.195(D-596 개정 2026-10-10): 결과는 아래 `GET /host/lamp/identify/{request_id}`로도 묻는다. 기존 `HW_TEST_COOLDOWN`/`HW_TEST_UNAVAILABLE` 거절을 공유한다. |
| GET | `/api/v1/host/lamp/identify/{request_id}` | Operator | v1.195 (D-596 개정 2026-10-10). 마지막 식별 요청의 결과 `{request_id, state:"pending"\|"shown"\|"refused"\|"expired", reason, detail}`. `shown` = rosy-face가 점멸을 켰다(영상 식별 성공 아님). `refused` = 켜지 않았거나 끊었다, `reason`은 rosy-face의 거절 이유 `CAUTION_ACTIVE`(주의 표시: 차선 HOLD·도킹 실패·배터리 등)·`ESTOP`·`STATE_DISPLAY`(고장·booting·blocked 등 정상 패턴 아님)·`CORE_UNAVAILABLE`(CORE 인계 없음)·`LAMP_UNAVAILABLE`, 이 이유를 모르는 payload나 다른 실패면 hw-test 상태 대문자(`FAILED`·`UNAVAILABLE`·`BUSY`). 답이 20 s 안에 없으면 `expired`. CORE는 마지막 요청 하나만 기억한다: 다른 `request_id`나 CORE 재시작 뒤에는 404 `IDENTIFY_REQUEST_UNKNOWN`. 이유는 다음 로봇 payload(rosy-face·rosy-hw-test)부터 온다(D-412). 이 경로가 없는 CORE도 404다. |
| POST | `/api/v1/host/hardware/confirm` | Admin | D-247 6 (v1.23, payload: `{device: "buzzer"\|"lamp", observed: bool}`, 엄격한 bool) — 사람의 답을 `{observed, by(토큰 id), label, at}`로 CORE 상태 디렉터리 `~/.rosy/hw-confirmations.json`(0600, 원자적 교체)에 기록한다. `rosy-hw-test`의 마지막 결과가 같은 장치·`state:"done"`·5분 안에 끝난 것이어야 하며, 아니면 409 `HW_CONFIRM_NO_TEST`. 기록에는 그 시험의 `request_id`가 함께 남는다(파일에만, 응답·카드에는 싣지 않음). 장치마다 마지막 답 하나. 200 `{recorded:true, device, observed, by, label, at}`. 쓰지 못하면 503 `HW_CONFIRM_UNAVAILABLE` |

---

## 5.8 로봇 SSH 접속 (D-418, v1.89)

관리자가 로봇에 SSH로 들어갈 길을 연다. 모든 경로는 **Admin** 전용이다. CORE는 비특권이라(D-161) 직접 적용하지 않는다: `/run/rosy/ssh-access.request`(`{schema:1, request_id, action, requested_at, answer_by, by, ...}`; `answer_by`는 CORE가 기다리기를 멈추는 epoch 초)를 쓰면 root `rosy-ssh-access.path`가 도우미를 깨우고, 도우미가 형식·개수·만료를 **따로 다시 검사**한 뒤 적용하고 `/run/rosy/ssh-access.response`(root:rosy-core 0640)에 답한다. CORE는 그 답을 **최대 10 s** 기다리고(다른 요청의 잠금 대기까지 합한 한 기한), 읽자마자 지운다. 답이 없으면 503 `SSH_ACCESS_UNAVAILABLE`이고 요청 파일은 거둬들인다. `POST /password`가 시간 초과면 CORE가 기다리지 않는 `password_off` 요청을 남기고, 도우미도 `answer_by` 1 s 전을 넘긴 비밀번호는 답에 싣지 않고 되돌린다. 아직 처리되지 않은 그 `password_off`는 덮어쓰지 않고 기한 안에서 처리되기를 기다린다. 답 파일을 못 쓰면 켠 비밀번호를 다시 끈다. 본문이 JSON이 아니면 400 오류 봉투이고 도우미까지 가지 않는다. 시각은 모두 UTC `YYYY-MM-DDTHH:MM:SSZ`. 스키마: `core_common.protocol.schemas`의 `Ssh*` 모델.

| Method | Path | Role | 요구사항 |
|---|---|---|---|
| GET | `/api/v1/host/ssh/host-keys` | Admin | `{hostname, host_keys:["<type> <base64>", ...]}` — `/etc/ssh/ssh_host_*_key.pub`의 공개키(주석 제외). 등록 도구가 첫 접속 전에 `known_hosts`를 쓴다(TOFU 없음). CORE가 직접 읽는다 |
| GET | `/api/v1/host/ssh/keys` | Admin | `{keys:[{label, type, fingerprint("SHA256:…"), added_at, expires_at, added_by}]}` — 관리 키 목록. 만료가 지난 키는 도우미가 정리하며 `history.jsonl`에 `expire`로 남긴다 |
| POST | `/api/v1/host/ssh/keys` | Admin | payload `{public_key:"<type> <base64> [comment]", label, expires_days:1..365}`, 다른 키 거부. 허용 종류 `ssh-ed25519`·`sk-ssh-ed25519@openssh.com`·`ecdsa-sha2-nistp256\|384\|521`. 라벨 `^[a-z0-9][a-z0-9._:-]{0,47}$`(팀 키 `team:<name>`, 기기 `dev:<name>`). **201** `{label, fingerprint, expires_at}`(만료는 분 단위로 내림). 422 `SSH_INVALID`, 409 `SSH_LABEL_EXISTS`·`SSH_KEY_EXISTS`·`SSH_KEYS_FULL`(32개). `added_by`는 요청한 토큰의 라벨(없으면 토큰 id) |
| DELETE | `/api/v1/host/ssh/keys/{label}` | Admin | **204**. 없는 라벨 404 `SSH_KEY_NOT_FOUND` |
| POST | `/api/v1/host/ssh/password` | Admin | payload `{minutes:1..60}`. **200** `{user:"rosy", password:"<temporary-password>", expires_at}`, `Cache-Control: no-store`. 값의 형식은 접두어 `rosy-` 뒤에 하이픈으로 나눈 4자 세 묶음이다. 비밀번호는 AP 비밀번호와 같은 헷갈리지 않는 31자(`abcdefghjkmnpqrstuvwxyz23456789`)로 `secrets`가 만들고 `chpasswd`(stdin)로 적용한다. 이 응답과 shadow 밖 어디에도(기록·로그·상태 파일) 남지 않는다. 다시 부르면 새 비밀번호·새 만료. LCD에는 아직 보이지 않는다(후속) |
| GET | `/api/v1/host/ssh/password` | Admin | `{enabled: bool, expires_at: "<Z>"\|null, lock_pending: bool}` — 비밀번호는 싣지 않는다. `lock_pending`은 `usermod` 잠금이 실패해 거부 drop-in이 막고 있고 재시도를 기다리는 중 |
| DELETE | `/api/v1/host/ssh/password` | Admin | **204** — 지금 끈다 |

- **관리 키 파일:** `/var/lib/rosy/ssh/authorized_keys`(0644, `keys.json`에서 매번 다시 만든다). 줄 형식 `expiry-time="YYYYMMDDHHMMZ" <type> <base64> rosy-managed:<label>` — 만료는 sshd가 직접 강제한다. sshd는 drop-in `/etc/ssh/sshd_config.d/50-rosy-managed-keys.conf`(`Match User rosy` 안의 `AuthorizedKeysFile .ssh/authorized_keys /var/lib/rosy/ssh/authorized_keys`)로 `rosy` 계정에만 이 파일을 읽는다. `/etc/ssh`는 D-388 이미지 층 밖이라 도우미가 설치·유지한다.
- **메타데이터·감사:** `/var/lib/rosy/ssh/keys.json`·`password.json`·`history.jsonl`(root 0600). 사건: `add`, `revoke`, `expire`, `password_on`, `password_off`(`reason: requested|expired|boot|late|undelivered` — `late`는 `answer_by` 안에 답하지 못해 되돌림, `undelivered`는 답 파일을 못 써서 되돌림), `password_deny`(`usermod` 잠금 실패: 거부 drop-in과 재시도).
- **임시 비밀번호:** 켜면 `/etc/ssh/sshd_config.d/60-rosy-temp-password.conf`에 `Match User rosy Address 10.0.0.0/8,172.16.0.0/12,192.168.0.0/16` → `PasswordAuthentication yes`, `MaxAuthTries 3`, 이어서 `Match User rosy` → `PasswordAuthentication no`(사설 대역 밖은 전역 설정과 상관없이 거부). `sshd -t`가 거부하면 되돌리고 503. 끄기(요청·만료·부팅)는 shadow 필드를 `*`로 먼저 잠그고, drop-in을 지우고, 실행 중인 `ssh.service`를 다시 읽힌다. 만료 검사는 비밀번호가 켜진 동안만 도는 `rosy-ssh-password-expire.timer`(30 s)이고(타이머가 안 켜지면 비밀번호도 켜지 않는다), 부팅 때마다 `rosy-ssh-access-boot.service`가 `sockets.target`·`ssh.socket`·`ssh.service`보다 먼저 끈다(`DefaultDependencies=no`; `ssh.socket`이 켜진 Ubuntu 24.04에서 순서 순환이 없다). 끄기는 다른 정리(키 기록 손상 등)보다 먼저, 따로 돈다. `usermod`가 잠그지 못하면 `Match User rosy` → `PasswordAuthentication no` drop-in으로 sshd가 거부하게 하고 타이머가 잠금을 다시 시도한다. 비밀번호 만료는 벽시계(`expires_at`)나 부팅 시계(`CLOCK_BOOTTIME` 기한과 boot id) 중 먼저 오는 쪽이다. 키 만료는 시계와 지금까지 본 가장 늦은 시각(`clock.json`) 중 늦은 쪽으로 판단한다(RTC 없는 Pi가 과거 시각으로 부팅해도 만료가 되돌아가지 않는다). 시계보다 2일 넘게 앞선 기록은 앞서 간 시계로 보고 버린다. 그래서 시계가 마지막 기록보다 2일 넘게 뒤처진 채로 부팅하면 기록도 버려지고, NTP가 맞출 때까지 키 만료는 뒤처진 시계로 센다(sshd의 `expiry-time`도 같은 시계를 쓴다). NTP 동기는 `timedatectl show -p NTPSynchronized`로 본다. timedated가 커널의 `STA_UNSYNC`를 읽으므로 이미지의 chrony에서도 맞다. 도우미가 직접 `adjtimex`를 부르지 않는 까닭은 단위의 seccomp 필터(`@system-service`, `ProtectClock=true`)가 그 호출을 SIGSYS로 죽이기 때문이다. 동기되면 기록은 시계로 맞춘다. 비밀번호는 boot id를 읽지 못하면 켜지 않는다(503).

---

## 5.9 OMX-AI Gazebo Pilot 전용 API (D-390, v1.70)

오류는 ERR-101의 `{error:{code,message,detail}}` 형식이다. 스키마 오류는 400 `VALIDATION_ERROR`, 인증 없음은 401 `UNAUTHORIZED`, 조종권·상태 충돌은 409 `MODE_CONFLICT`로 돌려준다.

이 경계는 격리된 개발용 Gazebo 컨테이너에서만 제공한다. CORE/Fleet 토큰, 실물 OMX profile, Fleet Action UDS 권한과 분리된다. `/pilot` 정적 화면과 아래 API는 같은 origin이다. 브라우저 명령은 단일 `ArmCommandOwner`를 거쳐 `/arm_controller/follow_joint_trajectory`로 간다.

| Method | 경로 | 요청/응답 |
|---|---|---|
| GET | `/api/v1/sim/omx/target` | 공개 `{kind:"omx_sim",simulation:true,instance_id,joints,gripper,camera,recording,controls}`; `controls`(v1.87 additive, D-411 B)는 §9.1 `rosy.controls/1` — SIM은 `joint_jog` 하나(`id:"arm"`, 관절별 한계 = 고정된 vendor URDF 범위(`omx_f_kinematics.yaml`) ∩ SIM owner 허용 범위, `max_step_rad` 0.05, `duration_s` 0.4 = 각 요청에 보낼 목표 길이, `command:"bounded_goal"`; 이전 목표가 끝난 뒤에만 다음 목표, 100 ms 스트림 없음, D-390 §2). D-411 C부터 그리퍼는 `joint_jog`에서 빠지고 따로 `gripper` 항목(`id:"gripper"`, `joint`, `open`·`closed` = 셀 프로필 `gripper.open`·`gripper.closed`(1.0·0.0 rad), `presets{open, half, close}` — `half`는 가운데, `readback:["position","grasp"]`, `max_velocity` = 셀 프로필과 URDF 그리퍼 속도 중 작은 값(0.5 rad/s))이 된다. SIM owner 허용 범위는 모든 관절(팔·그리퍼)이 `deploy/robot/omx/sim/cell_profile.yaml` 범위 ∩ URDF 범위다(실물 한계 아님, URDF에 없는 관절은 서버 기동 오류). `joint_jog`에 알리는 범위는 그 허용 범위를 양쪽에서 `start_state_tolerance_rad`(0.02 rad)만큼 줄인 것이다 — 알린 끝을 조금 넘어 멈춰도 readback이 허용 범위 안이라 owner가 HOLD(`joint_state_limit`)를 걸지 않는다. 조그는 알린 범위 밖으로 더 나가는 목표를 409 `joint_limit`으로 거절하고, 범위 밖에서 안쪽으로 돌아오는 목표는 받는다. 시뮬레이션 전용이며 실물 OMX를 열지 않는다; Pinky CORE에서는 404 |
| POST | `/api/v1/sim/omx/pair` | 로컬 콘솔의 10분 유효 일회용 `{code}` → `{token}`; 성공 201, 재사용 403 |
| GET | `/api/v1/sim/omx/whoami` | Bearer → `{role:"operator"}` |
| POST/PUT/DELETE | `/api/v1/sim/omx/seat[/{seat_id}]` | 단일 조종권 취득·1초 간격 갱신·반납. lease 10초; 만료/반납 시 진행 목표 취소 요청. 취소 ACK는 정지 증거가 아니다 |
| GET | `/api/v1/sim/omx/state` | `{instance_id,ready,owner_state,owner_reason,action_server_ready,state_sequence,joint_age_ms,positions,active_goal,gripper}`. 신선한 관절 상태와 action server가 없으면 `ready:false`(목표 실행 중에도 `ready:false`·`owner_state:"active"`). `gripper`(v1.87, D-411 C) `{joint, position, state, open, closed, hold_target}`(`hold_target` = 끝난 그리퍼 목표 뒤 팔 목표가 그리퍼 칸에 보낼 명령 값, 없으면 `null`) — `state` ∈ `open`·`closed`·`holding`·`moving`·`unknown`. `unknown` = 관절 상태가 낡았거나 owner HOLD, 마지막 그리퍼 목표가 `UNKNOWN_HOLD`. `moving` = 그리퍼 목표 진행 중이거나 최근 0.5 s 안에 위치가 0.005 rad 넘게 변함. `closed` = 위치가 `closed`에서 0.05 rad 이내. **`holding`** = 닫기 목표(`closed`에서 0.05 rad 이내인 목표)가 `SUCCEEDED`로 끝났는데 위치가 `closed`에서 0.05 rad 넘게 떨어져 멈춤 — 손가락이 무언가에 걸렸다는 시뮬레이션 위치 판정이며 쥠 힘 증거가 아니다(D-390 §5). 그 밖은 `open` |
| POST | `/api/v1/sim/omx/goals` | `OmxSimJog` → `OmxSimGoal`, 202. 같은 `request_id`·동일 payload는 멱등; 다른 payload는 409 |
| POST | `/api/v1/sim/omx/gripper` | v1.87, D-411 C. `OmxSimGripperGoal` → `OmxSimGoal`, 202. 그리퍼만 절대 위치로 옮기는 목표 하나(팔 관절은 현재 readback). 조그와 같은 seat·instance·만료·단일 진행 목표·HOLD 규칙, 같은 영수증 공간(같은 `request_id`를 조그와 그리퍼가 함께 쓰면 409). 위치가 알린 범위(허용 범위에서 0.02 rad 안쪽) 밖이면 409 `gripper_limit`, `|position − readback| − 0.05 rad > max_velocity × duration_s`이면 409 `gripper_velocity_limit`(0.05 rad는 클라이언트가 목표를 잰 readback과 접수 시 readback의 차이를 받는 여유), 그리퍼 목표를 받지 않는 서버는 409 `gripper_not_configured`. 진행·취소는 `/goals/{command_id}` 경로 그대로 |
| GET | `/api/v1/sim/omx/goals/{command_id}` | 비동기 goal readback. 미등록 404 |
| POST | `/api/v1/sim/omx/goals/{command_id}/cancel?seat_id=...` | 취소 요청. `CANCEL_REQUESTED`는 정지 완료가 아니다 |

`OmxSimJog` 필수 필드: `instance_id`, `seat_id`, `request_id`, `joint`, `delta_rad`(0이 아니며 절댓값 ≤0.05 rad), `duration_s`(0.1~1.0), `state_sequence`, `expires_at_ms`. 명령은 현재 관절 상태에서 해당 관절만 상대 이동하며 모든 관절의 현재 값을 함께 보낸다. 최근 5초 안에 Pilot API가 제공하지 않은 sequence, 6초보다 먼 만료 시각, 이미 만료된 요청, 범위 초과, 진행 중 goal, HOLD는 거부한다. ROS는 새 sequence를 계속 발행하므로 제출 시점에는 가장 최근의 신선한 관절 상태를 사용한다. `OmxSimGoal.state`는 `LOCAL_ACCEPTED`, `ROS_ACCEPTED`, `RUNNING`, `SUCCEEDED`, `REJECTED`, `CANCEL_REQUESTED`, `CANCELED`, `UNKNOWN_HOLD` 중 하나다. `LOCAL_ACCEPTED`는 ROS 수락이 아니고, action의 `SUCCEEDED`는 물리적 정지나 목표 도달의 독립 증거가 아니다. schema 정본은 `core_common.protocol.omx_sim`이다.

`OmxSimGripperGoal`(v1.87, D-411 C) 필수 필드: `instance_id`, `seat_id`, `request_id`, `position`(유한한 rad, 절대값), `duration_s`(0.2~2.0), `state_sequence`, `expires_at_ms`. 다른 필드는 거부한다. SIM owner의 목표 길이 상한은 2.0 s다(`OmxSimJog`는 스키마가 1.0 s까지만 받는다). 그리퍼 목표가 `SUCCEEDED`로 끝난 뒤의 팔 조그는 그리퍼 칸에 readback 대신 명령 값을 보낸다(readback을 보내면 쥔 물체를 놓는다). 닫기 목표가 닫힘에 못 미쳐 멈춘 경우(`holding`)에는 **멈춘 위치에서 닫힘 쪽으로 `gripper.preload`(셀 프로필 0.05 rad)만큼** — 닫힘 자체가 아니다(위치 제어에서 닫힘을 명령하면 멈춘 오차 전체로 누른다). 이 값은 목표가 끝난 순간의 readback(없으면 그 뒤 첫 신선한 readback)으로 고정되어 조그마다 더 조여지지 않으며 닫힘을 넘지 않는다. 컨트롤러는 SUCCEEDED 뒤 그 목표의 마지막 점(닫힘 쪽 목표 = 멈춘 오차 전체)을 계속 명령하므로, 서버는 쥐고 있음이 된 닫기 직후 owner가 비면 그리퍼 목표만 `hold_target`으로 옮기는 목표 하나(`command_id` `hold-<닫기 id>`)를 스스로 낸다 — 쉬는 동안의 조임과 팔 조그 중의 조임이 같아진다. 그동안 `owner_state`는 `active`다. ROS 실패·시간 초과로 끝난 그리퍼 목표는 `UNKNOWN_HOLD`(`reason` `terminal_status_<status>_result_<code>`)이며 `holding`으로 읽지 않는다. Pilot은 한 번에 목표 하나를 보내며, 길이는 `거리 / (0.9 × max_velocity)`를 올림해 0.2–2.0 s 안으로 맞추고(0.9는 readback 흔들림 여유), 2.0 s로 못 가는 거리(0.5 rad/s에서 0.9 rad 넘게)는 2.0 s에 닿는 곳까지만 보낸다(다시 누르면 마저 간다). `max_velocity`가 없는 서버에는 전체 행정을 2.0 s로 보고 비례한다. 열림 % 슬라이더는 손을 뗄 때 목표 하나만 보낸다.

v1.70 추가 경로(모두 Bearer 인증):

| Method | 경로 (`/api/v1/sim/omx` 아래) | 요청/응답 |
|---|---|---|
| GET | `/camera` | `{available,fresh,capture_time_ns,sim_time_ns,age_ms,camera_identity,width,height}` |
| GET | `/camera/frame` | 신선한 RGB 프레임의 JPEG, `Cache-Control:no-store`; 결측/오래됨 409 |
| GET | `/recordings` | `OmxSimRecording`: `{status,episode_id,task,task_outcome,frame_count,issues}` |
| POST | `/recordings` | 소유 조종권 `{seat_id,task}` → 기록 상태, 201; 신선한 영상/관절/명령 소유자 필요 |
| POST | `/recordings/{episode_id}/stop` | 소유 조종권 `{seat_id,outcome:success\|failure\|unspecified}` → 기록 상태 |
| GET | `/recordings/{episode_id}/manifest` | 원본 manifest; 미등록/잘못된 UUID 404; 서버 파일 경로 없음 |

기록은 10 simulation FPS 영상과 그 시각 이전 50 ms 이내의 관절 상태, ROS 수락 UUID가 있는 절대 목표(rad)를 묶는다. 영상 신선도 2초와 현재 관절 스트림 신선도 0.5초는 별도다. 지연 영상은 과거 상태와 pair하며 미래 상태를 사용하지 않는다. 프레임 누락/시계 역행/취소/HOLD/조종권 반납·만료/서버 종료/미선택 결과는 `incomplete`이며 export를 거부한다. `success`는 운용자가 지정한 과제 결과이며 Action 성공과 구분한다. 기록은 최대 3000프레임, 저장 위치는 서버 설정으로만 지정한다. 행의 목표 길이는 0.1~2.0 s다. v1.87(D-411 C): 그리퍼 목표를 받는 서버의 에피소드는 출처에 `gripper_joint`를 두고 모든 행에 `action.gripper`(그 행 `action`의 그리퍼 칸과 같은 절대 목표 rad)를 남기며, LeRobot export에 `action.gripper` 특성(`float32`, `(1,)`, `["position_rad"]`)을 더한다. `gripper_joint`가 없는 이전 에피소드는 그대로 검증·export된다. LeRobot 0.4.4 오프라인 변환은 `omx_sim_ros`/rad를 유지하고, 영상 시간축은 index/fps, 실제 Gazebo 시각은 int64 source 필드와 원본 해시로 보존한다. 업로드·학습·정책 실행 API는 없다. 실물 OMX 명령을 이 경로로 보내거나 `omx.disabled.yaml`을 켜서는 안 된다.

## 5.10 Pilot 로봇 녹화 (D-411, v1.83)

녹화 주체는 카메라 유닛(`rosy-camera`)의 `pilot_recorder_node` 다. CORE 는 `std_srvs/SetBool` `pilot_recorder/set_active` 로 시작·정지를 **요청**만 하고, 래치된 `pilot_recorder/status`(`rosy.pilot.recording.status/1`, 1 Hz)를 받아 판단한다. 녹화는 증거일 뿐이며 제어 경로는 이 토픽들을 읽지 않는다(D-2). 스키마 정본은 `core_common.protocol.recording` 이다.

| Method | 경로 | 권한 | 요청/응답 |
|---|---|---|---|
| GET | `/api/v1/recordings` | Viewer | `{active, items[RecordingSummary], download_allowed, download_blocker}` — `active` 는 녹화기 상태(낡았으면 `null`), `items` 는 최신순 `{id, started_at, ended_at, duration_s, bytes, topics, status: recording\|complete\|incomplete, manifest_sha256, fetched}`, `download_blocker` 는 `RECORDING_BUSY`·`ROBOT_MOVING`·`null` |
| GET | `/api/v1/recordings/active` | Viewer | `{active, owned, preview_modes}` — `owned` 는 호출 토큰이 시작한 녹화인가. 신선한 recorder 상태와 설치된 typed start 서비스가 있으면 preview_modes는 raw/annotated, legacy는 raw, 미확인은 [] |
| POST | `/api/v1/recordings` | Operator | optional `{preview_mode:raw\|annotated}`; body 생략은 raw. 임의 key·다른 값·잘못된 타입은 400. 201 실제 `RecorderStatus`(대개 `starting`, 아래); preview_mode는 recorder 확인값이다. 거부: 409 `RECORDING_BUSY`, 507 `RECORDING_QUOTA_FULL`·`RECORDING_DISK_FULL`, 503 `RECORDER_UNAVAILABLE` |
| POST | `/api/v1/recordings/active/stop` | Operator | `RecorderStatus`(대개 `stopping`). `starting`·`recording` 에서 받는다. 시작한 토큰·Admin, 또는 소유자가 없는 녹화(CORE 재시작)면 아무 Operator; 그 밖은 403 `FORBIDDEN`. 없으면 409 `RECORDING_NOT_ACTIVE` |
| GET | `/api/v1/recordings/{id}/archive` | Operator | `application/x-tar` 무압축 USTAR(mcap 은 이미 zstd), `Content-Length` 정확, `Cache-Control: no-store`. 멤버는 `<id>/manifest.json` 다음 manifest 가 적은 파일만. 정지 중에만(409 `RECORDING_BUSY`·`ROBOT_MOVING`), 한 번에 한 수신만(진행 중이면 409 `RECORDING_BUSY`), 없는·안전하지 않은 id 404 `RECORDING_NOT_FOUND`. 수신 중에도 정지 조건을 블록마다 다시 보고, 깨지거나 파일이 계획과 달라지면(링크·교체·크기) 본문을 `Content-Length` 보다 짧게 끊는다. 짧은 본문은 실패이며, tar 는 이어 받을 수 없으므로 나중에 처음부터 다시 받는다 |

- 녹화기 상태 `state`: `idle` · `starting` · `recording` · `stopping` · `error`. `starting`·`recording`·`stopping` 은 `id` 를 싣고, 셋 다 진행 중으로 친다(시작·수신 `RECORDING_BUSY`, 목록의 그 항목은 `status: recording`, 소유자·링크·seat 규칙 적용, 정지 가능).
- `starting`: 시작 요청(201)은 대개 `starting` 을 돌려준다. `ros2 bag record` 는 띄운 뒤 첫 파일을 열기까지 몇 초 걸리고(Gazebo 실측 4.0 s), 그동안은 아무것도 기록되지 않는다. 녹화기는 `<세션>/bag/*.mcap` 이 생기면 `recording` 으로 넘긴다 — 파일 크기는 보지 않는다(mcap 은 zstd 청크·캐시를 닫을 때까지 디스크에 쓰지 않아 20 s 세션 내내 0 바이트였다). rosbag2 는 이 파일을 연 직후 구독한다(실측: 파일 연 뒤 0.2 s 에 첫 메시지, 0.4 s 안에 모든 토픽 구독). 그 순간부터 `elapsed_s` 를 세고, session.json 의 `started_at` 도 그 시각으로 바꾸며(처음 요청 시각은 `requested_at`), manifest `duration_s` 와 600 s 상한도 거기서 센다. 15 s 안에 파일이 없으면 녹화기가 스스로 멈추고 `last_stop_reason: writer_start_timeout` 을 남긴다. `starting` 중 정지는 정상 정지다(`duration_s: 0`). session.json `writer_ready` 는 시작 때 `false`, 파일이 생기면 `true` 이고, `false` 인 채 끝난 세션(`starting` 중 종료·충돌 뒤 복구)의 길이는 0 이다. 운전은 `recording` 이 보인 뒤에 시작한다. 카메라 압축 토픽은 `starting` 부터 켠다(`pilot_recorder/active`). `recording.started` 는 시작 요청이 받아들여진 때(대개 `starting`) 나가며, 기록이 실제로 시작된 시각은 아니다.
- 배포: 카메라 유닛(녹화기)과 CORE 는 함께 올린다. `starting` 은 같은 `rosy.pilot.recording.status/1` 스키마에 새로 더한 값이라, 이전 CORE 는 `starting` 상태를 검증에서 버린다 — 준비 중인 몇 초 동안 마지막 `idle` 을 붙들거나 낡았다고(`RECORDER_UNAVAILABLE`) 보고, 그사이 두 번째 시작도 막지 못한다.
- 녹화본 `id` 의 기기 부분(session.json `device`)은 로봇이다: 노드 파라미터 `device`, 없으면 노드 네임스페이스(장비에서는 `ROSY_NAMESPACE` = `rosy_NN`), 둘 다 없을 때만 호스트 이름. 영숫자·`_`·`-` 만, 48자 이하, `_` 로 끝나지 않는다.
- 한 번에 1개, 최대 600 s. 전용 쿼터(기본 4 GiB, 예비 1 GiB) 안에서 시작하며, 디스크 빈 공간이 512 MiB 이하면 시작하지 않는다. 쿼터를 넘기면 녹화기가 `quota`, 빈 공간이 바닥나면 `disk_full` 로 스스로 멈춘다.
- 정지 뒤 녹화기가 manifest(`rosy.pilot.recording.manifest/1`: 파일별 `{path, bytes, sha256}`, 선택 `bag_returncode`·`writer_killed`)를 작업 스레드에서 쓰는 동안 상태는 `stopping` 이고, 그동안 시작·수신은 `RECORDING_BUSY` 다.
- 토픽: `camera/front/compressed`(녹화 중에만 발행), `cmd_vel`, `odom`, `scan`, `line/observation`, `teleop/intent`, `line/keep_debug`, `ir_sensor/range`(`std_msgs/UInt16MultiArray`, 로봇 기준 좌·중·우 원시 ADC 0–4095). 초음파 `us_sensor/range` 는 넣지 않는다.
- CORE 가 스스로 멈추는 경우: 시작 토큰이 `/ws/state` 를 한 번이라도 연 뒤 그 연결이 5 s 넘게 없음(`link_lost`), 다른 토큰의 teleop 이 수락됨(`seat_changed`). `/ws/state` 를 열지 않은 REST 전용 소유자는 `link_lost` 로 멈추지 않는다(600 s 상한은 그대로). 둘 다 비차단 정지 요청이고, `recording.stopped` 는 녹화기 상태가 정지를 확인한 뒤에야 낸다(거부되거나 3 s 안에 확인되지 않으면 다음 상태에서 다시 묻는다). 소유자 없는 녹화(CORE 재시작)가 녹화기 쪽에서 끝나도 `recording.stopped`(`by: null`)를 한 번 낸다. 이벤트는 §8 `recording.started`·`recording.stopped`.
- 녹화기 상태는 `boot_id`(녹화기 기동마다 새 값)와 `seq`(상태를 만들 때마다 증가)를 싣는다. CORE 는 같은 `boot_id` 에서 이미 받은 것보다 오래된 상태(예: 시작 전에 나가 시작 뒤에 도착한 `idle`)를 버린다. `seq: 0` 은 순번 없음.
- tar 의 마지막 바이트가 나간 녹화만 CORE 가 `pilot_recorder/fetched`(`{id}`)로 알리고, 녹화기가 `fetched.json` 을 써 쿼터 정리 대상으로 삼는다. 받지 않은 녹화는 지우지 않는다.
- 저장 위치는 `/var/lib/rosy/pilot-recordings`(설정 `recording.pilot_root`): `rosy-camera` 가 쓰고 setgid `rosy-core` 그룹으로 CORE 가 읽기만 한다.

`teleop/intent`(ROS `std_msgs/String` JSON, `rosy.teleop.intent/1`)는 CORE 가 teleop 판정마다 낸다 — 관리자 앞 거부(capability·보정 lease·keep)도 포함. 싱크 실패는 명령을 거부하지 않는다. 수신 중에도 정지 조건을 블록마다 다시 보고, 깨지거나 파일이 계획과 달라지면(링크·교체·크기) 본문을 `Content-Length` 보다 짧게 끊는다. 짧은 본문은 실패이며, tar 는 이어 받을 수 없으므로 나중에 처음부터 다시 받는다.

| 필드 | 형 | 의미 |
|---|---|---|
| `schema` | str | `rosy.teleop.intent/1` |
| `raw_linear` · `raw_angular` | float\|null | 요청 값(유한하지 않으면 null) |
| `linear` · `angular` | float\|null | 수락 시 클립된 값, 거부면 null |
| `source` | str | 명령 원천(`manual`) |
| `mode` | str | 판정 시점 모드 |
| `accepted` | bool | 수락 여부 |
| `code` | str | 거부 코드, 수락이면 `""` |
| `t_mono_ns` | int | CORE monotonic ns |

## 5.11 Pilot 방 목록 — `GET /api/v1/site/rooms` (D-343·D-432·D-452, v1.98)

브라우저는 mDNS를 직접 수행하지 않는다. CORE는 공용 `_rosy._tcp` event cache를 먼저 읽고, 해당 adapter가 없을 때만 제한된 Avahi fallback을 사용한다.
행은 발견 규칙 v0.1의 공개 정보만 싣는다 — 토큰·비밀은 싣지 않는다(D-193).

| Method | 경로 | 권한 | 요청/응답 |
|---|---|---|---|
| GET | `/api/v1/site/rooms` | 공개 발견 읽기(인증 없음) | `{rooms: [{hostname, address, port, kind, url}]}` — `url`은 그 기기의 pilot 진입(`http[s]://<hostname>:<port>/pilot/#join`; hostname은 정규화된 `.local` FQDN이고 `tls=required`는 HTTPS). 발견 adapter/Avahi가 없거나 실패하면 503 `DISCOVERY_UNAVAILABLE`. `Cache-Control: no-store`. |

행은 미승인 발견 힌트이고 선택 후 해당 origin의 기존 인증·승인을 거친다. 자격을 전달하거나 자동 등록하지 않는다. canonical private IPv4 분류·최대 64행·중복/신원 충돌 제외를 유지한다. fallback은 동시 한 번, 성공/실패 5초 cache, stdout 128KiB, subprocess 4초와 유한 종료/회수 상한을 갖는다. 응답 typed 계약은 `core_common.protocol.schemas.SiteRoomsSnapshot`이다.

---

# 6. WebSocket 프로토콜 (로봇)

## 6.1 `/ws/state` — 상태 스트림

서버가 10 Hz(기본, 설정 가능)로 상태 JSON을 push한다.

```json
{
  "robot_id": "rosy_01",
  "online": true,
  "mode": "NAVIGATION",
  "navigation": "NAVIGATING",
  "map_id": "warehouse_a",
  "pose": { "x": 1.82, "y": 3.21, "yaw": 0.73 },
  "velocity": { "linear": 0.12, "angular": 0.0 },
  "battery": { "percent": 81 },
  "safety": { "estop": false },
  "power": {
    "mode": "STANDBY",
    "presence": "none",
    "info_visible": false,
    "sample_rate_hz": 2.0,
    "last_wake_reason": null,
    "idle_seconds": 412.5,
    "lidar_spinning": false,
    "lidar_ready": false,
    "devices": [
      { "name": "lidar", "level": "off", "ready": false, "managed": true, "required_for_motion": true }
    ],
    "motion_ready": false
  },
  "line_follow": {
    "mode": "CAMERA_LINE",
    "state": "TRACKING",
    "source": "CAMERA_LINE",
    "error": -0.214,
    "confidence": 0.82,
    "age_s": 0.04,
    "linear": 0.047,
    "angular": 0.171,
    "reason": "tracking"
  },
  "traffic_policy": {
    "mode": "ENFORCED",
    "state": "WAIT_SIGNAL",
    "reason": "signal_red",
    "enforced": true,
    "map_id": "map_260905_update_v2",
    "scene_revision": "road-scene-v1",
    "policy_revision": "traffic-policy-v1",
    "junction_rule": "signal_controlled",
    "evidence_revision": 42,
    "age_s": 0.04,
    "stop_line_visible": true,
    "stop_line_distance_m": 0.08,
    "crosswalk_visible": true,
    "signal_colour": "RED",
    "signal_confidence": 0.93,
    "signal_conflict": false,
    "signal_source_kind": "camera",
    "signal_head_age_s": null,
    "signal_head_frozen": false,
    "linear_scale": 0.0
  },
  "diagnostics_summary": { "rosy_core": "OK", "nav2": "OK" },
  "seq": 10241,
  "timestamp": "2026-08-29T12:00:00.123Z",
  "evidence": {
    "pose": { "received_at": "2026-08-29T12:00:00.023Z", "evidence": "fresh", "stale_after_s": 2.0 },
    "velocity": { "received_at": "2026-08-29T12:00:00.100Z", "evidence": "fresh", "stale_after_s": 0.5 },
    "battery": { "received_at": "2026-08-29T11:59:58.000Z", "evidence": "delayed", "stale_after_s": 5.0 },
    "navigation": { "received_at": "2026-08-29T12:00:00.000Z", "evidence": "fresh", "stale_after_s": 2.0 },
    "safety": { "received_at": "2026-08-29T12:00:00.110Z", "evidence": "fresh", "stale_after_s": 0.2 },
    "docking": { "received_at": null, "evidence": "disconnected", "stale_after_s": 2.0 }
  }
}
```

`GET /api/v1/robot/state` 도 같은 스냅샷이다.

`localization` 은 v1.69 additive 다(D-395). v1.72 부터 CORE 가 로봇 sensing 노드의 `localization/state` 토픽으로 채운다(D-395 P2-1). 그 토픽이 한 번도 오지 않은 로봇(D-395 이전)은 `null` 이다. 토픽이 3 s 끊기면 CORE 는 `state: UNKNOWN`, `reason: state_stale` 로 내린다(닫힌 실패).

```json
"localization": {
  "state": "LOCALIZED",
  "pose_frame": "map",
  "confidence": 0.93,
  "reason": null,
  "needs_human": false,
  "request_id": "rosy_01-7",
  "unmapped_objects": [{ "x": 0.62, "y": -0.08 }],
  "objects_stamp": 1834.5
}
```

- `state`: `UNKNOWN` \| `CANDIDATES` \| `LOCALIZED` \| `SUSPECT`. 로봇이 소유한다. 전원 투입은 항상 `UNKNOWN` 이고 자율 주행은 `LOCALIZED` 에서만 한다.
- `pose_frame`: 같은 스냅샷 `pose` 의 프레임, `map` \| `odom`. CORE 가 map→base TF 를 2 s 넘게 못 읽어 `pose` 에 odom 을 대신 쓰는 동안에는 로봇이 `map` 이라 해도 `odom` 이다(v1.72). CORE 는 `odom` 을 `map` 으로 올리지 않는다. Fleet 교통정리·bays 는 `odom` 이거나 `LOCALIZED` 가 아닌 자세를 쓰지 않는다(D-395 10항).
- `confidence`: 스캔/지도 적합도 0–1. `reason`: SUSPECT 사유(`pickup`, `fit_drop`, `inject_rejected`, `fleet_monitor`), 또는 `CANDIDATES` 에서 결정의 3 s 주입 검사가 도는 동안 `checking`(`core_common.protocol.localization.CHECKING`; Fleet 사다리는 멈추고 CORE 는 미션을 `busy` 로 거부한다, D-395 S1 재실행 R6). `needs_human`: 사다리 시간 초과. `request_id`: 진행 중인 후보 보고의 id.
- `unmapped_objects`(v1.75, 선택, ≤16, 기본 `[]`): `LOCALIZED` 로봇의 LiDAR 가 전체 스캔에서 지도로 설명하지 못한 물체 `{x, y}`(base_link, 앞 x·왼쪽 y, m; 자기 차체 안쪽은 뺀다). `objects_stamp`(v1.74, 선택): 그 스캔의 로봇 시각 s. 시계가 동기되지 않으므로 Fleet 은 스캔을 구별하는 데만 쓰고 신선도는 처음 본 때부터 잰다. `LOCALIZED` 밖에서는 빈 목록이다(후보 물체는 `CandidateReport` 에 실린다). CORE 는 그대로 넘기되 `pose_frame` 이 `odom` 이거나 상태가 끊겨 `state_stale` 이면 둘 다 비운다. Fleet 감시(D-395 9항, 개정 4 5항 후속)가 닻 로봇의 보고 자세로 이 물체를 놓아 다른 `LOCALIZED` 로봇의 거울 잠금을 잡는 데 쓴다.

`odom_pose` 는 v1.112 additive 다(D-494 2). `{x, y, yaw, stamp}` 는 로봇 odom 프레임의 자세와 CORE 가 그 odom 메시지를 받은 시각(ROS 헤더 시각이 아님)이다. 유한하지 않은 표본은 버리고 이전 값을 둔다. `stamp` 는 UTC epoch 초(실수)로, sighting 의 `captured_at` 과 같은 형식이다(로봇 단조 시각이 아니다). `pose` 가 map 프레임이어도 같이 싣는다. odom 이 한 번도 오지 않은 로봇과 D-494 이전 로봇은 `null` 이다. odom 이 끊겨도 마지막 값이 남으므로 소비자는 `stamp` 로 신선도를 판단한다. 같은 값이 Fleet 하트비트(1 Hz)의 상태 스냅샷에도 실린다.

```json
"odom_pose": { "x": 1.204, "y": -0.311, "yaw": 1.57, "stamp": 1791374400.123, "epoch": 0, "mono_s": 5123.875 }
```

v1.234(D-758 0단계)부터 `epoch`(odom 불연속 횟수)와 `mono_s`(같은 수신의 CORE 단조 시각)를 같이 싣는다. 뜻과 규칙은 위 「v1.234」 절이다. 이전 CORE는 둘을 싣지 않는다.

`safety_policy` 는 v1.71 additive 다(D-400). 공급자가 없거나 공급자가 실패하면 `null` 이다(CORE 가 실패를 로그에 남긴다). 같은 블록이 Fleet 하트비트의 상태 스냅샷에도 실린다. `safety` 는 e-stop 요약, `safety_policy` 는 D-400 정책 모드·그림자 기록이다.

```json
"safety_policy": {
  "mode": "shadow",
  "mode_effective": "shadow",
  "mode_error": "",
  "revision": "abcd1234abcd1234",
  "sources": { "lidar_yaw_offset": "unused while lidar_use_tf (TF = URDF nominal); line_follow uses: line_follow lidar_forward_deg (hand value; no accepted mount)" },
  "shadow": {
    "counts": { "allow": 312, "limit": 4, "stop": 1, "unavailable": 0 },
    "last_stop": { "t": 1843.512, "reason": "pickup", "source": "navigation" },
    "last_unavailable": null,
    "eval_ms": { "p50": 0.4, "p99": 1.1, "n": 317 },
    "dropped_events": 0,
    "suppressed_events": 2,
    "record_errors": 0
  }
}
```

- `mode`: `off` \| `shadow` \| `enforce`. `mode_effective`: 실제로 도는 모드(그림자 워커가 못 뜨면 `off`). `mode_error`: 그림자 워커가 시작하지 못한 이유(예외 종류: 메시지), 없으면 빈 문자열. 설정 오류는 CORE 시작을 막으므로 여기 나타나지 않는다.
- `revision`: 워커 파라미터 해시 16자. `sources`: 키별 값의 출처.
- `shadow`: `{counts, last_stop, last_unavailable, eval_ms{p50,p99,n}, dropped_events, suppressed_events, record_errors}`. `shadow` 가 없으면 `null`. `last_stop`·`last_unavailable` 은 `{t, reason, source}` 또는 `null`, 기록이 없으면 `eval_ms.p50`·`p99` 는 `null`.
- `hold`: v1.223 additive (D-400 4항). `enforce` 에서만 `{count, reason}`, 그 밖에는 `null`. `count` 는 CORE 시작 뒤 HOLD(명령 0, 래치 없음)로 답한 센서 끊김의 수, `reason` 은 가장 최근 HOLD 틱의 정책 사유(`policy_unavailable` \| `policy_failed` \| `policy_invalid`)이고 없었으면 빈 문자열이다. 끊김이 `stale_hold_s` 에 닿아 래치하면 `safety.estop` 의 `source` 가 `control:<사유>` 다.
- 시각 `t` 는 CORE monotonic 초이며 벽시계가 아니다.

`activity` 는 v1.68 additive 다(D-321 부록). 보정 세션 lease 가 살아 있는
동안만 객체이고, 아니면 `null` 이다.

`trip_lease` 와 `trip_lease_ended` 는 v1.157 선택 필드다(D-541 1). **없으면 키가 없다**
(`null` 이 아니다). `trip_lease` `{lease_id, trip_id, holder, operator_name, since,
expires_in_s, job_id}` 는 Fleet trip lease 가 살아 있는 동안만 있다(`job_id` v1.236, 작업의 lease 가 아니면 `null`). `trip_lease_ended
{lease_id, reason, by}` 는 lease 가 끝난 뒤 10 s 동안(다음 lease 가 열리면 없어진다)
있어 1 Hz heartbeat 와 `/ws/state` 가 모두 한 번은 본다. `reason` 은 `mode_left`(IDLE·
MANUAL·도킹으로 감, D-407 ABORT, 주인 아닌 토큰의 `navigation/cancel`·line-follow OFF)·
`estop`·`taken_over`·`expired`·`released` 다. 주인의 NAVIGATION ↔ line-follow 전환(trip 의
`lane` ↔ `free`)은 lease 를 끝내지 않는다: lease 주인의 `navigation/goal` 은 line-follow 가
켜져 있어도 받아 line-follow 를 끄고 목표로 간다(주인이 아니면 그대로 409
`LINE_FOLLOW_ACTIVE`).

```json
"activity": {
  "kind": "CALIBRATING",
  "session_id": "3f9c1a0b7d2e4c55",
  "calibration_kind": "drive",
  "label": "주행 보정",
  "owner": { "id": "a1b2c3d4e5f6", "role": "operator", "label": "pilot tablet" },
  "started_at": "2026-10-01T09:00:00+00:00",
  "remaining_s": 24.5
}
```

화면(Pilot·대시보드·LCD 얼굴)은 이 값이 있으면 "보정 중 — <label>" 을 보여야
한다. `owner.id` 가 자기 토큰(`/auth/whoami` 의 `id`)이 아니면 주행 조작을
사유와 함께 끄고, E-Stop 은 켜 둔다. `remaining_s` 는 마지막 heartbeat 로부터
남은 lease 시간이다.

보정 lease 규칙 (D-321 부록, v1.68):

- **소유는 토큰 단위다.** 같은 사람이라도 다른 토큰(다른 기기·재발급)은 owner 가
  아니다. 회수·만료·로그아웃된 토큰의 lease 는 즉시 풀리지 않고 `ttl_s` 가 지나야
  만료된다 — 더 기다릴 수 없으면 Administrator 가 `DELETE` 한다.
- **시작 조건:** 모드가 IDLE 또는 MANUAL 이고 navigation·mapping·도킹·line-follow·
  swarm follow 가 돌고 있지 않을 때만 연다. 아니면 409 `MODE_CONFLICT`.
- **비소유자에게 막히는 쓰기(409 `CALIBRATION_ACTIVE`):** teleop, `/mode`(IDLE 제외),
  line-follow 모드(OFF 제외)·hold, navigation goal·home, `/api/v1/do` 의 같은 동사,
  docking dock·undock, swarm follow, `PUT /safety/limits`(Admin 포함),
  `POST /localization/initialpose`, `/slam/start`·`stop`·`reset`, `POST /power/mode`,
  그리고 `POST /host/release/install`·`/release/rollback`·`/reboot`(Admin 이
  `override_calibration: true` 를 보내면 통과 — CORE 가 재시작되어 보정이 끝난다).
  `/ws/swarm/reference` 는 비소유자 프레임을 조용히 버린다.
- **열려 있는 것:** `POST /safety/stop`(Viewer 포함), `/mode` IDLE, line-follow OFF,
  navigation·swarm·docking cancel, `/do` stop, `/power/wake`, `/slam/save`.
- **배터리 복귀는 lease 를 보지 않는다.** SAF-005 `battery_critical_policy:
  RETURN_HOME` 은 CORE 내부 경로(`nav.home(source="battery_policy")`)로 가며 일부러
  막지 않는다 — 방전 보호가 보정보다 앞선다.
- Pilot 은 자기가 MANUAL 을 잡은 적이 있고 남의 보정으로 잠겨 있지 않을 때만 나가면서
  `/mode` IDLE 을 보낸다.

`line_follow` 는 v1.10 additive 다. `state` 는 `OFF | WAITING | TRACKING |
HOLD | LOST | RECOVERING`(v1.74; D-407 후진, D-468 로컬 차선 복귀 `lane_return_*`, D-476 예상 도로 bridge `lane_bridge` 이동 중에만) 이며 `LOST` 는 모드를 `OFF` 로 바꾼 뒤 다시 선택하기 전까지
해제되지 않는다. 선택되지 않은 소스, 신뢰도 미달, 원본 센서 시각 기준 stale,
형식 오류는 모두 선속도·각속도 0으로 fail-closed 된다. `linear` 는 이 모드의
별도 상한 0.10 m/s를 넘지 않는다(D-143).

`traffic_policy` 는 v1.11 additive 다. `mode` 는 `DISABLED |
MONITOR_ONLY | ENFORCED`, `state` 는 `DISABLED | FOLLOW | APPROACH |
STOP_REQUIRED | WAIT_SIGNAL | PROCEED | HOLD` 다. `ENFORCED`에서는 stale,
신호 충돌, map/scene revision 불일치, 거리 미확정이 모두 0 명령을 만든다.
정지선에서는 신호색과 무관하게 먼저 완전 정지와 dwell을 완료한 뒤, 신뢰도
기준을 통과한 `GREEN`만 `PROCEED`를 허용한다. `MONITOR_ONLY`는 같은 판정을
표시하지만 주행 후보를 변경하지 않는다. `junction_rule`은 v1.54 additive다.
2026-10-12(D-735): ENFORCED FOLLOW/APPROACH/PROCEED의 이동 후보는 선속도와
각속도에 같은 감속 비율을 적용한다. 선속도 0의 제자리 회전은 기존 각속도를 유지한다.
`signal_controlled`(기본)는 위 동작 그대로다. `stop_and_go`는 무신호 교차로
선언이다 — 완전 정지와 dwell을 마친 뒤 신호가 관측되지 않으면
`PROCEED / unsignalized_proceed`로 `proceed_speed_scale` 속도로 진입하고,
신호가 관측되면(약한 오탐 포함) `HOLD / signal_unexpected`로 정지한다. 이 값은
운영자의 씬 선언이지 카메라의 부재 판단이 아니다
(`docs/plans/2026-09-29-traffic-policy-unsignalized-junction-design.md`).
`signal_source_kind`·`signal_head_age_s`·`signal_head_frozen`은 v1.56 additive다
(D-337). 운영자가 파일 설정(`traffic_policy.signal_observer` = `{url, roi_map,
timeout_s}`, `~/.rosy/rosy.yaml` 오버레이 — stage 대상이 아니다)으로 관측 서비스의
읽기 전용 `GET /observed`(측정된 빛)를 묶으면 정지선 판정이 그 증거를 카메라와
함께 쓴다. `fused`는 관측 증거가 유효한 동안만 표기되고, 소스 불일치는
`signal_source_conflict` HOLD, 소등·부정은 `signal_dark` 진입 불허, 침묵(503·동결·
debounce 미확정·stale)은 카메라 단독으로 강등되며 그 전환마다
`nav.traffic_policy_signal_source_stale` 경보가 1회 발행된다. 미설정 사이트는 값이
`camera`·`null`·`false`로 고정되고 동작은 v1.54와 같다.

카메라 preview는 v1.12 additive다. Control은 인식 오버레이가 포함된 bounded JPEG를
최대 2 FPS로 만들고 CORE는 최신 한 장만 보관한다. 대시보드는 Viewer 토큰으로
`status`를 먼저 조회한 다음 sequence가 바뀐 경우에만 `frame`을 가져온다. 프레임이
`preview_stale_after_s`를 넘으면 CORE는 이미지를 제공하지 않고 관제 화면은 `STALE`로
전환한다. raw frame은 `/ws/state`, Fleet, Games 또는 명령 경로에 포함하지 않는다.

`GET /api/v1/vision/front/status` 응답 예:

```json
{
  "available": true,
  "stale": false,
  "source": "GAZEBO",
  "frame_id": "front_camera_link",
  "captured_at": 42.25,
  "age_ms": 80,
  "width": 640,
  "height": 360,
  "overlay": "semantic-road-v1",
  "sequence": 7,
  "quality": null
}
```

CORE-only 런타임(`runtime_mode: core`, D-161)에서 한 번도 값이 오지 않은 채널은 출처가 구성되지 않은 것이므로 `unavailable` 이다 — `disconnected` 는 출처가 있는데 값이 오지 않는 경우에만 쓴다. 첫 표본이 오면 보통 판정으로 돌아간다(v1.18).

`evidence` 는 v1.8 additive 다. 채널별 `{received_at, evidence, stale_after_s}` 이며, `evidence` 는 서버가 판정한 `fresh` | `delayed` | `disconnected` | `unavailable` 이다. 판정에 쓴 임계값(`stale_after_s`)도 같이 실는다. 클라이언트는 임계값을 다시 계산하지 않고 이 문자열을 그대로 표시·게이트한다. 알 수 없는 채널 키는 무시한다(API-002). `PROTOCOL_VERSION`(envelope 1.0)은 바꾸지 않는다.

Camera preview transfer rules (v1.12, D-152):

- v1.102 운전자 MJPEG 스트림(D-368): `GET /api/v1/vision/front/stream` 는 최신 프레임 저장소에서 **새 sequence가 들어올 때만** 파트를 내보낸다(multipart, boundary `frame`). 받을 수 있는 사람은 **현재 운전자 한 명** — 조종 소유권은 좌석 임대가 아니라(D-460) 가장 최근 수락된 teleop의 토큰이다. 운전자가 없거나 다른 토큰이면 409 `CAMERA_STREAM_NOT_DRIVER`, 스트림은 동시에 하나만 열린다(409 `CAMERA_STREAM_BUSY`). 다른 토큰의 teleop가 수락되면 열린 스트림은 끝나고 슬롯이 비며, 클라이언트 끊김도 슬롯을 돌려놓는다. 인증은 `Authorization` 헤더로만 하고 토큰을 URL에 두지 않는다(D-193) — 브라우저 `<img>` 는 헤더를 못 보내므로 클라이언트는 `fetch()` 스트림을 잘라 그린다. 발행 주기 상향(기본 12 fps)은 ROS-SIM/DEVICE 단계의 로봇 측 사항이며 이 경로 계약에 속하지 않는다.

- v1.91 `raw_available`와 `raw_sequence`는 같은 capture stamp·frame_id·크기의 원본이 있는지 표시한다. raw_sequence는 대응 주석 sequence와 같다. `GET /front/frame?sequence=S&overlay=false`는 원본, 생략/true는 주석 JPEG이며 Variant(raw/annotated)·Frame-Id·Captured-At·Sequence 응답 header로 구분한다. 최근 최대 4개 frame 쌍을 보관하고 source image age와 monotonic 수신 TTL을 2초로 제한한다. 한 viewer의 같은 pair는 각 variant를 한 번만 가져올 수 있으며 둘이 한 admission을 공유한다. 반복 variant/400ms 안의 다음 pair는 429, 교체되어 짝을 확인할 수 없으면 409, 없거나 낡은 raw는 404이다. 원본 요청을 주석으로 대체하지 않는다.
- `quality_age_ms`는 source image age + monotonic 수신 나이이며 얼굴 조명 보조 handover도 이 나이에 파일 전달 나이를 더해 만료한다. source clock이 없거나 잘못되거나 image age가 0..2초 밖이면 조도는 null이고 raw pair로 채택하지 않는다. 기존 주석 JPEG 표시 경로는 유지한다.
- 브라우저 video evidence는 optional `preview_mode`(raw/annotated)와 `pair_group_id`(소문자 32 hex)를 함께 제공한다. annotated 저장은 같은 group·started_at·stopped_at·frame_count의 raw가 먼저 저장돼야 한다. 두 파일은 별도로 보존하며 서버가 `annotation_origin=none` 또는 `model_unreviewed`를 붙인다. 모델 주석은 사람이 검토한 라벨이 아니다. legacy 영상의 출처가 없으면 새 provenance 필드는 null이다.

- v1.90 `quality`는 원본 픽셀의 조도 관측 `{valid:false, reason:"low_light"|"overexposed"}` 또는 `{valid:true, reason:"usable"}`이며 물체·차선 판정이나 이동 허가가 아니다. legacy·잘못된 metadata·2초를 넘긴 원본 촬영·수신은 null이다. 저조도·과다 노출에서도 JPEG는 보이며 CAMERA_LINE 관측은 visible=false/confidence=0으로 무효화되어 즉시 정지, 지속 시 기존 LOST 재선택을 요구한다. 저조도 조명 보조는 `low_light`에만 허용하며 `overexposed`에서는 해제한다. LiDAR·IR 안전 기준은 유지한다.

- Both `status` and `frame` responses are `Cache-Control: no-store`.
- A client MUST request
  `GET /api/v1/vision/front/frame?sequence={status.sequence}`. If the latest
  frame advanced between the two calls, CORE returns
  `409 CAMERA_FRAME_ADVANCED`; the client refreshes status instead of pairing
  old metadata with new JPEG bytes.
- Omitting `sequence` fails request validation with `400 VALIDATION_ERROR`.
- CORE returns `429 CAMERA_RATE_LIMITED` when the same authenticated token
  successfully pulls frames less than 400 ms apart. A sequence mismatch is
  checked first and does not consume this allowance.
- `captured_at` is the ROS/source capture clock. `age_ms` is the independent
  local receipt age used for freshness; the dashboard displays both.
- Successful JPEG responses include `X-Rosy-Camera-Sequence`,
  `X-Rosy-Camera-Captured-At`, and `X-Rosy-Camera-Source`.

Operator camera capture (v1.39): `/console`의 카메라 화면은 인증된 preview JPEG만 최대 2 FPS로 기록한다. 스크린샷은 해당 JPEG 그대로, 영상은 브라우저 canvas의 녹화 형식(WebM 또는 MP4)으로 만든다. 조작 기록은 정해진 운전·도킹·정지 API의 작업 이름, 요청 접수/실패, 녹화 시작 후 경과 시간만 포함하며 토큰·명령 본문·IP를 포함하지 않는다. 화면에서 `이 PC`, `로봇 SD`, `PC와 로봇 SD`를 고를 수 있다. PC 저장은 브라우저 다운로드이며 CORE 저장 API를 호출하지 않는다.

로봇 SD 저장의 `POST` 본문은 `application/octet-stream`: little-endian unsigned 32-bit JSON 길이(최대 32,768바이트), UTF-8 JSON, 미디어 바이트 순서다. JSON은 `schema_version:1`, `kind:screenshot|video`, `mime_type`, 저장 또는 시작·종료 UTC 시각을 포함한다. screenshot은 `saved_at`, `sequence`, `source`, video는 `started_at`, `stopped_at`, `frame_count`와 최대 200개의 `{action,result,elapsed_ms}` 항목을 요구한다. JPEG는 1 MiB, 영상은 64 MiB, 전체 저장 미디어는 512 MiB 상한이며 CORE의 HOME 아래 `captures/`에 원자 기록한다(네이티브 `/var/lib/rosy/core/captures`, 컨테이너 `/var/lib/rosy/captures`). 한도를 넘으면 413/507로 실패하고 부분 파일은 삭제한다. 저장 응답은 `{id,kind,file_name,mime_type,bytes,sha256,created_at}`이다. 이 기능은 Control의 고속 원본 영상 캡처나 장치 카메라 활성화를 의미하지 않는다.

## 6.1.1 Vision `DetectionEvidence` (v1.9 additive, D-137)

검출기는 박스를 보고, 움직일지는 정하지 않는다. 한 프레임의 증거:

```json
{ "model_revision": "yolo11n-r1", "observed_at": 1000.0, "seq": 41,
  "input_width": 640, "input_height": 640, "input_fps": 10.0,
  "inference_ms": 12.3,
  "detections": [
    { "label": "person", "x": 0.4, "y": 0.3, "w": 0.2, "h": 0.4,
      "confidence": 0.8, "track_id": 3 }
  ] }
```

- 박스 좌표는 입력 프레임 정규화(0..1)다. `model_revision`은 가중치+입력 규격을
  묶는다(D-47 패턴) — 모르는 revision은 fail-closed.
- 신선도 상한 300 ms(D-136). 빈 `detections` + 전진 `seq`는 "없음"이고,
  `seq` 점프는 "놓침"이다 — 둘을 혼동하지 않는다.
- `inference_ms` 는 생산 측이 report하는 추론 지연(ms)다 — 선택 필드이고
  없어도 패킷은 유효하다 (v1.11 additive).
- 자문 전용이다. 이 증거 하나로 정지·해금을 만들지 않는다(SAF-006, D-137).
- D-423 `object_detector_node` 는 같은 필드를 ROS 토픽 `vision/detections` 에 내고, 검출마다
  거리를 담은 추가 목록 `ranges`(`detections` 와 같은 순서, 항목 `{m, s}` 또는 `null`; `m` 카메라
  앞 미터, `s` `L` LiDAR·`G` 바닥 평면)를 붙인다. CORE 는 이 토픽을 구독하지 않는다(CORE 의 자문
  입력은 `detection_evidence`). `DetectionEvidence` 파서는 `ranges` 를 무시한다.

클라이언트→서버 선택 메시지(WS Teleop, Operator 권한):

```json
{ "type": "teleop", "linear": 0.1, "angular": -0.2 }
```

WS Teleop에도 Watchdog·감사 로그가 동일 적용된다(SAF-002).

## 6.2 `/ws/events` — 이벤트 스트림

구독 필터: `?types=nav.*,safety.estop` (콤마 구분, `*` 와일드카드).

서버 메시지는 EVT-001 이벤트 모델 그대로 전송한다. 연결 끊김 후 재구독 시 `since_seq`로 갭을 보정한다(EVT-003).

---

# 7. Fleet ↔ Robot 프로토콜 (WS + REST)

로봇이 Fleet WS endpoint(`wss://fleet:8081/ws/robots`)에 **outbound 접속**한다(ADR-D-5).

## 7.1 Envelope (PRT-001)

모든 WS 메시지의 공통 포장:

```json
{
  "protocol_version": "1.0",
  "msg_id": "uuid",
  "correlation_id": "uuid|null",
  "type": "hello|heartbeat|event|command|ack|error",
  "ts": "2026-08-29T12:00:00.123Z",
  "payload": { }
}
```

## 7.2 핸드셰이크 (PRT-002)

접속 후 로봇이 첫 메시지로 전송:

```json
{ "type": "hello",
  "payload": { "robot_id": "rosy_01", "pairing_token": "pt_xxx",
               "api_versions": ["v1"], "protocol_version": "1.0" } }
```

추가 선택 필드(additive, 없어도 유효): `device_uid`, `device_name`, `model`, `hardware_serial`.

Fleet 응답: `welcome`(성공, 장기 토큰 발급) / `error(PAIRING_INVALID)`.

## 7.3 Heartbeat (PRT-003)

로봇 → Fleet, 1 Hz:

```json
{ "type": "heartbeat",
  "payload": { "state_snapshot": { "...": "/ws/state 스키마 동일" } } }
```

### 7.3.1 교차로 신호 질의 (D-620, v1.202)

명시적 `line_follow.junction_signal_enabled:true`인 CAMERA_LINE 시험은 지시 없는
교차로에서 정지한 에피소드의 UUID hex(32자)를 선택 필드
`payload.junction_signal_request`로 보낸다. 기본값은 `null`이고 기존 heartbeat는 그대로 유효하다.
HELLO로 인증된 해당 로봇 신원만 조회한다. Fleet 답은 heartbeat 선택 필드다:

```json
{"type":"heartbeat","payload":{"junction_signal":{"request_id":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","lamp":"red","may_enter":false,"reason":"approach_signal"}}}
```

`lamp`는 `green|red|unknown`, `may_enter`는 엄격한 boolean, `reason`은 최대 96자다.
Fleet는 기존 trip 신호/통행권을 사용하거나, 2초 이내 지도 자세의 진행 방향 차로 안에서
다음 장소까지 0.6m 이내인 접근로의 기존 신호표를 사용한다. 지도/신호 없음·조회 오류는
`unknown/false` 응답이다. 답변은 통행권을 만들거나 늘리지 않는다.

CORE는 `green && may_enter:true`인 수신 후 2초 이내 답을 우측 진입 선택에 사용한다.
응답이 한 번도 없는 정지 에피소드는 3초 뒤 기존 D-495 `right/turn_deg:-90`을 한 번 선택한다.
적색·미확인·진입 불허·만료 답·잘못된 상관 답·Fleet ERROR·pairing 거부는 대기한다.
실제 회전 전 적색은 fallback도 취소한다. 이전 ID·OFF·회전 시작 뒤 답은 다음 회전을 만들지 않는다.
모든 CORE 회전/장애물/횡단보도/통행권/정지 검사는 유지한다. 무응답 fallback은 현장 감독 시험에 한정한다.
v1.239: Fleet 통행권 아래(`authority_required`, 이 세션의 통행권, 본 trip lease)에서는 무응답이어도 우측을 고르지 않고 대기한다(D-620 노트 2026-10-15).
v1.239: 교차로 기동·호 시계는 통행권 `HOLDING` 대기를 전부 더하고, `NONE`·`EXPIRED`와 횡단보도 몫은 15 s까지만 더한다(D-760 개정 4).

상태 API의 `line_follow.junction`에 선택 필드 `signal_request_id`와 `signal_state`를 추가한다.
상태는 `waiting|red|unknown|green|fallback|entered` 또는 `null`이다.
CORE journal에는 요청 ID별 질의, 답 변화, 우측 선택을 기록한다.
`entered`는 회전 단계 시작이며 실물 이동 증거는 별도다.

## 7.4 이벤트 전달

로봇은 내부 이벤트(EVT-001)를 `type: "event"`로 Fleet에 실시간 forward한다. 재접속 시 로봇은 미전송 이벤트를 `since_seq` 기준으로 재전송한다(PRT-005).

## 7.5 명령 및 추적 (PRT-004)

명령은 **REST**(Fleet → 로봇 §5 API)로 전달하고, WS는 추적 보조로 사용한다.

```text
Fleet → Robot (REST):  명령 헤더에 X-Correlation-Id 부여
Robot → Fleet (WS):    { "type": "ack", "correlation_id": "...",
                         "payload": { "status": "ACCEPTED|STARTED|COMPLETED|FAILED",
                                      "error": "..." } }
```

Fleet 추적 타임아웃(기본 10초) 내 ack 없으면 Fleet 기록에 `COMMAND_TIMEOUT`을 남긴다.

> **상태 (v1.15, ADR D-170)**: 위 추적 흐름의 **로봇 측 구현**(ack 송신,
> `correlation_id` 설정·소비, 로봇 ACK의 실행 상태와 Fleet 추적 레코드)는
> 중앙 Fleet 서버 착수와 함께 제공된다(D-297). `TIMEOUT`은 Fleet 기록
> 전용이며 로봇 `AckPayload`에 추가하지 않는다(D-215).
> 이 보류는 PRT `Envelope.correlation_id`와 `AckPayload`의 설정·소비에
> 적용된다. D-316의 Site Fleet Pinky navigation 경로는 별도 REST
> `GoalRequest.correlation_id`와 CORE navigation event data를 사용하며,
> PRT envelope/schema/version은 바꾸지 않는다.

## 7.6 재접속 (로봇 측 의무)

- Exponential backoff: 1s → 2s → 4s → ... 최대 30s
- `fleet.discovery`를 설정한 로봇은 재접속마다 예상 `.local` 호스트의 `_rosy-fleet._tcp` 광고를 조회하고 별도 설치된 사이트 CA로 TLS health를 확인한다. mDNS 광고만으로 토큰을 발급하거나 연결 대상을 바꾸지 않는다. 승인된 `fleet.pairing_token`이 없으면 Agent를 시작하지 않는다.
- 재접속 즉시 `hello` → 마지막 전송 `seq` 이후 이벤트 재전송
- 접속 단절 시 SAF-003 정책 적용 (D-419, v1.86): Agent 가 돌고 있고, 링크가 끊긴 순간 Fleet 주행 목표(`correlation_id` 가 있는 `POST /navigation/goal`)가 진행 중이었으며, 그 목표가 그대로인 채로 `safety.fleet_loss_timeout_s` 동안 계속 끊겨 있으면 한 번 적용한다. 로컬 목표·teleop·swarm follow(SWM-004 가 따로 지킴)·끊긴 뒤 들어온 목표는 대상이 아니다. `STOP` 은 그 목표 취소(e-stop 아님), `HOLD` 는 같은 정지에 재개용 목표 기록(자동 재개 없음), `RETURN_HOME` 은 취소 뒤 `__home__` 귀환(home 이 없거나 `LOCALIZED` 가 아니면 선 채로 `applied: STOP`), `CONTINUE` 는 이벤트만. 재접속은 아무것도 재개하지 않는다. 링크가 살아 있다는 것은 허브 `welcome` 을 받은 뒤이고 마지막 허브 수신이 링크 신선도(1 s 하트비트 주기 + `fleet.heartbeat_reply_timeout_s` + 0.5 s) 이내라는 뜻이다 — 판정 시간과 따로다(설정 여부는 기동 설정으로 정하고, 뒤에 Agent 가 hello 거부·중지로 꺼져도 끊긴 링크로 본다). 하트비트 답이 `fleet.heartbeat_reply_timeout_s`(기본 2 s) 안에 오지 않으면 로봇이 소켓을 끊는다(반쯤 열린 TCP). 하트비트에 대한 `error` 답(예: `TASK_PROJECTION_UNAVAILABLE`)도 답이라 링크를 유지하고, `PAIRING_INVALID`·`SESSION_NOT_PAIRED`·`DUPLICATE_IDENTITY`·`IDENTITY_DRIFT`·`PROTOCOL_UNSUPPORTED` 가 하트비트에 대한 답이면 세션을 즉시 끝낸다(`PAIRING_INVALID` 는 언제나). `event` 에 대한 `error` 는 이벤트 거부로 기록하고 세션을 유지한다. SAF-003 은 허브 건강이 아니라 링크 생존을 판정한다. hello 답 시한은 D-407 의 5 s(링크는 `welcome` 전까지 끊긴 것이라 SAF-003 판정에 영향 없음). `event` 에 대한 `error` 는 D-407 규칙대로 `EVENT_NOT_AUDITABLE` 이면 버리고, 다른 코드면 최대 3 번까지 다시 보낸다. 답을 기다리는 `event` 는 한 번에 8 개까지만 보낸다 — 재접속 뒤 밀린 이벤트가 하트비트 답을 시한 밖으로 밀어내지 않게. 단절은 마지막 허브 수신부터 잰다 — 답 하나를 놓친 기본 설정에서 정책은 마지막 수신 뒤 5 s. 재접속 backoff 는 세션이 하트비트 답 3 개를 받은 뒤에만 1 s 로 돌아간다. 취소가 그 목표를 찾지 못하면 `applied: NONE`·`reason: goal_changed`

## 7.7 프로토콜 버저닝 (PRT-006)

`MAJOR.MINOR`. MINOR는 추가 전용. Fleet이 로봇보다 낮은 버전만 지원하면 Fleet 지원 최고 MINOR로 통신한다.

## 7.8 Leader Pose Stream (Swarm, SWM-003)

Leader 로봇 → Fleet ≥10 Hz, Fleet → Follower 릴레이 ≥5 Hz. envelope `type: "pose"`(v1.1 추가).

```json
{ "protocol_version": "1.0", "msg_id": "...", "type": "pose",
  "ts": "2026-08-29T12:00:00.123Z",
  "payload": { "robot_id": "rosy_01", "pose": { "x": 1.1, "y": 0.5, "yaw": 0.2 }, "seq": 8123,
               "map_id": "site_a", "frame": "map" } }
```

Follower의 rosy_core은 스트림 수신 여부를 `stream_timeout_ms`(기본 1000 ms)로 감시하고 단절 시 SWM-004 정책(HOLD)을 적용한다.

`frame` 은 v1.170 additive 다(D-559): `map` 또는 `odom`. 리더의 map TF 가 2 s 넘게 끊기면 보고 pose 는
odom 으로 떨어지는데, 그 좌표는 맵의 장소가 아니다. trail 팔로워는 `odom` 표본을 자취에 넣지 않고 멈춘다
(`hold_reason: reference_frame_not_map`). 아직 pose 가 없는 CORE 는 `null` 을 보낸다. trail 은 `map` 표본만 쓴다 — 필드가 없는 옛 리더도 trail 에서는 멈춘다(offset 은 확인하지 않는다).

`anchor`·`for_robot_id`·`anchor_age_s`·`anchor_hold` 는 v1.176 additive 다(D-581). TRAIL 대형에서 리더가 `frame: odom` 을 보내면
(로봇에 map pose 가 없는 모터 모드 현장) Fleet 은 그 프레임을 팔로워마다 **그 팔로워의 odom 좌표로** 다시 써서 보낸다:
`frame: odom`, `anchor: "fleet"`, `for_robot_id: <받는 팔로워>`, `map_id`(천장 카메라 사이트 맵), `anchor_age_s`(리더·팔로워
천장 기준 중 오래된 쪽, s — 진단용이며 CORE 는 읽지 않는다). 변환은 D-494 3 Fleet map pose 의 천장 기준(map ← odom)이다. 천장 기준이
없거나 5 s 넘게 낡았거나, DEGRADED 가 2 s 를 넘었거나(또는 T 를 만든 기준이 바뀌었거나), 추적기 odom 이 재시작했거나, 기준이 로봇
위치에서 0.20 m·15° 넘게 튀었거나, 리더 스트림 odom 이 추적기 odom 과 맞지 않으면(`leader_odom_mismatch`) 그 팔로워에게는 쓸 수 있는
표본 대신 **정지 표본** `anchor_hold: "<robot>:<이유>"`(좌표는 리더 odom 그대로, 자취에 들어가지 않는다)을 리더 프레임마다 보낸다 —
침묵은 리더 상실(D-20 승계)로 읽히기 때문이다. 리더 프레임이 끊기면 Fleet 도 아무것도 보내지 않는다. `map` 프레임은 지금처럼 바이트 그대로 중계한다. trail 팔로워는 `anchor: fleet` 이고
`for_robot_id` 가 자기 id 이고 `frame: odom` 이고 follow `source` 가 `fleet` 인 표본만 자취에 넣고, 그때 자기 위치는 상태
스냅샷의 `odom_pose` 다(`own_pose_not_map` 판정 없음, CORE 가 받은 지 단조 시계로 0.5 s 넘으면 `own_pose_stale`). 조건이 맞지 않는 `anchor` 표본은
`reference_anchor_invalid` 로 선다. `anchor_hold` 표본은 `anchor_withheld` 로 세우되 스트림은 살아 있다(승계 없음). 정지 표본마다
D-559 건너뜀 한도의 시계가 다시 시작되므로, 긴 정지 사이 리더가 0.3 m 넘게 갔으면 다음 표본은 `trail_lost` 다. `anchor`·`for_robot_id`
는 길 찾기 검사이지 인증이 아니다 — operator 토큰이면 이 소켓에 넣을 수 있다(map 프레임 trail 과 같다). 한 자취는 처음 쌓인 종류(map 또는 fleet)만 받는다 — 다른 종류 표본은
`reference_frame_changed` 로 서고 follow 를 다시 걸 때까지 유지된다. `anchor` 표본의 `map_id` 는 로봇 자신의 `map_id` 와
비교하지 않는다(아래 `map_mismatch` 는 `anchor` 없는 표본에만 적용).

`map_id` 는 v1.7 additive 다. 좌표만으로는 받는 쪽이 그것이 자기 맵의 좌표인지 알 수 없고,
다른 맵의 리더를 따라가면 그럴듯해 보이는 엉뚱한 지점으로 간다 — 웨이포인트가 MAP-002 로
막는 것과 같은 사고다. 팔로워는 **양쪽 다 값이 있고 서로 다를 때만** 거부하고, 목표를 거둔 뒤
`swarm.hold`(`reason: map_mismatch`)를 한 번 낸다. 대형은 끝나지 않으므로 리더가 우리 맵으로
돌아오면 새 `follow` 없이 이어진다. 필드가 없는 프레임은 그대로 따라간다 — 이 필드를 모르는
릴레이가 계속 동작해야 하기 때문이다.

로봇은 이 envelope 을 쓰는 소켓 두 개를 직접 제공한다(D-31). Fleet 이 가운데 서지 않아도 군집이 성립하고,
Fleet 이 들어오면 같은 envelope 을 중계하므로 어느 쪽 끝도 바뀌지 않는다.

| Path | Role | 방향 | 요구사항 |
|---|---|---|---|
| `WS /ws/swarm/pose` | Viewer + capability `swarm.lead` | 로봇 → 밖 | SWM-003 리더 pose 스트림. ≥10 Hz 는 하한이며 설정으로 낮출 수 없다 |
| `WS /ws/swarm/reference` | Operator | 밖 → 로봇 | 팔로워의 참조 pose 입구 (SWM-007). 형식이 어긋난 프레임은 버리고 소켓은 유지한다 |

인증은 AUTH-101 첫 메시지 방식이다(Fleet 도 D-370 S7 부터 `?token=` 을 쓰지 않는다).

close code: `4401` 은 토큰이 없거나 틀린 것(`/ws/state` 와 동일), `4403` 은 인증은 됐지만 허용되지 않는 것 — 역할이 모자라거나 capability 가 그 기능을 선언하지 않은 경우(CAP-003)다.

## 7.9 Fleet 보조 위치 확정 모델 (D-395, v1.69 스키마만)

원천은 `core_common.protocol.localization` 이다. v1.69 는 모델만 고정했고, v1.72(D-395 P2-4)에서 전송이 열렸다. Fleet 은 `GET /api/v1/localization/candidates` 로 `CandidateReport` 를 읽고 `POST /api/v1/localization/decision` 으로 `LocalizationDecision` 을, `POST /api/v1/localization/suspect` 로 의심을 보낸다(§5.3, capability `LOCALIZE_ASSIST`, §2). CORE 는 결정을 ROS `localization/decision` 에 `{decision, received_s}`(`received_s` 는 CORE 가 받은 ROS 시각)로 싣고, 로봇의 `localization/result` 는 이벤트 `localization.result` 로 나온다(§8). 토픽 계약은 `docs/plans/2026-10-01-d395-phase2-interfaces.md` §1 이다. Fleet 이 결정을 보낸 뒤 확인할 곳은 다음 스냅샷의 `localization` 과 그 이벤트다.

| 모델 | 방향 | 필드 |
|---|---|---|
| `CandidateReport` | 로봇 → Fleet | `robot_id`, `request_id`(1–64자 `[A-Za-z0-9_.:-]`), `candidates[1..8]` `{x, y, yaw, scan_fit 0–1, paint_score 0–1\|null}`(map 프레임 base_link), `unmapped_objects[≤16]` `{x, y}`(base_link, 앞 x·왼쪽 y), `square_sightings[≤4]` `{bearing_rad, range_m>0\|null, confidence 0–1}`, `pickup`, `stamp`(로봇 시각 s) |
| `LocalizationDecision` | Fleet → 로봇 | `request_id`, `candidate_index`(0–7) **또는** `pose {x, y, yaw}` 중 정확히 하나, `source` `candidate`\|`overhead`\|`homing_ref`\|`human`(`candidate` 는 인덱스와만, 나머지는 `pose` 와만), `cues`(≤6, `square`\|`paint`\|`peers`\|`slot`\|`last_good`\|`overhead`), `evidence`(≤16 키), `ttl_s`(받은 때부터 유효한 초, 0 초과 30 이하, 기본 5) |

로봇은 낡은 `request_id` 와, 받은 뒤 `ttl_s` 가 지난 결정을 무시한다(Fleet·로봇 시계 동기 불필요, D-395 개정 3). 사람이 아닌 결정은 `cues` 에 비대칭 단서(`square`·`paint`·`peers`·`slot`)가 하나 이상 있어야 받는다 — `last_good`·`overhead` 만으로는 거부한다. 받아들인 결정도 주입 뒤 3 s 스캔/지도 일치를 통과해야 `LOCALIZED` 가 되고, 실패하면 `SUSPECT`(`inject_rejected`)다. 대칭 맵에서는 거울상도 같은 적합도라 이 검증이 거울 주입을 거르지 못한다 — 거울은 Fleet 중재와 감시가 막는다. `square_sightings` 는 설계 4.2절 표 이후 개정 1의 `square_seen` 단서를 위해 더한 선택 필드다. `range_m` 이 null 인 목격(방위만)은 선로에 그대로 실리지만 Fleet 은 근거로 세지 않는다(D-395 개정 11).

---

# 8. 이벤트 카탈로그

> 소비자(Core 감사로그·Fleet·AI)가 의존하는 안정적 계약. 추가는 허용, 제거·의미 변경은 폐기 정책(API-003) 적용.

| type | severity | 발신 | payload 예시 |
|---|---|---|---|
| `system.boot` | info | 로봇 | `{version}` |
| `system.shutdown` | warning | 로봇 | `{}` |
| `config.changed` | warning | 로봇 | `{key, id, role, deleted}` — `key`: `robot.identity` \| `auth.tokens` \| `safety.limits` \| `dds.rmw`. `id`·`role` 은 토큰 추가, `id`·`deleted` 는 토큰 삭제·로그아웃, `id` 만은 이름표 변경일 때 실린다. 토큰 원문도, 원문에서 유도된 값도 싣지 않는다 |
| `auth.paired` | warning | 로봇 | `{id, role, source, expires_at}` — 로그인 코드로 토큰이 발급됐다(D-193). 코드도 토큰도 싣지 않는다 |
| `auth.code_burned` | warning | 로봇 | `{code_id, attempts}` — 틀린 시도가 쌓여 로그인 코드를 폐기했다 |
| `auth.enrollment_code_issued` | warning | 로봇 | `{code_id, role, by}` — 관리자(`by` = 토큰 id)가 등록 코드를 받았다. 코드는 싣지 않는다 |
| `auth.credentials_refused` | warning | 로봇 | `{count}` — 장치 모드가 기동 때 개발 토큰·평문 항목을 거부했다 |
| `auth.development_mode` | warning | 로봇 | `{marker}` — 장치 모드인데 개발 모드 표식이 있어 공용 개발 토큰을 받는다(D-548) |
| `fleet.link_provisioned` | warning | 로봇 | `{by, expected_hostname}` — D-555 (v1.163). `by` = 호출 토큰 id. 토큰은 싣지 않는다 |
| `fleet.link_cleared` | warning | 로봇 | `{by, removed}` — D-555 (v1.163) |
| `mode.changed` | info | 로봇 | `{from, to, by, run_id?, boot_id?}` |
| `trip_lease.opened` | info | 로봇 | `{lease_id, trip_id, holder, operator_name, ttl_s}` — D-541 (v1.157) |
| `trip_lease.renewed` | info | 로봇 | `{lease_id, trip_id, ttl_s}` — renew 는 0.5 s 마다 오므로 lease 하나에 30 s 에 한 번만 낸다 (v1.157) |
| `trip_lease.ended` | info, warning | 로봇 | `{lease_id, trip_id, holder, operator_name, reason, by, note}` — `reason` `released` 는 info, 그 밖(`mode_left`·`estop`·`taken_over`·`expired`)은 warning. `note` 는 넘겨받기 `reason`(없으면 빈 문자열) (v1.157) |
| `trip_lease.shared_token` | warning | 로봇 | `{lease_id, trip_id, holder, use, origin}` — lease 주인 토큰이 Fleet 밖에서 쓰인 흔적: `use: teleop`(trip 은 teleop 하지 않는다, `origin` 빈 문자열) 또는 `use: ws_state`(lease 를 연 주소와 다른 `origin` 의 `/ws/state`). lease·쓰임·출발지마다 한 번 (v1.157) |
| `calibration.session_started` | info | 로봇 | `{session_id, kind, label, owner, ttl_s}` — `owner` 는 토큰 id (D-321 부록, v1.68) |
| `calibration.session_ended` | info | 로봇 | `{session_id, kind, owner, by, duration_s}` — `by` 는 끝낸 토큰 id(Admin 강제 해제면 owner 와 다름) (v1.68) |
| `calibration.session_expired` | warning | 로봇 | `{session_id, kind, owner, ttl_s}` — `ttl_s` 안에 heartbeat 가 없어 lease 가 풀림. 보정 도구가 죽었거나 링크가 끊겼다는 신호 (v1.68) |
| `nav.started` | info | 로봇 | `{goal, by, correlation_id}` — `goal` 은 `{x, y, yaw}`; Fleet가 dispatch 시도 ID를 보낸 경우 그 값, 아니면 `null` |
| `nav.completed` | info | 로봇 | `{correlation_id}` — 동일 dispatch 시도 ID 또는 `null`; native goal 종결이면 추가 `run_id`, `boot_id`가 붙는다 |
| `nav.failed` | error | 로봇 | `{error_code, correlation_id}` — 동일 dispatch 시도 ID 또는 `null`; native goal 종결이면 추가 `run_id`, `boot_id`가 붙는다 |
| `nav.canceled` | info | 로봇 | `{source, correlation_id, run_id, boot_id}` — 로컬 취소 요청을 냈다는 뜻이며 액션 완료나 물리 정지를 증명하지 않는다. native goal이면 정확한 run/boot ID가 붙는다 |
| `nav.stuck` | error | 로봇 | `{timeout_s}` — NAV-006 무진척 판정 시간(초) |
| `nav.lane_lost` | warning | 로봇 | `{mode, reason, lost_after_s}` (NAV-007 차선 상실 — 유예 `lost_after_s` 초과 시 정지, 자동 재탐색 없음. CAMERA_LINE은 D-407 개정 2026-10-10에 따라 차선이 다시 보이면 같은 모드로 이어 감, `nav.lane_reacquired`) |
| `nav.lane_reacquired` | info | 로봇 | `{mode, frames, since_s}` — D-407 개정 2026-10-10: CAMERA_LINE `LOST`(`camera_reselection_required`)가 `line_follow.lost_resume_frames`(3)개 연속 신선·확신 프레임이 `lost_resume_s`(1.0 s) 넘게 이어지고 앞 물체 정지가 없으며 IR 감시가 비어 있을 때 풀려 같은 모드로 이어 감(재선택 없음). `lost_auto_resume: false`면 옛 잠금 (v1.181) |
| `nav.lane_cue` | info | 로봇 | `{action, state, fleet_epoch, seq, principal_ref, latch, angle_deg}` — D-511 개정 1·2 / D-430 검토: Fleet 차로 신호(`POST /line-follow/lane-cue`)의 상태 변화(`state`), 래치 HOLD(`latched`: `fleet_off_map`·`fleet_cue_lost`·`fleet_turn_unconfirmed`), 풀림(`unlatched`), 제자리 회전 시작(`pivot`, `angle_deg`). `principal_ref`는 보낸 토큰 |
| `nav.line_mode_changed` | info | 로봇 | `{from, to}` — D-143 line-follow 모드 선택 |
| `nav.line_driver_released` | info | 로봇 | `{mode}` — D-344 §8 운전자 확인(`hold_s`)이 끊겨 CORE 가 line-follow 를 스스로 내림 (v1.63) |
| `nav.line_obstacle_hold` | warning | 로봇 | `{mode, clearance_m, held_s}` — D-344 §11 앞 물체 정지(`obstacle_ahead`)가 `line_follow.obstacle_escalate_s` 넘게 이어짐, 정지 한 번에 한 번 (feat/device-prep, v1.64). 몸 기준 정지(D-422)면 `body_gap_m`·`stop_gap_m`·`clearance_source` 도 온다 (v1.84) |
| `nav.lane_arc_end_unarmed` | warning | 로봇 | `{end_place_id, arc_seq, travelled_m}` — D-520 2 호(`line_follow.arc`)가 odom 길이로 끝났는데 `end_place_id` 의 `armed` 지시가 없거나(만료 포함) 다른 장소의 지시였음(그 지시는 `aborted`·`arc_mismatch`). CORE 는 오늘의 차선 추종으로 돌아간다 (v1.145) |
| `nav.line_stuck_opened` | warning | 로봇 | `{stuck_id, cause, front_clearance_m, rear_clearance_m, rear_state, turn_clearance_m, rear_blind_m, last_lane, preview_seq, restuck_of, attempts, inquiry}` — D-407 §1 막힘 열림: `cause` 는 `obstacle_ahead`(앞물체 정지가 `obstacle_escalate_s` 이상) 또는 `lane_lost`. 여유는 로봇별 self-mask 적용, 앞은 LiDAR 기준 경로 띠, 뒤는 URDF 몸 뒤끝 기준, 회전은 회전 반경 밖; `rear_blind_m` 은 LiDAR `range_min` 때문에 안 보이는 뒤 거리. 같은 막힘에 한 번 (v1.74) D-573 4 (v1.179): `cause` `crosswalk_blocked` 는 횡단보도 게이트가 `crosswalk_report_s`(기본 10 s) 동안 "비었다"를 증명하지 못했거나 무장한 횡단보도 앞에서 앞물체 정지가 길어진 때다. 이때만 `detail`(`person_present`·`look_unknown`·`sensor_stale`·`zone_lost`)이 붙고, 로컬 후진 없이 관제 답만 기다린다(`nav.line_stuck_asked` `reason: crosswalk_gate`, `decisions` `[WAIT, MANUAL, ABORT]`; status `stuck.detail`·`stuck.decisions` 도 같다). 게이트가 스스로 비었음을 확인하면 `cleared` 로 닫힌다. 2026-10-10 (v1.187): `cause` `no_motion` 은 활성 차선 모드에서 line-follow 결정이 `line_follow.stuck_report_s`(기본 5 s, 0 = 끔) 동안 0 이고 다른 원인이 없을 때다(사유 무관: `lane_departure`, `angular_limit_zero`, `obstacle_sensor_stale`, `nominal_ground_requires_driver` 등). `detail` 은 그 HOLD 사유다. 로컬 후진 대체 없이 곧바로 관제 답만 기다린다(`nav.line_stuck_asked` `reason: no_motion`, `ask_remaining_s` null). 다섯 답은 다른 원인과 같고 CORE 가 다시 검사한다. 명령이 다시 0 이 아니면 `cleared` 로 닫힌다. D-520 arc·D-468 로컬 복귀가 틱을 가진 동안과 저조도·과노출 HOLD 는 세지 않는다. D-407 개정·D-607 2026-10-10 (v1.201, `line_follow.progress_watch_enabled` 기본 `false` — 꺼져 있으면 아래 두 원인은 열리지 않고 동작은 그대로; D-607 P1 배포 뒤 켬): `cause` `no_progress` 는 명령은 움직이는데 바퀴 odom 이 제자리일 때다 — `stuck_report_s` 창 동안 odom 순이동 < URDF 몸 길이의 절반(`(body_front_x_m − body_rear_x_m)/2`, Pinky 0.059 m)이고 순 |yaw| < `line_follow.no_progress_yaw_deg`(기본 30)인데 창 안에 명령이 있었다(HOLD↔주행 번갈아도 창을 다시 시작하지 않는다). `line_follow.no_progress_creep_enabled`(기본 `false`)를 켜면 `recovery_restuck_s`(20 s) 동안 `recovery_restuck_m`(0.30 m) 미만으로 기어가며 틱의 30 % 이상 명령이 있었던 때도 연다. `dithering` 은 같은 제자리 조건에 창 안의 v 또는 ω(|ω| > 0.05 rad/s) 부호가 두 번 이상 바뀐 때다. `detail` 은 마지막 HOLD/전략 사유(`tracking` 이 아닌 것; 없으면 현재 사유). 의도한 대기(D-494 교차로 `junction_*`, D-517 권한 `authority_*`, D-573 횡단보도 `crosswalk_*`, D-525 신호·D-517 M4 교통 게이트가 0으로 만든 틱)와 OFF·odom 없음은 창을 지운다. D-468 로컬 복귀가 틱을 가진 동안에도 연다(그러면 D-468 은 기존대로 틱을 돌려준다). URDF 몸(`body_stop_known`)이 없거나 `stuck_report_s: 0` 이면 열지 않는다. 열린 뒤 답이 오기 전까지 CORE 는 원래 결정대로 움직인다(보고만, 로컬 후진 없음, `nav.line_stuck_asked` `reason` = 원인, `ask_remaining_s` null). 수락된 답은 다른 원인과 같다(WAIT 면 HOLD). 몸 길이만큼(창 동안 2×반 길이) 다시 가면 `cleared` 로 닫힌다. Fleet 규칙은 D-607(WAIT + 사람). |
| `nav.line_stuck_asked` | info | 로봇 | `{stuck_id, cause, console_linked, local_fallback_s, attempts, reason, decisions, inquiry}` — D-407 §2·§3 관제 판단 요청(FleetAgent 가 중계). `local_fallback_s` 가 null 이면 로컬 복구로 넘어가지 않고 관제 답만 기다린다(`reason`: `opened`·`console_wait`·`local_disabled`·`local_refused`·`local_aborted`·`attempts_exhausted`·`local_candidates_exhausted`). 늦게 연결한 관제는 반복 이벤트가 아니라 로봇 status 의 열린 stuck 으로 찾는다 (v1.74) |
| `nav.line_stuck_answered` | info | 로봇 | `{stuck_id, decision, by, principal_ref, accepted, reason, rear_blind_m, trail_m, trail_yaw_deg, trail_age_s}` — D-407 §2 관제 답. `by` 는 역할, `principal_ref` 는 답한 토큰의 이름 — 설정된 id 가 있으면 그 id, 없으면 `anon-` + CORE 프로세스마다 새로 만드는 키로 낸 HMAC 앞 12자(해시 앞자리를 그대로 내면 후보 토큰으로 확인할 수 있어서다; 이 값은 CORE 한 번 실행 동안만 같다). 비밀이 아니다. v1.80 에서 `token_id` 에서 이름을 바꿈: Fleet 감사 저장소가 자격 증명 이름으로 거부했다. `BACK_AND_RETRY` 거부면 판정한 scan 의 `rear_blind_m`·`trail_m`·`trail_yaw_deg`·`trail_age_s`, 아니면 null. 거부된 답(`stuck_id_mismatch`, 거부 사유)도 남는다 (v1.74) |
| `nav.line_stuck_local_attempt` | warning | 로봇 | `{stuck_id, attempt, trigger, back_m, speed_mps, rear_clearance_m, rear_blind_m, trail_m, trail_age_s, realign_attempt?, realign?}` — D-407 §4 로컬 후진 시작. `rear_blind_m` 은 LiDAR `range_min` 과 몸 뒤끝을 넘는 self-mask 창이 가리는 뒤 깊이, `trail_m` 은 방금 앞으로 지나온 거리(사용자 결정 2026-10-02: 사각 띠는 그 안에서만 들어간다)(`trigger`: `ask_timeout`·`no_console`·`retry`·`console`) (v1.74). D-607 8 (v1.199): `trigger: realign`일 때 `realign_attempt`와 `realign {kind, leg, turn_spot, turned_deg, remaining_deg, ticks}`를 더한다. |
| `nav.line_stuck_local_result` | info | 로봇 | `{stuck_id, attempt, result, reason, lane_visible, front_clear, rear_clearance_m, rear_blind_m, trail_m, trail_yaw_deg, trail_age_s}` — D-407 §4 결과: `recovered`·`still_stuck`·`refused`(시작 전)·`aborted`(후진 중 뒤 여유·scan stale·관제 WAIT) (v1.74) |
| `nav.line_stuck_closed` | info | 로봇 | `{stuck_id, cause, reason, attempts, held_s}` — D-407 막힘 닫힘(`cleared`·`recovered`·`console_resume`·`console_manual`·`console_abort`·`mode_off`·`mode_changed`·`driver_released`·`estop`) (v1.74) |
| `nav.traffic_policy_staged` | info | 로봇 | `{actor, policy_revision}` — D-151 traffic policy 변경 대기 |
| `nav.traffic_policy_applied` | info | 로봇 | `{actor, policy_revision, mode}` — D-151 대기 정책 적용(정지 상태에서만) |
| `nav.traffic_policy_reset` | info | 로봇 | `{reason}` — D-151 정책 상태 초기화(HOLD/DISABLED 로 복귀) |
| `nav.traffic_policy_signal_source_stale` | warning | 로봇 | `{outcome, silent_for_s}` — D-337 관측 신호 소스 침묵(카메라 단독으로 강등, 전환마다 1회) |
| `sim.traffic_signal_changed` | info | 로봇 | `{actor, colour}` — 시뮬레이션 신호등 제어가 켜진 프로필에서만 |
| `nav.blocked` | warning | 로봇 | **미구현** — CORE 는 Nav2 액션 피드백을 구독하지 않아 막힘을 알 방법이 없다. 진척이 없는 주행은 NAV-006 이 `nav.stuck` 으로 끝낸다 |
| `safety.estop` | critical | 로봇 | `{source}` |
| `safety.estop_released` | warning | 로봇 | `{by}` |
| `safety.watchdog` | warning | 로봇 | `{timeout_ms}` |
| `safety.shadow_verdict` | info | 로봇 | `{verdict, reason, source, t, commanded, output, limited, suppressed}` — D-400 그림자 판정. 판정이 바뀔 때·명령 중(0 아닌 후보) 같은 판정 1 s마다·최대 5/s. `suppressed` 는 그 사이 억제된 판정 변화 수, `commanded` 는 프로필 클립 뒤 값, `t` 는 CORE monotonic 초 (v1.71) |
| `safety.policy_off` | warning | 로봇 | `{source}` — D-400 정책 off 에서 navigation·docking 출력이 처음 0 이 아닐 때, 모드 진입마다 한 번 (v1.71) |
| `safety.fleet_lost` | warning | 로봇 | `{policy, applied, activity, correlation_id, goal, disconnected_s, reason}` — SAF-003(D-419): FleetAgent 링크가 `fleet_loss_timeout_s` 넘게 끊긴 채 Fleet 주행 목표가 진행 중이어서 정책을 적용했다(행동 뒤 발행, 단절마다 한 번). `policy` 는 설정값, `applied` 는 실제로 한 것(`STOP`·`HOLD`·`RETURN_HOME`·`CONTINUE`·`NONE`), `activity` 는 `navigation`, `goal` 은 `{x, y, yaw}`, `reason` 은 `null` 또는 `unknown_policy`·`home_unavailable: …`·`action_failed: …`·`goal_changed`(취소 순간 그 목표가 이미 끝났거나 바뀜, `applied: NONE`). 취소는 `nav.canceled {source: fleet_loss}` 로도 보인다 (v1.86) |
| `safety.fleet_restored` | info | 로봇 | `{applied, correlation_id, disconnected_s, held_goal}` — `safety.fleet_lost` 뒤 링크가 돌아왔다. 아무것도 재개하지 않는다. `held_goal` 은 `HOLD` 가 보관한 `{correlation_id, x, y, yaw}` 또는 `null` (v1.86) |
| `battery.low` | warning | 로봇 | `{percent}` |
| `battery.critical` | critical | 로봇 | `{percent, policy}` |
| `battery.deep` | critical | 로봇 | `{percent, voltage, dwell_s}` — D-27 딥 방전. 모터가 서고 셧다운 센티넬이 무장된다 |
| `battery.shutdown_request_failed` | error | 로봇 | `{path, error, armed}` — D-27 셧다운 센티넬을 쓰지 못했다. 딥배터리 보호가 무장되지 않았다는 뜻이므로 조용히 넘어가면 안 된다 |
| `command.rejected` | warning | 로봇 | `{source, reason}` |
| `native.operation.terminal` | info | 로봇 | `{run_id, boot_id, kind, correlation_id, result, reason}` — 단발 teleop의 첫 native 종결. mode 이탈·안전 정지·watchdog 만료 후 기존 감사 포트로 전달된다 (D-732, v1.220) |
| `recording.started` | info | 로봇 | `{id, owner}` — D-411 §5.10 Pilot 로봇 녹화가 시작됐다. `owner` 는 시작한 토큰 id (v1.83) |
| `recording.stopped` | info | 로봇 | `{id, by, reason}` — D-411 녹화 끝. `by` 는 정지한 토큰 id 또는 `null`(CORE 가드·녹화기 쪽 종료). `reason` ∈ `operator`·`link_lost`·`seat_changed`·`max_duration`·`quota`·`disk_full`·`recorder_exit`·`requested`·`shutdown`·`recovered` (v1.83) |
| `waypoint.created/updated/deleted` | info | 로봇 | `{name}` |
| `slam.started` | info | 로봇 | `{by, reset}` — `reset` 은 재시작일 때만 (NAV-005) |
| `slam.stopped` | info | 로봇 | `{by}` |
| `power.mode_changed` | info | 로봇 | `{from, to, reason, sample_rate_hz}` (PWR-001) |
| `power.wake` | info | 로봇 | `{reason, source?}` — `proximity\|contact\|api\|battery\|command` (PWR-004). `command` 는 절전 중 받아들여진(2xx) 명령 REST 호출(D-24 개정 2026-10-04)이며 `source` 에 명령 출처(`teleop`·`mode`·`navigation`·`mission`·`docking`·`line_follow`·`fleet_task`·`intent`·`safety`)를 싣는다. GET·텔레메트리·WS 구독·`/power/*` 는 무명령 타이머를 리셋하지 않는다 |
| `presence.detected` | info | 로봇 | `{state, range}` (PWR-002) |
| `presence.cleared` | info | 로봇 | `{range}` |
| `power.lidar_changed` | info | 로봇 | `{spinning, reason, spinup_s}` (PWR-005 STANDBY LiDAR 정지) |
| `power.device_changed` | info | 로봇 | `{device, from, to, reason, wake_ready_s}` — 기기별 전원 정책(D-440)이 선언된 기기의 수준(`on`·`reduced`·`off`)을 바꿨다. 벤치 스위치 `power.device_policy.enabled`(기본 false)가 꺼진 로봇에서는 나오지 않는다 |
| `map.saved` | info | 로봇 | `{map_id}` |
| `localization.initialpose` | info | 로봇 | `{x, y, yaw, source}` — 운영자가 자세를 놓았다. `source` 는 결정 출처로 이 경로에서는 늘 `human`(v1.72). D-395 로봇에서는 `localization/decision` 으로 가 로봇의 3 s 검증을 거친다. 누가 놓았는지는 envelope 의 `source` 에 있다 |
| `localization.state` | info | 로봇 | `{state, previous, pose_frame, reason, request_id}` — D-395 상태가 바뀌었다(v1.72). `previous` 는 처음이면 `null`. 상태 토픽이 3 s 끊기면 `UNKNOWN`(`reason: state_stale`). `previous: LOCALIZED` 에서 벗어나면 CORE 가 자율 주행을 기존 정지 경로로 멈춘다: swarm follow 취소(`swarm.aborted`, `reason: localization`), 도킹 취소, line-follow OFF, Nav2 취소(`nav.canceled`), NAVIGATION → IDLE. MANUAL(teleop)은 그대로 |
| `localization.candidates` | info | 로봇 | `{request_id, count, pickup}` — 새 `request_id` 의 후보 보고가 왔다(v1.72). 2 s 재보고는 다시 내지 않는다 |
| `localization.result` | info | 로봇 | `{request_id, accepted, reason, state, source, cues}` — 로봇이 결정을 받았거나 거부했다(v1.72). `source`·`cues` 는 CORE 가 그 `request_id` 로 보낸 결정의 것이고, 모르면 `null`·`[]` |
| `localization.request` | info | 로봇 | `{request_id, reason}` — lane_return 이 위치 요청을 열었다(v1.163). 같은 사유의 갱신은 다시 내지 않는다 |
| `localization.request_cleared` | info | 로봇 | `{request_id, why}` — 요청이 닫혔다(v1.163). `why`: `answered`(수락된 결정), `lane_return_resumed`, `line_follow_reset`. `ttl_s` 만료는 이벤트 없이 사라진다 |
| `localization.mission` | info | 로봇 | `{phase, kind, reason, elapsed_s, travelled_m, turned_rad}` — D-395 P2-7 미션이 시작했거나(`phase: started`, `reason: null`) 끝났다(`phase: done`\|`aborted`, `reason` 은 `POST /localization/mission` 의 끝 사유). 같은 내용이 ROS `localization/mission` 으로 로봇 sensing 노드에 가서 다시 탐색하게 한다 (v1.73) |
| `motion.rotate_to` | info | 로봇 | `{delta_deg, yaw_odom, tol_deg, max_rate_dps, timeout_s, lease_owner, operator_name, by}` — D-603 회전 요청을 받았다 (v1.194) |
| `docking.started` | info | 로봇 | `{dock_id}` (DNC-003) |
| `docking.docked` | info | 로봇 | `{dock_id}` — dock native 종결이면 추가 `run_id`, `boot_id`, `kind`, `result`, `native_reason`가 붙는다 (D-732) |
| `docking.charging` / `docking.charge_lost` | info | 로봇 | `{dock_id}` — 독립된 두 소스로 확인한 충전 상태 (D-28) |
| `docking.full` | info | 로봇 | `{dock_id, source, voltage_v}` — 만춫 감지, 1회 방출. `source: instrumented` 또는 `voltage_only` (D-350) |
| `docking.undock_started` | info | 로봇 | `{dock_id}` |
| `docking.undocked` | info | 로봇 | `{}` — undock native 종결이면 추가 `run_id`, `boot_id`, `kind`, `result`, `native_reason`가 붙는다 (D-732) |
| `docking.canceled` | info | 로봇 | `{dock_id}` — 닫힌 dock/undock의 추가 `run_id`, `boot_id`, `kind`, `result`, `native_reason` (D-732) |
| `docking.retry` | warning | 로봇 | `{reason, attempt}` — 접근 재시도 |
| `docking.reseat` | warning | 로봇 | `{reason, attempt}` — 접점 재착좌 |
| `docking.failed` | error | 로봇 | `{reason, dock_id}` — 종착이며 스스로 재시도하지 않는다. native 종결이면 추가 `run_id`, `boot_id`, `kind`, `result`, `native_reason` (D-28/D-732) |
| `docking.return_started` | warning | 로봇 | `{dock_id, reason}` — SAF-005 저배터리 복귀 |
| `mission.assigned` | info | Fleet | `{mission_id, robot_id}` |
| `mission.started` | info | Fleet | `{mission_id}` |
| `mission.step_completed` | info | Fleet | `{mission_id, step_index}` |
| `mission.completed/failed/canceled` | info/error/info | Fleet | `{mission_id, reason}` |
| `robot.online/offline` | info/warning | Fleet | `{robot_id}` |
| `pairing.requested/approved/revoked` | warning | Fleet | `{robot_id}` |
| `swarm.role_assigned` | info | 로봇 | `{role, formation, target_robot_id, mode, reference_source, by}` — `mode` 는 D-559 (`offset`\|`trail`) |
| `swarm.hold` | warning | 로봇 | `{reason, formation, stream_timeout_ms, reference_map_id, map_id}` — `reason`: `reference stream lost`(+`stream_timeout_ms`) \| `map_mismatch`(+`reference_map_id`, `map_id`) \| D-559 trail (v1.170): `trail_lost`(자취에서 0.30 m 넘게 벗어났거나 리더가 표본 사이에 0.3 m + SAF-004 `max_linear` × 경과 시간(최대 1.5 m)보다 멀리 건너뜀, follow 를 다시 걸 때까지 유지) \| `reference_frame_not_map` \| `own_pose_not_map` \| `own_pose_stale`(자기 pose 가 0.5 s 넘게 갱신되지 않음 — map 자취는 map pose, D-581 Fleet 기준 자취는 `odom_pose`) \| `obstacle`(D-422 몸체 정지, 멈춘 판정의 재개 거리를 넘어야 다시 간다) \| `obstacle_sensor_stale` \| D-581 (v1.176): `reference_anchor_invalid`(`anchor` 표본이 이 로봇 몫이 아니거나 `frame: odom` 이 아님) \| `reference_frame_changed`(map 자취에 Fleet 기준 표본, 또는 그 반대 — follow 를 다시 걸 때까지 유지) \| `anchor_withheld`(Fleet 이 `anchor_hold` 정지 표본을 보냄, 스트림 유지) |
| `swarm.aborted` | warning | 로봇 | `{formation, reason, robots, by, run_id, boot_id, kind, result, native_reason}` — D-732 native follow 종결 ID·결과 포함. `reason`: `canceled` \| `estop` \| `docking` \| `stuck` \| `manual` \| `navigation_canceled` \| `localization`(D-395 로봇이 `LOCALIZED` 를 벗어남, v1.72) \| `trail_join_too_far`(D-559, v1.170) |
| `swarm.succession` | warning | 로봇 | `{leader, dead, role, by}` — 명단이 공유된 대형에서 리더(`dead`)를 잃은 팔로워가 follow 를 끝내고 낸다. `leader` 는 `next_leader` 규칙이 고른 다음 리더(없으면 `null`), `role` 은 이 로봇의 새 역할, `by`: `followers` |

---

# 9. 데이터 스키마 카탈로그

## 9.1 Capability Descriptor (CAP-001)

```json
{
  "capability_version": 1,
  "navigation": { "goal_navigation": true, "return_home": true,
                  "max_linear_velocity": 0.2, "max_angular_velocity": 0.8 },
  "teleop": true,
  "slam": true,
  "swarm": { "follow": true, "lead": true },
  "docking": { "supported": false },   // true 이면 DNC-004~006 전체가 활성
  "sensors": ["lidar", "imu", "battery", "encoder"],
  "events": ["nav.*", "safety.*"],
  "api_versions": ["v1"],
  "protocol_version": "1.0"
}
```

**`withheld` (v1.18 additive, v1.21 판정 변경, D-32/D-161/D-192)**: 지금 런타임이 지킬 수 없는 하드웨어 플래그
(`teleop`, `navigation.goal_navigation`, `navigation.return_home`, `slam`, `swarm.follow`, `swarm.lead`,
`docking.supported`)를 `false` 로 내리고, 내린 것과 이유를 싣는다. `reason` 은 첫 플래그의 이유(v1.18 호환),
`reasons` 는 플래그마다의 이유다(v1.21 additive).

```json
"withheld": {
  "flags": ["teleop", "navigation.goal_navigation", "slam"],
  "reason": "drive_disabled:no_motion",
  "reasons": {"teleop": "drive_disabled:no_motion",
              "navigation.goal_navigation": "drive_disabled:no_motion",
              "slam": "navigation_absent"}
}
```

판정은 설정 문자열(`runtime.mode`)이 아니라 **살아 있는 증거**로 한다(v1.21). 네이티브 이미지는 `runtime.mode: core`
그대로 운용자가 `rosy-io` 를 손으로 켠다(D-192). 플래그마다 아래 순서로 첫 이유 하나:

| 이유 | 조건 | 대상 플래그 |
|---|---|---|
| `runtime_mode:core` | `runtime.mode: core` 이고 오도메트리(velocity)·배터리 표본이 한 번도 없음 | 전부 |
| `hardware_silent` | 표본이 온 적은 있으나 단조 시계 기준 15 s 안에 없음 | 전부 |
| `drive_disabled:no_motion` | bringup 이 `motor/ready: false` 를 보고(D-192 무동작: torque off, `cmd_vel` 미구독) | `slam` 을 뺀 전부 |
| `drive_lease_expired` | `motor/ready: true` 였으나 lease(`navigation.readiness.stale_after_s`)가 지남 | `slam` 을 뺀 전부 |
| `drive_absent` | `motor/ready` 보고가 없고, readiness 게이트가 motor adapter 를 요구하거나 오도메트리가 살아 있지 않음. `slam`도 오도메트리 없이 배터리만 들어오면 보류 | 이동 플래그 및 오도메트리 없는 `slam` |
| `navigation_absent` | readiness 게이트가 required 이거나 bringup 이 `motor/ready` 를 보고했는데, 백엔드 프로파일의 Nav2/SLAM lifecycle 노드가 모두 active 로 보고하지 않음 | `navigation.goal_navigation`, `navigation.return_home`, `slam` |
| `readiness_hold:<missing>` | 필수 하드웨어 준비 게이트가 HOLD | 이동 플래그 및 `slam` |

`motor/ready` 없이 오도메트리만 오는 시뮬 벤치(gz_multi, CORE-only)는 종전대로 광고를 유지한다. 명령 경로의
CAP-003 게이트는 이 변경으로 바뀌지 않는다. `POST /teleop`, `/navigation/goal`,
`/navigation/home`은 지원 여부를 먼저 확인한 뒤 현재 보류된 기능을 409
`CAPABILITY_WITHHELD`와 동일한 `reason`으로 거절한다. 준비 상태가 판정과 전송 사이에
변하면 기존 503 `HARDWARE_NOT_READY`가 발생할 수 있다.

**`runtime` (v1.21 additive)**: 위 판정의 근거. 대시보드는 하드웨어 존재를 `runtime_mode` 문자열이 아니라 이것으로 읽는다.

```json
"runtime": {
  "mode": "core",
  "hardware": "on",
  "evidence": ["odometry", "battery"],
  "drive": "disabled",
  "navigation": "absent",
  "maps": {"occupancy": false, "global_costmap": false}
}
```

`hardware`: `on`(오도메트리 또는 배터리 표본이 15 s 안) \| `silent`(온 적은 있으나 끊김) \| `off`(온 적 없음).
`drive`: `ready` \| `disabled`(`motor/ready: false`) \| `stale`(lease 만료) \| `unknown`(보고 없음).
`navigation`: `ready` \| `absent` \| `unknown`(판정하지 않음 — 게이트 비필수이고 bringup 보고도 없음).
`maps`: 스냅샷이 있는지. `false` 인 것을 `GET /api/v1/map`·`/map/costmap?scope=global` 로 물으면 404 다 — 클라이언트는
묻지 않는다.

**`lifecycle` (v1.58 additive, D-347)**: 광고된 플래그 각각의 런타임 생애를 **단일 어휘**로 실는다. 원천은 이미
있는 두 값 — 위 `withheld` 판정(모드 마스킹 사유가 우선)과 플래그의 참/거짓 — 이며, 새 판정을 만들지 않는다.
`withheld.flags` 는 항상 `lifecycle` 의 `unavailable` 집합과 정확히 일치한다.

```json
"lifecycle": {
  "teleop": {"state": "unavailable", "reason": "drive_disabled:no_motion",
             "reasons": ["drive_disabled:no_motion"]},
  "slam": {"state": "ready"}
}
```

- `ready`: 지금 아무것도 보류하지 않는다.
- `unavailable`: `reason`·`reasons` 는 `withheld.reasons` 와 같은 값이다.
- `activating`: **예약** — 온디맨드 그래프 기동(D-347 토론 B레인)용 슬롯으로, 아직 이 상태로 진입하는 생산자는
  없다. 클라이언트는 이 값을 "준비 안 됨, 실패 아님"으로 읽는다: 갱신하거나 기다리지, 오류로 승격하지 않는다.

프로파일과 런타임 어느 쪽도 true 로 말하지 않는 플래그(예: `docking.supported`)는 `lifecycle` 에 없다(설계 §7).
inventory 기술자의 `state`(available/constrained/… presentation 어휘)와의 대응은 D-347 본문의 표가 정한다:
`unavailable` ≈ `blocked`, `ready` ≈ `available`·`constrained`·`degraded_fallback`, 대응 없음 ≈ `not_provided`.

**`controls` (v1.87 additive, D-411 B)**: 이 기기가 받는 조작부 서술자 `rosy.controls/1` `{schema, items[]}`. 항목은
`{id, kind, label, ...}`이고 kind 는 `base_velocity`(`max_linear`·`max_angular`·`pivot`·`fine`·`autonomy`),
`joint_jog`(`joints[{name, lower, upper}]`·`max_step_rad` ≤ 0.05·`duration_s` 0.1–1.0·`command: "bounded_goal"`),
`gripper`(`joint`·`closed`·`open`·`unit`·`presets{open, half, close}`·`readback`)다.

- `base_velocity`: `max_linear`·`max_angular` 는 지금의 수동 한도다. **0 은 "구동은 있으나 지금 정지로 제한됨"**
  (`PUT /safety/limits` 가 0 을 받는다)이며 오류가 아니다. `autonomy` 는 기기가 **제공하는** 자율 모드다 — CORE 는
  line-follow 서비스를 가질 때 `["line"]`, 없으면 `[]`. 이것은 지금 차선 추종을 시작할 수 있다는 런타임 증거가 **아니다**
  (차선 관측은 모드를 켠 뒤에만 들어오고, 쉬는 동안 카메라·차선 준비를 보여 주는 신호가 없다). 시작 가능 여부는
  `PUT /line-follow/mode` 응답과 `GET /line-follow` 상태(`WAITING`·`LOST` 등)가 판정한다. `pivot`·`fine` 은 Pinky
  프로필 상수다(런타임 증거 아님).
- `base_velocity` trip 필드(v1.112 additive, D-494 1, 선택): `robot_kind` 는 로봇 패키지 이름(`robot.model`, 없으면
  CORE 기본 로봇 패키지; 예 `pinky_pro`)이다. `drive_modes` 는 Fleet trip 에 쓸 수 있는 주행 방식 목록이다 — CORE 가
  line-follow 서비스를 가지면 `lane`, 같은 응답의 `navigation.goal_navigation` 이 참이면 `free`(보류 뒤 값)다. 둘 다 없으면
  `[]` 이다. `trip_max_linear`(m/s, ≥0)는 로봇이 trip 에 허용하는 최고 속도로, `safety` 의 `max_linear`·`fleet_linear` 와
  line-follow 가 있을 때 그 `max_linear` 중 가장 작은 값이다. `junction_turn`(bool, D-495)은 CORE line-follow 가 교차로의
  제한된 회전 동작을 지원할 때 `true` 다(지원하지 않으면 `false`, 없으면 지원하지 않는 것으로 읽는다). 지원은 읽을 때마다 다시 판단한다: keep 모드 교차로 감지 증거와 회전의 운동 근거가 함께 있어야 한다. 운동 근거는 D-400 enforce 바닥 증명이거나, D-498/D-507 6 현장 근거(`line_follow.site_floor_map_id` 선언 + `ir_guard_enabled` 의 신선한 IR 가드 판정(이탈 아님) + `obstacle_mode: path`·URDF 몸 + 신선한 스캔의 D-422 몸체 정지)다 (v1.118, v1.126). `site_floor_map_id`(문자열, D-507 9, v1.126)는 로봇의 현장 바닥 선언, 곧 걸어서 확인한 지도의 `SiteMap.map_id`다. 선언이 없으면(설정 null) 필드가 없다. Fleet 은 이 값이 활성 지도의 `map_id`와 다른 로봇의 `lane` trip 을 열지 않는다. `junction_pivot`(bool, D-507 2항, v1.127)은 CORE 가 `POST /line-follow/junction` 의 `map_id`·`expect_in_m`·`expect_tol_m`·`pivot_past_line_m` 를 받고, 최근 2 s 안에 받은 `line/keep_debug` 프레임이 표지 `junction_ahead_v`(정수 ≥ 1, 인식이 모든 프레임에 싣는다)를 실었을 때만 참이다(`junction_turn` 의 `corner_turning` 과 같은 창). 표지가 끊기면 다시 거짓이다. 없거나 거짓이면 Fleet 은 그 필드를 보내지 않는다. `lane_bend`(bool, D-507 보충, v1.142)는 CORE 가 `POST /line-follow/junction` 의 `action: bend` 와 `bend_in_m`·`bend_tol_m`·`bend_radius_m` 를 받을 때 참이다(D-400 증명이 살아 있으면 그 증명이 구성됐을 때, 아니면 `site_floor_map_id`·`ir_guard_enabled`·`obstacle_mode: path`·URDF 몸이 모두 있을 때). 없거나 거짓이면 Fleet 은 굽이 지시를 보내지 않는다. `lane_bend_next_line`(bool, D-754, v1.225)은 CORE 가 `bend` 의 `next_line_in_m` 을 받을 때 참이고 값은 `lane_bend` 와 같다. 없거나 거짓이면 Fleet 은 그 필드를 보내지 않는다. `lane_bend_map_entry`(bool, D-759 2항, v1.224)는 CORE 가 `bend` 의 `map_entry` 를 받을 때 참이다. `line_follow.bend_map_entry_enabled`(기본 꺼짐)가 켜져 있고 `lane_bend` 가 참일 때다(없으면 받지 않는 것으로 읽는다). `lane_instruction_stamp`(bool, D-767 A부, v1.241)는 CORE 가 `POST /line-follow/junction` 의 `pose_stamp` 를 받아 거리를 그 odom 표본부터 잴 때 참이다. 값은 `line_follow.instruction_stamp_enabled`(기본 꺼짐)다(없으면 받지 않는 것으로 읽는다). `line_follow_authority`(bool, D-517 4, v1.143)는 CORE line-follow 가 `POST /line-follow/authority` 를 받아 강제할 때 `true`(line-follow 가 없으면 `false`)다. 없거나 거짓인 로봇에 Fleet 은 통행권을 보내지 않고 M1 교차로 보류만 쓴다. `line_follow_authority_required`(bool, D-517 4, v1.143)는 설정 `line_follow.authority_required` 가 참이라 CORE 가 첫 통행권 전에도(E-Stop·CORE 재시작 뒤 포함) 통행권 없이는 서는 때 `true`(line-follow 가 없으면 `false`)다. `fleet.traffic.authority: true` 인 Fleet 은 `line_follow_authority` 가 참인데 이 값이 참이 아닌 로봇의 `lane` trip 을 열지 않는다(422 `TRIP_AUTHORITY_NOT_REQUIRED`). `line_follow_authority_shrink`(bool, D-760 3항, v1.226)는 CORE 가 통행권의 `shrink`·`seq` 와 5 s 까지의 `ttl_s` 를 받을 때 참이다. `line_follow_authority_under_lease`(bool, D-760 2항, v1.226)는 이 CORE 가 trip lease 가 열려 있는 동안 통행권을 강제할 때 참이다(둘 다 없으면 거짓으로 읽는다). `lane_arc`(bool, D-520 1항, v1.145)는 CORE 가 `POST /line-follow/junction` 의 `exit_segment` 를 받을 때 참이다. `lane_arc_map_anchor`(bool, D-744 2항, v1.221)는 CORE 가 `exit_segment.map_anchor` 를 받을 때 참이고 `lane_arc` 와 같은 값이다(없으면 받지 않는 것으로 읽는다). v1.154(D-520 개정 2026-10-09)부터 `line_follow.arc_enabled` 는 기본 켬이고, 능력은 그 설정과 현장 바닥 선언 `site_floor_map_id`, `ir_guard_speed_scale` > 0 이 함께 있을 때만 참이다(선언 없는 켬은 시작 거부가 아니라 능력 거짓). 없거나 거짓이면 Fleet 은 `exit_segment` 를 빼고 오늘처럼 보낸다. `trip_lease`(bool, D-541 1, v1.157)는 CORE 가 `PUT/DELETE /api/v1/trip-lease`·`POST /trip-lease/takeover` 를 받고 lease 동안 주인 아닌 움직임을 거절할 때 `true` 다. 없는 로봇은 이전 이미지다. D-494 세 필드 `robot_kind`·`drive_modes`·`trip_max_linear`가 **없는** 로봇은 D-494 이전 이미지다(`junction_turn`도 없다). `robot.model`이 로봇 패키지 이름(`[a-z][a-z0-9_]*`, 64자 이하)이 아니면 CORE는 `robot_kind`만 뺀다. Fleet 은 모르는 `drive_modes` 값을 무시한다. Fleet 은 그
  로봇의 계획 미리보기를 지금처럼 허용하고, trip 실행은 열지 않는다(`TRIP_ROBOT_CAPS_UNKNOWN`, D-494 5).
- `joint_jog`: 요청 한 번은 관절 하나를 `max_step_rad` 이하로 옮긴다. `duration_s` 는 **클라이언트가 각 요청에 보낼 목표
  길이**다. 이전 목표가 끝난 뒤에만 다음 목표를 보낸다(D-390 §2).
- `gripper`: `presets.open` = `open`, `presets.close` = `closed`, `presets.half` 는 둘 사이(끝값 제외)다. 목표는 절대
  위치 하나씩이다. `max_velocity`(선택, rad/s)를 알리는 기기는 `|목표 − readback| / duration_s` 가 그보다 큰 목표를 거절하므로
  클라이언트는 그 속도로 목표 길이를 정한다. `readback` 의 `grasp` 는 상태 readback 의 그리퍼 상태(`open`·`closed`·`holding`·`moving`·`unknown`,
  OMX SIM 은 §5.9 `/state` `gripper`)를 낸다는 뜻이다.

Pinky 는 켜진 adapter manifest `provides` 의 `drive`(manifest 가 없으면 `teleop`)에서 `base_velocity` 하나
(`id: "base"`, 최대값 = `safety.manual_linear`·`manual_angular`)를 낸다. `teleop` 이 보류되면(`withheld`) `items` 는
비어 있다. 빈 `items` 는 "지금 조작부 없음"이지 "구 서버"가 아니다 — 이 필드가 **없는** 구 서버에서만 Pilot 이 기존
Pinky 프로필로 대체한다.

호환: 스키마 정본 `core_common.protocol.controls`(`ControlsDescriptor`)는 **생산자** 스키마다(모르는 필드 거부). `/1`
안에서는 새 kind 와 새 선택 필드를 더할 수 있고, 소비자(Pilot)는 모르는 kind·필드를 무시하고 kind 는 "지원하지 않는
조작부"로 보인다. 필드를 빼거나 뜻을 바꾸면 `rosy.controls/2` 다.

같은 동안 `GET /api/v1/system/inventory` 의 descriptor 는 `available: false`, `state: "blocked"` 이고 `reason` 은
그 플래그의 런타임 이유다. **런타임 이유가 `device_state` 보다 먼저다(v1.21, 이전에는 반대)** — 비상정지를 풀어도
구동이 없는 로봇은 움직이지 않으므로 SAFE_STOP 이 더 오래 가는 이유를 가리면 안 된다. `reasons`(v1.21 additive)는
모든 이유를 기본적인 것부터 싣는다: `["runtime_mode:core", "device_state:SAFE_STOP"]`.

## 9.2 Waypoint (WPT-001)

```json
{ "name": "dock_1", "x": 2.5, "y": 1.8, "yaw": 1.57,
  "map_id": "warehouse_a", "metadata": { "label": "충전독 앞" } }
```

## 9.3 Mission DSL v1 (MSN-001)

```json
{ "mission_id": "patrol_evening",
  "target": { "robots": ["rosy_01"] },
  "idempotency_key": "pe-20260829-01",
  "steps": [
    { "action": "goto", "waypoint": "zone_a" },
    { "action": "home" },
    { "action": "wait", "seconds": 30 },
    { "action": "formation", "formation": "V", "robots": ["rosy_01","rosy_02"], "center": {"x":0,"y":0} }
  ] }
```

v1 action: `goto`(waypoint|x,y,yaw) / `home` / `wait(seconds)` / `formation`. 상태머신은 FLEET SRS MSN-002.

## 9.4 Robot Profile (HWA-001)

```yaml
profile:
  model: Pinky Pro
  drivetrain: differential
  wheel_base: 0.15
  max_linear_velocity: 0.20
  max_angular_velocity: 0.80
  sensors: [ {lidar: rplidar_c1}, {imu: bno055}, {battery: adc} ]
```

## 9.5 Command 추적 레코드 (PRT-004)

```json
{ "correlation_id": "uuid", "robot_id": "rosy_01",
  "action": "goto", "params": { "waypoint": "zone_a" },
  "status": "ACCEPTED|STARTED|COMPLETED|FAILED|TIMEOUT",
  "issued_by": "user:admin|mission:m123|fleet:stop_all",
  "ts_issued": "...", "ts_final": "..." }
```

`TIMEOUT`은 Fleet 측 레코드 전용이며 로봇 ack에는 나타나지 않는다 (D-215).
타임아웃은 로봇의 정지나 실패 증거가 아니다. 늦은 ACK는 동일
`correlation_id`로 조정하고, 타임아웃만으로 물리 명령을 재발행하지 않는다(D-297).

---

# 10. Fleet REST API 카탈로그

Fleet(rosy_fleet)이 제공하는 엔드포인트. Base: `http://<fleet-host>:8081`

> **상태 (v1.97, D-454): 로봇 레지스트리 읽기 두 경로 구현.**
> `fleet console --central`이 기존 사이트 앱에 §10.1의 GET 두 경로를 마운트한다.
> 기본 사이트 프로파일에는 이 경로가 없다. 별도 8081 서비스나 중앙 쓰기·명령·
> 미션 API는 아직 구현하지 않았다. 기존 `:8090`의 `/api/fleet/*`와 SiteHub는
> 유지하며, 로봇↔사이트 프로토콜은 §5~§7을 따른다.

사이트 시드의 추가 경로는 §10.6에 기록한다. 이 API는 로봇 `/api/v1/*`와 다른
listener·자격 증명이다. §10.1의 명시된 읽기 경로 외 중앙 카탈로그의 구현 상태로
간주하지 않는다.

## 10.1 로봇·페어링

D-454 1단계의 구현은 아래 GET 두 경로에 한정한다. 기존 Fleet Viewer 이상의
인증을 사용하며, CLI 활성화에는 기존 `--robot-credential-key-file`과 `--tasks-db`
등록 구성이 필요하다. 나머지 행은 후속 목표 계약이다. 등록·페어링·권한을
읽기 요청이나 발견 광고로 변경하지 않는다.

목록은 `{robots: [...]}`, 상세는 한 행이며 각 행은 `robot_id`, `source`
(`static`·`enrolled`), `online`, `state`, `capabilities`, `address_last_seen`을
반환한다. 등록 로스터가 정본이며 등록되지 않은 상세는 404 `UNKNOWN_ROBOT`이다.
목록은 robot_id 오름차순이고 이 단계에는 pagination이 없다. `online`은 기존
Hub의 연결 상태이고 물리 동작 수락 증거가 아니다. `state`·`capabilities`는 기존
스냅샷에 없으면 null이며 서버가 기능을 추정하지 않는다. 마지막 발견 주소도
등록 신원과 안전하게 대조할 수 없으면 null이다.

| Method | Path | Role | 요구사항 |
|---|---|---|---|
| GET | `/api/v1/fleet/robots` | Viewer | REG-002 (상태·Capability 포함) |
| GET | `/api/v1/fleet/robots/{id}` | Viewer | REG-002 |
| PATCH | `/api/v1/fleet/robots/{id}` | Admin | 이름·그룹 변경 (REG-003) |
| DELETE | `/api/v1/fleet/robots/{id}` | Admin | 등록 해제 (REG-001a) |
| POST | `/api/v1/fleet/pairing-tokens` | Admin | 1회용 발급 (SEC-201) |
| DELETE | `/api/v1/fleet/pairing-tokens/{token}` | Admin | 폐기 (SEC-201) |
| GET | `/api/v1/fleet/pending-robots` | Admin | 승인 대기 목록 (SEC-202) |
| POST | `/api/v1/fleet/pending-robots/{id}/approve` | Admin | 승인 (SEC-202) |
| POST | `/api/v1/fleet/robots/{id}/token/revoke` | Admin | 토큰 폐기 (SEC-203) |

## 10.2 명령

현행 Site Fleet 구현의 `POST /api/fleet/estop`은 각 등록 로봇의
`POST /api/v1/safety/stop`에 요청을 보낸다. 응답의 레거시 `stopped` 및 로봇별
`stopped`는 CORE HTTP 응답을 받은 수/여부다. CORE 안전 래치, 속도 0,
물리 E-stop 또는 드라이버 인터록의 확인 결과가 아니다. 응답 실패 대상의 실제
정지 상태는 `UNKNOWN`으로 취급하며 현장 readback을 따로 확인한다(D-298).
이 경로는 래치형 **전체 비상 정지**다: CORE EMERGENCY 래치와 Fleet 발행 래치를
걸고, 다시 움직이려면 로봇별 Admin `safety/release`와 발행 재허가가 필요하다.
래치 없는 **전체 주행 취소**는 `POST /api/fleet/cancel-all`이다(D-421, v1.81,
§10.8): 대기 Fleet 작업 취소, 대형 해제, 로봇마다 `swarm/cancel`·
`navigation/cancel`·`line-follow/mode OFF`. e-stop 래치·발행 래치·수동 조작은
건드리지 않으며 응답은 CORE 응답이지 물리 정지 증거가 아니다. CTR-002 STOP ALL은
이 두 경로로 나뉜다.
아래 `/api/v1/fleet/*`는 목표 계약이며 현행 `/api/fleet/*`와 혼동하지 않는다.

| Method | Path | Role | 요구사항 |
|---|---|---|---|
| POST | `/api/v1/fleet/commands` | Operator | 다중 로봇 명령 `{robot_ids, action, params}` (CTR-001, PRT-004) |
| POST | `/api/v1/fleet/stop-all` | Operator | STOP ALL (CTR-002) |
| GET | `/api/v1/fleet/commands/{correlation_id}` | Viewer | 추적 상태 조회 |

`action`: `goto | home | stop | estop | estop_release | mode | formation`

## 10.3 Mission·Formation

| Method | Path | Role | 요구사항 |
|---|---|---|---|
| POST | `/api/v1/fleet/missions` | Operator | 생성·실행 (MSN-001/003) |
| GET | `/api/v1/fleet/missions` | Viewer | 목록 |
| GET | `/api/v1/fleet/missions/{id}` | Viewer | 상세(스텝 상태) |
| POST | `/api/v1/fleet/missions/{id}/cancel` | Operator | 취소 (MSN-002) |
| POST | `/api/v1/fleet/formations` | Operator | `{formation, robots, params}` (FOR-001) |

## 10.4 Waypoint·맵·운영

| Method | Path | Role | 요구사항 |
|---|---|---|---|
| GET | `/api/v1/fleet/waypoints?map_id=` | Viewer | 전체 로봇 Waypoint 조회 |
| POST | `/api/v1/fleet/waypoints/sync` | Operator | `{robot_ids, waypoints}` 로봇 동기화 (WPT-005) |
| GET | `/api/v1/fleet/maps` | Viewer | map_id·버전 목록 (MAP-003) |
| POST | `/api/v1/fleet/robots/{id}/backup` | Admin | 스냅샷 수집 (OPS-001) |
| POST | `/api/v1/fleet/robots/{id}/restore` | Admin | 복구 프로비저닝 (OPS-002) |

## 10.5 이벤트·감사

| Method | Path | Role | 요구사항 |
|---|---|---|---|
| GET | `/api/v1/fleet/events?robot_id=&type=&since=` | Viewer | 통합 이벤트 조회 (OBS-202) |
| GET | `/api/v1/fleet/audit` | Admin | Fleet 감사 로그 |

## 10.6 Site Fleet sighting (D-257 Proposed)

Base: `https://<site-fqdn>:8443`. 이 경로는 지도 위 표시·로봇 pose 대조용이다.
이미지나 자동 정책 입력이 아니며 source 설정이 없는 앱에는 경로를 등록하지 않는다.
`fleet console --sightings-config <site-cameras.yaml> --sightings-db <fleet.sqlite3>`로
source/map/calibration 허용 목록과 SQLite 영속 저장을 설정한다. source token은 YAML이 아닌
별도 secret mount에서 환경 변수로 읽는다. HTTPS/WSS 종단과 내부 upstream TLS는 `deploy/site`
Compose/Caddy 구성이 담당한다. 로컬 합성 카메라의 Docker end-to-end 경로를 확인했지만 현장
인증서·실제 카메라·survey calibration은 별도 수용 gate다.

| Method | Path | Credential | 요구사항 |
|---|---|---|---|
| POST | `/api/fleet/sightings` | source 전용 Bearer token | vision worker가 `SiteSightingPayload`를 제출. 토큰 설정이 허용한 source/robot/map/calibration만 수용 |
| GET | `/api/fleet/sightings` | console Bearer token | 로봇별 최신 sighting, server-derived source, capture/receive age 및 1 s lease stale 상태 |
| POST | `/api/fleet/place-markers` | source 전용 Bearer token | D-564 (v1.168): vision worker가 `PlaceMarkerPayload {map_id, calibration_revision, captured_at, seq, markers[1..16]{marker_id 0–49, x, y, yaw}}`(`core_common.protocol.place_markers`)를 제출. source는 token에서 정하고 본문의 `source_id`는 422. 그 source의 `place_markers`에 없는 id 403 `PLACE_MARKER_FORBIDDEN`, `MAP_MISMATCH`·`CALIBRATION_MISMATCH`·`SIGHTING_FUTURE`·`SIGHTING_STALE`(2 s)·`SIGHTING_OUT_OF_ORDER`(source·marker별) 409. (source, marker_id)마다 최신 하나를 메모리에만 둔다. 표시·가르치기 입력만이고 지도 자세·trip·교통정리는 읽지 않는다 |
| GET | `/api/fleet/place-markers` | console Bearer token | D-564: `{markers[{marker_id, x, y, yaw, source_id, map_id, calibration_revision, captured_at, seq, received_at, age_ms, stale}], ts, lease_s: 2.0}` |
| GET | `/api/fleet/site-map` | console Bearer token 또는 viewer 이상 | 설정된 `corner_world_m` 사각형을 `map_id`별로 묶어 반환(`frame: map`, m 단위 `polygon_m`·`bounds_m`, source별 `source_id`·`calibration_revision`·`calibration_source`·`corner_marker_ids`(D-484 `field_boundary` 소스는 `null`)·`robot_ids`·`robot_markers`). 토큰은 싣지 않는다. 설정·기하가 없으면 404 `NO_SITE_MAP`. 표시 전용 |

`POST` body `SiteSightingPayload`:

```json
{
  "robot_id": "rosy_01",
  "x": 1.25,
  "y": -0.5,
  "yaw": 0.2,
  "captured_at": 1790000000.25,
  "seq": 42,
  "map_id": "lane-map:sha256:abc",
  "calibration_revision": "ceiling-1-v2",
  "processor_revision": "aruco-map-v1",
  "quality": null,
  "corner_marker_ids": [30, 31, 32, 33]
}
```

`quality`가 `null`이면 측정하지 않은 상태다. 화면 표시에만 사용하며 D-268 정책 증거로 승격하지 않는다.

D-484(v1.109)부터 `corner_marker_ids`는 선택 필드가 되고, 대신 `calibration_source`가
추가된다. 값은 `corner_markers`(기본, 코너 ArUco 마커 측정) 또는 `field_boundary`
(흰 경계 사각형+페인트 정합 orientation 캘리브레이션)다. `field_boundary` sighting은
`corner_marker_ids` 없이 `calibration_source: "field_boundary"`만 싣고, 서버 설정의
`calibration_source`까지 일치해야 한다. 과거 페이로드(마커 id만)는 그대로 유효하다.

D-587(v1.177)부터 `calibration_source`에 `approved_record`가 더해진다. Vision 추적 단계가
그 source의 승인 추적 보정(D-457, `GET /api/fleet/detections/config`의 `calibration`)으로
투영한 로봇 마커(`robot_markers`에 있는 것만)의 sighting이다. `corner_marker_ids`는 `null`,
`calibration_revision`은 그 승인 기록의 revision이다. Fleet은 그 revision이 지금 그 source의
승인 기록(같은 `map_id`)일 때만 받고, 다르거나 기록이 없으면 409 `CALIBRATION_MISMATCH`다.
이 경로는 서버 설정의 `calibration_source`와 고정 `calibration_revision`을 보지 않는다.
`x, y, yaw`는 마커 아래의 로봇 자세다(마커 높이 시차 보정, URDF 부착 위치, 로봇별
`marker_yaw_offset_deg`). D-494 지도 자세의 앵커가 된다.

```json
{
  "robot_id": "rosy_01",
  "x": 1.25,
  "y": -0.5,
  "yaw": 0.2,
  "captured_at": 1790000000.25,
  "seq": 42,
  "map_id": "lane-map:sha256:abc",
  "calibration_revision": "ceiling-1-v2",
  "processor_revision": "aruco-map-v1",
  "quality": null,
  "corner_marker_ids": null,
  "calibration_source": "field_boundary"
}
```

`captured_at`은 UTC Unix seconds다. 서버가 `source_id`와 `received_at`을 붙인다. client가
`source_id`, image/JPEG/URL 또는 policy 필드를 추가하면 422다. map/calibration/코너 설정
불일치, 1 s 초과 stale/future/out-of-order 입력은 409, 허가되지 않은 robot은 403이다.
source token은 console/robot REST/CORE Agent token과 달라야 하고 이 credential로 명령
경로를 호출할 수 없다. D-268 policy evidence 및 자동 실행은 이 API에 포함되지 않는다.

### 10.6.1 Site Fleet camera preview and rectification (D-318 Accepted)

The phone sends latest-only JPEG frames to Vision over the authenticated
`rosy-overhead/1` WSS. The Fleet browser receives a short-lived source-scoped
lease, then reads one fresh JPEG directly from Vision. Fleet does not relay image
bytes. The optional `rectification` object on lease creation is signed into the
lease, so Vision can verify and bound CPU preview work without a new camera
credential. No browser or Fleet process connects to ROS/DDS.

D-691: those authorized reads, from any Rosy product, are what asks the phone to
send. Vision answers on the same socket with `demand.wanted`. The phone keeps
sending for 30 seconds after the last read, then releases the sensor and stops
JPEG while the socket stays up. Severe phone heat stops the sensor first and
resumes after the phone cools, using the same thresholds as the screen-off
guard. A read that finds no frame, a stale frame, or
429 still asks. 401 does not. An older phone ignores `demand` and keeps sending.

| Method | Path | Credential | Result |
|---|---|---|---|
| GET | `/api/fleet/vision/sources` | Site console Bearer token, or tokenless through the site Caddy proxy from a private LAN address | Configured preview source IDs |
| POST | `/api/fleet/vision/lease` | Viewer Bearer token, or tokenless through the site Caddy proxy from a private LAN address | 60 s source-scoped lease and direct Vision frame path |
| GET | `/api/vision/sources/{source_id}/frame` | Vision preview lease Bearer token | One latest fresh JPEG; `Cache-Control: no-store`; `X-Frame-Seq`, `X-Frame-Age-Ms`, `X-Frame-Captured-At`, `X-Frame-Width`, `X-Frame-Height`, `X-Frame-Rotation-Deg`, and `X-Frame-Rectified` (`true` manual, `auto` D-484 field calibration, `map` D-560 map plane, `false` raw) describe that exact frame; `mode: "map"` requests add `X-Frame-Plane` and `X-Frame-Calibration` or answer 409 `X-Frame-State: plane-unavailable` (never the raw JPEG); `mode: "auto"` requests additionally report `X-Field-Calib` (calibration state) and, while no accepted quad exists, answer the raw JPEG with `X-Frame-State: field-unavailable` |
| GET | `/api/vision/sources/{source_id}/field-proposal` | Vision preview lease Bearer token | D-360 field-corner proposal JSON for operator review (`proposal` null when no full field is visible); own 1/s bucket per lease subject; detection runs at most once per source per second, off the event loop (readers in between get the last result, 429 while the first run is busy); `no-store`, same freshness 404s, 422 on undecodable frame. Display only, never applied to sightings |

The tokenless camera exception applies only to the two Fleet preview endpoints above. Caddy determines the immediate peer's private address and overwrites a private proxy header for those paths; it strips client-supplied copies on all other Fleet paths. Fleet and Vision are not published outside the site backend network. The issued lease is still required at Vision, source scoped, and expires after 60 seconds. Robot state, commands, enrollment, and other Fleet APIs still require their existing credentials.

D-610 AI case reads use a separate 10-second Vision lease: `GET /api/fleet/ai/case/{problem_id}` (role `ai_observer`) may return `views.rosy_cam: {frame_path, lease}` only for a fresh accepted sighting on the active map. Its observed x/y centers a preview crop, including during pose loss; it grants no control authority. The lease signs `rectification: {mode: "map"}`, `crop_map: [x, y, radius_m]` (radius 0.1–2.0 m; AI case uses 1.0 m), `crop_map_id` and `crop_revision`. The AI PC requests `frame_path` with that lease from Vision directly. The reply carries the cropped JPEG and ordinary frame headers with `X-Frame-Rectified: map-crop`; missing or mismatched map/calibration returns 409 `plane-unavailable`. Fleet does not relay or persist the Rosy Cam JPEG. Each case fetches a fresh front image while the operator's retained image stays separate.

D-618: open lane-stuck cases are readable without AI-first enrollment. Reading a case does not enroll the robot or grant command authority; proposal admission and D-577 execution checks remain unchanged.

D-610 deadlock cases appear in `/api/fleet/ai/problems` after a stable wait cycle, only when every member is AI-first. A case has `context: {cycle, avoidable}` and `members: {robot_id: {context, views}}`, with both camera views per member. A VLM `REPLAN` proposal chooses a member `robot_id`, supplies `body: {blocked_edges: [...]}` within that robot's avoidable set, and cites its chosen views plus every member's views in `evidence.members`. Fleet rechecks all members' evidence and current avoidable edges; the trip runner repeats its admission checks before switching routes. Closed or changed cycles invalidate the published case.

#### Fleet → AI PC → Fleet → CORE 판단 교환 규약 (D-577 / D-610 / D-618)

기존 API의 비동기 요청·응답 구조를 사용한다. Fleet이 열린 문제를 게시하고 AI PC가 조회한다. AI PC의 HTTP 서버나 로봇 직접 명령 경로를 추가하지 않는다.

| 단계 | 기존 API / 필드 | 완료 조건 |
|---|---|---|
| Fleet 판단 요청 | `GET /api/fleet/ai/problems`의 `problems[] {problem_id, kind, robot_id}` | 열린 문제 ID가 요청의 상관 ID다. 재조회·재판단은 같은 ID를 사용한다. |
| 입력 획득 | `GET /api/fleet/ai/case/{problem_id}` | `context`, `history`, `views.front`, `views.rosy_cam`을 읽는다. 닫힌 문제는 404 `AI_CASE_NOT_OPEN`, 다른 역할의 사례 조회는 403 `AI_CASE_FORBIDDEN`. |
| AI 판단 응답 | `POST /api/fleet/ai/proposals` | `robot_id`, `stuck_id`(요청 ID), `decision`, `reason`, `confidence`, `source`, `observed_at`, `ttl_s`, `evidence`, `body`로 응답한다. |
| Fleet 접수 | 위 POST의 `state` | `queued`는 접수만 뜻한다. `absent`, `owner_busy`, `robot_not_acting`은 실행 대기열에 넣지 않는다. |
| Fleet 판정·CORE 결과 | `GET /api/fleet/ai`의 `proposals[]`, `chain.robots[].last_answer`; `GET /api/fleet/line-stuck` | `robot_id` + `stuck_id`로 묶고 `source`, `decision`, `verdict`, `outcome`을 함께 보여준다. `forwarded`는 Fleet 실행 검사를 통과한 전달 예정 상태다. 실제 CORE 전달·수락은 `outcome`과 명령 기록으로 확인하며 물리적 성공은 별도 확인한다. |

`captured_at`, `observed_at`, `judged_at`은 UTC Unix seconds이며 `age_s`, `ttl_s`는 초 단위 기간이다. VLM 응답의 `source`는 `vlm:<model>@<digest12>:<prompt>`이며 `evidence.seen`은 영상에서 판단한 내용, `reason`은 짧은 사유 코드다. `evidence.views`의 두 영상은 각각 `frame_id`, `captured_at`, `age_s`, `sha256`으로 추적한다. JPEG와 Vision lease는 응답 기록에 복사하지 않는다. 모델 이름만 같아도 digest가 다르면 동일 판단자로 간주하지 않는다.

현재 Qwen 어댑터는 두 영상이 모두 있어야 판단하며 모델 호출 제한은 10 s, 제안 TTL은 12 s다. 누락 영상·모델 부재·시간 초과·잘못된 JSON·허용 목록 밖 단어는 제안을 보내지 않고 기존 규칙으로 돌아간다. Fleet은 실행 시점의 문제 ID, TTL, 원인별 허용 단어, 교차로·위치·뒤쪽 차량·trip 권한을 다시 검사한다. CORE는 현재 센서, 차체 여유, 후방 경로와 사각, 충돌 정지·watchdog을 재검사한다. AI-first 전용 영상 신선도 제한은 별도로 적용하며 사례 조회만으로 이 모드를 활성화하지 않는다.

예시의 `queued`와 최종 `verdict`를 구분한다. 아래는 계약 시험용 상황이며 실제 현장 모델 판단 결과는 별도 증거로 기록한다.

Qwen 프롬프트 `d618-v1`은 `evidence.seen`에 실제 보이는 차선 경계·벽/코너·장애물/빈 공간과 불확실한 부분을 구체적으로 설명하도록 요구한다. 입력 `context.cause`를 영상 정답으로 취급하거나 카메라 이름만 반복하지 않는다. 이 요구는 프롬프트 계약이며 기하학적 정확성을 자동 보증하지 않는다. 모델 설명과 실제 영상의 일치 여부는 예시 검토와 현장 수용에서 확인한다.

v1.202 / D-619: `evidence.assessment`를 선택 추가한다. 공통 계약은 `core_common.protocol.situation`이며 `version: situation-v1`, `domain: mobility|manipulation`, `type: geometry|obstruction|visibility_limited|target_missing|target_misaligned|resource_conflict|action_unconfirmed|unknown`, `direction: hold|reobserve|recover|replan|human_review|continue`, `observations: [{source, frame_id, description}]`, `uncertainties: [text]`, `verification: unverified`다. 현재 lane-stuck API에는 mobility만 허용한다. 로봇암은 같은 판단 형식을 사용할 수 있지만 이번 변경은 로봇암 명령 API나 실행 capability를 추가하지 않는다.

각 observation은 `evidence.views`의 실제 source/frame_id와 일치해야 한다. 모든 공급 영상에 각각 설명이 있어야 하며 각 설명·불확실성은 300자 이내, 관찰·불확실성 목록은 각각 최대 8개다. 모델이 검증 완료를 자칭하거나 영상 ID를 바꾸면 Fleet은 422로 거절한다. 이전 assessment 없는 proposal은 호환되며 기존 D-577 실행 검사를 그대로 따른다. Qwen `d619-v1`은 이 구조를 반드시 생성해야 하며 누락·오류면 제안을 폐기하고 기존 규칙을 사용한다.

`direction`은 처리 분류다. `reobserve`는 새 관측 후 같은 문제를 재판단, `hold`는 현재 작업 보류, `recover`는 장치별 허용 복구 후보, `replan`은 현재 자원·경로·Skill 후보 재검토, `human_review`는 독립 검토, `continue`는 기존 작업 지속 후보다. 어떤 방향도 속도·회전·조인트 명령·3D 자세를 직접 만들지 않는다. 이동 로봇은 기존 decision/D-577/CORE 검사, 로봇암은 기존 capability·Skill allowlist·보정 frame·실행 receipt 경계에 연결해야 한다.

영상 설명의 정확성은 모델 confidence와 별개다. 모델 평가 상태는 항상 unverified이며 기존 incident review/episode/outcome으로 별도 센서 대조·독립 검토·사람 정답·실제 완료를 기록한다. 오버레이는 다른 알고리즘의 출력이며 독립 거리·정답 증거가 아니다. 신규 프롬프트와 이전 프롬프트 결과를 동일 프로필로 비교하지 않는다. 새 사례 재생은 실제 모델·계약 fake·신선한 운영 case를 구분하고 응답 시간과 판단 불확실성을 함께 보여준다.

`d619-v5` case 입력은 원본 front frame(`overlay=false`, 실제 raw sequence)을 요구한다. 원본이 없으면 VLM은 보류하며 운영자 retained preview를 덮어쓰지 않는다. front view에는 overlay/width/height, Rosy Cam lease view에는 target_robot_id/map_id/calibration_revision/crop_map 출처가 추가된다. AI PC가 Vision JPEG로 교체한 뒤에도 이 출처는 유지한다. case context는 `state_age_s`와 `clearance_at_open_m {front_clearance_m, rear_clearance_m, turn_clearance_m, rear_blind_m}`을 포함한다. 누락값은 null이며 영상 추정값으로 채우지 않는다. `clearance_at_open_m`는 막힘 발생 당시 값이다. 현재 state age가 작아도 이 거리가 새 측정값이 되지 않는다.

로봇 문의는 기존 사건 스트림을 쓴다. CORE의 `nav.line_stuck_opened`/`nav.line_stuck_asked`에 선택 `inquiry {version:"situation-inquiry-v1", domain:"mobility", task:"lane_follow_recovery", problem_id, goal, requested_output:"assessment_and_direction", attempts, observations:{cause, detail, lane_visible, front_clear, scan_age_s, geometry_known, rear_state, preview_seq, trail_m, trail_age_s}, execution_authority:"CORE_recheck_required"}`가 온다. problem_id는 그 stuck_id이며 신원은 인증된 FleetAgent 연결에서 정한다. Fleet은 발생 문의와 사건의 원래 ts를 case context의 `robot_inquiry`/`inquiry_observed_at`로 전달한다. 관찰은 그 사건 시점의 snapshot이며 새 scan 증거가 아니다. 이전 로봇은 두 필드가 null이다. 로봇 문의 → Fleet case → AI proposal/assessment → Fleet verdict → 기존 `POST /api/v1/line-follow/stuck/decision` → CORE 사건/outcome을 같은 stuck_id로 추적한다. OFF/비상정지 상태에서 문의를 만들기 위해 추종 모드를 강제로 무장하지 않으며, 문의 자체가 새로운 이동 권한을 주지 않는다.

`inquiry_observed_at`은 기존 사건의 ISO-8601 UTC 문자열이다. VLM evidence에는 실제 `model_options`도 기록하고 프로필은 `<model>@<digest12>:<prompt_id>:<options_sha8>`로 설정을 구분한다. exact prompt와 options가 같아도 모델 설명의 정확성은 독립 검증이 필요하다.

v5는 작업 보고가 영상 해석을 왜곡하지 않도록 영상별 개별 관찰 뒤 작업 맥락으로 판단한다. 전체 호출이 하나의 10초 제한을 공유하며 하나라도 실패하면 proposal을 만들지 않는다. `evidence.prompt.calls[]`에 모든 실제 호출의 text/model_options와 관찰 단계의 robot_id/view를 기록한다. 최종 `assessment.observations`는 원본 프레임별 개별 관찰을 그대로 연결한다. 2초/3초 신선도 admission은 유지하며, 판단의 반환과 명령 수락은 별개다.

모델에는 문제 종류·목표 로봇·센서/지도 상태·최근 실제 처리 결과·영상 메타데이터를 전달한다. 임의 operator_report/requested_outcome을 포함한 요청은 사용자 보고·가설로 명시하며 측정 사실로 승인하지 않는다. 최근 history는 최대 3건만 입력하고 맥락 JSON이 12,000자 또는 전체 프롬프트가 20,000자를 넘으면 VLM 판단을 보류한다. JSON을 중간에서 잘라 보내지 않는다. Qwen 응답은 JSON Schema로 필수 assessment를 제한한다. proposal evidence의 `prompt {id, sha256, text}`는 모델이 받은 정확한 요청문이고 `inference_s`는 실제 모델 호출 이후 파싱까지의 측정 시간이다. JPEG·lease·credential은 prompt 기록에서 제외한다. 기존 API의 권한과 CORE 실행 검사는 그대로 유지한다.

| 입력 상황 | AI 응답 예 | Fleet 최종 결과 예 | 운영자가 받을 내용 |
|---|---|---|---|
| 벽 앞 차선 상실, 뒤쪽 통로가 보임 | `BACK_AND_RETRY`, `reason: rear_clear`, `evidence.seen: rear corridor visible` | D-577 후진 전제 충족 시 `forwarded`, CORE 응답 후 `outcome` 기록 | 판단 영상 ID·모델·근거와 CORE 수락 여부 |
| 같은 영상이지만 실제 뒤쪽 센서가 막힘 | `BACK_AND_RETRY` | `rear_blocked` 등 검사 사유로 거절하고 기존 규칙 적용 | 모델 제안과 센서 때문에 실행하지 않은 이유 |
| 영상 누락 또는 지원하지 않는 `REALIGN` 응답 | 제안 없음 | 기존 규칙 유지; 잘못된 단어를 API에 직접 보내면 422 | 영상 판단 미완료, 자동 명령 성공으로 표시하지 않음 |

API 계약 시험은 `operations/situation/test/test_ai_case_flow.py`, `test_vlm.py`, `operations/fleet/test/test_ai_facts.py`, `test_ai_first.py`에서 사례 조회, 모델 응답, 역할·접수·만료·실행 검사를 각각 검증한다. 모델 대신 시험 응답을 사용한 결과와 실제 Qwen 추론 결과를 구분한다.

Lease request body accepts `{ "source_id": "ceiling-north" }` for the original
JPEG or an optional `rectification` object:

```json
{
  "source_id": "ceiling-north",
  "rectification": {
    "fx": 1.2, "fy": 1.2, "cx": 0.5, "cy": 0.5,
    "k1": -0.18, "k2": 0.03, "p1": 0.0, "p2": 0.0, "k3": 0.0,
    "corners": [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9]],
    "output_aspect": 1.0
  }
}
```

Intrinsics (`fx`, `fy`) are normalized focal lengths in `[0.25, 4]`; principal
point (`cx`, `cy`) is normalized to `[0, 1]`. Radial coefficients (`k1`, `k2`,
`k3`) are bounded to `[-1, 1]`, tangential (`p1`, `p2`) to `[-0.5, 0.5]`.
`corners` is four normalized `[x,y]` pairs in clockwise top-left, top-right,
bottom-right, bottom-left order; crossed, degenerate, non-finite, or out-of-frame
polygons are rejected. `output_aspect` is automatic `0` or `[0.25, 4]`; output
dimensions are capped at 1920×1080. The Vision service keeps its raw latest JPEG
for ArUco/sighting processing. OpenCV correction is applied only to the returned
preview copy. Existing source/principal limit of 5 frame reads per second still
applies. Invalid settings return 422; missing or stale images remain unavailable.

D-484(v1.109)부터 `rectification`에 `mode: "manual" | "auto"`가 추가됐다(기본
`manual`, 과거 리스는 그대로 유효). `auto`면 이 문서의 `corners`·왜곡 계수는 무시되고,
Vision worker가 수용한 필드 경계 사각형으로 평면 보정한다(렌즈 왜곡값도 함께 안 쓴다).
수용된 사각형이 없으면 원본 JPEG와 `X-Frame-State: field-unavailable`을 돌려준다.
자동 보정은 미리보기 전용이며 원본 프레임·sighting 경로를 바꾸지 않는다.

D-560(v1.167)부터 `rectification`에 `{"mode": "map"}`이 추가됐다. `map`은 다른 필드를
받지 않는다(있으면 lease 생성 422). Vision은 추적이 Fleet `/api/fleet/detections/config`에서
이미 읽는 승인 보정 기록(D-457 `map_to_image`, `image`, `track_bounds_m`, `lens`,
`calibration_revision`)으로 최신 원본을 지도 평면에 편다. 그 기록은 추적 worker가 넘기므로
그 source에 추적(`rosy-vision` `--track`)이 켜져 있어야 평면이 나온다. 꺼져 있으면 늘 409다.

- 영역: `track_bounds_m`에 여유 `0.15 m`를 더한 직사각형. 지도 `+x`가 오른쪽, `+y`가 위.
- 축척: `400 px/m`. 긴 변이 1920 px를 넘으면 그 안으로 줄인다(소수 넷째 자리에서 내림).
- D-636: 시야 밖·지평선 반대편·원본의 bilinear 보간 경계는 어두운 hatch(BGR 24/40)로 표시한다. JPEG 품질 88.
- 응답 헤더: `X-Frame-Rectified: map`, `X-Frame-Plane: <min_x>,<min_y>,<max_x>,<max_y>,<px_per_m>`
  (미터, 여유 포함, 소수 넷째 자리; `px_per_m`은 줄인 뒤 값), `X-Frame-Calibration: <calibration_revision>`.
  D-636 `X-Frame-Observed-Fraction: <0..1>`은 이 응답 plane 또는 crop에서 원본의 유효 픽셀로
  채워진 비율이다. 물리적 가림·교정 오차·로봇 위치 신뢰도를 뜻하지 않는다. 헤더가 없는 구버전은
  관측 비율 미확인이다. 알려진 기준 지도는 카메라 밖에서도 별도로 표시할 수 있다.
  픽셀 수를 반올림한 뒤 `max_x = min_x + 폭 / px_per_m`, `min_y = max_y − 높이 / px_per_m`로 다시 정하므로
  이 사각형은 영상 크기 / `px_per_m`와 같다.
  `X-Frame-Width`·`X-Frame-Height`는 평면 영상 크기이고 `X-Frame-Rotation-Deg`는 `0`이다.
  `X-Frame-Seq`·`X-Frame-Age-Ms`·`X-Frame-Captured-At`·`X-Source-Lens`는 원본 프레임 그대로다.
- 픽셀↔지도: 캔버스 좌표(픽셀 모서리 기준) `(u, v)`는 `x = min_x + u / px_per_m`,
  `y = max_y − v / px_per_m`이다.
- 못 펼 때: 승인 기록이 없거나 source·map·렌즈(`X-Source-Lens`와 같은 비교)·영상 비율(1 % 초과)이
  기록과 다르면 `409`, `X-Frame-State: plane-unavailable`, 본문 `map plane unavailable`. 원본으로
  대신하지 않는다. 오래된 프레임은 다른 모드와 같은 404다.
- 펴기는 이벤트 루프 밖에서 프레임·revision마다 한 번 하고, 같은 프레임의 다른 읽기는 그 결과를 쓴다.
  평면 영상은 표시·좌표 확인용 사본이며 원본 프레임·추적·sighting을 바꾸지 않는다(D-560 7).

Fleet stores operator drafts per source in the current browser only. Until the
camera intrinsics and floor plane have been measured and reviewed, this view is a
visual adjustment and not calibrated site evidence. Rectified pixels do not
change sightings, navigation, mission acceptance, or robot motion.

## 10.6.2 Site Fleet policy-eligible evidence (D-268 Proposed)

작업 **발의 자격** 증거의 제출·보관 계약이다(승격 사다리 1단계). sighting(§10.6)은 표시·대조
자료이고 목표 성공 증거는 Mission 원장의 별개 면이다 — 어느 쪽도 이 경로를 대신하지 않는다.

| Method | Path | Auth | 설명 |
|---|---|---|---|
| POST | `/api/fleet/policy-evidence` | 정책 증거 source Bearer 토큰 | `PolicyEvidencePayload` 제출. 서버가 토큰에서 출처를 결정하고 클라이언트 제시 출처는 신뢰하지 않는다 |
| GET | `/api/fleet/policy-evidence/latest` | Viewer | 최근 증거 기록(최대 50건, `payload` 포함) |

`PolicyEvidencePayload`(`core_common.protocol.policy_evidence`): `evidence_id`(≤160, 식별자
규칙), `asset_kind`(robot·workcell·object), `asset_id`, `task_kind`(v1 닫힌 집합 `navigate`),
`captured_at`, `map_id`·`calibration_revision`·`model_revision`(공백 불가), `observation`
(`kind`만 담는 닫힌 봉투). 클라이언트가 `source`·`source_id`·`token`·`policy`·`satisfied`를
보내면 422다(`satisfied`는 목표 판정 전용 어휘).

제출 검증 순서: 출처(401 `EVIDENCE_SOURCE_UNKNOWN`, 폐기 토큰 포함) → transit
(`captured_at`→수신 0~300 ms) → 출처 허용의 `task_kind`·`asset_kind`·revision 삼종 →
관측 등록부. 수용·거절 모두 SQLite에 기록으로 저장되고 200에
`{evidence_id, source_id, payload, received_at, outcome, reason}`을 반환한다. `reason`은
`EVIDENCE_TRANSIT_LATE`·`EVIDENCE_REVISION_MISMATCH`·`EVIDENCE_TASK_KIND_NOT_REGISTERED`·
`EVIDENCE_ASSET_NOT_PERMITTED`·`EVIDENCE_OBSERVATION_KIND_UNKNOWN` 중 하나다. **v1 관측
등록부는 비어 있어 잘 구성된 제출도 전부 `EVIDENCE_OBSERVATION_KIND_UNKNOWN`으로
거절된다(fail-closed)** — 첫 관측 종류는 실 사용 사례와 함께 등록된다. 같은 `evidence_id`의
같은 내용 재전송은 멱등(동일 기록 반환), 다른 내용은 409 `EVIDENCE_REPLAY`.

**발의 binding.** `source="policy"` 작업 제출은 `evidence`에 정확히 `{"evidence_id": ...}`
참조를 담아야 한다(다른 모양은 400 `INVALID_EVIDENCE_REFERENCE`, 작업 미생성). admission은
저장 기록의 `outcome`·`task_kind`·`asset`·수신 시각 age(사이트 설정 `max_age_s`, 미설정 시
거절)를 대조해 실패 사유를 작업 HOLD 이유로 남긴다: `EVIDENCE_NOT_CONFIGURED`(서비스에
증거 저장이 연결되지 않음)·`EVIDENCE_NOT_FOUND`·`EVIDENCE_ASSET_MISMATCH`·`EVIDENCE_STALE`
또는 제출 거절 사유의 전달. admission을 통과해도 `POLICY_DISPATCH_ENABLED`가 False인 한
`HOLD(POLICY_NOT_ACCEPTED)`에 머문다 — 이 계약은 자동 실행을 열지 않는다.


## 10.6.1 Site Fleet marker-priority tracking (D-457)

지도 표시·대조 전용. source 설정이 있는 Fleet에 등록된다. 기존 sighting 계약은 유지한다.
Vision `vision --track`은 모서리 마커 보정 우선, 없으면 승인 사각형·차선 맞춤 보정으로 투영한다.
로봇 마커가 보이면 그것을 우선하고 없으면 익명 배경 blob으로 폴백한다.
`robot_markers`는 `robot_ids`의 중복 없는 부분집합이며 빈 대응도 허용한다.
`robot_ids: enrolled`(D-580, v1.175)이면 대상은 Fleet의 살아 있는 명단이고, `robot_markers`는 예외만 적는다(명단에 없는 로봇은 무시). 나머지 로봇의 마커는 로봇 번호(`rosy_NN`의 NN, 40–49)이며 모서리·장소 마커·예외 값과 겹치면 배정하지 않는다.

| Method | Path | Credential | 내용 |
|---|---|---|---|
| POST | `/api/fleet/detections` | source Bearer | `OverheadDetectionsPayload` 제출. source/map/revision·1 s lease 검사. v1.186(D-600): 선택 `unknown_floor` `[{x, y, radius_m}]`(최대 16, `OK`일 때만, 비면 생략) — 배경이 아직 못 본 바닥 v1.189(D-589): 선택 필드 `tuning` `{state, score, ev, locked}`(없으면 JSON에서 빠짐, 추가 키 거부). 이 Fleet 이전 판은 `tuning`이 실린 payload를 422로 거부한다. Vision은 그 422를 받으면 같은 payload를 `tuning` 없이 한 번 다시 보내고, 그 프로세스에서는 다시 싣지 않는다 |
| GET | `/api/fleet/detections/config` | source Bearer | 해당 source의 승인 calibration 또는 null, relearn_seq. v1.130(D-472): `identity_challenge` `{request_id, color, not_before, not_after}`(Fleet 벽시계, 창 ≤ 6 s) 또는 null — 이 source가 보는 로봇에 열린 LED 확인 요청. v1.175(D-580): `robot_markers` `{robot_id: marker_id}` — 이 source의 현재 로봇 마커(`robot_ids: enrolled` source는 살아 있는 명단, 마커 = YAML 예외 또는 로봇 번호 40–49). Vision은 이 값을 YAML보다 먼저 쓴다. v1.185(D-596): `identity_challenges` — 이 source의 열린 LED 확인 요청 전부(색마다 하나, 최대 2, 같은 모양). `identity_challenge`는 그중 가장 오래된 것(이전 Vision 호환). Vision은 열린 창이 끝날 때까지 배경 학습·장면 변경 재학습·유령 치유를 멈춘다. v1.186(D-600): `occupied` `[{robot_id\|null, x, y, radius_m, basis:"marker"\|"sighting"\|"operator_pin"\|"map_pose"\|"own_pose"\|"blob"}]` — Vision 배경 학습이 배우지 않을 로봇 자리(지도 m). 로봇마다 마커 > D-494 지도 자세(반경 + odom 다리, 최대 0.3 m) > LOCALIZED 자기 자세, 그리고 배정 없는 마커와 마지막 OK 프레임(60 s 이내)의 익명 blob |
| POST | `/api/fleet/detections/identity` | source Bearer | D-472 (v1.130). 한 `identity_challenge`에 대한 Vision 판정: `{source_id, map_id, request_id, processor_revision, state:"matched"\|"ambiguous", reason?:"none"\|"multiple"\|"frames_missing"\|"stale"\|"calibration_changed", x?, y?, captured_at?, calibration_revision?, evidence}`. 숫자만, 영상 바이트 없음(D-136). 다른 키 422. `matched`는 창 안 `captured_at`, source의 현재 map·보정 revision, 최신 탐지에서 0.25 m 안의 이어지는 익명 blob이 있고 0.30 m 안에 다른 blob이 없을 때만 확인 트랙이 된다. 열린 요청이 아니면 409 `IDENTIFY_NOT_PENDING`, 묻지 않은 source 409 `IDENTIFY_SOURCE_MISMATCH`. 응답 `{robot_id, state:"CONFIRMED"\|"UNKNOWN", reason?}` |
| GET | `/api/fleet/tracking` | viewer 이상 | sources 상태·fps(출처마다 `calibration_drift` — 승인 교정과 새 맞춤 제안의 비교 판정, 없으면 null), robots 대조, unknown 위치. v1.186(D-600): source 행 `unknown_floor` `[{x, y, radius_m}]`(신선한 페이로드, 아니면 `[]`) v1.189(D-589): `sources[].tuning` `{state, score, ev, locked}` 또는 null — Vision이 마지막으로 보낸 그 카메라의 인식 맞춤 상태(lease 안에서만). `state` `off`(폰 스위치 꺼짐)·`waiting`·`tuning`(맞추는 동안 그 source의 검출은 `LEARNING`)·`locked`·`paused`(폰 열)·`unsupported`(연결 15 s 동안 `camera_state`가 없는 옛 앱), `score` 0–1 인식 점수(표시용 측정값, 맞춤 판단에 쓰지 않음) 또는 null(미측정), `ev` 적용된 노출 보정(실제 EV, 소수) 또는 null, `locked` AE 잠금. 사이트 `auto_tune: false`인 source는 `tuning`을 보내지 않아 null. 표시 전용 |
| GET | `/api/fleet/tracking/identity` | viewer 이상 | D-472 (v1.130), 읽기 전용. v1.185(D-596): `pendings[]`(열린 요청 전부, 각 `trigger`), `pending`은 가장 오래된 것, `last.trigger`, `config.auto_min_interval_s`. `{ts, use:"observation-only", pending:{robot_id, request_id, color, sources, not_before, not_after}\|null, robots:[{robot_id, state:"CONFIRMED"\|"UNKNOWN", reason, x, y, yaw:null, age_s, source_id, map_id, calibration_revision, confirmed_at, use, last}], config:{window_s, identity_ttl_s, overlap_m, auto_request}}`. 확인 트랙은 트랙 손실(`track_lost_s` 1 s)·0.30 m 겹침·map/보정 revision 변경·`identity_ttl_s` 경과 중 하나로 UNKNOWN이 된다(addendum 4). D-511 차로 준수 입력과 콘솔 표시 전용이며 `map-pose` 중재·trip·initialpose·경로·명령에 쓰지 않는다(addendum 3) |
| POST | `/api/fleet/tracking/relearn` | operator | `{source_id}`의 배경 재학습 번호 증가. v1.186(D-600): 응답 `{source_id, relearn_seq, occupied, unlocated:[robot_id]}` — 로봇은 그대로 두고, `occupied` 자리는 배우지 않으며, `unlocated` 로봇은 배경이 될 수 있다 |
| GET | `/api/fleet/calibrations` | viewer 이상 | 승인 기록 목록과 `use: display-only` |
| POST | `/api/fleet/robots/{robot_id}/identify` | named `operator` (D-540 9, v1.161) | D-472, v1.130; v1.185(D-596). 본문 생략 또는 `{color?:"blue"\|"amber"}`(생략 = 파랑, 파랑이 그 로봇을 보는 source에서 쓰이는 중이면 주황. 주황은 주의(caution) 램프와 같은 점멸이라 자동 요청은 파랑만 쓴다). 자동 요청은 CORE에 `?quiet=true`(호출음 없음, 이전 payload는 이 값을 무시하고 소리를 낸다), 마커가 계속 안 보이는 로봇은 30 s → 2 min → 5 min 간격. Vision의 `matched`는 그 로봇의 예상 자리 안이어야 하고(v1.191: Fleet 지도 자세, 반경 `auto_near_m` + 앵커 뒤 odom 1 m마다 0.15 m·최대 1.0 m; 지도 자세가 없으면 마지막 천장 마커 자리·`auto_near_m`; 아니면 UNKNOWN `far_from_robot`; v1.193부터 파랑 점멸 판정은 예상 자리 밖에서도 받는다, 주황과 정색 표시는 아님), 예상 자리를 모르는 주황 요청은 UNKNOWN `no_prediction`. 신원 미확인 등록 로봇에 서 있든 움직이든(로봇을 움직이지 않는다) CORE `POST /host/lamp/identify`를 전달하고 그 로봇을 보는 Vision source에 6 s 창을 연다. 동시에 source마다 색 하나씩(최대 2대): 같은 로봇이 이미 확인 중이거나 요청한 색이 쓰이는 중이거나 두 색 모두 쓰이는 중이면 창+2 s 동안 409 `IDENTIFY_BUSY`, 확인된 로봇 409 `IDENTIFY_ALREADY_CONFIRMED`, 로봇 거절(또는 쓰이는 색으로 답함) 502 `IDENTIFY_NOT_ACCEPTED`. 로봇이 주의 표시 중(차선 HOLD, 도킹 실패)이면 409 `IDENTIFY_ROBOT_CAUTION`(v1.191, 자동 요청은 묻지 않는다). v1.195: 요청 뒤 창이 열린 동안 Fleet은 로봇 CORE `GET /host/lamp/identify/{request_id}`를 1 s마다 묻고, `refused`면 창을 닫고 UNKNOWN `lamp_refused`(`last.lamp_reason`에 로봇의 이유)로 남긴다; 404(이전 CORE)면 그 요청은 다시 묻지 않는다. `IDENTIFY_NOT_MOVING`은 없어졌다. 응답 `{robot_id, request_id, color, not_after, sources, state:"pending_visual_confirmation", trigger:"operator"}`는 카메라 신원 확정이 아니다. 사이트 YAML `identity.auto_request`(기본 true, v1.185)면 Fleet이 스스로 요청한다: 마커를 본 로봇의 마커가 `auto_marker_missing_s`(3 s) 넘게 안 보이고 마지막 마커 자리(없으면 로봇 지도 자세) `auto_near_m`(0.5 m) 안에 익명 blob이 있을 때(`marker_missing`), 겹침으로 풀린 확인 트랙 근처 blob이 다시 혼자일 때(`split`), 로봇 자세가 odom 원점으로 뛴 뒤 익명 blob이 있을 때(`odom_reset`). 로봇마다 `auto_min_interval_s`(30 s)에 한 번, 상태가 신선하고 `safety.estop`이 정확히 false일 때만 |
| POST | `/api/fleet/robots/{robot_id}/power` | named `operator` (D-540 9) | D-440 6 (v1.222): `{action: sleep\|wake}`, 다른 값·다른 필드는 422. `sleep` 은 그 로봇의 `POST /api/v1/power/mode {"mode":"STANDBY"}`, `wake` 는 `POST /api/v1/power/wake` 로 로봇 자격으로 그대로 보낸다 — CORE 인터록(IDLE 이 아닌 로봇은 ACTIVE 유지)은 CORE 가 판정하므로, 거절된 절전은 200 과 `result.mode: "ACTIVE"` 로 돌아온다. 200 `{robot_id, actor_id, result}`(`result` 는 CORE 의 `PowerStatus`), 모르는 로봇 404 `UNKNOWN_ROBOT`, 전송 실패 502. 전원 상태는 `GET /api/fleet/state` 행의 `state.power` 그대로다 |
| POST | `/api/fleet/calibrations` | operator | source_id/map_id, map_to_image(9), image(width,height), track_bounds_m, fit_score, lens 또는 null, frame_seq 또는 null을 승인·영속 기록 |
| DELETE | `/api/fleet/calibrations/{source_id}` | operator | 승인 기록 철회·감사 |
| GET | `/api/fleet/start-points` | viewer 이상 | `{start_points, persistent}`. 저장한 무마커 시작 위치·방향, `use: reference-only`; 주행·로봇 위치 증거가 아니다 |
| PUT | `/api/fleet/start-points/{source_id}` | named `operator` (D-540 9, v1.161) | `{map_id, calibration_revision, expected_revision: string 또는 null, x, y, yaw}`. 승인된 paint-fit 지도 내부 좌표(m), yaw(rad, -π~π). 새 기록은 expected_revision null, 수정은 읽은 revision. 응답은 저장 기록 |
| DELETE | `/api/fleet/start-points/{source_id}?expected_revision=...` | named `operator` (D-540 9, v1.161) | 읽은 revision과 일치할 때만 삭제. 보정이 철회돼도 기록 삭제 가능 |

무마커 시작점(v1.103)은 `source_id`, `map_id`, `calibration_revision`, `revision`, `x`, `y`, `yaw`, `saved_by`, `saved_at`(Unix초), `valid`, `use: reference-only`를 반환한다. 승인된 보정이 현재 source/map과 일치하고 기록 revision과 같을 때만 valid=true다. 좌표는 지도 원점을 바꾸지 않으며, 저장은 goal·initialpose·로봇 신원 대응·주행 승인에 쓰지 않는다. 시작점에 마커는 요구하지 않는다. SQLite는 보정 DB와 같은 writable 데이터 디렉터리의 start-points.sqlite3에 저장한다. 보정이 메모리 전용이면 persistent=false이며 서버 재시작 시 사라진다. 미등록 source는 404 UNKNOWN_SOURCE, 보정 미승인은 409 CALIBRATION_REQUIRED, 지도 불일치는 409 MAP_MISMATCH, 보정 변경은 409 CALIBRATION_CHANGED, 동시 편집은 409 START_POINT_CHANGED, 범위 밖은 400 START_POINT_OUT_OF_BOUNDS다. bool/NaN/Infinity·추가 필드는 거절한다.

| Method | Path | 권한 | 내용 |
|---|---|---|---|
| GET | `/api/fleet/tethers` | viewer 이상 | `{watch_age_s, tethers: [{robot_id, anchor_xy: [x, y], radius_m, set_by, watch}]}`. `watch_age_s`: 감시 루프 마지막 틱 나이(null: 틱 없음; 2 s 넘으면 루프가 멈춘 것). `watch`(v1.153, D-526)는 아직 틱이 없으면 null, 아니면 `{state: watching\|tripped, trip: null\|tether_radius\|tether_turn\|tether_pose_stale, distance_m, turn_deg, pose_age_s, stop_sent, stop_error, stop_failures, tick_age_s}` |
| POST | `/api/fleet/robots/{robot_id}/tether` | named operator | `{anchor_xy: [x, y], radius_m}`. 같은 본문을 다시 보내도 결과가 같다. 응답은 저장 행. 보낼 때마다 그 로봇의 감시를 새로 시작한다(트립 해제, 회전 0) |
| DELETE | `/api/fleet/robots/{robot_id}/tether` | named operator | 테더를 지운다. `{robot_id, cleared}`, 없던 테더도 200 |

테더(v1.140, D-512 개정 1의 표시·설정 쪽)는 로봇별 map 프레임 원(anchor_xy 각 −1000~1000 m, 0 < radius_m ≤ 50)이다. Fleet 지도는 원과 기준점을 그리고, 로봇 map pose가 원 밖이면 주의 색, 감시가 정지를 내렸으면 위험 색으로 바꾼다. D-526(v1.156): Fleet tether 감시가 0.5 s마다 테더가 있는 로봇의 지도 자세(`GET /api/fleet/state`와 같은 상태 pose, `localization.pose_frame`이 `odom`이면 자세 없음)를 읽는다. 기준점 거리 > `radius_m` + 0.15 m(`tether_radius`), 선언 뒤 펼친 누적 yaw의 절댓값 > 405°(`tether_turn`), 신선한 지도 자세 없음 2 s 초과(`tether_pose_stale`) 가운데 하나면 그 로봇에 기존 CORE E-Stop(`POST /api/v1/safety/stop`, 전체 정지와 같은 로봇 클라이언트)을 보내고 열린 trip을 `tether_trip`으로 끝낸다. 트립은 다시 POST하거나 DELETE할 때까지 래치되고 정지는 CORE가 답할 때까지 틱마다 다시 보낸다. 되돌아가기는 하지 않는다(운영자 몫). CORE E-Stop 해제는 기존 관리자 경로 그대로다. 메모리에만 두어 Fleet 재시작 때 사라지고, 로스터에서 빠진 로봇의 테더는 목록에서 지운다. 미등록 로봇은 404 UNKNOWN_ROBOT, bool·Infinity·범위 밖·추가 필드는 422다. JSON이 아닌 NaN도 저장 전에 거절된다(현재 앱 공통 검증 응답이 NaN을 담지 못해 500). 지도 궤적(지나온 길)은 브라우저가 기존 `GET /api/fleet/state` pose로 모으며(최근 120 s, 600점, 1 cm 이상 이동 시, `localization.pose_frame`이 `odom`인 자세는 넣지 않는다) 새 필드가 없다.


`OverheadDetectionsPayload`는 source_id/map_id/calibration_revision/processor_revision/captured_at/seq/status,
`detections[{x,y,footprint_m,score,marker_id?}]`(최대 16)를 싣는다. x/y는 map metres,
captured_at은 Vision 수신 시각 기반 Unix seconds다. status는 OK/LEARNING/CALIBRATION_REQUIRED/SCENE_CHANGED.
OK 외에는 검출이 비어 있고 CALIBRATION_REQUIRED에서만 calibration_revision이 null이다.
marker_id는 음이 아닌 strict 정수·프레임 내 유일이며 익명 검출에서는 생략한다. robot_id·영상은 싣지 않는다.
공유 스키마는 `contracts/foundation/core_common/protocol/overhead_detections.py`, 벡터는
`test/fixtures/protocol/overhead-detections.v1.json`이다. envelope protocol_version 1.0은 그대로다.

Fleet은 인증된 source의 marker 대응으로 `MARKER` 이름을 확정하고 없으면 신선한 같은-map pose와 익명 검출을 대조한다.
robots 상태는 MARKER/MATCHED/NO_DETECTION/NO_POSE/CAMERA_UNAVAILABLE이고 camera·pose·offset_m은 없으면 null이다.
마커 관측은 pose 없이도 표시하며 익명 이름은 odom으로 추측하지 않는다. 남은 검출은 unknown이다.
unknown 행은 `{source_id,x,y,footprint_m,score,marker_id}`이다. 익명 검출은 `marker_id: null`, 배정 로봇이 없는 마커 검출(D-575, Vision은 D-562 로봇 범위 40–49만 보냄)은 그 id를 싣고 발자국 안의 익명 검출 하나를 흡수한다.
token 오류 401, source 불일치 403, map/revision/future/stale/out-of-order 409, 잘못된 body 422.
보정과 검출은 CORE pose 주입·자동 작업·주행 명령의 입력이 아니다.

**교정 낡음 자동 검사.** Fleet이 `--vision-url`(Vision 수신 서버 origin)과
`--vision-preview-secret-env`로 추적 보정 감시를 켜면, 승인된 교정(`tracking_calibrations`)이
있는 출처마다 `--calibration-drift-interval-s`(기본 60 s, 0이면 끔)마다 Vision의
`GET /api/vision/sources/{id}/map-proposal`을 콘솔용 preview lease로 한 번 읽어 승인
`map_to_image`와 제안 `image_to_map`을 map 평면에서 비교한다. 판정 `calibration_drift`는
`{state: "stale"|"ok", max_move_m, rotation_deg, calibration_revision, frame_seq, checked_at}`이며
출처 상태 행에 실린다(검사 전·무조건 null). 정량화는 승인 `track_bounds_m` 네 모서리를 승인
교정으로 화소로 보낸 뒤 제안 `image_to_map`으로 다시 map 미터로 보내 최대 이동 거리와
선형부 상대 회전각을 재고, 최대 이동 0.3 m 초과 또는 회전 3° 초과면 stale이다. 수락(accepted)
제안만 근거가 되고, 거부 제안·크기 바뀐 프레임·Vision 사용 중(429, 수동 맞춤 실행 중)은 그
회차를 건너뛰어 마지막 판정을 유지한다. 새 승인·철회는 그 출처의 판정을 지운다. 표시 전용
(D-457)이며 관측·목표·주행 경로에 쓰지 않는다. 콘솔 조감도는 로봇 표본 판정(정지 로봇 차이
3폴링)이 살아 있으면 그것을 우선하고, 없으면(관측 0/0대 등) 서버 판정 stale로 실영상 대신
미터 눈금과 "카메라 교정 어긋남(자동 검사)" 경고를 보여 준다.

## 10.7 Site Fleet CORE Agent event history (D-269 Proposed)

CORE Agent WebSocket의 pairing 및 `EventMessage` 검증을 통과한 이벤트는 Fleet SQLite의
`core_event_audit`에 append-only로 기록한다. `event_id` 재전송은 멱등이며 동일 ID에 다른
내용이 오면 거절한다. 자격 증명 필드, private key 또는 64 KiB 초과 payload는 저장하지 않는다.
SQLite `audit_id`는 재시작 뒤에도 유지되는 페이지 커서다. `--events-db`는 `--sightings-db`와
같은 영속 파일로 설정할 수 있다. CORE Agent pairing을 켠 CLI는 `--events-db`를 요구한다.

| Method | Path | Credential | 요구사항 |
|---|---|---|---|
| GET | `/api/fleet/events?after_id=&limit=&robot_id=` | console Bearer token | 인증된 CORE 이벤트 감사 기록을 audit cursor 순으로 조회. `limit` 1–200, 기본 100 |
| POST | `/api/fleet/ai/heartbeat` | site-users `ai_observer` only | D-577 4 (v1.183): the AI PC situation service's status every 2 s, body `{service_version, model_profiles[] (≤8), owner_mode: available\|shared\|owner_busy, gpu_used_mib?, mem_used_mib?, input_lag_s?, build_commit? (v1.198: the git commit the service runs from, `[0-9a-f]{7,40}` with optional `-dirty`)}` (extra fields 422); answers the status below. Not written to `fleet_api_audit` (the facts table is its record). |
| POST | `/api/fleet/ai/facts` | site-users `ai_observer` only | D-577 3·4 (v1.183), shadow only: `{facts: [ {kind, robot_ids[1..16], value, confidence 0–1, evidence {…}, source, observed_at (epoch s), ttl_s} ]}`, at most 32 facts. `kind` is one of D-577 3 (`wait_cycle_confirmed`, `wait_cycle_stale_input`, `waiting_but_moving`, `livelock`, `stalled`, `unknown_occupancy_long`, `lane_obs_vs_range`, `lane_conf_collapse`, `shadow_active_drift`, `pose_vs_paint`, `pose_sources_disagree`, `obstacle_identity`, v1.188: `rear_blocked`, `path_blocked_by_robot`, `incident_context`); `source` is `analyzer:<name>@<version>` (`ttl_s` ≤ 5) or `vlm:<profile_id>` (`ttl_s` ≤ 8). 422 `AI_FACT_INVALID` for a command word (`WAIT`, `RESUME`, `BACK_AND_RETRY`, `YIELD`, `ABORT`, `MANUAL`, `STOP`, `GO`, any case) as a key or value anywhere in `value`/`evidence`, a ttl over its bound, `observed_at` more than 1 s in the future, an unknown kind or field; 413 `AI_FACTS_TOO_LARGE` over 64 KiB; 429 `AI_FACTS_RATE` over 2 posts in one second. 200 `{accepted, ignored, ai}`: with no heartbeat for 6 s (`ai: absent`) or `owner_mode: owner_busy` every fact is ignored. Accepted facts go to memory (256 newest) and `fleet_ai_facts` (`--tasks-db`, written off the event loop) with `stage: shadow`; nothing reads them as a rule input. D-577 개정 2026-10-10 (v1.188): a `rear_blocked` or `path_blocked_by_robot` fact whose first robot id is in site config `fleet.stuck_resolver.ai_facts_acting` (robot id list, default empty) is stored `stage: acting`, and while it is live the Fleet stuck resolver turns any back-off it would send that robot (R2/R3/R6 `BACK_AND_RETRY`) into R5 `WAIT` plus a human row `<cause>_hold:ai:<kind>`; it never adds another answer. |
| POST | `/api/fleet/ai/proposals` | site-users `ai_observer` only | D-577 개정 2026-10-10 (v1.188, 사용자 결정 "AI PC 제안 → Fleet 검증 후 실행"): `{robot_id, stuck_id, decision: WAIT\|BACK_AND_RETRY\|YIELD\|ABORT\|RESUME\|MANUAL, reason ([a-z0-9_:.-], ≤64), confidence 0–1, evidence {…}, source, observed_at, ttl_s ≤ 8}` (extra fields or another word 422; `observed_at` over 1 s ahead 422 `AI_PROPOSAL_INVALID`). 200 `{state: queued\|absent\|owner_busy\|robot_not_acting}`: kept (newest per robot, memory) only for a robot in site config `fleet.stuck_resolver.ai_facts_acting` while the service is present. The stuck resolver waits up to 5 s from first seeing a stuck of such a robot for a proposal, judges it once (`stuck_id`, ttl, word allowed for the cause: `lane_lost`/`no_motion` WAIT·BACK_AND_RETRY·ABORT, `obstacle_ahead` also RESUME, none for `crosswalk_blocked`; trip robots WAIT only; YIELD and MANUAL never forwarded; BACK_AND_RETRY under the R2/R3/R6 preconditions and not `rear_state: blocked`; v1.198 Safety-Review: RESUME is no longer an AI word for any cause (`word_not_allowed`), every word but WAIT needs CORE to report `line_follow.crosswalk` and it null, BACK_AND_RETRY needs every R3 precondition (no R6 peer waiver), no live acting AI fact, R1 first for a peer ahead — verdicts `crosswalk`, `crosswalk_unknown`, `peer_ahead`, `peer_unknown`, `pose`, `ai_fact:<kind>`; a held ABORT is sent as R5 WAIT with the human row `ai_abort_held:<verdict>`; a proposal for a stuck already answered is only audited, verdict `after_answer`) and forwards it to CORE as the decision (`tier: ai`, a WAIT also raises the human row `ai_wait:<reason>`, v1.198 an ABORT `ai_abort:<reason>`), else the rules R1–R6 answer. Verdicts and CORE outcomes go to `fleet_ai_proposals` (`--tasks-db`) and `GET /api/fleet/ai` `proposals[]` (64 newest). |
| GET | `/api/fleet/ai` | any configured user bearer | D-577 5 (v1.183): `{status {state: present\|absent, owner_mode, age_s, service_version, …heartbeat fields}, facts[]}` — live facts (within `ttl_s`, none while absent). v1.198: `proposals[]` (64 newest, each with `outcome` once CORE replied) and `chain {resolver: bool, robots[] {robot_id, credential: enrolled\|token\|none (presence only), ai_acting, last_answer {stuck_id, decision, tier, rule, accepted, code, escalated, at} \| null}, proposals_1h {accepted, held, refused, pending}}` for the console 연동 상태 fold; a `line_stuck` row carries `ai_proposal {decision, reason, verdict, outcome, class: accepted\|held\|refused\|pending} \| null` for that stuck. Each `line_stuck` row (state and `/api/fleet/line-stuck`) carries `ai {state, owner_mode}` and that robot's live `ai_facts[]`; the console shows them as the AI chip ("AI 판단 있음/없음") and fact lines. Role `ai_observer` (site-users, token only, no console login) reads every GET like a viewer and is refused with 403 `AI_OBSERVER_FACTS_ONLY` on every other write route, whatever that route's own guard (stops, stuck answers, trips, goals included). |

조회 응답은 `events`, `next_cursor`, `has_more`를 포함한다. 이벤트 수신/저장은 DDS 접근이나
동작 명령을 수행하지 않는다. SQLite 쓰기 실패 시 Agent 이벤트를 성공 수신으로 응답하지 않는다.

---

# 10.8 Site Fleet task submission, role authorization, and readback (D-276 Accepted)

Fleet `GET /api/fleet/state` (D-493) rows also carry `state_age_s`: seconds from when
that robot's state was observed (hub heartbeat time, or the REST read) to the moment
the response was built, so shared-gather cache age is included; `null` for an offline
row, absent on an older Fleet. The top level carries `gathered_at` (server UTC epoch
seconds, display only; clients must not subtract it from their own clock). The console
exception queue adds its receive-time age to `state_age_s` and warns above 5 s.
Fleet `GET /api/fleet/state` robot rows also expose optional `capabilities`: the
authenticated CORE CAP-001 object, or `null` when it cannot be read. Presentation
may reuse this value for up to 5 seconds; an absent field denotes an older Fleet.
This value is not permission to move. Immediately before goal dispatch (including
yielding to a bay), Fleet reads CAP-001 again and requires
`navigation.goal_navigation == true`. Formation planning similarly requires
leader `swarm.lead` and each follower `swarm.follow` before opening relay streams.
Missing/false flags are refused as `NOT_SUPPORTED`; transport errors remain errors.
CORE still performs its own authorization, localization, and safety checks.

Fleet `GET /api/fleet/state` robot rows also expose optional `link` (D-499):
`up`, `unreachable`, `moved`, `tls-refused`, or `protocol`. Absent on a robot
API error other than HTTP 401. `up` is a successful gather and carries no
console tag. The field is display-only. CORE paths, envelope 1.0, and the
dispatch loop's online/state/goal read are unchanged. An older Fleet omits the field.
D-535 (v1.155) adds optional `link_reason {code, message, action, retry}` to a row whose
gather failed: the D-535 reason (transport failure classified by the Fleet, or the robot's
`error.code`/HTTP status). Message and action come from Fleet's own table, never the robot's text.

Fleet `GET /api/fleet/state` robot rows also carry `rule_m` (D-550 8, D-760 3 stage 1; display only,
nothing is refused): `{state: bounded|unbounded|idle, motion: lane_trip|goal|null, reason}`. It is
Fleet's verdict on the motion Fleet itself started for that robot, counting only the TTL bounds Fleet
holds: CORE traffic authority or a held trip lease for a trip, a goal lease for a navigation goal.
The robot's link and SAF-003 policy are not counted. `reason` is null unless `state` is `unbounded`:
`hold_back` (lane trip with neither), `no_goal_lease`, `leg_unknown`. A row with `online: false` has
no `rule_m`. Stage 1 covers two of the three D-550 item 7 violations: a line follow Fleet opens
outside a trip is not detected. An older Fleet omits the field.

Fleet `GET /api/fleet/state` robot rows also carry optional D-509 display fields
`power_health` and `power_health_age_s`. `power_health` is the existing shared
`core_common.protocol.power_health.PowerHealthResponse` (the authenticated
Viewer `GET /api/v1/power/health` readback), or `null` if the robot is offline,
the robot answers an error, or the body violates that schema. Fleet refreshes it
about once a second off the request path; a refresh that gets no answer (timeout,
refused) keeps the last good body, which is shown up to five seconds old and is `null`
after that. `power_health_age_s` is the nonnegative
Fleet monotonic-clock age in seconds, or `null` whenever `power_health` is null.
The browser adds its own elapsed time after receiving the Fleet response and
checks CORE `battery.sample_age_s` against `stale_after_s` before showing a
current percentage, and separately checks `charging_evidence_age_s` against
the CORE five-second confirmation window before showing confirmed charging.
`battery_status.charging` is a
policy latch, not current charging evidence. These fields are display-only:
Fleet never uses them for motion admission, E-Stop release, or power policy.
The response type is already a shared schema; no CORE endpoint or envelope
field changes.

When durable task storage is configured, the operator navigation route creates a
persistent task before contacting CORE. The browser sends a fresh
`Idempotency-Key`; repeating the same request with the same authenticated
operator identity returns the original task without issuing another robot
command. Reusing a key for a different request returns `409 IDEMPOTENCY_CONFLICT`.

| Method | Path | Credential | Requirement |
|---|---|---|---|
| GET | `/api/fleet/session` | any configured site-user bearer | Returns only the authenticated `principal_id` and role for the current console session. |
| GET | `/api/fleet/auth/connection` | none | D-473 (v1.108): `{mode: "development"\|"paired"}` with `Cache-Control: no-store`. `development` only when Fleet started with both `ROSY_DEPLOYMENT=development` and `--connection-mode development`; any other combination, or a missing setting, is `paired`. D-519 (v1.137): also `password_login: bool`, true when site-users holds at least one login account; the console then offers 아이디·비밀번호 and folds the token field. |
| POST | `/api/fleet/auth/development-session` | none (development mode only) | D-473 (v1.108): 201 `{token, principal_id, role: "operator", expires_at}` with `Cache-Control: no-store`. `principal_id` is `development-<8 hex>`; the token is returned once and lives 1 h in Fleet memory only (gone on restart). The caller address (the last `X-Forwarded-For` entry when Fleet runs with `--lan-camera-proxy` behind the site proxy, otherwise the TCP peer) must be loopback, RFC1918, link-local or the Tailscale tailnet `100.64.0.0/10`; `Host` must be a LAN IP literal, `localhost`, a `.local` name or the host name, and a present `Origin` must equal `Host`; otherwise, and always in paired mode, 403 `FORBIDDEN`. More than 6 requests per address per minute is 429 `RATE_LIMITED` with `Retry-After: 60`. At most 8 sessions are live; a ninth evicts the oldest. The session is a named operator: it passes the named-operator gate (missions included), and the issue and every later POST are written to the API audit under that principal; an unavailable audit is 503 `AUDIT_STORAGE_UNAVAILABLE` and no session. Robot credentials (`robots.yaml`, D-361 enrollment) and stop paths are unchanged. |
| POST | `/api/fleet/auth/login` | none (site-users login accounts only) | D-519 (v1.137): body `{login, password, remember?: bool}`. 204 with `Cache-Control: no-store` and `Set-Cookie: rosy_fleet_session=<random>; HttpOnly; Secure; SameSite=Strict; Path=/`, plus `Max-Age=2592000` (30 d) only when `remember` is true. Accounts are `site-users.yaml` entries with `login` (`^[a-z0-9._-]{1,32}$`, unique) and `password_scrypt` (`scrypt$<n>$<r>$<p>$<salt b64>$<hash b64>`, made by `python -m fleet.server.site_users hash-password`); `service` cannot have a login. A wrong password and an unknown login give the same 401 `LOGIN_FAILED`. More than 5 failures per address or 10 per login in a minute is 429 `RATE_LIMITED` with `Retry-After: 60`. A present `Origin` must equal `Host`, else 403 `CSRF_REJECTED`; a malformed body is 422 `INVALID_REQUEST`. Success is audited under the principal, failure as `login:<name>` (role `viewer`); 429 is audited the same way at most once per address per minute. A login that does not match the pattern is the same 401 (after the dummy scrypt) and is audited as `login:?`. At most two password checks run at once; one that cannot start within 5 s is 429 `RATE_LIMITED`. Without any login account in site-users this route and logout are 404. The session lives in the `--tasks-db` (SHA-256 of the cookie only) and survives a Fleet restart: idle limit 12 h (sliding), 30 d with `remember`, never more than 30 d after login; account changes take effect when Fleet restarts with the edited site-users file (as for tokens), and then every session whose login's principal, role or password changed, or whose entry was removed, ends at once. A session read that cannot reach the DB is 503 `SESSION_STORAGE_UNAVAILABLE`; a cookie validated in the last 60 s needs no DB, and `POST /api/fleet/estop` also accepts an older cached cookie while the DB is unavailable. |
| GET | `/api/fleet/auth/profile` | completed human session cookie | D-689 (v1.211): own login, principal_id, email, role and display_name; no-store. |
| PATCH | `/api/fleet/auth/profile` | completed human session cookie, same-origin | D-689 (v1.211): display_name only, trim 1..80 characters without controls; own profile response. |
| POST | `/api/fleet/auth/change-password` | valid human session cookie, same-origin | D-686 (v1.210): `password` body only, 8..1024 characters different from login ID; 204 replacement cookie, revoke prior account sessions, persist source-bound scrypt in existing SQLite. Initial sessions have no other protected Fleet read/write authority. See first-login contract above for refusal and storage errors. |
| POST | `/api/fleet/auth/logout` | session cookie | D-519 (v1.137): 204; deletes the cookie's session and expires the cookie. With a cookie, `Origin` must equal `Host`, else 403 `CSRF_REJECTED`. |
| GET | `/api/fleet/auth/session` | site-user bearer, development session or session cookie | D-519 (v1.137): `{principal_id, role, via: "cookie"\|"bearer"\|"development", expires_at}` with `Cache-Control: no-store`; `expires_at` is the cookie session's UTC ISO end, `null` for bearer and development. 401 without a credential. **Cookie rule (all `/api/fleet/*` routes):** an `Authorization: Bearer` header is checked exactly as before and wins; only without it is `rosy_fleet_session` read. A cookie-authenticated request other than `GET`/`HEAD` needs an `Origin` whose authority equals `Host`, else 403 `CSRF_REJECTED`. The cookie principal is a named operator for `require_named_operator`. Machine clients keep their Bearer tokens. |
| POST | `/api/fleet/robots/{robot_id}/goal` | named `operator` (D-540 9, v1.161) + `Idempotency-Key` | Validates the configured robot and finite goal, durably accepts the task as `QUEUED`, then lets the dispatcher request a CORE goal. |
| POST | `/api/fleet/robots/{robot_id}/route` | named `operator` (D-540 9, v1.161) + `Idempotency-Key` when durable tasks are configured | D-463 (v1.100): body `{edges: [edge_id, ...]}` of 1 to 8 stored lane-graph edge ids; extra fields 422. Each edge must exist and its `to` must equal the next edge `from`, or 400 `ROUTE_UNKNOWN_EDGE` / `ROUTE_DISCONTINUOUS`. Fleet expands the stored polyline and submits only the next point about 0.20 m ahead, yaw equal to the tangent, through the existing goal path. When that 0.20 m chord would put the nominal body outside the imported lane, the step shortens but stays at least 0.12 m, still past the 0.10 m device goal ball. A remainder of 0.12 m or less keeps the end. The ring's 0.20 m sag stays inside the body clearance, so that step stays 0.20 m. The shorter step is only this point goal. It does not submit the far junction as that goal. The fresh snapshot must be `LOCALIZED` with `pose_frame` `map` and within 0.08 m of the polyline; otherwise 409 `ROUTE_POSE_UNTRUSTED` or `ROUTE_OFF_LANE` and CORE is not called. A snapshot with no localization block is refused. Within 0.05 m of the end the response is 200 `ROUTE_COMPLETE` and no goal. Both 200 bodies carry `context` (D-726, v1.219): `{role: fact, planner: lane_step, supplied: {edges}, holds: {complete, step_m, chord_m, body_clear_m, body_inside, s_m}, planners}`. `context` is a fact for an AI or another system, not a command. `GoalRequest` stays `{x, y, yaw}`. |
| GET | `/api/fleet/site-map/active` | any configured user bearer | D-488 (v1.111): the active `rosy.site_map/1` (places `{id, name, x, y, yaw?, kind park/charge/stop/junction/turnaround/start/bend, exit_yaw?, radius_m?}; D-513 (v1.124): a `start` place needs `yaw`, else 422 `SITE_MAP_INVALID`; D-507 addendum (v1.142): a `bend` place is the vertex of two lane centre lines with `yaw` (entering heading as its edge is drawn), `exit_yaw` and `radius_m` (0, 0.5], the arc the robot drives inside the lane, all required and a turn of 15–90°; other kinds may not carry `exit_yaw`/`radius_m`; bends do not split edges``, edges `{id, from, to, polyline, direction one_way/two_way, width_m, speed_cap_mps, drive_mode lane/free, robot_kinds?}`, optional `turn_bans {at, from_edge, to_edge}`, optional `view_turn_deg` 0/90/180/270 (D-513 7, v1.130: clockwise screen turn of the plain +y-up map view that every Fleet map and camera view follows; display only, default 0), optional `crosswalks` (D-573 1, v1.174) `[{id, polygon [[x, y]] (3–32 points, map frame), approach [[[x, y]]] (0–4 waiting bands, 3–32 points each), lanes [edge_id], revision}]` at most 50: the polygon is the import lane graph's `crosswalks[].polygon` as is (ids `cw1`.. in file order, `revision` `lane_graph:<sha256[:12]>` of that file), `lanes` is recomputed from the edges the polygon touches on every validation (a submitted value is replaced), waiting bands are drawn in the site map editor. 422 `SITE_MAP_INVALID` when crosswalk ids repeat, a polygon or band is not finite, under 1 cm² or over 3 m across, a crosswalk touches no edge, a band does not reach one of its lanes (within half the lane width) or a band point is off the D-507 9 site floor (farther than half the width + 0.30 m from every edge). Absent when empty; map data only, nothing is sent to a robot) with `version`, `sha256`, `activated_by`, `activated_at`. Places are more than 0.05 m apart and every edge is longer than 0.10 m between its places. 404 `SITE_MAP_NOT_ACTIVE` when the site has none. Errors here and on `/trip` are `{"detail": {"code", "detail"}}`. `GET /api/fleet/site-map` (D-257 camera rectangle) is unchanged. |
| GET | `/api/fleet/site-map/lane-graph-crosswalks` | any configured user bearer | D-573 1 (v1.174): `{source, crosswalks [{id, polygon, approach: [], lanes: [], revision}]}` read from the configured `--site-map-import` lane graph, for the site map editor to merge into the draft (polygons replaced by id, drawn bands kept); the draft is then saved by a named operator like any edit. 404 `SITE_MAP_NO_LANE_GRAPH` without a configured import, 422 `SITE_MAP_NO_LANE_GRAPH` when the file cannot be read. Writes nothing. |
| GET / PUT | `/api/fleet/site-map/draft` | GET any user; PUT named `operator` | D-488 (v1.111): one editable draft. PUT `{map, expected_revision}` (body at most 2 MiB, else 413 `SITE_MAP_TOO_LARGE`); the map is validated or 422 `SITE_MAP_INVALID` with `detail.errors [{loc, msg}]` (no submitted values). A stale `expected_revision` is 409 `SITE_MAP_DRAFT_CHANGED`. Each save is a recorded site map event. A draft is never used for planning. |
| POST | `/api/fleet/site-map/activate` | named `operator` | D-488 (v1.111): `{expected_revision}` copies the saved draft into a new immutable version that becomes active; audited. 409 `SITE_MAP_NO_DRAFT`, `SITE_MAP_DRAFT_CHANGED`, or `SITE_MAP_ROUTE_ACTIVE` while a lane route (`/route`) was stepped in the last 30 s; 422 `SITE_MAP_UNPLANNABLE` when the planner cannot use the map; 422 `SITE_MAP_START_INVALID` (D-513, v1.124) when a `start` place is not a trip start pose (within half a lane width of a lane whose direction there agrees with its `yaw` within the planner heading tolerance), `detail.message` names the place and `TRIP_START_OFF_MAP` or `TRIP_HEADING_CONFLICT`. The first version may come from `fleet console --site-map-import <lane_graph.yaml>` when the store is empty. `/route` reads the active map's edges and answers 409 `SITE_MAP_NOT_ACTIVE` without one. |
| POST | `/api/fleet/robots/{robot_id}/trip` | named `operator` | D-488/D-490 (v1.111): body `{to: place_id or {x, y, yaw?}, via?: [place_id] (max 8), arrive_yaw?, speed_cap?, blocked_edges?: [edge_id] (max 32, no duplicates), extra_cost?: {edge_id: seconds} (max 32, each key 1–64 characters, each value finite and >= 0), execute?: false}`. Plans one layered lane-state A* over the vias and the goal on the active map from the robot's fresh `LOCALIZED` map pose (start snaps within half the lane width) and returns 200 `{plan_id, map_version, segments [{edge_id, forward, s_from, s_to}], places, actions [{place_id, action straight/left/right/uturn/stop, theta_deg}], length_m, eta_s, context, expires_at}`; a robot already on the goal place gets an empty plan. Nothing is sent to CORE. `context` (D-726, v1.219) is `{role: fact, planner: lane_graph, supplied: {to, via, arrive_yaw, speed_cap, blocked_edges, extra_cost}, holds: {map_version, segments, places, length_m, eta_s}, planners}` and is stored beside the plan, not inside the executed plan. A later replan unions those `blocked_edges` with traffic blocks and keeps `extra_cost`. Empty fields leave the same route. An edge id blocks both directions of that edge. `context` is a fact for an AI or another system, not a command. Refusals are 422 `{code, detail}`: `TRIP_START_OFF_MAP`, `TRIP_HEADING_CONFLICT`, `TRIP_OFF_MAP`, `TRIP_UNKNOWN_PLACE`, `TRIP_UNKNOWN_EDGE` (`detail.edge`: a `blocked_edges` or `extra_cost` id that is not an active-map edge), `TRIP_NO_ROUTE` (`detail.segment`, `detail.unblock_would_help`), `TRIP_ARRIVE_YAW_UNREACHABLE`, `TRIP_NO_ACTIVE_MAP`, `TRIP_POSE_UNTRUSTED` (also a pose without yaw); 404 `UNKNOWN_ROBOT`; an unexpected planner failure is 500 `TRIP_PLAN_FAILED` in the same body. Every plan and refusal is recorded (last 1000 within 30 days). Costs come from site config `fleet.routing`. D-494 (v1.112): when the robot's capabilities carry the `base_velocity` trip fields, the plan uses only edges of its `drive_modes` and its `robot_kind`, at most `trip_max_linear` (0 m/s allows no edge, so `TRIP_NO_ROUTE`); `junction_turn` is read for trip execution (D-495), not for planning; a robot without them is planned as before (every drive mode, kind-restricted edges left out). D-517 2 (v1.141): a place that is no lane's end (a D-513 `start` place part-way along a lane) is planned as a coordinate goal at its `x, y` with its `yaw` as arrive yaw (D-489 6 snapping, `TRIP_OFF_MAP` when no lane is within twice its width); as a `via` it cuts the plan into legs that carry on along the same lane. `repeat: true` (needs `to` as a place id and at least one `via`, otherwise 422 validation) records a lap trip: see `/trips/{plan_id}/start`. D-517 9 M3 (v1.146): `convoy: {leader: robot_id (1–96)}` (only with `repeat`, otherwise 422 validation) asks to follow that robot in a lane convoy; refused 422 before planning when `leader` is the robot itself `TRIP_CONVOY_SELF`, has no open `repeat` trip `TRIP_CONVOY_LEADER_NOT_RUNNING`, follows another robot `TRIP_CONVOY_LEADER_IS_FOLLOWER` (`detail.follows`), or its `{to, via}` place set differs `TRIP_CONVOY_OTHER_LOOP` (`detail.leader` on each). D-601 (v1.192): a plan with a `lane` edge first reads the robot's `GET /api/v1/vision/front/status` once (site config `fleet.trip.lane_camera_check`, default true; false where no preview exists, e.g. Gazebo SIM); `available` not true, or no answer, is 422 `TRIP_LANE_CAMERA_UNAVAILABLE` (`detail {stale, age_ms}` or `{error}`, recorded). D-604 (v1.195): when the robot's capabilities carry `line_follow.camera` (and Fleet's kept capability value is at most two refreshes old) that answers the check without the call (`detail {stale, age_ms, source}`, `stale` true when a frame exists but is old). The 200 body carries `start_check` `{code, edge_id, heading_err_deg, tol_deg, off_lane_m}` (`{code: null}` for a `free` first edge): the start's alignment check (below) on the planning pose, `code` null when it would pass. The planner's 422 `TRIP_HEADING_CONFLICT` carries `detail.heading_err_deg` (the smallest heading difference to a lane within half its width) and `TRIP_START_OFF_MAP` `detail.off_lane_m`. |
| POST | `/api/fleet/trips/{plan_id}/start` | named `operator` | D-494 5 (v1.116, was a 501 reservation in v1.111–v1.114): runs the stored plan through the Fleet trip loop; the trip id is the `plan_id`, audited. Checks in order: 404 `TRIP_PLAN_UNKNOWN`, 409 `TRIP_ALREADY_STARTED`, 422 `TRIP_PLAN_EXPIRED` (more than 30 s after the plan), 422 `TRIP_MAP_CHANGED` (active map version differs; checked again just before the trip opens), 422 `TRIP_ROBOT_CAPS_UNKNOWN` (no D-494 1 capability fields), 422 `TRIP_MODE_UNSUPPORTED` (`detail.edge_id`; an edge outside the robot's `drive_modes`/kind, any `lane` edge on a robot without `junction_turn: true` `JUNCTION_TURN_UNSUPPORTED` (D-495 3: without keep-mode evidence CORE neither stops at a junction nor turns), a `lane` U-turn `LANE_UTURN`, a `lane` turn over 150° `LANE_TURN_TOO_SHARP`, or a `lane` trip not ending at a place `LANE_END_NOT_A_PLACE`), 422 `TRIP_SITE_FLOOR_MISMATCH` (D-507 9, v1.126: a plan with a `lane` edge on a robot whose `base_velocity` capability `site_floor_map_id` is a string other than the active map's `map_id`, `detail {site_floor_map_id, map_id}`; an absent or null key is not checked), 422 `TRIP_AUTHORITY_NOT_REQUIRED` (D-517 4, v1.143: with site config `fleet.traffic.authority: true`, a plan with a `lane` edge on a robot whose capability `line_follow_authority` is true but `line_follow_authority_required` is not (D-760 2: `line_follow_authority_under_lease` counts too while `fleet.trip_lease_required` is true; the same rule decides `TRIP_AUTHORITY_SITE_OFF`), so after an E-stop or CORE restart it could move before Fleet's first authority; a robot without `line_follow_authority` keeps the M1 hold-back as before), 422 `TRIP_AUTHORITY_SITE_OFF` (D-517 4, v1.150: with site config `fleet.traffic.authority` off, a plan with a `lane` edge on a robot whose capability `line_follow_authority_required` is true: Fleet sends no authority, so CORE would stand at `authority_none` and the trip would end on `stall`), 409 `TRIP_BUSY` (D-517 1, v1.141: this robot already has an open trip, `detail.trip_id`; other robots run their own trips at the same time), 409 `TRIP_ROBOT_BUSY` (the robot already moves for the console: `detail.reason` `goal` (running), `queued`, `yielding` or `formation`), 422 `TRIP_LINE_FOLLOW_NOT_ACTIVE` (a plan with a `lane` edge while the robot's `GET /api/v1/line-follow` `mode` is not `CAMERA_LINE`, `detail.mode`; CORE takes junction instructions only on `CAMERA_LINE`), 422 `TRIP_POSE_UNTRUSTED` (D-494 3 map pose not `LOCALIZED`, or its sighting anchor older than 2 s or unknown; D-593 7, v1.180: an `operator_pin` anchor up to the map pose's 10 s limit also starts while `dead_reckon_m` ≤ `fleet.trip.pin_start_still_m` (0.02) and `bridge_turn_deg` ≤ `pin_start_still_deg` (2°)), 422 `TRIP_LOOP_FULL` (D-517 3, v1.141, `repeat` plans only: one more repeat trip on the same set of edges would break N·h ≤ S − 1, `detail {robots, capacity, held_per_robot}`, h = 3). D-517 3 (2026-10-09 signal SIM, v1.172), with site zones (`fleet.traffic.zones`) no trip stops inside a zone (within a body length + u of a zone lane): a destination or a `repeat` lap's last place reached over a zone lane moves on along the route to the nearest place the robot can hold outside every zone (2026-10-09 user decision "다음 지점까지 가서 섬"; the old destination becomes the last `via`, a coordinate one is dropped), and the trip view's `stop_moved` is `{from, to}` (`from` null for a coordinate) or null; a `stop` at a place next to a zone (a hold, the last place) sends `stop_after_m` shortened so the robot stands outside the zone, and lane arrival counts from that point; no replan hold is set at a place reached over a zone lane. 422 `TRIP_STOP_IN_ZONE` (`detail {place, repeat}`) only when the route has no such place. D-517 9 M3 (v1.146), plans with `convoy`, after the capability checks and before the loop check: 422 `TRIP_CONVOY_SELF`, `TRIP_CONVOY_LEADER_NOT_RUNNING`, `TRIP_CONVOY_LEADER_IS_FOLLOWER`, `TRIP_CONVOY_OTHER_LOOP` (the lap edge sets differ), `TRIP_CONVOY_NOT_BEHIND` (the plan reaches the leader's located lane position only through an edge outside the leader's lap, such as a roundabout shortcut, or starts ahead of it on the same lane), `TRIP_CONVOY_NO_AUTHORITY` (the follower would not get CORE authority: site `fleet.traffic.authority` off or no `line_follow_authority`; the gap is kept only by authority), and `TRIP_CONVOY_LOOP_FULL` in place of `TRIP_LOOP_FULL` (same detail; the leader and every follower count, 1 + N). The trip view carries `convoy` `{leader}` or null. D-517 2 (v1.141): a `repeat` plan may end part-way along a lane but needs a place in it; within `arm_distance_m` of the lap's last place Fleet runs the start checks above again (no named operator) and plans the next lap from the lap end with the same `via`/`to`. The same route as the last lap is appended and the robot drives through (`lap` + 1); a failed check or another route sets `hold {reason: lap, plan (null with code/detail on a failed check), map_version, length_m, eta_s}` and the robot stops at that place; `confirm-replan` takes it. 200 is the trip view `{trip_id, plan_id, robot_id, started_by, state started/running/link_wait/arrived/stopped/failed/canceled, reason, detail, map_version, plan {segments, places, actions}, segment_index, current_edge, drive_mode, next_place, next_action, hold, pose {x, y, yaw, state, source, dead_reckon_m, age_s, anchor_age_s}, caps, created_at, updated_at, repeat, lap, stop_moved}` (`lap` null unless `repeat`). Every 0.5 s every trip robot steps at once, each in its own task (D-517 7, v1.141: a robot whose last step is still running skips that period, so a slow robot never delays another), and the trip robot's state/odom is read once over REST (past the 1 Hz hub cache) and, on a `lane` segment, its `line_follow.junction` before anything is sent; each robot call gives up after 1.5 s. `lane`: within 0.6 m of the segment's end place the action there goes through robot `POST /api/v1/line-follow/junction` (`straight`; `left`/`right` with `turn_deg` = the map's signed junction angle, D-495; `stop` at the last place, where the trip leaves the lane and at a replan hold, with `stop_after_m` = the distance left to the place clamped to [0, 2] because CORE measures it in odom from receipt). D-507 2 (v1.126): only to a robot whose `base_velocity` capability reports `junction_pivot: true`, each instruction also carries `map_id` (the active map), for `straight`/`left`/`right` `pivot_past_line_m` (v1.135: the signed distance from the first painted line past the place, searched along the lane heading at the place since v1.139, to the place; with no line within 0.30 m the outgoing lane `width_m / 2`, at most 0.30, and no window) and the window pair: `expect_in_m` = the distance along the lane polyline from the robot's snapped position to the place (v1.139, 2026-10-08 user decision: CORE compares it with its odom path length, so a bend or the 260919 ring gets a window too; before v1.139 Fleet sent the straight-ahead distance and no pair past a 15° bend), sent only within (0, 2], and `expect_tol_m` = 0.05 per metre of odom travel (dead-reckoned since the last sighting plus `expect_in_m`) + `trip_max_linear` × (pose age + measured pose-read-to-send time + 0.2 s allowance) + 0.05 m `ENDPOINT_TOL_M`, at least site config `fleet.trip.expect_tol_min_m` (default 0.12), plus the robot's distance beside the lane centre line × the lane's total heading change (rad) from the robot to the place (beside the centre line a curve is that much longer or shorter), and at most 0.30 (0.30 when the pose age or dead-reckoned distance is unknown). D-520 1–2 (Fleet side; the API version is the D-520 CORE entry's): only to a robot whose `base_velocity` capability also reports `lane_arc: true`, and only with `map_id`, a `straight`/`left`/`right` whose outgoing lane is a whole `lane` arc to its place, at most 1.0 m, at least 6 polyline points all within site config `fleet.trip.arc_fit_tol_m` (default 0.005 m; the 260919 ring fits within 0.0001 m) of one circle with 0.5 ≤ |κ| ≤ 5.0 1/m, also carries `exit_segment {curvature_1pm` (signed, left +)`, length_m, outer_line_offset_m` (site config `fleet.trip.arc_outer_line_offset_m`, default 0.095: the site map carries no paint)`, end_place_id}`; such a `left`/`right` sends the plain tangent `turn_deg` (no 6° over-turn) and no `advance_m`. An instruction also counts as carried out once the robot's `line_follow.arc.from_place_id` is its place with an `arc_seq` newer than at its send (the turn before an arc and the chained `straight`, which CORE marks done without `executing`); the end place's instruction goes out while the arc runs (the arc is no manoeuvre). A `line_follow.arc` opened after the trip's first instruction with `state: stopped` ends the trip `stopped` (`reason: lane_arc`, `detail.arc_reason`, `arc_place`, `arc_end_place`); one with `reason: lane_arc_end_unarmed` sets `detail.arc_end_unarmed {end_place_id, travelled_m}` and the trip goes on; an instruction CORE drops at an arc end (`aborted`, `junction_reason: arc_mismatch`) ends the trip like any abort (`reason: junction`). A plan whose map version is no longer active sends none of them (`detail.junction_fields_dropped: map_version`). A robot answer 409 `JUNCTION_ODOM_STALE` is not a trip failure: nothing counts as sent, `detail.junction_retry` shows the code and the next tick sends again (the `waiting` rules still bound it). The keeper detects a junction 0.45 m ahead (`JUNCTION_AHEAD_M`), so `arm_distance_m` (0.6) should be at least 0.45 + `pivot_past_line_m` + `expect_tol_m`; SIM checks it. D-507 addendum (v1.142): only to a robot reporting `lane_bend: true`, a `bend` place whose two tangent points lie on the current lane segment (within 0.05 m, entering heading within 15° of the lane) and that the robot has not passed comes before the segment's place: within 0.6 m (`arm_distance_m`) of its arc start Fleet sends `action: bend`, `place_id` = the bend place, `turn_deg` = its signed turn in the direction of travel, `map_id`, `bend_in_m` = the lane distance to the arc start, `bend_tol_m` = the `expect_tol_m` rule without the travelled-distance and curve-offset terms (odom drift over the dead-reckoned distance only), `bend_radius_m`; refreshed at half its expiry while CORE shows it `armed`; the place's own instruction waits until CORE has carried the bend out (`bending`/`reacquiring` seen under our seq, then `idle` or a newer seq; `JUNCTION_ALREADY_DONE` counts) or the robot passed the arc start without one. A plan on another map version sends no bend. Each `repeat` lap (D-517 2) sends its bends again. Nothing is sent while CORE is `executing` or `turning`/`advancing`/`reacquiring`/`bending` (a new instruction would abort the manoeuvre); a `stop` is sent once; `straight`/a turn is refreshed at half its 15 s expiry only while CORE still shows it `armed` with the same seq and place, or sent again when CORE is `idle`/`waiting` before the place. An instruction CORE has shown under our seq as `executing` or `turning`/`advancing`/`reacquiring` is carried out and never sent again; a robot answer 409 `JUNCTION_ALREADY_DONE` also counts as carried out. Lane arrival needs our accepted `stop` for the last place and the robot within 0.15 m, or CORE holding that `stop` (our seq `executing`) within 0.3 m. The next segment is current once CORE reports the instruction done (`idle` or a newer seq) within 0.3 m of the place, or once the pose is more than 0.02 m along the next lane and closer to it. `free`: the D-463 point 0.20 m ahead goes as a navigation goal. Ends: CORE `aborted`/`unresolved` for one of the trip's instructions, or `waiting` for 10 s, is `stopped` (`reason: junction`, `detail.junction_state`, `junction_reason`); D-507 3 (v1.126): on a `lane` segment CORE `unexpected`, or `waiting` with the next place farther than 0.6 m (`arm_distance_m`), is `stopped` at once (`reason: junction_unexpected`, `detail.junction_state`, `junction_reason`, `line_reason` = the robot's `line_follow.reason`; the trip `pose` is the map pose where it stopped); lap SIM A (v1.148): CORE `line_follow.reason` `junction_corner_hold` on our instruction (`junction.seq` ≥ the trip's first seq) is `stopped` at once (`reason: junction_corner_hold`, `detail.line_reason`), not after `stall_s`; D-507 2 (v1.139, 2026-10-08 user decision): a `left`/`right` that would go without the window pair (`expect_in_m`/`expect_tol_m`): a robot without `junction_pivot: true`, a plan whose map version is no longer active, no painted line within 0.30 m past the place, or the place outside (0, 2] m, is never sent and the trip is `stopped` at once (`reason: junction_no_window`, `detail.junction_place`, `junction_action`, `junction_fields` = the fields it would have carried or null), because a turn without a window could be taken at any sighting (a misread bend included); `straight` and `stop` are unchanged; a pose that is not `LOCALIZED` or more than half a lane width off the lane is `stopped` (`reason: pose`, with the provider's `sightings_filtered_map_id` and `odom_refused` in `detail`); less than 0.05 m of progress for `fleet.trip.stall_s` (default 20 s), outside a junction manoeuvre and a replan hold, is `stopped` (`reason: stall`); D-517 (v1.141): standing because the Fleet block table refuses the robot its next block is not a stall, and no `straight`/`left`/`right` goes to CORE while a block at or before that place is refused (CORE waits at the junction; the `waiting` timeout does not run); a goal the console did not send (queued behind traffic, yielding, untrusted) is `failed` (`TRIP_GOAL_REFUSED`, `detail.goal_reason`) and the robot's console queue is cleared, as at every free trip end; a robot error is `failed` (its code, or `TRIP_ROBOT_JUNCTION_UNSUPPORTED` for a 404 junction call, or `TRIP_ROBOT_UNREACHABLE`); D-760 4 (stage 3): on a trip whose lease is `held`, a robot call that gets no answer (connection error or timeout; any other error ends the trip as before) or a state read that fails (no new state/odom) is not an end: the trip goes `link_wait` (`wait {reason: link_wait, since, kind}`), stays open, sends no junction instruction, goal or extended authority, and the robot's blocks stay held (UNKNOWN); only `lease_lost` ends it, or the stall rule once it has waited longer than the lease `ttl_s` (counted from the first loss until one whole step passes without one); no goal lease is renewed meanwhile; when calls answer again and a lease renew sent since the loss was confirmed, Fleet checks the map version and, with a lane ahead, `CAMERA_LINE` (else `failed` with that start refusal code, `detail.link_wait`) and the trip is `running` again; a trip without a lease ends as before; a loop fault is `failed` (`TRIP_LOOP_ERROR`). Every end stops the robot at once (lane: junction `stop` and `PUT /api/v1/line-follow/mode {mode: OFF}`; free: navigation cancel; a free robot that lost its pose is left to its deadman) and records `detail.stop_sent` (and `detail.error`). A Fleet restart turns an open trip into `stopped` (`reason: restart`), stops that robot (retried every 10 s, at most 30 times, outside the loop tick, until it takes, the robot leaves the roster or a new trip takes the robot) and never resumes it. While a trip runs, Fleet refuses other motion for that robot with 409 `TRIP_ROBOT_BUSY`: `POST /api/fleet/robots/{robot_id}/goal` and `/route`, the durable task dispatcher (the robot is not available), `POST /api/fleet/formation/start`, `formation/reform`, `formation/resume`, `POST /api/fleet/robots/{robot_id}/line-stuck/decision` with `RESUME`, `BACK_AND_RETRY` or `YIELD`, and `POST /api/fleet/robots/{robot_id}/line-follow` with `IR_LINE`; the Fleet stuck resolver does not answer a trip robot. Stops are never refused, reach the robot first and then end the trip `canceled`: `POST /api/fleet/robots/{robot_id}/cancel`, `/api/fleet/cancel-all` and intent cancel (`reason: operator_cancel`), `POST /api/fleet/estop` (`operator_estop`), `line-follow` `OFF` (`operator_line_follow_off`), line-stuck `ABORT`/`MANUAL` (`operator_stuck_abort`/`operator_stuck_manual`; `WAIT` is forwarded and the trip goes on). Console traffic never asks a trip robot to yield and never hands it another robot's mission. `/trip` with `execute: true` still answers 501 `TRIP_EXECUTION_NOT_AVAILABLE`. D-541 7 (v1.162, Fleet side; default off): with site config `fleet.trip_lease_required: true`, after the pose check Fleet opens a CORE trip lease with the robot's REST token (`PUT /api/v1/trip-lease` `{lease_id` = a new uuid per trip, never reused`, trip_id, holder` = the Fleet site name`, operator_name` = the named operator`, ttl_s` = site config `fleet.trip_lease_ttl_s`, default 8 since D-760 1 (was 5), 1–10, above 5 when `fleet.traffic.authority` is true`}`); 422 `TRIP_LEASE_UNSUPPORTED` (the robot's `base_velocity` capability has no `trip_lease: true`), CORE's open refusals as 409 `TRIP_ROBOT_LEASED` (`TRIP_LEASED`), `TRIP_ROBOT_MANUAL` (`MANUAL_MODE`), `CALIBRATION_ACTIVE`, or `TRIP_LEASE_REFUSED` (any other, `detail.code`), 422 `TRIP_ROBOT_UNREACHABLE`; a later start refusal releases the lease. The trip view carries `lease` `{lease_id, state: held|lost|released, renewed_at, reason?}` or null. Every period Fleet renews it (same body) apart from the step; a renew answered 404 (CORE ended it: `detail.ended.reason` `taken_over`, `expired`, `mode_left`, `estop`), 409 or another 4xx, `renewed: false` (CORE restarted; that new lease is released at once, `core_restarted`), or no confirmed renew for `ttl_s` since the last confirmed one was sent (`renew_timeout`) ends the trip `stopped` (`reason: lease_lost`, `detail.lease_reason`, `lease_by` = CORE's `by`); a free robot gets a navigation cancel, a lane robot nothing; the lease is never opened again in that trip. Fleet's own stops inside a trip (a replan or lap hold, D-517 traffic, a free/lane switch) keep it. Every other trip end sends `DELETE /api/v1/trip-lease/{lease_id}` after its stop (404 if CORE already ended it). With the setting true the console token may not equal a robot REST token (startup error): the lease owner is that token and must be Fleet's own (D-541 1). D-601 (v1.192): for a plan whose first edge is `lane`, `TRIP_LINE_FOLLOW_NOT_ACTIVE` is now only `IR_LINE` or an unknown mode (a plan starting on a `free` edge still needs `CAMERA_LINE`): a robot with `mode` `OFF` starts, and after every check above, the trip lease and the trip opening, Fleet sends robot `PUT /api/v1/line-follow/mode {mode: CAMERA_LINE}` (the trip loop only; `POST /api/fleet/robots/{robot_id}/line-follow` still takes `IR_LINE`/`OFF`) and the view has `detail.line_follow_started: true`; a robot already on `CAMERA_LINE` gets nothing. A refusal or no answer ends the trip `failed` (`reason: TRIP_LINE_FOLLOW_START_FAILED`, `detail {error, status}`), stops the robot as every end, and the start answers 409 `TRIP_LINE_FOLLOW_START_FAILED` (after no answer at all, Fleet stops it once more after `port_timeout_s`); a cancel or E-stop that closes the trip meanwhile stops it again after the answer. Every trip end still sends `OFF`, also when the robot was on `CAMERA_LINE` before. After the pose check, a plan whose first edge is `lane` is refused 422 `TRIP_START_OFF_LANE` (the pose more than half the lane width from that lane) or `TRIP_START_HEADING_MISMATCH` (yaw unknown or more than site config `fleet.trip.start_heading_tol_deg`, default 20, at most 90, from the lane direction at the pose's projection), `detail {code, edge_id, heading_err_deg, tol_deg, off_lane_m}`; a `repeat` lap's next-lap check does not use it. D-603 (v1.194, Fleet side; default off): with site config `fleet.trip.auto_align: true`, a start refused `TRIP_START_HEADING_MISMATCH` with a known `heading_err_deg` (the robot is on its first lane) first asks robot `POST /api/v1/motion/rotate_to {delta_deg: -heading_err_deg, operator_name}` (the named operator), polls `GET` every `period_s` up to 12 s (a turn still running then gets `DELETE`), waits up to 3 s for a map pose whose sighting anchor is newer than the turn's end and runs the pose checks again; at most two turns (the second corrects odom over-rotation). CORE's refusal is 422 `TRIP_ALIGN_REFUSED` (`detail {error, delta_deg, core}`, `core` = CORE's detail such as `{nearest_m, need_m}`), an aborted or unfinished turn 422 `TRIP_ALIGN_ABORTED` (`detail {delta_deg, reason, final_err_deg}`), no fresh sighting 422 `TRIP_POSE_UNTRUSTED` (`detail.after_align: true`); a mismatch left after two turns is the same `TRIP_START_HEADING_MISMATCH`. A started trip's view carries `detail.aligned [{delta_deg, final_err_deg}]`. With the setting on, `/trip`'s `start_check` adds `auto_align: true` to such a mismatch and the console does not hold the start for it. D-763 10 (c) (v1.238): a lane route entering a site-map crosswalk or a signalled zone is refused 422 `TRIP_REGULATION_CAPS_MISSING` `{missing: {cap: [ids]}}` when the robot announces `lane_crosswalk_gate` / `lane_junction_signal` false; an older CORE without the field starts with `detail.regulation_caps_unknown {cap: [ids]}` and a Fleet warning log; also checked on each lap and replan. |
| POST | `/api/fleet/trips/{trip_id}/cancel` | `operator` bearer (a stop; named until v1.160) | D-494 5 (v1.116): ends an open trip `canceled` (`detail.canceled_by`) and stops the robot now, without waiting for a loop tick in flight (a send that lands after it is stopped again): lane sends junction `stop` and then `PUT /api/v1/line-follow/mode {mode: OFF}` (robot `POST /line-follow/hold` extends a hold-to-run session and is not a stop), free sends a navigation cancel; `detail.stop_sent` false with `detail.error` when the robot did not take it. 404 `TRIP_UNKNOWN`, 409 `TRIP_NOT_RUNNING`. Audited. |
| POST | `/api/fleet/trips/{trip_id}/confirm-replan` | named `operator` | D-494 5 / D-489 9 (v1.116): a blocked remaining edge (or a changed map) replans only at the next place; a changed route sets `hold {reason: replan, plan, map_version, length_m, eta_s}` and the robot is held there (`stop`, or a goal at the place). This call switches the trip to `hold.plan`. 409 `TRIP_NO_REPLAN`, 409 `TRIP_REPLAN_FAILED` (`hold.plan` null, `hold.code` from the planner; cancel instead), 409 `TRIP_MAP_CHANGED` (the map changed after the hold; the trip plans again at the same place), 409 `TRIP_NOT_RUNNING`. Audited. |
| GET | `/api/fleet/trips` · `/api/fleet/trips/{trip_id}` | any configured user bearer | D-494 5 (v1.116): `{running: trip view or null, trips: [recent trip views]}` (D-517 1, v1.141: `running` is the most recently started open trip and `open` lists every open trip); one trip view, or 404 `TRIP_UNKNOWN`. D-763 8 (v1.231): an open trip's `wait` carries `waiting`, `bound_s` and `over_bound` (see the v1.231 entry). While a trip is `started`/`running`, `POST /api/fleet/site-map/activate` answers 409 `SITE_MAP_ROUTE_ACTIVE` (replaces the v1.111 "`/route` stepped in the last 30 s" guard; `/route` itself is unchanged). |
| GET | `/api/fleet/traffic` | any configured user bearer | D-517 3 (M1, v1.141): read-only Fleet fixed-block table of the last trip period; nothing of it is sent to a robot (CORE authority is M2). `{map_version, block_length_m {edge_id: m}, units [{id, capacity, zone, two_way, state FREE/GRANTED/OCCUPIED/UNKNOWN, holders [robot_id], waiting [robot_id]}], robots [{robot_id, authority_end_m, front_d_m, convoy, waiting_for [robot_id], lap, trip_state}], loop_capacity [{edges, capacity, robots}], wait_cycle [robot_id] or null, unplaced [robot_id]}`. Blocks are cut per active map version with ℓ ≥ L + max(d_stop(v) + 2u, 0.45) (Pinky body, `RobotBody` stop gap + hysteresis, u = `expect_tol_min_m` + 0.05 × dead-reckoned m, at most with 1.5 m); zones from site config `fleet.traffic.zones {zone_id: {edges, capacity}}` (default none), a two-way lane outside a zone is one direction-locked zone. `authority_end_m` and the units are route metres from the start of each trip's first lane. A robot whose pose is not `LOCALIZED` keeps its last occupancy as `UNKNOWN`. A robot whose trip ended, or whose trip is on another map version, keeps its grants and last body as `UNKNOWN` until a fresh `LOCALIZED` map pose shows it clear of them (D-517 6); a map activation re-places every robot from its last `LOCALIZED` pose. While `unplaced` names a trip robot never localized, no trip gets a junction instruction. `loop_capacity` lists each loop: the edge set of one lap of an open `repeat` trip (its cycle via…, to, not the approach); `TRIP_LOOP_FULL` counts trips by that set and S by that lap's blocks. Empty lists before the first period or without an active map. D-517 4 (M2, v1.143): with site config `fleet.traffic.authority: true` (YAML boolean, default false) each trip whose robot advertises `line_follow_authority` gets `POST /api/v1/line-follow/authority` once per trip period after the table: `until_m` = its `authority_end_m` − its route position at the map pose the table used (clamped to [0, 10]), `pose_stamp` = that pose's `odom_stamp`, `ttl_s` 2, `leg_id` `{trip_id}:{route revision}`, never a smaller end on the same leg than already sent (plan metres, so dropped laps do not count as a shrink). D-760 3/5 (stage 3, Fleet side): `leg_id` is `{trip_id}:{route revision}:{fleet_epoch}` (a random id per Fleet process, so a restarted Fleet never reuses a leg whose `seq` CORE remembers) and every request carries `seq`, rising per robot and leg; a robot whose `base_velocity` capability reports `line_follow_authority_shrink: true` gets `ttl_s` 5, others 2 and never a shrink. A robot whose step is still running gets nothing that period and rolls on its held `ttl_s`. No extended authority goes to a robot in `link_wait`, before the trip's own `CAMERA_LINE` start was answered, or within 5 s after Fleet started. In those periods, and whenever the table gives no end (a pose jump, a table fault, another map version, a convoy follower whose end would go back), a shrink-capable robot that holds an extend gets `{shrink: true, until_m: 0, ttl_s: 5}` with the newest `pose_stamp` Fleet has, every period until CORE answers `accepted: true` or `reason: shrink_none_held`; until then the table pins that robot's body plus its last `until_m` when it is off the table (a new map version), and after a trip end whose halt got no answer until that extend's send time + 5 s + the client timeout. At most one send per robot in flight, no retry inside a period; when sends stop the robot stops on expiry. A trip view carries `traffic_authority: core` (sent) or `hold_back` (M1 junction hold-back only) and `caps.line_follow_authority`; a trip robot standing at its authority end (CORE answered `HOLDING`) is not a stall. D-517 9 M3 (v1.146): `front_d_m` is the robot front the table used (route metres, null without a `LOCALIZED` pose); `convoy` is null except on a follower: `{leader, follows, gap_m}`. Each period a follower follows the nearest `LOCALIZED` member of its convoy (the leader or another follower of it, while the leader's trip is open) whose front, mapped onto the follower's route over the same arcs under that member's body, lies past the follower front − body − both u; `gap_m` is that member's rear minus the follower front. Its `authority_end_m` is then min(its fixed-block end, that rear − (d_stop(v) + 2u_follower + u_member)) with d_stop(v) the `RobotBody` stop gap + hysteresis at its `trip_max_linear`, and it may be granted a unit held by that member only (never another robot's) where the span reaches past that end; such a grant ends its fixed-block authority while it no longer follows that member and the member still holds the unit. Without a member to follow (unknown pose, not on the same arcs, leader trip ended: the convoy dissolves and the follower keeps lapping on fixed blocks) it is on fixed blocks. A follower never gets an end smaller than one it had: the row has `authority_end_m` null, nothing is sent and CORE stops on expiry, with `waiting_for` naming the member (not a stall). D-517 5 M4 (v1.149): `resolver` lists the robots Fleet's resolver took over this period as `[{robot_id, trigger, decision, cycle?, blocked_edges?, since?}]` (empty when none). `trigger: wait_cycle` (the robot is in `wait_cycle`): one member whose refused unit lies past its next place (not on its current segment, not on its last segment) gets `decision: replan` with `blocked_edges` (that unit's edges); the trip loop plans it again from just before its next place with those edges closed (D-489 9 `replan_hold`), so a changed route stands at that place as `hold.reason: replan` for a named operator to confirm and no route is `plan: null`; Fleet never switches a route by itself. The other members are `wait`. No member able to leave first, a replan already given on the same route (trip id and route revision), or an UNKNOWN member makes every member `human`. `trigger: unknown`, `decision: human`, `since` (Fleet epoch s): the robot has held an `UNKNOWN` unit for more than 30 s. |
| GET | `/api/fleet/robots/{robot_id}/path` | any configured user bearer | D-594 (v1.184): read-only recorded path `{robot_id, now, retention_s, use: "display-only", truncated, points: [{t, x, y, state, source, seg, map_id, trip_id, formation_id}]}`, oldest first. Query `since`·`until` (UTC epoch s, ≥ 0), or `last_s` (0 < s ≤ 86400, back from Fleet's `now`; not with `since`), optional `trip_id`; default the whole 24 h retention. At most 5,000 points: when more match, the newest 5,000 and `truncated: true`. Fleet writes one point per robot per second only in map coordinates: `state` LOCALIZED + `source` `robot` (the robot reports LOCALIZED in the map frame, D-395), else the D-494 3 map pose LOCALIZED/DEGRADED + `sighting`/`bridged`, else CAMERA_ONLY + `tracking` (D-457 marker, or a match to a verified map pose; display-only). A `localization: null` pose and odom are never recorded. A point is kept after 2 cm of travel, a change of state/source/map/trip/formation, or 30 s; a new `seg` starts after a tick without a point. Kept 24 h and at most 86,400 points per robot in the site DB (`--tasks-db`, table `fleet_robot_path`; in memory without one). 404 `UNKNOWN_ROBOT` off the roster; 422 `BAD_PATH_RANGE` for `since` with `last_s` or `until` < `since`. Traffic, routes, trips and stops do not read it |
| GET | `/api/fleet/robots/{robot_id}/map-pose` | any configured user bearer | D-494 3 (v1.113): read-only trip map pose `{robot_id, x, y, yaw, state LOCALIZED/DEGRADED/UNKNOWN, source sighting/bridged, dead_reckon_m, age_s, anchor_age_s, map_id, odom_refused, odom_refused_reason, sightings_filtered_map_id}`. Fleet anchors on each accepted `/api/fleet/sightings` row (lease 1 s, source token bound to the robot, `quality` ≥ `min_quality` when present, `map_id` equal to the active site map's when one is active, otherwise counted in `sightings_filtered_map_id`) paired with the robot's `odom_pose` (its `stamp` is UTC epoch seconds, like `captured_at`) at `captured_at`: sightings wait in order (up to 32, at most 3 s) for an odom sample at or after their capture, then are interpolated between two samples at most 1.2 s apart, else paired with the nearest sample within 0.25 s, and bridges with the odom delta since. `DEGRADED` after more than `max_dead_reckon_m` (1.5 m) or `max_bridge_turn_deg` (270°) of odom, an anchor in another map frame than the active one, an anchor older than `max_anchor_age_s` (10 s), or a sighting more than `max_jump_m` (0.15 m) / `max_jump_deg` (20°) off the bridged prediction (re-anchored; 2 consistent sightings recover, a first anchor needs the same 2). `UNKNOWN` (x/y/yaw null) before any anchor, with odom older than 3 s, and after an odom gap over 3 s or a step faster than `max_speed_mps` (1 m/s) or a turn faster than `max_turn_rate_dps` (360°/s) (an odom reset) until the next sighting. Odom stamped more than `max_odom_future_s` (0.5 s) ahead is refused and counted in `odom_refused`. Robot and site clocks must agree within 0.1 s. Limits come from site config `fleet.map_pose`. The read refreshes the robot state (hub snapshot when fresh, else REST; skipped while odom is under 0.2 s old); an unreachable robot answers its last odom. 404 `UNKNOWN_ROBOT`. Only trip execution uses this pose: `/route`, traffic and D-395 are unchanged. `odom_stamp` (v1.143, D-517 4): the `stamp` of the newest odom sample in a `LOCALIZED`/`DEGRADED` pose (null when `UNKNOWN`), the CORE authority's `pose_stamp`. `anchor_source` (v1.180, D-593): `sighting` \| `operator_pin` \| null; `source` is also `operator_pin` while no odom arrived since a pin. `bridge_turn_deg` (v1.180): summed odom heading change since the anchor. |
| POST | `/api/fleet/robots/{robot_id}/map-pin` | named operator (D-540 9) | D-593 (v1.180): body `{x, y, yaw}` (map frame, m, rad; finite, |x|,|y| ≤ 1000, |yaw| ≤ 2π). Fleet reads the robot state, then anchors the map pose on this pose at the newest odom sample (must be within `max_odom_age_s`, 3 s): `LOCALIZED` at once, `anchor_source: operator_pin`, bridged by odom under the same limits as a sighting anchor (1.5 m, 270°, 10 s). A later sighting is checked against it like any anchor (0.15 m / 20° → `DEGRADED`); sightings captured before the pin are dropped. Answer: the map-pose body. Errors: 404 `UNKNOWN_ROBOT`, 409 `MAP_PIN_TRIP_ACTIVE` (that robot is on a trip), 409 `MAP_PIN_ODOM_STALE`, 409 `MAP_PIN_POSE_INVALID`, 422 body. Site map event `map_pin` (principal, pose, map_id, the pose before). A pin is never a D-546 overhead decision to a robot. Trip start (D-593 7): a pin older than `start_anchor_age_s` (2 s) still starts while the robot has not moved since it (≤ 0.02 m, ≤ 2°). |
| GET | `/api/fleet/robots/{robot_id}/lane-compliance` | any configured user bearer | D-511 M0 (v1.128): read-only lane compliance `{robot_id, level OK/WARN/ACT/UNKNOWN, pose_state, edge_id, arc_id, offset_m, margin_m, width_m, body_half_width_m, warn_count, act_count, moving, map_version, at}`. A 2 Hz Fleet monitor projects the D-494 3 map pose onto the arcs of the active site map; an arc counts only when the foot point lies strictly inside it (not clamped to either end), within `max_lateral_m` of its centreline (default: that arc's `width_m`) and with its tangent within `heading_gate_deg` (45°) of the robot heading, and the nearest such arc is used (so a two-way edge or a junction takes the lane being driven): `offset_m` is signed against the arc tangent (left +), `margin_m = width_m/2 − (|offset_m| + body_half_width_m)` with the Pinky Pro URDF half width (`core_common.robot_body`). `WARN` after `persist_n` consecutive samples with `margin_m < warn_margin_m`, `ACT` after `persist_n` with `margin_m < 0`; `UNKNOWN` (edge/offset/margin null) when the pose is not `LOCALIZED`, no site map is active, or no arc passes those tests — a robot parked in a bay or yard off the graph, past a dead-end arc, crossing a lane, or backing along a one-way lane — and it restarts both counts; UNKNOWN is never a departure. Robots whose odom moved more than `moving_min_m` (0.01 m) or `moving_min_deg` (2°) within `fleet.map_pose.max_odom_age_s` get a REST state read per tick, cut at 0.5 s (`moving: true`); others are judged from their heartbeat odom. The console exception queue raises WARN/ACT only for `moving` robots and says the body is over the edge whenever `margin_m < 0`. Thresholds come from site config `fleet.lane_compliance` (`warn_margin_m` 0.02, `persist_n` 3, `act_timeout_s` 3.0, `max_lateral_m` null, `heading_gate_deg` 45, `moving_min_m` 0.01, `moving_min_deg` 2; provisional until measured). The same object is the `lane_compliance` field of each `GET /api/fleet/state` robot row (`null` before the first tick). Before the first tick the route answers `{level: UNKNOWN, pose_state: null, at: null}`. 404 `UNKNOWN_ROBOT`. Observe only: nothing is sent to the robot, and trip, `/route` and meet thresholds are unchanged (D-511 M1). v1.132 (D-472 addendum 3): when the map pose is not `LOCALIZED`, the robot's LED-confirmed track (`GET /api/fleet/tracking/identity`) is judged instead if it is `CONFIRMED`, its `age_s` lies within [−0.05 s, `fleet.map_pose.sighting_lease_s`] like a map pose sighting (`age_s` of `GET /api/fleet/tracking/identity` is not clamped at 0) and its `map_id` is the active site map; additive fields `pose_source` (`map_pose` \| `led_track`, the input judged) and `heading_source` (`pose` \| `track_motion` \| `none`): the blob has no yaw, so while the robot's odom says moving and the track moved more than `fleet.lane_compliance.track_heading_min_m` (0.05 m, provisional, above camera blob noise) the direction of that move is the heading, kept while the track stays fresh (a skipped camera frame repeats the position); before the first such heading (`none`) the nearest arc is taken without the heading gate, so on a two-way edge the offset sign may belong to the opposite arc and at a junction the nearest arc can be the crossing lane. A change of `pose_source` restarts `warn_count`/`act_count`. `pose_state` stays the map pose state. The track never feeds the map pose, trips, initialpose or commands. |
| GET / POST | `/api/fleet/teach` · `/api/fleet/teach/start` · `/stop` · `/confirm` · `/place` | GET any configured user bearer; POST named `operator` | D-494 6 (v1.119): teach a lane by driving it. Teach never sends anything to a robot (the driver moves it with Pilot). `POST /start {robot_id}` opens the one recording of the site (409 `TEACH_BUSY` with `detail.teach_id` and `detail.robot_id` of the recording, also when another start wins while the pose is read; 404 `UNKNOWN_ROBOT`; 422 `TEACH_POSE_UNTRUSTED` with `detail.state` when the robot's D-494 3 map pose is not `LOCALIZED`). Every 0.5 s Fleet reads the robot state over REST (`refresh(force_rest)`) and keeps the map pose only when it is `LOCALIZED` with `dead_reckon_m` ≤ 0.5 m (`DEGRADED` is never kept), at least 0.1 m from the last kept point (at most 20000 points). A recording that keeps no new point for 10 min, or reaches 20000 points, stops itself through the same stop path (site map event principal `system:teach_idle`, `detail.reason` `idle`/`full`; operator stops are `operator`) and then waits for confirm like any stopped recording. `POST /stop` (409 `TEACH_NOT_RECORDING`) ends it and returns `{teach_id, robot_id, points, kept, polyline, from_candidates, to_candidates, expires_at}`: the line simplified by Ramer–Douglas–Peucker (0.02 m, distance to the chord segment) and, per end, the existing places within 0.15 m nearest first `[{place_id, name, distance_m}]` (empty: suggest a new address). A line of fewer than 2 points or not longer than 0.10 m is 422 `TEACH_TOO_SHORT` and dropped. Stop never writes the map. `POST /confirm {teach_id, from, to, direction one_way/two_way, drive_mode lane/free, speed_cap_mps, width_m? (default 0.185), expected_revision?}` where `from`/`to` is a place id or `{name, kind?}` for a new address at that end appends one edge (ids `teach_eN`, new places `teach_pN`, line ends pinned onto the places, dropping leading/trailing interior points within 0.15 m of them) to the draft (or a copy of the active map, or an empty map) and saves it like `PUT /site-map/draft`: same `expected_revision` rule (409 `SITE_MAP_DRAFT_CHANGED`), 422 `SITE_MAP_INVALID` `detail.errors [{loc, msg}]`, 413 `SITE_MAP_TOO_LARGE` over 2 MiB. 422 `TEACH_UNKNOWN_PLACE`, `TEACH_PLACE_TOO_FAR` (a chosen place more than 0.15 m from that end, `detail.end`); 404 `TEACH_UNKNOWN` (confirmed already, or stopped more than 10 min ago: a stopped recording that is not confirmed is discarded 10 min after its stop). A refused confirm keeps the recording. 200 `{edge_id, draft}`. `POST /place {robot_id, name, kind?, expected_revision?}` adds an address at the robot's `LOCALIZED` map pose (with its yaw) to the draft the same way (422 `TEACH_POSE_UNTRUSTED`); 200 `{place_id, draft}`. `GET /api/fleet/teach` is `{recording: {teach_id, robot_id, started_by, started_at, points [[x, y]] (mm-rounded), last_kept_at, stopped_at: null, result: null} or null, pending: [stop results, newest first]}`. Recordings live in memory only (a restart drops them). Start, stop, confirm and place are site map events (`teach_started`, `teach_stopped`, `teach_confirmed`, `teach_place`) beside the HTTP audit; activation stays `POST /site-map/activate`. Errors are `{"detail": {"code", "detail"}}`, except request body validation (FastAPI's default 422). |
| POST | `/api/fleet/teach/place-from-marker` | named `operator` | D-564 (v1.168): `{marker_id, name?, kind?, place_id?, expected_revision?}`. 그 마커의 가장 새로운 신선한 관측(2 s 이내, source 설정과 같은 map·calibration revision)으로 `place_id`가 없으면 새 초안 장소(`name` 필수, 없으면 422 `PLACE_NAME_REQUIRED`, `kind` 기본 junction, yaw 포함)를, 있으면 그 장소의 x·y·yaw(와 준 이름·종류)를 바꾼다. 409 `PLACE_MARKER_STALE`(관측 없음·만료), 409 `PLACE_MARKER_MAP_MISMATCH`(활성 사이트 지도 또는 초안(활성·초안이 없으면 빈 지도 `site`)의 `map_id`와 다름), 404 `PLACE_UNKNOWN`, 422 `PLACE_MARKER_BEND`, 503 `PLACE_MARKERS_DISABLED`(장소 마커 source 없음), 초안 저장 오류는 `/place`와 같다. 응답 `{place_id, draft}`, 이벤트 `teach_place {marker_id, source_id, place_id, updated, revision}`. 로봇에 아무것도 보내지 않고 활성 지도는 바꾸지 않는다 |
| POST | `/api/fleet/do` (when `do` is `navigate`) | named `operator` (D-540 9, v1.161) (any verb other than `estop`, `cancel`, `stop`, `formation_stop`, `follow_cancel`) + `Idempotency-Key` | Uses the same task service; each navigation step gets a deterministic child key from the request key and step position. |
| GET | `/api/fleet/tasks/{task_id}` | any configured user bearer | Returns the durable task projection and append-only status history. |
| POST | `/api/fleet/tasks/{task_id}/cancel` | `operator` bearer | Cancels a task only while it is still queued; it does not cancel a goal already dispatched to CORE. |
| POST | `/api/fleet/cancel-all` | `operator` bearer | D-421 (v1.81): non-latching site-wide driving cancel. In order: queued tasks of every robot become `CANCELED` with reason `FLEET_CANCEL_ALL` and the operator as actor (dispatch latch and generation unchanged); an open formation is stopped; then per robot, concurrently, `POST /api/v1/swarm/cancel`, `POST /api/v1/navigation/cancel`, `PUT /api/v1/line-follow/mode {mode: OFF}`, each attempted even when an earlier one failed. It never calls `safety/stop`/`safety/release`, `/mode`, signals or OMX stop. Each request writes a durable record in the task journal database (`fleet_cancel_all`: id, principal, opened/closed times, robot ids, canceled queued task ids, robots whose navigation cancel was answered; closed records older than 30 days are pruned when a window opens) and tags the in-flight dispatch attempts of those robots by `(task_id, attempt_id)` (`ACCEPTED`, `RUNNING`, mid-dispatch `QUEUED`, and `UNKNOWN` changed since the window opened or not already canceled). Dispatched tasks are not rewritten by Fleet: a correlated CORE `nav.canceled` (evidence that a cancel was issued, not of standstill, D-298) moves a tagged task to `HOLD` with reason `FLEET_CANCEL_ALL`, which releases its robot claim, so in-flight robots become dispatchable once CORE confirms the cancel. The event must match the tagged attempt, its `data.source` (when present) must be `api:*`, and the window must be open, or closed at most 30 s ago with that robot's navigation cancel answered or a fence re-cancel; other later cancels stay `UNKNOWN`. A dispatch started inside the window is tagged before its CORE goal call, and tagging settles an attempt whose `nav.canceled` already arrived during the window. Correlated events and dispatch receipts arriving after `HOLD(FLEET_CANCEL_ALL)` are logged, not applied. If the record cannot be written the fanout continues and the response carries `record_error: "CANCEL_ALL_RECORD_UNAVAILABLE"`; without that event the task stays as it was (`ACCEPTED`/`UNKNOWN`), the robot stays claimed and the task needs reconciliation (no operator reconcile route exists yet). An untagged `nav.canceled` still yields `UNKNOWN`/`CORE_CANCEL_RESULT_PENDING`. `tasks.awaiting_core_result` lists per robot the `ACCEPTED`/`RUNNING` tasks plus `UNKNOWN` tasks changed since the window opened. A dispatcher CORE goal call that overlaps the request (including a task submitted and dispatched inside the window) is inspected when it ends: an explicit CORE reject stays `FAILED`/`COMMAND_REJECTED`; a dispatch left in Fleet's own traffic queue with no live CORE goal becomes `CANCELED`/`FLEET_CANCEL_ALL`; otherwise the task is tagged, Fleet sends `navigation/cancel` to the robot and to any robot it sent to a bay for it, and the task becomes `UNKNOWN`/`FLEET_CANCEL_ALL_DURING_DISPATCH` (no retry); a goal call that raised is re-canceled the same way and keeps its existing classification. 200 even on partial failure: `{cancel_all_id, record_error, cancelled, total, evidence: "CORE_REPLY_ONLY", robots[{robot_id, result: cancelled\|failed\|unreachable, steps{swarm, navigation, line_follow: {ok, error?{reachable, sent?, code, message}}}, tasks{awaiting_core_result[]}}], formation{stopped, state, error?}, tasks{canceled[], error}}`; `sent: false` marks a step Fleet's D-361 address gate refused locally (`ADDRESS_UNVERIFIED`; `line-follow/mode` is not a stop path because a path-level gate would also allow turning it on). `cancelled` = all three CORE calls replied 2xx; `unreachable` = no call got a reply; otherwise `failed`. A reply is not physical stop evidence (D-298). Repeating the request is safe. Normal audit gate applies (`503 AUDIT_STORAGE_UNAVAILABLE`); the D-330 audit exception stays with `/api/fleet/estop`. |
| GET | `/api/fleet/line-stuck` | any configured user bearer | D-407 (v1.77): returns the board as of the last shared gather (it does not contact the robots) as `{pending[], answers[], observed_age_s}`; `observed_age_s` is null before the first gather. D-438 (v1.91): one shared gather feeds both `GET /api/fleet/state` and the stuck resolver loop and is reused for up to 1 s, so with the resolver running the board is at most about 1 s old even when no console is open. `pending` has one row per robot whose CORE `line_follow.stuck` is open: the CORE `LineStuckStatus` fields plus `robot_id`, `front_clearance_m`, `rear_clearance_m`, `turn_clearance_m`, `rear_blind_m`, `preview_seq` (from the `nav.line_stuck_opened` FleetAgent event, `null` when not received; `opened_event` says which), `robot_online` (false = last value kept while the robot is unreachable), `observed_age_s`, `fleet_answer` (the last forwarded answer for this stuck id; `ESCALATE` rows are not answers and are skipped) and `resolver` (D-438, see `.../line-stuck/claim`). `answers` is the recent forwarded-answer record `{robot_id, stuck_id, decision, principal_id, accepted, outcome, code, message, audit_id, tier, rule, escalated, at}` (`accepted` null = outcome unknown). The same row appears as `line_stuck` on each robot of `GET /api/fleet/state`. D-517 5 M4 (v1.149): the resolver also answers a robot on an open Fleet trip, with the stopping `WAIT` only (rule `R1`, a peer in the front band); any other rule (back-off, yield, resume) escalates that stuck to a human (`escalated: no_rule`), as D-494 14 refuses moving decisions on a trip. |
| GET | `/api/fleet/robots/{robot_id}/line-stuck/evidence?stuck_id=` | any configured user bearer | D-577 8 (v1.182): the open stuck's one evidence picture, `{robot_id, stuck_id, sequence, source, media_type: image/jpeg, age_s, jpeg_base64}`; `age_s` is the frame's age (CORE `age_ms` at the read plus the time since). The first read asks the robot (`GET /api/v1/vision/front/status`, then `/front/frame?sequence=` with Fleet's robot credential, 3 s limit); Fleet keeps that one frame in memory only while the stuck is open (never disk, bus or event; dropped when the stuck closes or is replaced) and later reads serve it without asking the robot again. 404 `STUCK_NOT_OPEN` (no open stuck with that id on the board, or it closed during the read), 404 `STUCK_PREVIEW_UNAVAILABLE` (`message` = the robot's code, e.g. `CAMERA_FRAME_UNAVAILABLE`; a failure is not kept, the next read asks again). The picture is display evidence only; nothing reads it as a rule input. One still per stuck, not a relay: D-136 T1 (no video or preview relay routes in Fleet) stays. v1.273: a request with `Accept: image/jpeg` (the console's 2 s live poll) gets the same picture as the raw body, `Content-Type: image/jpeg`, `Cache-Control: no-store`, and the other fields as compact JSON in the `X-Stuck-Evidence` header (no `jpeg_base64`); any other `Accept` gets the JSON body above. Same route, permissions, errors (JSON) and D-136 exception, also with `live=true`. |
| GET | `/api/fleet/line-stuck/episodes` | any configured user bearer | D-407 (v1.121): durable stuck episodes, newest first, `?limit=` 1-1000 (default 100), as `{episodes[]}`; empty when Fleet runs without `--tasks-db`. One row per `(robot_id, stuck_id)` from the same board transitions (no extra robot calls): `source` (`fleet_poll`, so times are poll resolution, about 1 s, and a stuck shorter than one poll can be missed), `cause`, `phase_at_open`, `local_enabled_at_open`, `trip_busy_at_open` (null before the trip runner is wired), `peer_ahead_at_open` (the D-438 R1 band test; null = no own pose), `opened_at`, `closed_at` (UTC ISO), `held_s_max`, `attempts_max` (CORE `held_s` is the duration of record), `close_reason` `cleared`\|`replaced`\|`left_roster`\|`fleet_restart` (an episode still open at start-up; the same `stuck_id` seen again reopens the row and keeps the first `opened_at`), `resolved_by` from the last non-`ESCALATE` answer (`human`\|`rule` when accepted, `<tier>_unconfirmed` when the outcome is unknown, null when only refused or unanswered), `resolved_principal`, `last_answer_tier`, `escalation_code` (the last `ESCALATE` row's `escalated`), and `pose_x`, `pose_y`, `pose_yaw`, `pose_state`, `pose_age_s` (Fleet map pose at open, null without the map pose service). An unreachable robot's episode stays open. |
| POST | `/api/fleet/robots/{robot_id}/line-stuck/decision` | `operator` bearer for `WAIT`·`ABORT`; named `operator` (D-540 9, v1.161) for `RESUME`·`BACK_AND_RETRY`·`MANUAL` | D-407 (v1.77): `{stuck_id, decision: WAIT\|RESUME\|BACK_AND_RETRY\|MANUAL\|ABORT}`; permission by value (D-540 9, v1.161): WAIT and ABORT stay open to any `operator` like the CORE route; RESUME, BACK_AND_RETRY, MANUAL and YIELD need a named operator (403 `OPERATOR_IDENTITY_REQUIRED`), and on a robot under a D-541 trip lease CORE answers the moving values from a non-owner token with 409 `TRIP_LEASED`; `stuck_id` 1-64 chars of `[A-Za-z0-9_.:-]` (CORE ids are `stuck-<12 hex>`), extra fields 422. Forwarded unchanged to that robot's `POST /api/v1/line-follow/stuck/decision` with the robot credential; Fleet never refuses on CORE's behalf. 200 `{robot_id, actor_id, answer, result}` (`result` is CORE's body incl. `outcome`). A CORE 409 (`STUCK_ID_MISMATCH`, `STUCK_DECISION_REFUSED` with its reason, `EMERGENCY_ACTIVE`, `CALIBRATION_ACTIVE`) is returned as 409 `{code, message, robot_id, robot_status}` with CORE's code and message verbatim; other robot error statuses are 502 with the same body, unknown robot 404. A transport failure is 502 `{code, message, robot_id, transport}`: `ROBOT_UNREACHABLE` when the connection was never made (not delivered), `STUCK_DECISION_OUTCOME_UNKNOWN` on a timeout or a dropped reply (CORE may have applied the answer; re-read the stuck before answering again). Every forwarded answer is recorded with the site principal in memory and, with durable task storage, in the `fleet_line_stuck_answers` table of the Fleet journal database, keyed by the API audit `request_id` (§10.10). D-438 (v1.91) nullable columns: `tier` (`human` for this route, `rule` for a resolver answer), `rule` (`R1`–`R3`, resolver only), `escalated` (hand-off reason). Every resolver hand-off to a human is its own row with `decision: "ESCALATE"`, `accepted` null, `tier: "human"`, `escalated` = the reason and `principal_id: "fleet-resolver"`. A database created before v1.91 gains the three columns when Fleet opens it (rows written before stay null). |
| POST | `/api/fleet/robots/{robot_id}/line-stuck/claim` | `operator` bearer (D-540 9: open, the console claims before an `ABORT` confirm) | D-438 (v1.91): `{stuck_id}` — 사람이 그 막힘을 맡는다. 판단기는 맡은 막힘에 답하지 않고 `human_claimed` 로 올린다. 200 `{robot_id, stuck_id, claimed_by}`, 모르는 로봇 404 `UNKNOWN_ROBOT`. `.../line-stuck/decision` 도 404 확인 뒤 먼저 맡고, CORE 전달이 실패해도 맡음을 유지한다. 로봇 행 `line_stuck.resolver` = `{tier, rule, decision, escalated, at, age_s}` 또는 null(escalated 사유: `no_rule`, `rule_budget`, `deadline`, `restuck_after_resume`, `estop`, `calibration`, `no_resolver_token`, `human_claimed`, `core:<CODE>`, D-577 `lane_lost_hold:<peer_behind|peer_unknown|attempts|local_disabled|crosswalk|crosswalk_unknown|pose|refused|rule_budget>`, v1.187 같은 이유의 `no_motion_hold:<…>`). 2026-10-10 (v1.187): CORE `no_motion` 막힘은 `lane_lost` 와 같은 조건으로 R6 `BACK_AND_RETRY`(조건이 모두 참) 또는 R5 `WAIT` + 사람(`no_motion_hold:<이유>`)이고 `RESUME`·`YIELD` 는 나가지 않는다. 뒤 띠는 `localization` 을 보고하는 신뢰 지도 자세로만 잰다: 동료가 온라인인데 자신이나 동료가 LEGACY(odom)이면 `peer_unknown`(D-577 남은 항목 1). 현장 설정 `fleet.stuck_resolver.enrolled_robots`(로봇 id 목록, `--site-config`)에 적은 등록(D-361) 로봇은 판단기가 Fleet 의 등록 CORE 자격(operator, `STUCK_DECIDE` 포함)으로 답한다. 기본은 빈 목록이다. D-577 1 (v1.173): `lane_lost` 막힘에 R3 `BACK_AND_RETRY`는 로컬 복구 켜짐·시도 남음·규칙 예산 남음·R3 거절 없음·CORE 상태의 `line_follow.crosswalk`가 `null`(키가 없으면 지금의 모든 CORE처럼 보고 안 함 → `crosswalk_unknown`, 객체면 `crosswalk`; D-573 구현은 구역 밖에서 `null`을 낸다)·Fleet 지도 자세가 `LOCALIZED`이고 `age_s` ≤ 2 s이거나 그 로봇의 목격 출처가 한 번도 없어 `UNKNOWN`(출처가 있었는데 `UNKNOWN`이면 `pose`)·뒤 띠(R1 띠의 반대쪽, D-395 신뢰 지도 자세로만 잼)에 동료 없음일 때만이다. 다른 로봇이 온라인인데 자신이나 그 로봇의 신뢰 자세가 없으면 `peer_unknown`. 아니면 R5가 `WAIT`을 보내고 같은 주기에 `lane_lost_hold:<이유>`로 사람에게 올린다(`tier: human`, `rule: R5`, `decision: WAIT`; CORE가 `WAIT`을 거절해도 올리고, 전송 실패면 `WAIT`을 한 번 다시 보낸 뒤 올린다). R5는 막힘마다 한 번이고 규칙 예산을 쓰지 않는다. `lane_lost`에 `RESUME`·`YIELD`는 어떤 경로로도 나가지 않는다. `age_s`는 그 메모 뒤 초이고, 콘솔은 30 s 넘게 답이 없는 올림 행을 큐 맨 위로 올린다(콘솔만, 로봇은 계속 HOLD). 판단기 답은 `principal_id: "fleet-resolver"` 로 기록하고, 전송 실패는 `ROBOT_UNREACHABLE` 이면 `accepted=false`, 아니면 null. 설정: `robots.yaml` 의 `resolver_token`(비어 있지 않은 따옴표 문자열, `token`·`fleet_pairing_token` 과 달라야 함). D-577 2 (v1.173): `fleet console` 은 판단기를 기본으로 돌리고 `--no-stuck-resolver` 로 끈다(`--stuck-resolver` 는 호환용, 효과 없음). 시작할 때 판단기가 답할 로봇(`resolver_token` 있음)을 stderr 에 적는다. 자격(`resolver_token`)이 없는 로봇의 막힘은 지금처럼 `no_resolver_token` 으로 사람에게 간다. `robots.yaml` 로봇만 판단기 클라이언트를 가진다(등록 D-361 로봇은 아직 없음) |
| POST | `/api/fleet/robots/{robot_id}/line-follow` | `operator` bearer for `{mode: "OFF"}`; named `operator` (D-540 9, v1.161) for `IR_LINE` | Forwards the bounded line-follow selection to CORE `PUT /api/v1/line-follow/mode`. OFF stops, so it stays open |
| POST | `/api/fleet/formation/start` · `/reform` · `/resume` | named `operator` (D-540 9, v1.161) | D-20 formation. `formation: TRAIL` (D-559, v1.170) = COLUMN slots, every follower armed with `mode: trail` and `distance` = slot × spacing behind the leader on its path; a follower whose follow reply lacks `mode: trail` is disarmed and the start fails `ARMING_FAILED` (`TRAIL_NOT_SUPPORTED`). D-581 (v1.176): while the leader streams `frame: odom`, Fleet re-expresses each frame in each follower's odom from the ceiling-camera map pose (§7.8 `anchor`); while an anchor is missing the follower gets `anchor_hold` samples, not silence; formation status carries `anchor: {followers: {robot_id: "<robot>:no_map_pose|anchor_stale|map_pose_degraded|anchor_jump|map_id_differs|leader_odom_mismatch" or null while sending usable samples}, robots: {robot_id: {anchor_age_s, residual_m, residual_deg, jumped}}, jumps}` (null when no map pose service), and `stream_evidence[robot_id].anchor_hold` repeats a follower's reason (frames flow, the follower stands). `/api/fleet/formation/stop` stays `operator` bearer (a stop) |
| POST | `/api/fleet/signals/{signal_id}/command` | `operator` bearer for `mode` `all_red`·`flash_red`; named `operator` (D-540 9, v1.161) otherwise | D-443 physical signal. `manual` without any configured credential still answers 401 `UNAUTHORIZED` first |

v1.136: 진행 중인 lane trip의 `detail.bend_candidate`는 읽기 전용 지도 굽이 **후보**다. 현재 활성 지도 버전이 trip과 같고, 자세가 `LOCALIZED`이며 나이 ≤0.30 s, dead reckoning ≤0.05 m, 현재 edge 중심선에서 ≤0.04 m, 투영 진행 거리 차 ≤0.05 m, 접선과 yaw 차 ≤15°일 때만 기록한다. 값은 `{map_id, map_version, arc_id, bend_in_m, heading_change_deg, map_offset_m}`이며 0.40 m 앞까지의 edge polyline에서 접선 변화 ≥15°와 전체 변화 ≤80°를 찾는다. 다음 tick에서 근거가 사라지거나 trip이 끝나면 삭제한다. CORE로 보내는 지시나 운동 허가가 아니며 페인트·벽·분기의 같은 경계 확인을 뜻하지 않는다.

**D-608 Fleet 사건 보고서 (additive).** `GET /api/fleet/incidents?limit=1..100`(viewer+, 기본 20)은 `{reports:[...],traffic_reports:[...]}` 최신순이다. 각 `rosy.incident.v1` 행은 `id: "line_stuck:<robot_id>:<stuck_id>"`, `stuck_id`, `classification: "line_stuck"`, `robot_ids`, `opened_at`, `closed_at`, `evidence`(`core`, `fleet`, `rosy_cam`, `ai_facts`, `front_image`), `actions`, `reviews`를 가진다. `rosy_cam`은 같은 DB의 사건 시작 ±5 s 수락 관측 1건 또는 null, `ai_facts`는 같은 로봇·시간대의 최대 3건이며 둘 다 원인 확정 근거가 아니다. `front_image.status: "requestable_while_open" | "not_retained"`는 D-577의 메모리 한정 사진이 닫힌 뒤 남지 않았다는 뜻이다. `POST /api/fleet/incidents/{robot_id}/{stuck_id}/review`(이름 있는 operator)는 `{root_cause, note}`를 받는다. `root_cause`는 `line_marking|obstacle|robot_fault|localization|traffic_wait|unknown`, `note`는 최대 1000자다. 검토는 append-only이며 성공 `{reviewed:true}`, 사건 없음 404 `INCIDENT_NOT_FOUND`, 잘못된 본문 422다. 사건·검토는 움직임 권한이나 모델 승격 권한을 주지 않는다.

같은 응답의 `traffic_reports[]`는 별도 D-577 AI 상황 사실(`wait_cycle_confirmed`, `wait_cycle_stale_input`, `waiting_but_moving`, `livelock`, `stalled`, `unknown_occupancy_long`) 최신순이다. `id: "ai_fact:<fact_row>"`, `classification`은 사실 종류, `evidence.ai_fact`는 원래의 값·출처·stage·시각, `evidence.core`·`fleet`·`rosy_cam`은 직접 연결된 표본이 없으면 null이다. `POST /api/fleet/incidents/facts/{fact_row}/review`는 같은 본문·권한·응답·오류 계약이고, 검토는 `fleet_ai_fact_reviews`에 누적한다. AI `wait_cycle_confirmed`의 `value.fleet_agrees: false`는 Fleet의 순환과 다른 AI 단독 판단이다. `incident_context`는 일반 AI 사실의 시간 근접 연결과 달리 같은 로봇의 `stuck_id`가 정확히 일치하고 시작 -5초~+120초인 경우만 해당 사건에 연결한다. 이 보고서가 Fleet 통행권이나 CORE 명령을 변경하지 않는다.

Task status is the shared `FleetTaskStatus` enum: `REQUESTED`, `QUEUED`,
`ACCEPTED`, `RUNNING`, `COMPLETED`, `FAILED`, `UNKNOWN`, `HOLD`, `CANCELED`,
or `EXPIRED`. The normal path is `REQUESTED` → `QUEUED` → `ACCEPTED`; a queued
task may instead become `CANCELED` or `EXPIRED`, and dispatch uncertainty is
`UNKNOWN`. `QUEUED` means Fleet durably recorded the request and has not yet
dispatched it. `ACCEPTED` means CORE returned an explicit receipt; it does not
mean the task started or completed. `RUNNING` and `COMPLETED` require separate
CORE status/final-result evidence. `CANCELED` and `EXPIRED` apply only before
dispatch. An ambiguous post-dispatch result is `UNKNOWN` and is never retried
automatically. This Fleet task enum does not change the robot DDS/WSS envelope
`protocol_version`.

The browser treats `QUEUED` as durably accepted by Fleet and shows the task ID,
server-computed `queue_position`, wait reason, blockers when available, and
queued-only cancellation. The position orders queued `READY` and
`WAITING_TRAFFIC` tasks by server priority and FIFO timestamp; it is not an
execution-time estimate and does not override robot availability or traffic
eligibility. Before cancelling, the browser reads the authenticated task
projection again; if the task has
already left `QUEUED`, the operator action uses the robot cancel route. Robot
cancel/stop and site E-Stop remove undispatched queued work before sending the
CORE safety request. An `UNKNOWN` task is shown as requiring manual CORE status
verification; the UI never turns a command receipt into completion.

The site Compose configuration loads an individual `site-users.yaml` registry.
Each row binds a unique `principal_id` and role (`viewer`, `operator`,
`policy-admin`, or `service`) to a SHA-256 digest of one high-entropy bearer token. The raw
token is delivered separately and is never stored in that file. `viewer` may
read Fleet state, evidence, and task history. `operator` may also request,
cancel, and stop work. A `service` principal may create and resolve `cell_job`
proposals only; it cannot admit work. Cell Job admission requires a different
named `operator` principal. `policy-admin` may not issue robot commands; no
policy mutation endpoint exists yet. The separate `/registry` endpoint
continues to use its own server-side credential.

Authenticated `POST /api/fleet/*` requests other than source-authenticated
`POST /api/fleet/sightings` and read-only mDNS observation
`POST /api/fleet/discovery/scan` attempt to append an `INTENT` and a `RESULT` row to the durable
API audit. The rows contain principal, role, method, path, and response code,
not the bearer token or request body. If the intent cannot be persisted, Fleet
normally returns `503 AUDIT_STORAGE_UNAVAILABLE` before calling CORE. The
dedicated `POST /api/fleet/estop` is the D-330 exception: an authenticated
operator's stop fanout continues on audit-storage failure, as specified in
§10.11. `POST /api/fleet/do` (including an `estop` step) retains the normal
audit gate. If the result row
cannot be written after an action, the intent remains pending and the outcome
must be reconciled; it is not safe to infer failure or retry.

The legacy shared `--token` mode is not per-user authorization and does not
satisfy D-276. Site Compose requires `--users-file`; replacing or removing a
digest and restarting Fleet rotates or revokes that user. Policy submissions
require a stored `evidence_id` reference (§10.6.2) and remain `HOLD` — with the
evidence admission reason, or `POLICY_NOT_ACCEPTED` when the admission itself
passes — while D-268 is Proposed and `POLICY_DISPATCH_ENABLED` stays false. A command timeout or unclassified post-dispatch error becomes
`UNKNOWN`; the server does not retry it. For a dispatched Pinky navigation task,
Fleet keeps `task_id` as its ledger identity and sends the current `attempt_id`
as CORE `correlation_id`. CORE echoes that value in correlated `nav.started`,
`nav.completed`, and `nav.failed` event data. Paired CORE events update the
matching robot and current attempt in Fleet's durable task projection; duplicate
event IDs and out-of-order sequences do not regress the projection. Events with
unknown, stale, or mismatched attempt IDs do not change a task. A cancel request
event leaves the task `UNKNOWN` while a correlated final result is pending; if
none is delivered, it remains `UNKNOWN` for reconciliation. None of these task
states is a physical stop readback. HTTP ambiguity remains
`UNKNOWN` and is not automatically retried. The dated P0
[boundary trace](../validation/2026-09-27-platform-p0-task-result-trace.md)
records the pre-change gap and counterexamples.

CORE binds the ID to one Nav2 action generation. An active Fleet-correlated
goal cannot be replaced by an uncorrelated moving goal; after a cancel request,
later goal generations carry no previous attempt ID. Fleet stores each CORE
event before projecting it. If projection temporarily fails, the durable audit
log is retried on subsequent CORE heartbeats and replayed after Fleet restart;
delivery does not depend on CORE retrying a sent event.

On Fleet startup, a persisted `REQUESTED` task is changed to `UNKNOWN` with a
`fleet-recovery` history entry; startup never assumes that it is safe to resend.

### D-613 유한 한 바퀴 `start_at` (v1.199)

`to`가 차선 중간의 이름 있는 `start` 또는 `stop` 장소이면 마지막 `actions[].place_id`에 그 장소 ID가 남고 Fleet이 마지막 차선에서 `stop_after_m` 정지를 보낸다. 좌표만 지정해 차선 중간에서 끝나는 lane trip은 기존 `LANE_END_NOT_A_PLACE`로 거절한다. 반복 lap의 중간 장소 통과는 정지 명령으로 바뀌지 않는다.

`POST /api/fleet/robots/{robot_id}/trip`의 선택 필드 `start_at: place_id`는 관제에서 고른 출발·복귀 장소다. 이 필드는 `repeat: false`, `to: start_at`, 하나 이상의 다른 `via` 장소와 함께 사용한다. 잘못된 조합은 422 유효성 오류다. Fleet은 계획 시 현재 `LOCALIZED` 지도 자세가 그 장소에서 0.05 m 이내인지 검사하고, `POST /api/fleet/trips/{plan_id}/start`에서 새 자세로 다시 검사한다. 멀면 422 `TRIP_START_PLACE_MISMATCH`와 `{place, distance_m, limit_m}`를 반환하며 출발하지 않는다. D-517 구역 규칙이 정지를 다른 장소로 옮겨야 하는 경로는 시작 시 422 `TRIP_START_PLACE_MOVED`로 거절한다. 필드가 없는 기존 trip의 동작은 같다. CORE API와 envelope 1.0은 바뀌지 않는다.

유한 `start_at` trip은 시작 직전 첫 계획 구간의 중심선 거리와 Pinky Pro 공칭 몸 반폭을 더해 차선 반폭 이내인지 확인한다. 넘으면 422 `TRIP_START_BODY_OUTSIDE_ROUTE`와 `{edge_id, body_margin_m}`(음수 m)를 반환한다. 알 수 없는 로봇 몸체는 `TRIP_BODY_UNKNOWN`, 비어 있는 계획 구간은 `TRIP_NO_ROUTE`로 출발을 거절한다. 계획 미리보기의 기존 `start_check`는 로봇 중심·방향 기준이며 시작 때 몸체 검사를 다시 수행한다.

AI PC의 `ai_observer`는 열린 trip 중 `GET /api/fleet/trips`와 필요할 때 `GET /api/fleet/site-map/active`를 읽고 `POST /api/fleet/ai/facts`에 `kind: "trip_route_check"`를 보낼 수 있다(D-577 개정, v1.199). `value`는 `{status: "ON_ROUTE"|"OFF_ROUTE"|"UNKNOWN", offset_m?, limit_m?, reason?}`이고 `evidence`는 `trip_id`, `map_version`, `pose_source`, `pose_age_s`, 가능한 경우 `edge_id`를 담는다. 이 사실은 `shadow`이며 Fleet의 정지 권한이나 CORE 안전 명령을 대체하지 않는다.

열린 Pinky Pro trip view는 `body_half_width_m`(m, D-424 URDF 공칭)을 싣는다. AI PC의 `trip_route_check`는 계획 선분의 `width_m/2 - body_half_width_m`를 `limit_m`으로 사용해 몸체 가장자리가 계획 구간 밖이면 `OFF_ROUTE`로 보고한다. 반폭이 없거나 유효하지 않으면 `UNKNOWN`이며 중심점 판정으로 대체하지 않는다. AI PC와 Fleet이 같은 지도 자세를 읽으므로 이 사실만으로 실제 차체 경계 침범이 없었다고 증명하지 않는다.

trip view의 `pose_observed_at`은 Fleet이 자세를 읽은 wall timestamp(Unix seconds)다. AI는 `pose.age_s + max(0, 관측 시각 - pose_observed_at)`이 1.5 s를 넘거나 나이·시각이 없거나 유효하지 않으면 `UNKNOWN`으로 판단한다. 미래 시각은 최대 0.5 s의 시계 차이만 허용한다. trip 저장 시각 `updated_at`은 자세 관측 시각을 대신하지 않는다. AI snapshot 관측 시각은 HTTP 읽기가 끝난 시각이다.

## 10.9 Site Fleet LAN discovery

The Ubuntu host Avahi bridge resolves `_rosy._tcp.local` and submits one full
scan every 15 seconds. `DiscoveryScanPayload.devices` contains at most 64
objects with `name`, optional `hostname`, private LAN IPv4 `address`, `port`,
`stage`, `release`, and `network=sta`. The host scanner has one dedicated Bearer
credential, separate from site users, CORE REST, and FleetAgent pairing.

| Method | Path | Authority | Result |
|---|---|---|---|
| POST | `/api/fleet/discovery/scan` | host scanner Bearer only | Replace the short-lived discovery scan; 401 invalid credential, 400 invalid observation |
| GET | `/api/fleet/peers` | site viewer+ | D-452 `PeerCatalogue`: bounded role catalogue, separate discovery/approval/readiness; no credentials or automatic enrollment |
| GET | `/api/fleet/discovery` | site viewer+ | `{scanner_online, scanner_state, scanner_age_s, devices[]}` with status `registration_pending`, `pairing_pending`, `verified_online`, or `conflict` |
| GET | `/api/fleet/discovery/addresses` | site viewer+ | `{scanner_state, all_outside, robots[]}`: per roster robot `{robot_id, origin, pinned, pinned_is_name, status, in_subnet, seen_addresses[], movable}`; status `in_scanned_subnet`, `outside_scanned_subnets`, `seen_at_other_address`, or `unknown`. Explains only: nothing resolves or follows a new address (D-361 3, D-370 5.3); no credentials |
| POST | `/api/fleet/enrollment/robots` | named operator | D-361 화면 코드 등록 `{code, discovery_name}` 또는 `{code, address}`. D-565 (v1.169): HTTPS(`tls=required`) 대상에 등록 행이 없으면 아직 등록되지 않은 승인 binding(`rosy.enrolled-tls/1`) 중 `hostname`·`port`가 같은 하나로만 TLS(그 CA·호스트 이름, 코드 전 identity `receiver_id`)로 짝짓고, `system/info` `robot_id`가 binding과 같을 때만 저장한다. 409 `tls_binding_required`(맞는 binding 없음), 409 `tls_binding_required`는 승인 binding이 가진 이름·주소를 HTTP로 등록하려 할 때도 요청 전에 낸다. 409 `tls_binding_mismatch`(코드 전 identity `receiver_id`가 binding과 다름, 코드는 나가지 않음), 409 `code_consumed` reason `tls_binding_mismatch`(코드 뒤 `system/info` `robot_id`가 binding과 다름) 또는 reason `tls_binding_required`(binding이 가진 ID·이름이 HTTP로 답함), 둘 다 토큰 로그아웃, 502 `unreachable`(binding 이름을 찾지 못함). HTTP로 내려가지 않는다 |
| POST | `/api/fleet/robots/{robot_id}/hub-link` | named operator | D-555 (v1.163): issue (or rotate) the enrolled robot's hub credential, store only its SHA-256, deliver it once with `PUT /api/v1/fleet/link` over the TLS-bound enrollment. 409 `tls_binding_required` (plain-HTTP enrollment), `hub_link_unavailable` (no `--hub-link-hostname`/`--hub-link-ca`, `--events-db` or console token), `robot_unsupported` (no `fleet_link_provisioning`), `not_active`; 502 `unreachable`, `robot_refused` (digest rolled back). 409 `fleet_goal_active` when a Fleet goal runs (this console's goal table or the robot's `fleet_goal_active`, or CORE's `FLEET_GOAL_ACTIVE`). Rotation drops the hub session made with the old credential. Returns the enrollment row |
| DELETE | `/api/fleet/robots/{robot_id}/hub-link` | named operator | D-555 (v1.163): 409 `fleet_goal_active` as above unless `?force=true` (named operator, confirmed in the console): then the digest and hub session are cleared during the goal too and the robot's SAF-003 STOP/HOLD applies (audit `forced_…`). Otherwise the digest is cleared and the hub session dropped first, then one robot `DELETE /api/v1/fleet/link` attempt behind the TLS fence (a changed or missing binding gives `robot_cleared: false`). `{…row, robot_cleared, was_linked}`. Enrollment rows add `hub_linked`, `hub_host`, `hub_online`, `hub_state` (`online` \| `checking` within 35 s of delivery or Fleet start \| `failed`), `hub_linkable` (never the digest) |

The scan expires after 45 seconds. Empty successful scans remove prior rows;
scanner failure sends nothing and later reads report `scanner_online=false`.
`scanner_state` is `never_seen` (no scan since Fleet started, `scanner_age_s`
null), `online`, or `expired` (the lease ran out; `scanner_age_s` is the age
of the last scan in whole seconds). The console raises an alarm on `expired`
because discovery and move-address stop until the scanner returns.
Advertisement data is not identity evidence. `verified_online` requires an
existing `robots.yaml` endpoint and an online authenticated FleetAgent HELLO
with a device UID and matching device name while the advertised stage is
`CORE_READY`. The endpoint is matched by advertised IP or `.local` hostname and
port. A duplicate advertised name or identity mismatch is a conflict. The
discovery routes never add an endpoint, assign a robot number, expose a token,
or command CORE. Cross-VLAN, blocked multicast, and AP mode use manual endpoint
configuration and the existing outbound FleetAgent path.

### D-452 역할 목록 (v1.94)

정본은 `core_common.protocol.network_peers`의 `PeerObservation`, `PeerSummary`,
`PeerCatalogue`이다. 기존 scanner payload의 `devices[]`는 로봇 등록 관찰로 유지한다.
선택적 `services[]`는 역할별 관찰이며 두 배열의 합계가 최대 64개이다. 생략하면 빈 배열이다.
`services[]`는 non-robot 5역할만 전달한다. 로봇 관찰은 기존 `devices[]`에서 한 번만 세며,
선택적 `transport=http|https`는 검증한 TXT의 TLS 요구를 표현한다(기존 생략 행은 legacy HTTP).
이는 TLS 인증 접속 성공이 아니다. catalogue는 이 기존 로봇 관찰을 역할 row로도 표현한다.
한 번의 성공한 scan이 두 관찰 목록을 교체하며 같은 45초 lease를 사용한다.
클라이언트 앱의 session presence를 scanner가 임의로 제출할 수 없다.

`PeerCatalogue`는 `{peers[], scanner_state, scanner_age_s}`이다. `scanner_state`는
`never_seen|online|expired`, age는 유한한 0 이상 초 또는 null이다. 각 row는
`name`, `role`(`robot|fleet|overhead-camera|dock|signal|model-host|pilot|cam`),
`transport`(`http|https|ssh|session`), nullable `service_type`, `hostname`, `address`, `port`,
nullable `peer_id`, `provenance`(`mdns|approved-directory`),
`freshness`(`fresh|expired|conflict|unavailable`), `approval`(`approved|unapproved`),
`readiness`(`unknown|verified|unreachable`)를 가진다. mDNS network endpoint는
정규화된 `.local` 이름, RFC1918 IPv4, 1..65535 port이다. 승인 directory는 기존 승인된
정규화 DNS 이름과 port를 유지하며 현재 미해결 address는 null로, 확인된 VPN/DNS 주소는
unicast 힌트로 표시할 수 있다. 둘 다 역할별 정본 service type과 transport를 검사한다.
기존 승인된 literal-IP profile은 `hostname=null`과 실제 `address`로 이주 전 상태를
보존하며 DNS 이름을 만들어 넣지 않는다. 정상 선택 화면은 승인 `peer_id`·이름을 사용한다.
이름은 제어 문자 없는 1..96자이다. token·key·개인 경로·임의 TXT를
반환하지 않는다. 앱 presence는 `transport=session`이며 inbound endpoint가 모두 null이다.

광고는 `peer_id`나 승인·검증 상태를 만들지 않는다. 승인 신원은 기존 directory가 제공하며,
`verified`는 fresh인 승인 대상의 endpoint owner가 실제 인증 접속을 확인했을 때만 가능하다.
충돌·만료·오류에서는 verified를 유지하지 않는다. 목록 조회는 viewer에게 허용하지만,
선택 이후 접속·쓰기·SSH 배포는 각 endpoint의 기존 인증과 운영자 권한을 그대로 적용한다.
다른 망의 approved DNS/profile 경로와 실제 연결 수락은 이 LAN 조회의 성공만으로 증명하지 않는다.

관제의 `--approved-peer-directory-file`은 배포 관리자가 준비한 metadata-only JSON 배열을
시작 시 읽는다(예: `deploy/site/approved-peers.json.example`). 최대 64행·1 MiB이며
각 행은 approved-directory/approved, unknown readiness와 unavailable freshness만 허용한다.
중복 JSON 키·신원·역할/hostname 소유 충돌·credential/extra·허위 live 상태는 시작을 거부한다.
이 파일은 토큰을 발급하거나 기존 endpoint를 변경하지 않으며 쓰기 API가 없다. 이후 접속은
해당 장비 owner의 기존 승인 profile과 인증을 따른다. IP/URL 가져오기는 운용자의 정상 선택 단계가 아니다.

MODEL은 `_rosy-model._tcp`, `product=rosy`, `role=model-host`, `proto=ssh/2`,
`tls=none`, `transport=ssh`를 필수로 광고한다. 실제 sshd listener의 SRV port만 제공하며
추론 HTTP API가 아니다. `tls=none`은 SSH 호스트 키 인증을 생략한다는 뜻이 아니다.
기존 승인 논리 이름의 HostKeyAlias·known_hosts·StrictHostKeyChecking이 계속 신원을 검증한다.

CORE `fleet.discovery`의 기존 `expected_hostname`·`ca_file`은 신원 pin으로 유지한다.
다른 망의 승인 경로는 선택적 `allow_dns_fallback: true`와 `approved_directory_url`
(`wss://<approved DNS or IP>:<port>/ws/robots`, userinfo/query/fragment 없음)을 함께
로컬 승인 profile에 명시한다. 기본은 fallback 없음이며 legacy `hub_url`을 대신 쓰지 않는다.
일치하는 광고가 없을 때만 이 대상의 `/healthz`를 기존 CA와 expected_hostname SNI로
검증한 뒤 같은 신원으로 WSS를 연다. 충돌·잘못된 일치 광고·인증서·health role·401/403
실패는 이 경로로 우회하지 않는다. health 요청에는 Agent token을 넣지 않으며 신원 검증
전 HELLO/credential을 전송하지 않는다. 이것은 새로운 등록/credential 생성 규약이 아니다.


## 10.10 Site Fleet intent interpretation and message boundaries (D-293 Accepted, D-316 Accepted)

The site API accepts a domain intent and lets Fleet interpret it. For the current
navigation request, CORE's typed `GoalRequest` contains goal intent and may
carry an optional `correlation_id` supplied internally by Site Fleet for the
current dispatch attempt. The public `/api/fleet/*` intent schema remains
limited to goal intent. The correlation value is
tracing metadata: it does not choose the goal, authorize motion, or claim an
execution result. The authenticated principal supplies the actor identity.
Fleet derives source, priority, task ID, eligibility, and dispatch state from
server configuration and policy. Clients cannot submit `priority_class`, worker
identity, arbitrary source identity, ROS/DDS topics, `cmd_vel`, raw camera
frames, or a claimed execution result. `GoalRequest` is not a general command
envelope.

Goal coordinates must be finite JSON numbers; booleans and non-finite values
are invalid. The direct `/api/fleet/robots/{robot_id}/goal` route rejects
undeclared body fields with HTTP `422`. `/api/fleet/do` rejects unknown intent
fields with HTTP `400` (`UNKNOWN_FIELD`) and invalid navigation numbers with
HTTP `400` (`INVALID_NUMBER`). These requests are rejected before a CORE
navigation call.

The interpreter returns stable `400` error codes: `UNKNOWN_VERB` for an unsupported action, `UNKNOWN_FIELD` for undeclared fields, `MISSING` for required values, `FORBIDDEN` for low-level robot payloads or unsupported peer operations, `INVALID_NUMBER` and `INVALID_FIELD_TYPE` for typed value failures, and `TOO_LONG` when the ordered plan exceeds eight steps.

`POST /api/fleet/do` OpenAPI describes either one intent step or an ordered
`steps` array containing 1 through 8 steps. Each step selects exactly one
supported `do` verb, exposes only that verb's fields, and rejects additional
properties. The schema is generated by `core_common.intent.request_schema()`
from the same verb table used by `interpret()`. Before dispatch, the interpreter
checks field types: non-finite or non-numeric values (including booleans in
numeric fields) return `400 INVALID_NUMBER`; mismatched string, integer, or
string-array fields return `400 INVALID_FIELD_TYPE`. Omit optional fields rather
than sending `null`. More than eight steps returns `400 TOO_LONG` before any CORE
dispatch. Verb-specific required fields and forbidden values remain checked by
the interpreter; OpenAPI does not replace those runtime checks.

The decision path is:

```text
authenticated intent
  -> role and typed-input validation
  -> append-only API audit + durable SQLite task
  -> Fleet-derived eligibility and priority
  -> existing per-robot CORE HTTPS REST contract
  -> explicit CORE receipt or UNKNOWN reconciliation
```

`QUEUED` means Fleet durably recorded the request and has not dispatched it.
`ACCEPTED` means CORE explicitly acknowledged receipt, not that execution began
or finished. `RUNNING`, `COMPLETED`, and `FAILED` require CORE navigation
events correlated to the current dispatch `attempt_id`; Fleet applies them to
the matching durable task history. A `nav.canceled` request event alone yields
`UNKNOWN` while the action result is pending. D-316 covers this Site Fleet
REST/event path; it does not activate D-297's PRT-004 envelope correlation or
ACK protocol. Any ambiguous result after dispatch stays `UNKNOWN` and is not
automatically retried. Fleet SQLite and append-only history remain the source
of truth. Priority is server-derived and never a public request field. Physical
stop evidence remains a separate readback.

Transport and payload ownership remain separate:

| Producer → consumer | Contract | Carries | Does not carry |
|---|---|---|---|
| Browser/operator → Site Fleet | HTTPS `/api/fleet/*`, per-principal Bearer (D-276) | typed task intent, idempotency key | DDS, command priority, raw video |
| Ceiling phone → overhead ingress | `rosy-overhead/1` WSS | latest JPEG frame, source-scoped credential | Fleet task or CORE command |
| Vision → Site Fleet | HTTPS sighting REST, `SiteSightingPayload` (D-257) | derived pose and map/calibration lineage | image bytes, caller-selected source, policy approval |
| CORE Agent → Site Fleet | existing PRT WebSocket `Envelope` | CORE heartbeat/event protocol | Site task queue state |
| Site Fleet → robot CORE | configured CORE HTTPS REST | CORE-supported robot request | direct DDS participation |

The PRT envelope's `protocol_version` remains `1.0`. `SiteSightingPayload` and
`FleetTaskStatus` are typed contracts but do not make their REST fields part of
the robot envelope. DDS remains inside CORE and robot runtime (D-59/D-269).

### 10.11 Fleet dispatch control and explicit rearm (D-330)

The Fleet task dispatcher starts closed on each process start. A site stop also
closes dispatch and advances a durable, monotonically increasing generation.
Claims are admitted only while dispatch is enabled and are stamped with the
current generation. A stop invalidates pre-send claims. A claim persisted as
`DISPATCHING` or `UNKNOWN` remains held until its result and resource state are
reconciled; rearm is refused while any such action claim remains.

| Method | Path | Authority | Result |
|---|---|---|---|
| GET | `/api/fleet/dispatch-control` | site viewer+ | `{authority_epoch, generation, dispatch_enabled, reason, queued_tasks, unresolved_actions, rearm_available}` |
| POST | `/api/fleet/dispatch/rearm` | named site operator (D-540 9, v1.161: reopening dispatch starts queued tasks) | explicitly opens dispatch at a new generation and attempts configured local OMX re-arm; stale generation, unresolved action, or any local re-arm failure returns 409 |

The rearm request is `{ "expected_generation": <integer >= 0> }`. The caller
must read the current generation and explicitly submit it. The response is the
new control state. The authority epoch advances at Fleet process startup; the
separate generation advances on startup hold, site stop, and successful rearm.
An old request cannot reopen a newer stop. Operator rearm is audited using the
normal mutation audit rule. If local OMX instances are configured, Fleet
attempts `RearmLocal` on each with the new epoch/generation and exposes their
receipts. Any missing/failed receipt re-trips Fleet dispatch and fans out a
local stop rollback. Empty OMX inventory remains `NOT_CONFIGURED`; this source
change does not enable Mission, policy, or the disabled-by-default OMX Action
runner.

Fleet rechecks the generation immediately before its CORE call. For configured
same-host OMX instances, it also sends `StopLocal` over the per-instance UDS and
includes `omx_local_stop` (`LOCAL_LATCHED`, `UNKNOWN`, or `NOT_CONFIGURED`) in
the stop response. These software latch receipts are not physical E-stop or
driver standstill proof. The existing CORE/mobile stop fanout remains
independent, and physical E-stop/readback remain separate.

The dedicated `POST /api/fleet/estop` requires an authenticated operator but
still sends the stop fanout if the audit store, dispatch-latch write, or queued
task cleanup fails. Fleet logs each failed durable step; the response reports
CORE request outcomes only and is not physical stop proof. Other mutations,
including goal and rearm, remain blocked with `503 AUDIT_STORAGE_UNAVAILABLE`
when their pre-command audit record cannot be written. The compound
`POST /api/fleet/do` continues to use the normal audit gate.

The current single-host dispatcher uses SQLite; there is no RabbitMQ API or
queue service in this release (D-271). If independent workers later require a
broker, its versioned message must identify the task and dispatch attempt, have
an expiry, and cause the consumer to re-read the authoritative task row.
Publisher confirmation/outbox recovery and consumer ACK ownership must be
specified and tested before deployment. A broker ACK is never a CORE receipt or
robot completion. Video frames, DDS streams, secrets, and raw physical command
payloads stay outside the generic work queue.

An API or message contract change updates this reference, the typed schema or
generated OpenAPI surface, implementation, and contract tests together. Add a
new PRT field only when the robot/Fleet protocol itself changes; do not version
the robot envelope for a site-only REST change. D-268 and field acceptance remain
prerequisites for any automatic source; a displayed sighting alone never
authorizes navigation or picking.

## 10.12 Site Fleet to OMX local Device Action contract (D-333, D-336)

This is a same-Linux-host, per-workcell Unix domain socket (UDS) contract. It is
not a robot REST route, Fleet-to-robot PRT message, ROS topic, or remote-host
API. The socket path is `/run/rosy/omx/{instance_id}/control.sock`; service-owned
directories and socket permissions are checked together with `SO_PEERCRED`
against the dedicated Fleet service UID. A bounded, versioned JSON frame has a
maximum encoded size of 64 KiB. Remote Fleet/OMX placement remains HOLD pending
the separate host-placement and device validation decisions in D-281/D-273.

The v1 `GetAction` request contains only `version`, `operation`, and `action_id`.
Its receipt includes `attempt_id`; Fleet compares the full receipt identity and
generation against the persisted grant before accepting that readback.
`DeviceActionLookup` is the identity-pair base for attempt-scoped operations
such as cancellation, not the v1 `GetAction` request shape. A lookup does not
resubmit or create an attempt.

Phased `PICK_PLACE` and `CELL_TRANSFER` receipts use UDS protocol v2 while
retaining the same six operation names. V2 adds at most four ordered `phase_summaries`, each containing
only fixed `phase_id`, `ordinal`, bounded ROS phase `state`, local
`journal_event_id`, and aware `observed_at`. It excludes ROS goal UUIDs, joint
trajectories, camera payloads, and planner scenes. Fleet requires v2 for
`PICK_PLACE` and `CELL_TRANSFER` submission, readback and cancellation, and
fails closed on a missing summary; it never falls back to v1.
V1 remains available to non-phased operations. Stop requests remain v1.
Every response — success or error — carries the version of the request it
answers; only frames rejected before version validation (bad JSON, framing,
an unsupported version) answer version 1.
Repeated phase snapshots are idempotently keyed by Mission/Action/attempt,
ordinal, and local journal event ID. Reuse with changed evidence conflicts;
older snapshots cannot regress the current phase projection.

Required operations are `SubmitAction(FleetActionGrant)`,
`GetAction(action_id)`, `CancelAction(DeviceActionCancelRequest)`,
`StopLocal(LocalStopRequest)`, `GetStopState(LocalStopQuery)`, and
`RearmLocal(LocalStopRearmRequest)`. Every request
and response is bound to the workcell and runtime instance. The submit grant
carries distinct `mission_id`, `step_id`, `action_id`, and `attempt_id`, a
SHA-256 request digest, `PICK_PLACE`, source and destination
`ResolvedTargetEvidence`, capability, configuration and observation revisions,
authority epoch, dispatch generation, and aware issue/expiry times. The two
object evidences must identify distinct objects in the same observation, image
digest, camera, optical frame, calibration, transform revision, and capture
time. Image evidence is not a 3D pose, grasp, reachability decision, or
permission to bypass the local planner.

D-403 adds the separate additive `FleetCellTransferGrant` variant with
`action_kind: CELL_TRANSFER`; it does not alter or widen `FleetActionGrant`.
Its bounded `cell_transfer` body binds `job_id`, recipe/cell SHA-256 revisions,
ordered `step_index`, item/pallet/layer, `frame: robot_base`, and finite `home`,
`pick`, and `place` poses with pick/place approach heights and `carry_z`. The
carry height must cover both approaches. This schema describes one atomic
pick-plus-place unit. It does not enable Fleet dispatch or certify that any
receiver executes the variant; the D-403 simulation gate remains in force.

D-779 §7 and D-780 §3, §5 add optional pair and barrier fields to the same variant
(v1.257). `arm_role` (`^[a-z][a-z0-9_]{0,31}$`), `pair_id` and `partner_instance_id`
(both present or both absent; the partner differs from `instance_id`) and `coupling`
(`independent`, `loose`, `tight`; only on a pair grant) sit on the grant. The
`cell_transfer` body may carry `barriers`, 1-4 entries of `{barrier_id, after_phase |
before_first_phase: true, coupling_after, max_wait_s}` in phase order, one per boundary,
with unique ids; `after_phase` is `approach`, `grasp` or `transfer` and `0 < max_wait_s <= 600`.
A barrier list requires a pair grant, and `coupling` must equal the strongest
`coupling_after` (`independent` without barriers), otherwise the grant is invalid.
Absent fields are omitted from serialization, so a single-arm grant serializes and
digests exactly as before; when present, the digest covers them.

D-781 §2 (v1.259) adds the optional `cell_transfer.sku` (`^[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}$`,
only with `item: "box"`): the recipe/3 item this step expects. It is omitted when absent,
so recipe/1-2 grants keep their bytes and digest. The owner looks up the accepted grasp
geometry (`grasp_width_m`, `grasp_depth_m`, `height_m`) by the payload's `item_key`:
`item` without a sku, `box:<sku>` with one. A recipe/3 recipe accepted by an owner holds
one geometry entry per sku under that key. The `pallet.transfer` Skill input keeps
`item: "box"`; the sku is a grant field only.

`DeviceActionState` is the durable local Action journal state: `PREPARED`,
`SUBMITTING`, `ACCEPTED`, `RUNNING`, `CANCEL_REQUESTED`, `UNKNOWN`, `SUCCEEDED`,
`FAILED`, or `HOLD`. A successful transport response or `SUCCEEDED` Action
journal entry is not independent Mission goal evidence and does not prove
object placement. Timeout or unknown acknowledgement is `UNKNOWN`; it never
authorizes an automatic re-submit. Read and cancel are fenced by the Fleet-
issued action/attempt pair.

Stop snapshots expose `OPEN`, `REQUESTED`, `LOCAL_LATCHED`, or `UNKNOWN`, with
request source (`fleet`, `operator_local`, or `coordinator` since v1.257) derived by the
trusted server. Caller-supplied stop principal is forbidden. `OPEN` means the software submission fence has been rearmed for the
reported generation. `LOCAL_LATCHED` is a middleware software fact; it is not a
driver standstill readback, safety-rated E-stop, or physical stop confirmation.
Physical stop and goal evidence remain separately sourced and correlated.
`RearmLocal(LocalStopRearmRequest)` is accepted only from the configured Fleet peer UID. Site Fleet may issue it only after an authenticated named-operator rearm request advances the shared dispatch generation; OMX independently requires the exact current Fleet authority/generation fence, zero unresolved local Actions, and a generation newer than its persisted latch. A Fleet rearm that cannot confirm every configured local instance rolls Fleet dispatch closed again and sends a local stop rollback. A process restart reopens neither Fleet nor OMX dispatch automatically. These checks coordinate software submission; they do not certify a physical E-stop reset or safe-to-move state.

#### OMX owner HOLD 복구 (D-442 U3)

owner recovery adapter를 가진 같은-host OMX 구성은 version 1의 `GetOwnerState`와 `RecoverOwner`를 추가로 제공한다. 기존 `RearmLocal`과 다른 owner HOLD 래치이며 preempt·motion 제출·물리 reset은 이 표면에 없다. Fleet peer UID만 허용한다. 모든 필드는 추가 필드를 거부하며 version·순번·generation은 실제 int(bool 제외)다.

- `GetOwnerState`: `{version:1, operation:"GetOwnerState", workcell_id, instance_id}`. 정확한 장치 identity와 `{state, reason, observed_sequence}`를 읽는다. 순번이 없으면 null이며 어떤 래치도 바꾸지 않는다.
- `RecoverOwner`: `{version:1, operation:"RecoverOwner", workcell_id, instance_id, authority_epoch, dispatch_generation, operator_confirmed:true, observed_sequence, actor_id}`. 확인은 실제 bool true, 순번/epoch/generation은 nonnegative int, actor는 Fleet가 인증한 이름 있는 operator identity다. 이름을 보냈다는 것만으로 사람 확인을 증명하지 않는다.
- local stop OPEN·현재 fence·미해결 Action 없음(PREPARED 포함)·선점 이후 fresh readback·operator 확인을 검사한다. stop→owner→journal 순서로 확인부터 복구까지 직렬화한다. journal commit 실패는 원래 owner HOLD를 같은 잠금 안에서 복원한다. 반환은 `decision`(accepted/state/reason), 정확한 장치·actor·readback identity이며 성공은 ready일 뿐 동작이나 물리 정지 증거가 아니다. 닫힌 fence/오래된 readback은 409, 저장소 실패는 503이다.

Fleet 표면은 `GET /api/fleet/workcells/{workcell_id}/owner`(viewer 읽기), `POST /api/fleet/workcells/{workcell_id}/owner/recover`(configured named operator만)다. POST 본문은 `{operator_confirmed:true, observed_sequence, expected_generation}`(strict bool/int, 추가 필드 금지). Fleet의 기존 durable INTENT/RESULT 감사 경로를 사용하고 저장 실패·닫힌 dispatch·미해결 Action·generation 불일치 시 UDS를 보내지 않는다. workcell은 configured OMX map에서 instance로 해석하며 사용자가 instance를 바꾸지 않는다. POST는 현재 epoch/generation과 인증된 actor를 UDS에 전달한다. ACK의 identity·순번·ready 상태를 검사하고 잃거나 불명한 ACK를 자동 재전송하지 않는다.

#### OMX 작업대 조율자 peer와 barrier (D-780)

양팔 작업대의 owner는 설정 `coordinator_peer_uids`(기본 비어 있음)와 `coordinator_liveness_s`를 가진다. 목록이 비어 있으면 아래 연산과 검사는 없고, `GetBarrier`·`ReleaseBarrier`는 지금처럼 404 `UNKNOWN_OPERATION`이다. 조율자 UID는 Fleet UID와 달라야 한다. 연산별 허용 주체는 다음과 같다.

| 연산 | Fleet | 조율자 |
|---|---|---|
| `SubmitAction`, `CancelAction`, `RecoverOwner`, `RearmLocal` | 허용 | 403 `COORDINATOR_NOT_ALLOWED` |
| `GetAction`, `GetOwnerIdentity`, `GetOwnerState`, `GetStopState` | 허용 | 허용(읽기, `GetAction`은 principal 검사 없이 읽는다) |
| `StopLocal` | 허용, 출처 `fleet` | 허용, 출처 `coordinator`, `reason`은 `PARTNER_FAILED`·`PARTNER_UNKNOWN`·`PARTNER_LINK_LOST`·`BARRIER_TIMEOUT` 가운데 하나(아니면 400) |
| `GetBarrier`, `ReleaseBarrier` | 403 `COORDINATOR_PEER_REQUIRED` | 허용(version 2) |

- `GetBarrier`: `{version:2, operation:"GetBarrier"}`는 이 owner의 미해결 짝 Action 목록 `actions`를, `action_id`를 더하면 그 Action 하나 `action`을 돌려준다. 항목은 Action·attempt·workcell·instance identity, `arm_role`, `pair_id`, `partner_instance_id`, `coupling`, 지금 구간의 결합 `coupling_now`, 이 owner의 정지 래치·Fleet fence가 그 generation에서 열려 있는지 `fence_open`, epoch·generation, `action_state`, 움직인 phase 여부 `moved`, 그리고 barrier마다 정의와 `gated_phase`, `state`(`not_reached`, `waiting`, `released`, `expired`), `arrived_at`, `released_at`이다.
- `ReleaseBarrier`: `{version:2, operation:"ReleaseBarrier", action_id, pair_id, barrier_id, authority_epoch, dispatch_generation, partner_arrival:{instance_id, action_id, arrived_at}}`. owner는 grant의 `pair_id`(409 `PAIR_MISMATCH`), 계획의 barrier(404 `BARRIER_NOT_IN_PLAN`), grant의 epoch·generation과 지금 stop·Fleet fence(409 `FENCE_STALE`), 도착(409 `BARRIER_NOT_REACHED`), 만료(409 `BARRIER_EXPIRED`)를 더 움직일 수 없는 Action(`HOLD`, `UNKNOWN`, 종료; 409 `ACTION_NOT_ACTIVE`), owner 재시작 전에 기록된 도착(409 `BARRIER_STALE_BOOT`)을 확인한 뒤 해제를 기록한다. 이미 해제된 barrier는 저장된 해제를 `created:false`로 그대로 돌려준다. 짝의 도착과 조율자 주체 `coordinator-uid-<uid>`는 추적용으로 기록한다. 조율자는 두 owner가 모두 도착했고 둘 다 `fence_open`일 때만 해제하며, 한쪽만 해제된 채 다른 쪽이 거절되면 단단한 결합 구간에 들어간 팔에 곧바로 결합 정지(`PARTNER_FAILED` 또는 `PARTNER_UNKNOWN`)를 보낸다.
- barrier에 이른 실행기는 다음 phase를 내지 않고 Action event `PHASE_WAIT`(barrier, 도착 시각)를 남긴다. ROS 목표가 없으므로 목표 시간 한계는 적용되지 않는다. owner의 주기 점검이 해제를 읽고 다음 phase를 낸다. 처음 phase 앞의 barrier에서 기다리는 Action은 `SUBMITTING`으로 보인다.
- `max_wait_s`가 지나면 움직인 phase가 없는 Action은 `FAILED`(`BARRIER_TIMEOUT`)로 끝나고 owner는 멈추지 않는다. 움직인 phase가 있으면 owner HOLD다. HOLD는 출처 `coordinator`의 로컬 정지 래치와 Action HOLD이며, 지금처럼 운영자 확인으로만 풀린다. barrier에서 기다리는 동안 정지 래치나 authority fence가 닫히면 그 Action은 곧바로 끝난다(움직인 것이 없으면 `FAILED`, 있으면 HOLD, 이유 `STOP_FENCED_AT_BARRIER`). 짝 팔은 이를 `PARTNER_FAILED`로 읽는다.
- `coupling_after: tight`인 barrier가 해제된 뒤부터 다음 barrier가 결합을 늦출 때까지, 조율자 UID의 요청이 `coordinator_liveness_s`(0.5 s 이상, 기본 2 s)보다 오래 없으면 owner는 출처 `coordinator`, 이유 `PARTNER_LINK_LOST`로 HOLD한다.
- 조율자가 없는 owner는 `pair_id`나 `barriers`가 든 grant를 journal 기록 전에 409 `BARRIERS_UNSUPPORTED`로 거절한다. 이 표면은 소프트웨어 제출 동기이고 물리 정지나 E-stop 증거가 아니다.

현재 이 recovery 표면은 OMX cell simulation composition에 연결된다. 실제 ROS/UDS·물리 장치 수용은 별도 증거이며, 이 API를 추가했다고 hardware owner를 켜지 않는다.


The source now provides a newline-delimited JSON UDS handler and local Action runner. Each connection carries one request frame, capped at 64 KiB, and peer UID is read from Linux `SO_PEERCRED`; the parent socket directory must already be provisioned. `request_digest` is lowercase SHA-256 over UTF-8 canonical JSON of the complete `FleetActionGrant` with `request_digest` omitted (sorted keys, compact separators, Pydantic JSON-mode ISO-8601 timestamps). The runner is disabled by default, journals before driver submission, and never replays an Action already in `SUBMITTING`, `UNKNOWN`, or later. These source modules do not register a service entrypoint, connect a selected ROS/gripper driver, or provide physical stop/goal proof; those remain gated by ROS-SIM, DEVICE, and FIELD.

`DeviceActionReceipt` binds every local readback to the same mission, step, action,
attempt, workcell, instance, request digest, authority epoch, dispatch generation,
journal event ID, and observed time. Site Fleet has one background Mission dispatcher;
it is disabled by default and can be constructed only with the complete Mission API,
shared persistent database, explicit OMX workcell/instance map, and a local Action
transport. Admission and provider proposal handlers never call the device API.
Before first submit, Fleet persists the exact grant and IDs while atomically moving
the Mission from `READY` to `RUNNING`. A process restart reads that stored grant and
calls `GetAction`; it does not regenerate IDs or replay `SubmitAction`. Lost
acknowledgement becomes Fleet `HOLD` with claims retained while one durable
reconciliation is pending. A readback that is missing or remains nonterminal clears
that one reconciliation attempt and leaves the Mission held for operator review.
An Action terminal success advances only to `ACTION_SUCCEEDED`; independent goal
evidence is still required for Mission completion. Goal confirmation is an internal
Fleet service operation and requires an explicitly injected trusted producer
verifier; no producer is registered by default, so completion fails closed. Evidence
must identify the current Action/attempt, a post-action frame with a new observation
ID and digest, the evaluator revision, and a separately identified post-action
gripper `OPEN` readback. The verifier is responsible for producer authentication
and current camera/calibration/evaluator revision checks. Model prose and the input
frame used to propose the task cannot confirm placement. Invalid or stale evidence
records HOLD and does not release Mission claims. No device, physical stop, or
manipulator acceptance follows from enabling this source worker.

## 10.13 Fleet proposal, Mission draft, and operator admission (D-333/D-334)

These Site Fleet routes are separate from `/api/v1/fleet/missions` on robot CORE.
They require the Site Fleet named-user authorization and persistent audit store.
The authenticated principal is server-derived; proposal data cannot supply an
actor or principal. Candidate metadata is limited to 32 KiB, retained for 30
days, and never includes source image bytes, provider credentials, or auth tokens.
Resolved Mission metadata is limited to 64 KiB and rejects the same secret/image fields.

| Method | Path | Role | Meaning |
|---|---|---|---|
| POST | `/api/fleet/proposals` | Operator; `service` for `cell_job` only | Store one immutable, idempotent candidate under `(principal_id, request_key)`; performs no model call or device submission. A cell service cannot submit ER 2 candidates; operators cannot submit Cell Jobs. |
| GET | `/api/fleet/proposals/{proposal_id}` | Viewer | Read the caller-owned candidate and resolution status; a named operator may inspect a Cell Job proposal. D-763 4 review: a Cell Job proposal follows the `GET /api/fleet/cell-jobs/{mission_id}` scope — the proposer; any operator once its Job is not `PROPOSED`; only a named operator for another principal's unresolved or `PROPOSED` one. A reader who is not the proposer gets no `proposal_principal_id` in `mission` and sees the proposer as `actor_id: "proposer"` in events. Any other proposal is the caller's own only. Others 404 `PROPOSAL_NOT_FOUND`. |
| POST | `/api/fleet/proposals/{proposal_id}/resolve` | Operator; `service` for `cell_job` only | Recheck current evidence/capability through the injected resolver or recompile a Cell Job through the process compiler port; create a proposal-only Mission draft and ordered steps. |
| GET | `/api/fleet/missions/{mission_id}` | Viewer | Read caller-owned candidate, Mission state, and Fleet Mission event history. |
| POST | `/api/fleet/missions/{mission_id}/admit` | Named Operator | Recheck evidence and revisions, then atomically acquire the shared workcell/object claims at `expected_generation`. Who may admit comes from the step-kind registry (D-763 item 7). v1.240 (D-763 4 review): the returned Cell Job is redacted for a caller who is not its proposer, as in `GET /api/fleet/cell-jobs/{mission_id}` (no `proposal_principal_id`; the proposer's events read `actor_id: "proposer"`). |
| POST | `/api/fleet/missions/{mission_id}/reject` | Named Operator | v1.230 (D-763 5b). Body `{expected_generation}`. End a `PROPOSED` Cell Job (HOLD/`CANCELLED_BY_OPERATOR`) or legacy Mission (`CANCELED`) without approval and without claims; the proposer withdraws (`WITHDRAWN_BY_PROPOSER`), another named operator rejects (`REJECTED_BY_OPERATOR`). Not `PROPOSED` or stale generation: 409 `MISSION_REJECT_REFUSED`. v1.240 (D-763 4 review): the returned Cell Job is redacted for a caller who is not its proposer, as in `GET /api/fleet/cell-jobs/{mission_id}` (no `proposal_principal_id`; the proposer's events read `actor_id: "proposer"`). |
| GET | `/api/fleet/cell-jobs/{mission_id}` | Viewer | Read the resolved Cell Job, ordered step states, and Fleet journal events; a named operator may inspect another principal's Cell Job. v1.237 (D-763 4): the same scope as the work list — the proposer; any operator for a Job that is not `PROPOSED`; only a named operator for another principal's `PROPOSED` Job (others 404 `CELL_JOB_NOT_FOUND`). A reader who is not the proposer gets no `proposal_principal_id` and sees the proposer as `actor_id: "proposer"` in events. |
| POST | `/api/fleet/cell-jobs/{mission_id}/reconcile` | Named Operator | Read the current step back from the OMX owner now (GetAction), ignoring the readback backoff. 503 when the dispatcher is disabled. v1.240 (D-763 4 review): the returned Cell Job is redacted for a caller who is not its proposer, as in `GET /api/fleet/cell-jobs/{mission_id}` (no `proposal_principal_id`; the proposer's events read `actor_id: "proposer"`). |
| POST | `/api/fleet/cell-jobs/{mission_id}/resume` | Named Operator | Body `{expected_generation}`. Re-approve a HOLD Job under the current fence: the first unconfirmed step becomes READY (or ACTION_SUCCEEDED if its last device outcome was a success; it is never resent), claims are re-taken at the new generation. Refused (409) while a claim is DISPATCHING or UNKNOWN, or for a cancelled Job. v1.240 (D-763 4 review): the returned Cell Job is redacted for a caller who is not its proposer, as in `GET /api/fleet/cell-jobs/{mission_id}` (no `proposal_principal_id`; the proposer's events read `actor_id: "proposer"`). |
| POST | `/api/fleet/cell-jobs/{mission_id}/arms/{arm_role}/resume` | Named Operator | v1.258 (D-779 §6). Body `{expected_generation}`. Multi-arm Job only: return one `HOLD`/`OFFLINE` arm to `READY` under the current fence and release its `HELD` arm and zone claims; its Action whose last device outcome was a success stays `ACTION_SUCCEEDED` and is never resent. Refused (409 `CELL_JOB_RECOVERY_REFUSED`) for a single-arm Job, an unknown or unheld arm, a cancelled Job, a changed stop generation or authority (resume the whole Job), a `DISPATCHING`/`UNKNOWN` claim of that arm, and an arm held `TIGHT_PARTNER_HELD` while its tight partner is still `HOLD`/`OFFLINE`. The returned Cell Job is redacted as for `/resume`. |
| POST | `/api/fleet/cell-jobs/{mission_id}/cancel` | Named Operator | End the Job: status HOLD with reason `CANCELLED_BY_OPERATOR` (terminal; no CANCELLED status until the D-420 v2 schema) and its claims released in the same transaction. Refused while a claim is DISPATCHING or UNKNOWN. v1.240 (D-763 4 review): the returned Cell Job is redacted for a caller who is not its proposer, as in `GET /api/fleet/cell-jobs/{mission_id}` (no `proposal_principal_id`; the proposer's events read `actor_id: "proposer"`). |
| GET | `/api/fleet/resource-claims` | Viewer | `{claims: [{resource_key, resource_kind, resource_id, owner_kind, owner_id, generation, phase, mission_id, job_status, job_reason}]}`; `mission_id`/`job_status`/`job_reason` are set when a Cell Job owns the claim, otherwise null. `phase` is CLAIMED, DISPATCHING, UNKNOWN or HELD (a held Cell Job; the stop latch keeps it, rearm ignores it). v1.240 (D-763 4 review): a viewer gets only `{resource_key, resource_kind, resource_id, phase}` per claim. An operator gets the full row for a Cell Job claim (`job_status` not null). Any other claim (legacy Mission, Task, direct action) is full only to the proposer of the legacy Mission that owns it, and reduced to the viewer fields for everyone else. |

`POST /api/fleet/proposals` accepts `request_key`, `workcell_id`, `instance_id`,
and either an ER 2 selector candidate or a service-owned `cell_job` candidate.
The Cell Job candidate contains `recipe`, `cell`, `recipe_sha256`,
`cell_sha256`, and submitted compiled `job`; its metadata limit is 64 KiB
(ER 2 remains 32 KiB). Fleet recompiles with the injected process compiler and
rejects a Job or digest mismatch. Recipe/Cell calculations remain outside
Fleet. Multi-arm proposals are described below. Its authenticated owner and request scope are
stored by Fleet; duplicate same-content requests return the existing proposal,
while reuse with a changed candidate or workcell/instance returns `409
REQUEST_CONFLICT`. The API does not call ER 2. Candidate records allow only
selector/provenance metadata and reject principal, credential, and image-payload
fields.

**Multi-arm proposal path (recipe/3, D-781 §5, D-779 stages 2-4; v1.259).** A
`cell_job` candidate whose `recipe.schema` is `rosy_cell.recipe/3` has the same envelope
`{kind, recipe, cell, recipe_sha256, cell_sha256, job}`. Its `cell` is the provisional
`rosy_cell.cell/3` document with `arms[{role, instance_id, workcell_id, base_in_cell, zone_id,
home}]`. Its `job` is `{recipe_hash, cell_hash, planner_version, plan_digest,
submission_version, plan}`, where `plan.steps[]` carry `sku`, `arm`, `alternates`, `zone`,
`coupling`, `depends_on`, `pose_cell` and `carry_z`, and `plan.feed_order` gives the order
per pick station. Resolve runs the process compiler's `compile_mixed` and refuses a Job
or digest mismatch as for recipe/1-2. It also refuses a cell with fewer than two arms (a
one-arm recipe/3 Job is not defined yet) and an `instance_id` that is not one of the cell's
arm instances. The proposal's `workcell_id` is the cell's own workcell. The resolved
multi-arm submission is:

- `job_id`: SHA-256 over canonical `{recipe_sha256, cell_sha256, job}`, as for a single-arm Job.
- `arms`: `[{role, instance_id, workcell_id}]` in cell order (2-4 arms; roles, instances and
  owner workcells are distinct).
- `steps`: one per plan step, `{skill_id: "pallet.transfer", version: "1.0.0", placement,
  goal_predicates?}`. `placement` is `{arm, alternates, zone, coupling, depends_on, actions}`.
  `actions` maps every primary and alternate role to its `pallet.transfer` inputs in that
  arm's base frame, with `sku`. A coordinated step (`arm` is a list of two roles) has no
  alternates. `goal_predicates` maps the same roles to the `item_at_pose` predicate in that
  arm's frame; it is present when a goal tolerance is configured.
- `resources`: `["workcell", <cell>]`, `["workcell", <each arm owner>]` and
  `["pallet", <id>]` per filled pallet. Arm and zone claims are taken per Action (D-779 §5).
- `ledger_markers` (one per pallet, after its last step), `recipe_digest`, `cell_digest`
  and `process_artifact_digest`.

The Job is stored `PROPOSED` with per-arm rows. A read adds `arms`, `placements` (with
`assigned`, the arm(s) that run the step) and `step_actions`. Admission, two-person
approval and dispatch are unchanged. A held single-arm step may go to a `READY`
alternate (`CELL_STEP_ALTERNATE_ARM` event), whose own payload and predicate are then used.

ER 2 feedback candidates use the same proposal read/resolve routes. Their
response adds `source_mission_id`, `source_action_id`, `source_attempt_id`,
`source_dispatch_generation`, `source_event_watermark`,
`source_observation_id`, and `supersedes_mission_id`. Fleet writes this row only
after one SQLite `BEGIN IMMEDIATE` transaction rechecks the active dispatch
latch/generation, source Mission/action/attempt, latest event watermark, and a
post-action observation captured no more than 30 seconds before candidate
commit. A later stop/generation change or
source event makes the candidate non-resolvable. Operator resolution creates a
separately identified `PROPOSED` successor Mission with
`supersedes_mission_id`; it never changes the source Mission. The successor
still requires the ordinary admission gate. Image bytes are used for model
reasoning only and are never persisted in proposal metadata.

ER 2 resolution is available only when a trusted current-observation and capability
resolver is explicitly injected into the Site Fleet app. It receives the stored
candidate, requested workcell/instance, and current time; it must verify image
digest, camera/frame, capture time, calibration/transform/config revisions,
freshness, unique target and destination, and capability. Missing resolver,
stale or ambiguous evidence, or changed revisions fail closed. Resolution
stores a target/goal predicate and shared resources in the Fleet Mission journal;
it does not submit a device Action. Cell Job resolution stores canonical
PlanBundle data as ordered `CELL_TRANSFER` rows in the versioned `cell_jobs`
journal; the legacy single-step `PICK_PLACE` table and digest are unchanged.
Admission recompiles and compares the ordered plan, then atomically claims the
workcell and every pallet for the complete Job. Only step zero becomes `READY`;
later steps remain `WAITING` until the prior step receives independent goal
confirmation. The Cell Job journal is not connected to a device dispatcher in
this source slice.

Admission requires a configured named operator credential; the development
fallback principal is refused. The server re-resolves the candidate and compares
the resulting target, goal predicate, revisions, and resource set with the
stored draft before the atomic generation check and claim acquisition. Stale
generation or any existing navigation/direct-action/workcell/object claim
returns `409` with no new claim. General mutation audit failure returns `503`
before proposal or admission mutation. The synchronous admission response reports
`physical_submission: NOT_CONNECTED`: admission itself is only a claim transaction.
For Cell Jobs, the approving operator must have a different principal ID from
the service proposer. This rule is read from the step-kind registry
(`step_action_kinds`, D-763 item 7): `CELL_TRANSFER` is two-person; legacy
`PICK_PLACE` stays proposer-only (other principals get 404) until the slice that
connects its physical dispatch. Changed compilation, changed generation, or resource
conflict leaves the Job unadmitted and creates no claim. If the separately configured, explicitly enabled background dispatcher is running,
it may later submit one fenced local Action. Neither response proves ROS goal
completion, software stop, driver standstill, object placement, or physical E-stop
state.


## 10.14 Mission progress snapshots and event cursor

These Site Fleet read routes are scoped to the authenticated proposal owner and
require the Viewer role. The robot CORE Mission API is a separate interface.

| Method | Path | Role | Meaning |
|---|---|---|---|
| GET | `/api/fleet/missions/{mission_id}` | Viewer | Return the owner-scoped Mission, progress axes, and up to 50 most recent journal events from one SQLite read snapshot. |
| GET | `/api/fleet/missions/{mission_id}/events?after_event_id={id}&limit={n}` | Viewer | Read a bounded Mission event page in Fleet journal ID order; `limit` defaults to 50 and is restricted to 1..200, with each event detail limited to 16 KiB of JSON. |

`progress` contains `snapshot_event_id`, `snapshot_at`, and five independently
sourced axes: `mission`, `step`, `action`, `goal_evidence`, and `stop`. Each axis
contains `state`, `source`, nullable `last_event_id`, nullable `observed_at`,
nullable `revision`, `freshness` (`CURRENT`, `FRESH`, `STALE`, or `UNKNOWN`), and
nullable `reason`. Action readback without a timestamp is `UNKNOWN`; an Action
success without a matching goal event leaves `goal_evidence` as `PENDING`.
Fresh negative evidence from the registered independent evaluator is shown as
`UNSATISFIED` and holds the Mission with `GOAL_NOT_SATISFIED`; rejected or stale
evidence remains `REJECTED` and cannot be interpreted as a negative result.
`stop.state` is `DISPATCH_ENABLED` or `DISPATCH_BLOCKED` and represents only
Fleet's dispatch-control latch. `physical_state: UNKNOWN` is returned because
this API does not receive an independent physical
stop readback. No percentage is returned because no physical-progress measure
is available.

The Mission response returns at most 50 recent events and includes
`history_truncated`. When true, older events were omitted or removed by a
retention policy; clients use the cursor endpoint to page the retained journal.
The snapshot still computes its Action and goal axes from the latest events for
the current `action_id`/`attempt_id`, even when those events are older than the
recent-history window.

Clients read the snapshot first and continue with
`after_event_id=progress.snapshot_event_id`. Event IDs describe Fleet journal
insertion order, not device timestamps or attempt recency. Clients ignore IDs at
or below their stored cursor and apply Action/goal events to the current view
only when their action/attempt pair matches the active attempt in the latest
snapshot. A late report from an older attempt can have a larger Fleet event ID.
`snapshot_event_id` in an event page is that read's high water mark;
`next_after_event_id` is the last returned event ID, or the supplied cursor when
the page is empty.

Mission event rows are retained for the lifetime of the Mission; v1 has no
automatic pruning. The per-Mission `cursor_floor` starts at zero and advances
only if a future retention process removes older entries. A cursor below that
floor returns `410 MISSION_CURSOR_EXPIRED`; a cursor above the current high water
mark returns `409 MISSION_CURSOR_RESET_REQUIRED`. Both responses include a fresh
snapshot and `snapshot_restart_required: true`. Missing or non-owned Missions
return `404` in both routes. WebSocket/subscription delivery is not part of this
contract.

Fleet can build an internal model context from the same snapshot after matching
the authenticated principal and workcell. It contains only Mission/step/Action/
goal/stop states and bounded reasons; it excludes object selectors, raw
observations, evidence payloads, and credentials. This context is consumed by an
internal ER 2 feedback adapter. It is not a public `get_mission_status` route.
The read-only status result also contains up to four ordered phase summaries
and `active_phase` from the durable Fleet event journal. These fields describe
local progress only and cannot submit, cancel, stop, rearm, or confirm a Mission.

## 10.15 ER 2 Mission feedback tools and outbox (D-357/D-358)

ER 2 feedback tools are provider-internal function declarations; they are not
authenticated Fleet REST routes and do not add a public control surface. The
allowlist contains `get_mission_status` and `propose_replan`. The former reads
the Mission already bound to the trusted turn scope. The latter declaration is
limited to a trigger event watermark and rationale; Fleet obtains the actual
observation ID from its trusted post-action reader rather than asking ER 2 to
guess an ID it has not been shown. Its candidate write
remains unavailable because no trusted fresh post-action observation source is
wired to Fleet. Before any future candidate path is enabled, it must use an
atomic stop/candidate transaction. It does not write an Action, admit a Mission, issue a motor/gripper
command, cancel, stop, or rearm. Fleet validates each tool call and returns a
bounded structured result. Unknown tools and malformed arguments are rejected.

Every turn scope is captured by trusted Fleet code and binds principal,
workcell, Mission, active Action/attempt, Mission dispatch generation, event
watermark, model-policy revision, and outcome policy. The separately built
feedback context adds current stop generation, authority epoch, per-axis
evidence source/freshness, and snapshot/observation timestamps. A replan context is invalid if the current stop generation
does not equal its Mission dispatch generation. Provider arguments cannot select
or widen these identities. A fresh `UNSATISFIED` state remains status-only until
Fleet has a trusted source for a new post-action image and candidate resolution;
`propose_replan` currently returns unavailable when that observation is missing.
The feedback context is capped at 8 KiB; tool arguments
and results at 4 KiB each; one turn allows at most four function calls, eight
replay steps, 64 KiB of replay and response, a 45-second request deadline, and
14 MiB per image. The configured estimated-turn cost ceiling is USD 0.10.
Missing provider project/service-tier, mission-progress, mission-instruction,
workcell, or task-class approval, or an acceptable cost estimate denies egress
before transport. The full Mission instruction is classified separately from
the structured progress fields. The outbox has a hard row cap configured when
`create_app()` is constructed through `mission_model_turn_max_rows` (default
10,000). At capacity, a trigger is dropped for each enqueue attempt,
the global cursor advances, and a durable counter plus error log records the
drop. Raising the configured cap is required to resume future enqueueing;
already dropped triggers are not replayed. A worker also requires a current-principal authorization callback;
absent authorization is denied. Its pre-submit SQLite transaction rechecks the
stop latch/generation, Mission owner/workcell/action/attempt/state, and exact
event watermark. Production policy loading and provider runtime wiring remain
disabled.

Interactions requests use `store=false`. Each tool-result request replays the
original user input, the exact model steps received so far, and the matching
function results. Replay data and opaque provider step material exist only in
turn memory. The SQLite model-turn outbox stores only trusted scope references,
watermarks, policy revision, and lifecycle state. Its state path is
`PENDING -> CLAIMED -> SUBMITTING -> RESPONDED | REJECTED | UNKNOWN`, with an
explicit `SUPPRESSED` state. A pre-transport policy/validation failure may
return a claim to `PENDING`. Once submission begins, a timeout or lost response
becomes `UNKNOWN` and is not automatically resubmitted. Stop-generation
suppression is atomic with provider submission admission; candidate fencing is
not implemented because candidate creation is unavailable. The scheduler polls
durable Mission events and fills the outbox; no provider worker is configured,
so this does not initiate model calls. Production provider configuration
remains disabled. A worker response would currently be marked `RESPONDED`
without storing or exposing model text; no user-visible model feedback channel
is implemented. No provider status or tool result changes Mission, Action, goal,
or physical stop state.

This source implementation enables event-to-outbox scheduling only; it does not
enable provider calls or policy dispatch. Fleet admission remains a separate operator/policy gate;
Action execution remains with the device-local controller; the independent
goal verifier and physical stop owner remain authoritative for their respective
evidence. `POLICY_DISPATCH_ENABLED` remains false.

## 10.16 Fleet goal-evidence producer contract (D-348)

The route is exposed only when Fleet Mission API composition includes a valid
goal-evidence producer registry. It does not enable ER 2 calls, automatic policy
dispatch, Mission Action dispatch, ROS, or a manipulator driver. The registry is
read-only YAML: each producer is scoped to one `workcell_id` and `predicate_id`,
exact object/destination IDs, `camera_observation`, an allowlist of evaluator
revisions, server-enforced `max_age_s`, a missing-evidence `grace_s`, and an
aware `valid_until`. YAML stores only a `token_env` name; the credential is read
from the process environment and never returned in a response.

| Method | Path | Credential | Meaning |
|---|---|---|---|
| POST | `/api/fleet/goal-evidence` | `X-Goal-Evidence-Token` | Submit `{ "mission_id": "?", "evidence": {?} }` from a registered independent producer. |

The evidence object must match the existing `GoalEvidence` contract, including
the producer ID, approved evaluator revision, current Mission Action/attempt,
new post-action observation, and independent gripper `OPEN` readback. A fresh,
registered `satisfied: true` predicate records `GOAL_CONFIRMED`. A fresh,
registered `satisfied: false` result is preserved as
`GOAL_PREDICATE_UNSATISFIED` and holds the Mission as `GOAL_NOT_SATISFIED`;
malformed, stale, untrusted, or mismatched evidence remains
`GOAL_EVIDENCE_REJECTED`. Negative evidence is never completion proof. Producer
credentials are separate from Site Fleet user roles. A
`viewer` can read Mission state, an `operator` can admit a draft, and registry
administration remains a deployment-controlled read-only file change; the
producer token cannot create or admit a Mission.

Accepted evidence is persisted in the same SQLite database as Mission state.
`evidence_id` is idempotent for identical content and conflicts if reused with
different content. The server records `received_at`; caller timestamps do not
set freshness policy. Invalid/rejected raw evidence is not stored. Evidence
received before action terminal readback stays pending and is checked when the
matching terminal success arrives. Evidence submitted after success is checked
immediately. Missing evidence remains pending through the registered grace
period and then moves the Mission to `HOLD` with `GOAL_EVIDENCE_TIMEOUT`;
stale, mismatched, untrusted, or conflicting evidence cannot produce
`GOAL_CONFIRMED` or release claims. HTTP errors include `401
PRODUCER_UNAUTHORIZED`, `404 MISSION_NOT_FOUND`, `409` scope/replay/rejection
codes, and `422 INVALID_GOAL_EVIDENCE_ENVELOPE`.

This route is independent of the software stop API. It never reports physical
stop, gripper, placement, or hardware acceptance unless the trusted producer
supplies the corresponding separately sourced evidence. SOURCE/LOCAL tests use
fake credentials and clocks; device and field acceptance remain separate gates.

## 10.17 Cell goal-evidence producer contract (D-413)

Exposed only when the existing Fleet app is composed with `cell_goal_registry`,
a persistent Cell Job compiler/API and `deployment_profile="simulation"`
(`sim_model_pose` is simulation-only evidence, D-403 §5); any other profile
refuses at startup. There is one Cell journal and one site dispatch worker
(`StepJobDispatcher`, C4b).

| Method | Path | Credential | Body |
|---|---|---|---|
| POST | `/api/fleet/cell-goal-evidence` | `X-Goal-Evidence-Token` | `CellGoalEvidenceSubmission`: `{ "mission_id": "...", "evidence": {...} }` |

The shared strict contract is `core_common.protocol.cell_goal_evidence`, exposed
through `core_common.protocol.schemas.CellGoalEvidenceSubmission`. All fields
are required; additional fields, Boolean step indices, nonfinite numbers and
whitespace/control characters in identifiers are rejected. The evidence includes:

| Fields | Meaning |
|---|---|
| `producer_id`, `evidence_id`, `evidence_source`, `evaluator_revision` | Registered producer, immutable evidence identity, literal `sim_model_pose`, pinned evaluator revision. |
| `job_id`, `step_id`, `step_index`, `action_id`, `attempt_id`, `request_digest`, `recipe_sha256`, `cell_sha256` | Exact persisted canonical CELL_TRANSFER grant and ordered step. Digests are lowercase 64-character SHA-256 values. |
| `model_id` | Attempt model identity: `cell_` followed by the saved Action ID. The independent evaluator must bind that model to the physical item and pinned recipe/cell. |
| `observation_id`, `observation_digest`, `evidence_revision`, `observed_at`, `model_pose_base` | Final independent model observation, provenance and robot-base pose. |
| `initial_observation_id`, `initial_observation_digest`, `initial_observed_at`, `initial_model_pose_base` | Initial independent observation after grant issuance and before terminal success. |
| `gripper_state`, `gripper_evidence_id`, `gripper_evidence_revision`, `gripper_observed_at` | Separately sourced post-terminal gripper `OPEN` readback. |

There is no `satisfied` field (C4b merge, 2026-10-03): a producer reports
observations only. Fleet judges `model_pose_base` against the `item_at_pose`
predicate stored in the step at resolution (target, xy/z/yaw/tilt tolerances and
their basis) and confirms the step only when it is met, after the step's durable
device `SUCCEEDED` for the same attempt. A submission carrying `satisfied` is
rejected (422).

v1.258 (D-779 §3): for a multi-arm Cell Job the evidence names the Action of the
arm the step's predicate was compiled for (the placement's first primary arm), the
producer is registered for the Job's cell `workcell_id` and that arm's
`instance_id`, and the step is judged on its own (not by `current_step_index`). A
coordinated step is confirmed only when every assigned arm Action's latest device
outcome is its attempt's `SUCCEEDED`; the final observations follow the last of
those successes and the initial one follows every arm's grant and precedes the
first success. A step run by an alternate arm is refused
(`EVIDENCE_SCOPE_MISMATCH`) until a per-arm predicate exists.

v1.259 (D-781 §5): the predicate arm is the step's first assigned arm. That is the first
primary arm, or the alternate that took the step. The step is judged against the
predicate stored for that arm (`goal_predicates[arm_role]`, in that arm's `robot_base`).
The producer must be registered for that arm's `instance_id`. A step run by an alternate
arm is accepted when its predicate exists. Without it the step is refused with
`CELL_GOAL_PREDICATE_MISSING` (409). A single `goal_predicate` is in the first primary
arm's frame and never judges an alternate.

Both poses require finite `x_m`, `y_m`, `z_m`, `roll_rad`, `pitch_rad`, `yaw_rad`.
Observation timestamps are nonnegative epoch seconds. The read-only YAML registry
pins producer/workcell/instance/recipe/cell/evaluator identities, `max_age_s`
(positive, at most 60 seconds), timezone-aware `valid_until`, and environment-only
`token_env`. Producer credentials must differ from user, robot, discovery,
Vision, pairing, policy and legacy goal producer credentials. They cannot propose,
admit, rearm or dispatch a Job.

The service matches evidence to the saved grant, checks registry scope/expiry and
freshness using server receipt time, and requires final model and gripper samples
after the local terminal success. Evidence received before terminal readback stays
`PENDING_ACTION_TERMINAL`; the composed dispatcher revalidates it after recording
the exact successful receipt. Rejected pending evidence retains the successful
Action record and claims. Placement geometry belongs to the pinned independent
evaluator, rather than Fleet journal arithmetic.

Already available invalid/preterminal evidence is rejected before persistence.
Accepted evidence IDs are immutable and replay identical content idempotently.
Completion rechecks the exact latest terminal event ID inside its SQLite
transaction. A concurrent newer terminal cannot complete a step using older
samples. Intermediate completion returns `READY` or `HOLD` depending on the live
site fence; only every ordered goal confirmed releases claims and returns
`GOAL_CONFIRMED`. Goal confirmation never rearms dispatch. Errors include `401
PRODUCER_UNAUTHORIZED`, `404 MISSION_NOT_FOUND`, `409` scope/conflict/invalid-evidence
codes, and `422` strict envelope validation errors. Responses never include tokens.

This contract and host tests establish SOURCE/LOCAL composition. Independent
Gazebo placement evaluation, the actual OMX owner/provider and ROS-SIM, device
and field acceptance require their own evidence.

## Fleet Cell 작업 화면 (D-450, v1.90)

`/console/cell`은 기존 Fleet Console 프로세스·인증·포트의 작업 화면이다. 신규 실행 writer나 원장을 만들지 않는다. 운영자 입력 문서는 초안으로 저장할 수 있으며, 저장 성공이 실행 가능한 문서임을 뜻하지 않는다. `compile`은 설치된 정본 process compiler로 검증하고 계산한다.

| 경로 | 권한 | 요청 · 응답 |
|---|---|---|
| `GET /api/fleet/cell-app/documents` | 기존 viewer | `{documents:[{kind,id,digest,updated_at}]}` |
| `GET /api/fleet/cell-app/documents/{kind}/{identifier}` | 기존 viewer | `{kind,id,digest,document,updated_at}` |
| `POST /api/fleet/cell-app/documents/{kind}/{identifier}` | named operator | `CellAppDocumentSaveRequest`: `{document,expected_digest:null 또는 sha256}` → 저장 문서. 생성은 null, 수정은 현재 digest가 필요 |
| `POST /api/fleet/cell-app/compile` | named operator | `CellAppCompileRequest`: `{recipe_id,recipe_digest,cell_id,cell_digest}` → `{candidate,process_artifact_digest,summary:{transfer_count,pallet_markers}}`. recipe/3는 `compile_mixed`로 보고 `summary.multi_arm:{arms,steps:[{index,sku,arm,alternates,zone,coupling,depends_on}]}`를 더한다(v1.259). 실행·제안·승인 부작용 없음 |
| `POST /api/fleet/cell-app/proposals` | named operator | `CellAppProposalRequest`: compile 참조 + `{request_key,workcell_id,instance_id}` → 기존 proposal resolve 응답. 구성된 service principal이 제안·resolve하며 admit하지 않음 |

`kind`는 `recipe|cell`, 문서 ID는 `[A-Za-z0-9][A-Za-z0-9_-]{0,63}`, digest는 소문자 sha256다. 문서는 finite JSON object, canonical JSON UTF-8 64 KiB 이하. 동일 DB의 문서 revision은 트랜잭션에서 비교한다. `request_key`는 160자 이하, `workcell_id`/`instance_id`는 96자 이하이며 공백 trim·제어문자 없는 기존 proposal 식별자 규칙을 따른다. 미리보기 candidate는 기존 `{kind:"cell_job",recipe,cell,recipe_sha256,cell_sha256,job}` 계약 그대로다. 저장 revision digest와 process의 recipe/cell hash는 각각 해당 canonical 표현의 해시다.

제안 composition은 `--cell-app-service-id`로 지정한 실제 site-users `role=service` ID를 검증한다. 미구성이면 제안은 503; 존재하지 않거나 operator/viewer ID이면 서버 구성을 거절한다. 서비스 자격은 브라우저에 전달하지 않는다. HTTP를 시작한 named operator의 API audit와 proposal 원장의 service author를 함께 유지한다. 같은 request key 재시도는 기존 ProposalStore idempotency/충돌 규칙을 사용한다. UI는 실패 시 자동 재제안·승인·재실행하지 않는다.

오류: `CELL_APP_UNCONFIGURED`(503), `CELL_APP_DOCUMENT_NOT_FOUND`(404), `CELL_APP_DOCUMENT_CHANGED`(409), `CELL_APP_DOCUMENT_INVALID`(422), `CELL_APP_COMPILE_INVALID`(422; `message`, `problems`). 문서 저장·compile·proposal POST는 기존 Fleet API audit를 받는다. 기존 proposal/admission 오류도 그대로 전달한다.

작업 화면의 승인·진행·복구는 기존 `/api/fleet/missions/{id}/admit`, `/api/fleet/cell-jobs/{id}`, `/reconcile`, `/resume`, `/cancel`을 사용한다. 승인/재승인은 현재 dispatch generation과 named operator가 필요하다. UNKNOWN의 자동 재시도는 없다. cancel은 기존 `HOLD/CANCELLED_BY_OPERATOR` 계약을 유지한다. 서비스 제안 성공·실행 성공·독립 목표 확인은 별개다.

## Cell 수동 슬립시트 대기 (D-450)

`rosy_cell.recipe/2`는 palletize의 작업자 간지 삽입을 명시한다. `slip_sheet`는
`{handling:"operator",thickness:<positive metres>}`이며 로봇 공급 station을 받지 않는다.
recipe/1의 자동 sheet·문서 해시·Job 직렬화는 유지한다. 수동 depalletize는 아직 거절한다.
PROCESS가 간지 두께를 다음 층 높이에 포함하고 non-motion `operator_sheet` Job 단계와
hash-bound checkpoint를 만든다. 실행 PlanBundle에는 box transfer만 들어간다.

`GET /api/fleet/cell-jobs/{mission_id}`는 수동 Job에만 `job.operator_checkpoints`를 추가한다.
각 행은 공유 `CellOperatorCheckpoint` 스키마이며 다음 필드를 가진다.

| 필드 | 의미 |
|---|---|
| `checkpoint_id` | recipe/cell digests와 아래 canonical instruction을 결합한 SHA-256 |
| `kind` | `operator_sheet` |
| `before_transfer_ordinal` | 다음 box transfer의 1-based 순번 |
| `pallet_id`, `layer_index` | 팔레트 ID와 0-based 층 번호 |
| `sheet_pose_base` | 작성된 간지 top-face 배치 지시 `{x_m,y_m,z_m,yaw_rad}`. 실측 pose가 아님 |
| `thickness_m` | 양수 두께(m) |
| `status` | `WAITING` 또는 `WAITING_ACCESS` |
| `updated_at` | timezone을 포함한 원장 변경 시각 |

`checkpoint_id = SHA256(UTF8(canonicalJSON({recipe_sha256,cell_sha256,checkpoint:descriptor_without_id})))`.
canonical JSON은 sorted keys·compact separators·`ensure_ascii=False`·`allow_nan=False`이며
descriptor는 위 필드 중 `checkpoint_id`, `status`, `updated_at`을 제외한 여섯 지시 필드다.

이전 box의 독립 목표 확인과 marker 원장 반영 후 다음 transfer를 READY로 만들기 전에
같은 SQLite transaction에서 checkpoint와 Job/다음 step을 HOLD하고 CLAIMED 자원을 HELD로 보존한다.
첫 층 간지도 admission에서 막는다. 재시작·start·일반 resume는 이 대기를 우회하지 못하며
완료 box를 다시 하달하지 않는다. 수동 checkpoint가 없는 기존 Job의 응답 필드는 유지한다.

현재 대기 이유는 `OPERATOR_SHEET_ACCESS_UNAVAILABLE`이며 일반 resume는 409다.
작업자 삽입 확인 API와 owner-exclusive 접근 허가 계약은 아직 제공하지 않는다.
owner ready, StopLocal ACK, caller 확인 boolean 또는 simulation pose만으로 다음 층을 열지 않는다.
이 readback은 작업자의 안전 접근이나 간지 삽입 완료 증거가 아니다.

### D-456 CORE 수신 승인과 기억한 연결 (v1.101)

이 규약은 LAN 최초 승인과 이미 승인된 키의 재접속을 구분한다. 모든 경로는 실제
HTTPS listener를 요구하며 CORE는 `proxy_headers=False`를 유지한다. 광고는 후보를
보여줄 뿐 인증서를 신뢰시키거나 권한을 발급하지 않는다. HTTP-only 로봇의 최초
신뢰·TLS provisioning과 Native Pilot 결합은 이 CORE 후보의 완료 범위가 아니다.

Prefix: `/api/v1/auth/peer-pairing`.

| Method / path | 입력·권한 | 결과 |
|---|---|---|
| GET `/identity` | 검증할 HTTPS origin | receiver_id, receiver_public_key(SPKI DER base64), receiver_key_sha256, optional tls_hostname/tls_ca_pem/tls_ca_sha256 |
| POST `/requests` | LAN, fields+P256 signature | request_id, request_secret, display_code, revision=0, state=pending, paired=false, expires_at |
| GET `/pending` | 현재 named administrator | 대기 요청(D-483부터 최대 3개); 비밀값 없음 |
| GET `/requests/{id}` | `X-Request-Secret` | state/revision, 승인됐다면 relationship_id/generation/persistent/authorization_expires_at/authorization_available |
| DELETE `/requests/{id}` | 같은 요청 비밀 | pending만 cancelled로 전환 |
| POST `/requests/{id}/decision` | 현재 named administrator; action=approve/reject, revision, persist_requested | 승인 거래 결과; **paired=false**, credential 발급과 구분 |
| POST `/requests/{id}/confirm` | 인증 없음, `X-Request-Secret`; 본문 `{approval_code}`(6자, `23456789ABCDEFGHJKMNPQRSTUVWXYZ`) | D-483 (v1.110): 수신 LCD 승인 코드로 같은 요청을 승인. 200 StateSnapshot(approved, persistent=false, 168 h); 틀림 400 `detail.remaining_attempts`(5회째 rejected); 요청 역할 > operator 403; 출처별 30회/분 공유 또는 전체 틀린 코드 20회/10분 초과 429; 변경·만료·비밀 불일치 409 |
| POST `/relationships/{id}/challenge` | 이미 승인된 관계 ID | fields와 receiver_signature; 최대 60초, 한 번만 사용 |
| POST `/relationships/{id}/session` | 해당 client key의 fields+signature | 기존 digest token의 id/token/role/expires_at; 최대 1시간 |
| DELETE `/relationships/{id}` | 현재 named administrator | revoked와 증가한 generation; 자식 세션 거부 |

Request fields: receiver_id, receiver_key_sha256, client_id, label(1–64자),
client_public_key(SPKI DER base64), role(viewer/operator), nonce(64자 hex).
관계 ID는 request ID와 같은 32자 base64url이다. 비밀 request_secret은 43자
base64url이며 서버는 hash만 보관한다. 4자리 영숫자는 양쪽 화면의 요청 비교용이고,
승인·로그인 자격이 아니다. 상태 polling 간격은 최소 2초다.

D-483 화면 승인 코드(v1.110): CORE는 요청마다 6자 승인 코드를 만들고 상수 시간
hash 비교만 한다. 원문은 응답·상태·`pending`·로그에 없고, 살아 있는 대기 요청을
가장 최근 것부터 최대 3개 `/run/rosy-peer-display/approval.json`(`rosy-core:rosy-display`
2750, 파일 0640, `{"requests": [{display_code, approval_code, expires_at}]}`)으로
rosy-face에 넘긴다. LCD는 요청마다 "표시 번호  승인 코드" 한 줄을 보인다. 대기 요청이
없으면(승인·거절·취소·만료·정리) 파일을 지우고, CORE 시작 때 남은 파일도 지운다.
살아 있는 대기 요청은 LCD 목록과 같은 3개까지(끝난 요청은 세지 않음), 출처별 동시 대기는
2개다. 요청 취소도 출처별 30회/분 한도에 센다. 모든 출처를 합친 틀린 승인 코드가 10분에
20회에 이르면 그 창이 지날 때까지 `confirm`은 맞는 코드에도 429(콘솔 승인 안내)를 돌려준다.
콘솔 `decision`은 영향이 없다. 상태 보관 행은 600초 전에는 승인되지 않은
끝난 요청만 먼저 비운다. 화면 코드 행의 `approved_at`이 60초 넘게 미래이면 사용 시점에 거부한다. `confirm`으로
생긴 관계는 `approved_by`·`issuer_id`·`issuer_source`가 `screen-code`, `issuer_digest`가
수신 키 지문, `persistent=false`, `approved_at`부터 최대 168시간이며 발급자 token 없이
관계 자체의 만료·폐기·수신 키만 확인한다. 토큰 id `screen-code`는 예약어다. 콘솔
`decision`과 경합하면 하나만 승인한다. 관계 128개 상한에 닿으면 만료·폐기되었고 살아
있는 세션이 없는 관계를 지우고 `relationship_pruned` 감사 행을 남긴다.

Challenge fields: relationship_id, challenge_id, nonce, receiver_id,
receiver_key_sha256, client_id, client_key_sha256, role, generation, expires_at.
처음 승인한 generation은 0이며 client는 기억한 승인과 정확히 비교한다. 폐기한
관계 ID는 재승인하지 않는다. 새 동의는 새 request/relationship ID를 쓴다.

서명 transcript는 `{"version":"rosy.peer-proof/1","context":...,"fields":...}`의
key를 정렬한 compact ASCII JSON이다. Python `ensure_ascii=True`, lowercase Unicode
escape와 UTF16 surrogate pair, `/` 비escape, `allow_nan=False`가 기준이다. Context는
request / receiver-challenge / session-request로 분리한다. P256 ECDSA SHA256,
DER signature의 canonical base64를 사용한다. 서버 challenge의 공개 키·키 지문은
광고에서 새로 받아 신뢰하지 않고 기존 HTTPS 또는 승인된 화면/QR trust anchor에
대한 값과 비교한다.

`persistent=true`는 수신 소유자가 `persist_requested=true`로 명시 승인하고 실제 현재
issuer record가 nonlegacy·nondevelopment digest·card/manual source의 만료 없는
administrator일 때만 허용한다. issuer ID/digest/source/named principal/scope를
보존하고 매 갱신과 HTTP·live socket 인증에 재확인한다. 임시 pair-* issuer는 기억
요청이 있어도 `persistent=false` 및 issuer보다 길지 않은 만료(최대 168시간)를
반환한다. 관계 기록은 세션 만료·오프라인만으로 지우지 않는다. issuer 폐기·키 변경·
관계 폐기·만료는 자식 세션과 새 발급을 거부한다.

동일 요청 승인 결과가 저장된 뒤 응답을 잃어도 같은 관계를 읽어 복구한다. 재시도는
권한 기간을 늘리거나 관계를 중복 생성하지 않는다. nonce 소비·token digest·관계·
감사는 CORE의 기존 config overlay 한 번의 atomic commit에 포함한다. 최대 관계
128개, pending 3개/300초(D-483, 상태 보관 600초), source 128개·신청 30회/분(잘못된
증명도 crypto 실행 전에 포함), challenge 64개/60초, 관계당 활성 세션 8개, audit
256개를 넘기지 않는다. 용량이 가득 차면 기존 관계를 암묵적으로 삭제하지 않는다.

API 오류: 실제 HTTPS 또는 최초 LAN 조건 불충족 403, 기존 인증 없음 401,
권한 부족 403, 409(변경·만료·한도·증명 거부), 잘못된 typed 입력 422,
4096 bytes 초과 413, 저장 identity 초기화 불가 503. 응답은 no-store다.

D-535 이유 코드(v1.155, additive): 위 거절은 상태와 기존 `detail`을 그대로 두고 ERR-101
`error {code, message, detail{action, retry, …}}`을 더한다. HTTP로 온 요청 403 `TLS_REQUIRED`,
수신 초기화 불가 503 `PAIRING_UNAVAILABLE`, LAN 밖 최초 요청 403 `LAN_REQUIRED`, 없는 관계
409 `PAIRING_REQUIRED`, 철회·발급자 회수 409 `APPROVAL_REVOKED`, 다른 수신 키·옛 수신 키 요청
`IDENTITY_CHANGED`, 관계 만료 409 `APPROVAL_EXPIRED`, 사라진 요청(없는 id·틀린 비밀 구분 없음)
409 `APPROVAL_TIMEOUT`, 끝난 요청의 확인·취소·결정은 상태대로(`APPROVAL_TIMEOUT`·`APPROVAL_DENIED`·
`APPROVAL_CANCELLED`; 이미 승인된 요청은 기본값 `PAIRING_REQUIRED`, 요청자는 상태를 읽는다),
틀린 화면 코드 400 `APPROVAL_CODE_WRONG`(`detail.remaining_attempts` 유지, 다섯째 `APPROVAL_DENIED`),
역할 초과 403·틀린 코드 전체 한도 429 `CONSOLE_APPROVAL_REQUIRED`, 모든 한도 `RATE_LIMITED` +
`Retry-After`(상태 읽기 간격 2 s, 나머지 60 s; 예전에 409였던 한도는 409 그대로).
이 로그인 발급은 Pilot seat·teleop 수락·calibration lease·모드·정지 해제를
발급하지 않는다(D-460/D-411). 실제 조작은 기존 CORE 게이트를 그대로 통과한다.

암호화 의존은 signed release의 `runtime-python` 보조 경로에 hashlocked ARM binary
wheels로 실어 CORE entry만 읽는다. D-189 base `python-runtime.sha256`과 이미지
global Python 요구사항은 변경하지 않는다. 기기에서 apt/pip download를 실행하지
않으며 새 CLI·user-site·`.pth` hook을 실행하지 않는다. native ARM build의 실제
import/sign/verify와 정상 signed candidate/device 수락은 별도 검증이다.


`authorization_available`은 현재 issuer와 관계가 유효할 때만 true다. 과거의 승인
결정은 revoked/expired 관계에서도 보관하지만 usable approval로 해석하지 않는다.
새 세션 token에는 `peer_binding={relationship_id,generation}`을 함께 저장한다.
관계 저장소·관계·session_ids 누락/손상이나 generation 불일치는 HTTP와 live socket
모두 거부한다. 기존 peer_binding 없는 D-193 token 의미는 바꾸지 않는다.

선택적 `network.tls.ca_file`은 TLS provisioning 소유의 절대 경로이며 cert_file과
key_file을 대체하지 않는다. 설정된 public CA 하나(최대 8192 bytes)가 현재 TLS
leaf/fullchain(최대 32768 bytes)을 실제 OS hostname.local에 대해 검증해야 한다.
CA BasicConstraints/keyCertSign/현재 validity 및 chain/SAN을 검증하고 실패하면
listener/first-contact를 닫는다. 성공할 때만 identity의 세 optional field를 함께
공개한다. 지문은 CA DER SHA256 lowercase hex이며 CA private key는 공개하지 않는다.
ca_file이 없으면 세 field는 null이며 기존 신뢰 검증을 대체하지 않는다.

수신 기기의 인증된 관리자 화면에 독립적으로 읽은 CA 지문과 hostname을 표시한다.
D-341 첫 접촉은 anonymous identity/request/status와 물리 화면의 지문 비교,
실제 관측 leaf의 CA binding/SAN 검증까지만 허용한다. 해당 신뢰가 확립되기 전
challenge/session이나 bearer 전송을 허용하지 않는다. mDNS·4자리 번호로 CA를
신뢰하지 않는다. 이 CORE slice의 public QR renderer는 아직 구현하지 않았다.

anonymous identity 호출은 D-533에 따라 source별 300회/분으로 따로 센다.
challenge/session 증명 호출은 기존 source별 합계 30회/분을 유지한다. 두 예산 모두
crypto 전에 적용하고 source map 최대 128개로 admission하며 한도는 429다. 최초 신청의 별도 30회/분
한도도 잘못된 증명을 포함한다. overlay 거래는 config.yaml.lock의 동일 UID
소유 0600 sidecar로 process/thread fence하고 unrelated token/config를 보존한다.
기존 lower-layer card/manual token은 실제 merged config provenance로 확인하지만,
peer 관계 저장소는 overlay 소유이며 삭제된 관계를 process memory에서 복원하지 않는다.

운영 수용은 별도다: HTTP-only Pinky의 TLS provisioning, 실제 native ARM crypto
build/import, signed delivery, Native Pilot coupled client, 실제 두 화면 승인과 재접속,
Fleet/Cam의 지속 관계 확장은 이 source/local 결과로 완료했다고 주장하지 않는다.


## 10.18 Learned-policy governance (D-793)

학습 정책이 실물을 움직이기 전의 사람 승인 기록이다. 규칙은 Fleet 서버가 판단하고 콘솔 `/console/policy`는 서버가 거절할 조작을 사유와 함께 미리 잠근다. 이 절의 어떤 경로도 장치에 명령을 보내지 않는다. 오류는 `{"detail": {"code": "UPPER_SNAKE"}}`다.

| 경로 | 권한 | 설명 |
|---|---|---|
| `GET /api/fleet/policy-governance/workcells` | `fleet.read` | 설정된 OMX 작업셀 id 목록 |
| `GET /api/fleet/workcells/{id}/policy` | `fleet.read` | `policies`(단계), `proposals`, `windows`(`active` 포함), `confirmations`, `incidents`, `now_ns`, `rules` |
| `POST .../policy/proposals` | `fleet.policy` | `{operator_confirmed, policy_revision, to_stage, rig_revision, calibration_revision, evidence_sha256, note}`. 다음 단계만 허용(`STAGE_SKIP_REFUSED`), 첫 단계는 L0 |
| `POST .../policy/proposals/{proposal_id}/decision` | `fleet.policy` | `{operator_confirmed, approve}`. L3·LIMITED 승인은 제안자와 다른 사람(`APPROVER_MUST_DIFFER_FROM_PROPOSER`, 403) |
| `POST .../policy/windows` | `fleet.policy` | `{operator_confirmed, policy_revision, kind: shadow\|supervised\|limited, minutes?, scope, rig_revision, calibration_revision}`. 최소 단계 L2·L3·LIMITED. revision이 단계 기록과 다르면 `REVISION_CHANGED_REAPPROVAL_REQUIRED` |
| `POST .../policy/windows/{window_id}/approve` | `fleet.policy` | `{operator_confirmed}`. supervised·limited는 요청자와 다른 사람. 작업셀당 열린 창 하나(`ANOTHER_WINDOW_ACTIVE`) |
| `POST .../policy/windows/{window_id}/close` | 이름 있는 운영자 | `{operator_confirmed, reason}`. 멈춤은 더 강한 권한이 필요 없다 |
| `POST .../policy/lease` | `fleet.operate`(operator·service) | `{episode_id, owner_session_id, duration_ms?(1..2000, 기본 1000), lease_id?}`. 열린 supervised·limited 창에서만, 확인 요청·사고가 없을 때만. 만료는 창 만료를 넘지 않는다. `lease_id`를 주면 같은 창·episode·owner session의 더 늦은 만료로 갱신. 응답의 `clock: "fleet_wall_ns"`, `device_delivery: "not_connected"` |
| `POST .../policy/confirmations` | 이름 있는 운영자 | `{operator_confirmed, reason, policy_revision?, evidence(≤8 KiB)}`. reason은 `rules.reasons` |
| `POST .../policy/confirmations/sync-owner` | 이름 있는 운영자 | owner readback이 `hold`이면 같은 HOLD당 한 건을 연다. `{owner, created}` |
| `POST .../policy/confirmations/{confirmation_id}/resolve` | `fleet.policy` | `{operator_confirmed, resolution: resume\|abort\|send_to_learning, note, demote_to?}`. abort·send_to_learning은 창을 닫고, send_to_learning은 단계를 낮춘다(기본 L1). resume은 owner HOLD를 풀지 않는다(§10.12 owner recover) |
| `POST .../policy/incidents` | 이름 있는 운영자 | `{operator_confirmed, description}`. 작업셀의 모든 창을 닫고 L3·LIMITED 승인과 새 창을 막는다 |
| `POST .../policy/incidents/{incident_id}/clear` | `fleet.policy` | `{operator_confirmed, note}`. 신고자와 다른 사람 |

# 11. 변경 이력

| 버전 | 일자 | 내용 |
|---|---|---|
| v1.301 | 2026-10-24 | (origin #135 v1.293, 2026-10-24 port) Additive (D-835): measured PNG/JPEG registration, bounded immutable line/contour candidates, non-writing candidate map validation and optional facility evidence. Existing STL hashes and envelope 1.0 unchanged. |
| v1.300 | 2026-10-24 | (origin #133 v1.291, 2026-10-24 port) Additive (D-825): Fleet STL source/projection APIs, explicit drawing registration and optional map drawing/road name; envelope 1.0 unchanged. |
| v1.297 | 2026-10-23 | D-855: strict control-unit delegation, owner snapshots and local approval; separate boot/run/correlation-scoped navigation cancellation. Runtime and device acceptance remain separate; envelope 1.0 unchanged. |
| v1.292 | 2026-10-21 | D-836: additive candidate_robot_ids/request_key trip admission, durable principal/key/body replay and existing lease/claim allocation. Existing robot_id form, named operator and simulation gate remain; envelope 1.0 unchanged. |
| v1.290 | 2026-10-20 | D-821 explicit named navigation handoff to existing Task owner, independently OFF by default; ko-KR/en-US locale. Model replies remain read-only. |
| v1.289 | 2026-10-20 | D-810 Console operator assistant: source-isolated strict intake, own conversation reads, durable model attempts, read-only facts and explicit unavailable/UNKNOWN states. No device execution authority. |
| v1.288 | 2026-10-19 | Integrate D-772/D-774/D-776/D-783 Station contracts from reserved v1.278–286 with the current v1.287 route-prior contract. Preserve both histories and envelope 1.0; no physical activation. |
| v1.287 | 2026-10-19 | D-769 rev 3 / D-573 rev 8 route-prior compatibility prerequisite: optional map-wall geometry, at most three-second source lifetime, receiver-first rollout, and the separately installed consumer's ignored-short extension exception. Operational Fleet remains one second; no physical activation. |
| v1.286 | 2026-10-16 | (origin #92 v1.255, 2026-10-19 port) D-772 완료된 native navigation의 exact boot/run/correlation/generation·quiescent transport를 확인한 수동적 IDLE handover. 새 이동·취소·물리 정지 판정을 추가하지 않음 |
| v1.285 | 2026-10-16 | (origin #92 v1.254, 2026-10-19 port) D-772 작업·attempt 결속 이안 허가/실측 Receipt. 명시적 로컬 피드·절연·후방 공간 검사와 native 이안·허가 갱신·실측 완료 API, 정확한 선행/진행 중 중단 |
| v1.284 | 2026-10-16 | (origin #92 v1.253, 2026-10-19 port) D-772 세션·현재 native owner에 한정한 station-stop. 근거 만료 뒤에도 권한을 닫으며 ACK는 물리 정지·자원 해제가 아님 |
| v1.283 | 2026-10-16 | (origin #92 v1.252, 2026-10-19 port) D-772 성공 terminal navigation/quiescence를 확인한 조건부 IDLE 인계와 이후 새 측정 정지 dwell |
| v1.282 | 2026-10-16 | (origin #92 v1.251, 2026-10-19 port) D-772 기존 trip lease와 충전 세션을 결속한 CORE 복귀 허가·최종 출력 검사·측정 정지 후 접안 인계 계약. 실기 활성화 없음 |
| v1.281 | 2026-10-16 | (origin #92 v1.250, 2026-10-19 port) D-772 source 전용 현재 관측 생성 범위 조회. 활성 세션·CORE binding/ACK·odom epoch를 결속하며 pose=null/visible=false 메타데이터만 반환. 로봇 자격과 이동 권한은 전달하지 않음 |
| v1.280 | 2026-10-16 | (origin #92 v1.249, 2026-10-19 port) D-772 인증된 스테이션 binding·관측·실행 및 근거 유효성을 포함한 상태 계약. native boot/generation과 세션 소유 principal 결속. 실기 자동 활성화 없음 |
| v1.279 | 2026-10-16 | (origin #92 v1.248, 2026-10-19 port) D-772 안전 검토: 착좌 위치와 충전기 정상 종단의 원본 표본 시각을 분리한다. 이전 표본을 다시 수신해도 신선도가 갱신되지 않는다. 정상 종단 시각 미지원은 UNKNOWN. 새 REST 경로·실기 capability·envelope 1.0 변화 없음 |
| v1.278 | 2026-10-16 | (origin #92 v1.245, 2026-10-19 port) Additive (D-772): station_charging 공유 DTO와 canonical schema export. 위치 버전·지도 revision·교정·충전 session·boot/odom 세대, 착좌·정상 종단·배터리 계측 근거를 구분한다. 이 단계에서 새 REST 경로·실기 capability는 추가하지 않는다. envelope 1.0 유지 |
| v1.275 | 2026-10-19 | Additive (D-801, feat/site-console-video): Fleet `POST /api/fleet/robots/{robot_id}/media-grant`·`/renew`·`DELETE`와 미디어 권한 서비스용 `POST /api/fleet/media/validate`. 사이트 로그인 주체(fleet.read)의 로봇별 READ 전용 영상 위임. 상세는 v1.275 절 |
| v1.273 | 2026-10-19 | Additive (docs/stuck-evidence-jpeg-api): `GET /api/fleet/robots/{robot_id}/line-stuck/evidence` with `Accept: image/jpeg` returns the raw JPEG and its metadata in `X-Stuck-Evidence`; the JSON body is unchanged for other clients. Documents the behaviour shipped in fix(fleet) 0659636cff. |
| v1.271 | 2026-10-18 | Additive (D-800, feat/omx-core-lerobot): operator-authenticated CORE `/api/v1/arm/policy`, `/observations`, `/actions`, `/stop`; single-use guarded source IDs and the existing OMX owner/fence. Default unbound, SIM-only, no lease issuance, rearm or physical activation. |
| v1.268 | 2026-10-18 | Additive (D-793, feat/legacy-policy-admin-flag): users-file `policy_admin`(operator 전용)과 세션 응답 `policy_admin`. envelope 1.0 변경 없음. |
| v1.266 | 2026-10-18 | Additive (D-793, feat/omx-policy-governance): `/api/fleet/workcells/{id}/policy/*` 학습 정책 단계·승인 창·확인 요청·사고 잠금·실행 lease와 `/console/policy`. 장치 전달 없음, envelope 1.0 변경 없음. |
| v1.265 | 2026-10-18 | Additive (D-789, feat/webrtc-camera-land): `/api/v1/vision/media/grants`·`/renew`·`DELETE`·`/source-grant`·`/validate` 영상 위임과 사이트 media origin의 `/v1/*` 경로. `vision.media.site_url`이 있으면 기본 활성, `enabled: false`로 끔. 상세는 v1.265 절 |
| v1.259 | 2026-10-17 | Additive (D-781 §2·§5, D-779 §4, feat/mixed-compile-followups): `cell_transfer.sku` 선택 필드(box만, 없으면 직렬화·digest가 같다)와 owner 형상 키 `item_key`(`box:<sku>`), recipe/3 Step의 팔별 `goal_predicates`, 대체 팔이 실행한 Step을 그 팔 술어로 판정(술어가 없으면 `CELL_GOAL_PREDICATE_MISSING`), `POST /api/fleet/cell-app/compile`의 recipe/3 `summary.multi_arm`, 두 팔 제안 경로 문서화. recipe/1·/2 Job·grant·미리보기와 envelope 1.0 변경 없음. |
| v1.258 | 2026-10-17 | Additive (D-779 §3·§6, feat/multi-arm-goal-evidence): `POST /api/fleet/cell-jobs/{mission_id}/arms/{arm_role}/resume` `{expected_generation}`(이름 있는 운영자, 두 팔 Job의 팔 하나, 단단한 결합 짝이 잡혀 있으면 409), `POST /api/fleet/cell-goal-evidence`의 두 팔 Job Step 단위 판정(술어 팔의 Action, 그 팔 instance의 producer, 협조 Step은 모든 팔 성공 뒤, 대체 팔 Step 거절). 한 팔 Job과 envelope 1.0 변경 없음. |
| v1.257 | 2026-10-17 | Additive (D-780, D-779 §7, feat/omx-coordinator-barriers): `StopRequestSource.coordinator`와 조율자 정지 이유 4종, `FleetCellTransferGrant`의 선택 필드 `arm_role`·`pair_id`·`partner_instance_id`·`coupling`과 `cell_transfer.barriers`(없으면 직렬화와 digest가 이전과 같다), OMX owner UDS `GetBarrier`·`ReleaseBarrier`(version 2, 조율자 UID만)와 연산별 peer 역할, `PHASE_WAIT`, barrier 시간 초과(FAILED 또는 HOLD), 단단한 결합 구간의 조율자 생존 HOLD. 조율자 peer가 없는 owner와 barrier 없는 grant는 바뀌지 않는다. Fleet `/api/fleet/*`와 envelope 1.0 변경 없음. |
| v1.256 | 2026-10-16 | Additive (D-775): preview 목적의 실측 교정 bundle 승인·영속 선택·CAS 철회, source config opt-in·수치 적용 readback, 현재 촬영 session에 결속한 named operator 확인과 signed measured preview. tracking/sighting 승인·주행 권한과 envelope 1.0은 유지한다. |
| v1.242 | 2026-10-15 | Additive (D-763 조각 7, feat/fleet-job-trip-steps): `POST /api/fleet/trip-jobs` `{robot_id, steps:[{to, via[]}]}`(1–8), 이름 있는 운영자, `simulation` 프로필이고 Step 원장이 있을 때만. 응답 `{job}`(Step 원장 행, 종류 `TRIP`). 거절: 404 `UNKNOWN_ROBOT`, 422 `TRIP_UNKNOWN_PLACE`, 422 `LINK_UNBOUNDED_MOTION` `{reasons, missing}`, 409 `TRIP_ROBOT_BUSY`, 409 `JOB_ESTOP`, 409 `JOB_ROBOT_REFUSED`. trip 작업은 `GET /api/fleet/work`에 `cell_job` 행(`action_kind:"TRIP"`)으로 나온다. 재개·취소는 지금의 `/api/fleet/cell-jobs/{id}/resume`·`/cancel`이다. 동작: 차로 `arrived` 뒤 다음 trip이 그 로봇이 쥔 정지 하나를 넘겨받는다. envelope 1.0 변경 없음. |
| v1.241 | 2026-10-15 | Additive (D-767 A부, feat/instruction-pose-stamp, Safety-Review 대상): `POST /api/v1/line-follow/junction` 선택 필드 `pose_stamp`(400 `VALIDATION_ERROR`), 능력 `base_velocity.lane_instruction_stamp`(설정 `line_follow.instruction_stamp_enabled`, 기본 꺼짐), `line_follow.junction.distance_basis`·`distance_basis_reason`. 거리 있는 지시의 쓸 수 없는 stamp는 409 `INSTRUCTION_STAMP_UNUSABLE`(`detail.reason`)이고 상태는 그대로다. Fleet은 그 능력의 로봇에 `pose_stamp`를 싣고 굽이 앞당김과 전송 지연 허용치를 뺀다. v1.238–v1.240은 다른 작업이 선점했다. Fleet `/api/fleet/*` 변경 없음. envelope 1.0 변경 없음. |
| v1.240 | 2026-10-15 | Behaviour (D-763 조각 4 리뷰, fix/fleet-proposal-read-scope; 인증·응답 범위만, 스키마 변화 없음): `GET /api/fleet/proposals/{proposal_id}`는 Cell Job 제안을 `GET /api/fleet/cell-jobs/{mission_id}`와 같은 범위로 읽는다 — 제안자, `PROPOSED`가 아닌 Job은 운영자, 남의 미판정·`PROPOSED` 제안은 이름 있는 운영자만, 나머지 404 `PROPOSAL_NOT_FOUND`(없는 id와 같은 본문). 제안자 아닌 독자는 `proposal_principal_id`가 없고 제안자의 사건은 `actor_id: "proposer"`. 레거시 Mission 제안은 제안자만. admit·reject와 Cell Job reconcile·resume·cancel 응답의 Job도 같은 가림. `GET /api/fleet/resource-claims`: viewer는 `resource_key`·`resource_kind`·`resource_id`·`phase`만, 운영자는 Cell Job claim 행 전체, 다른 claim은 그 레거시 Mission의 제안자만 행 전체. `POST /api/fleet/channel-requests/{request_id}/admit`·`/submit`은 이름 있는 운영자(이름 없는 공유 토큰은 403 `OPERATOR_IDENTITY_REQUIRED`). 작업이 쥔 로봇의 409 `TRIP_ROBOT_BUSY` detail은 `job_id` 대신 `{"reason": "job", "owner_kind": "mission"}`. |
| v1.239 | 2026-10-15 | Behavioural (D-620 노트 2026-10-15, D-760 개정 4, fix/signal-no-fallback-on-trip, Safety-Review 대상): Fleet 통행권 강제 중(trip lease·통행권·`authority_required`) 교차로 무응답 정지 에피소드는 3초 우측 fallback 없이 대기; 교차로 기동·D-520 호 시계는 통행권 `HOLDING` 대기를 상한 없이 더하고 `NONE`·`EXPIRED`·횡단보도 몫은 15 s 상한 유지. 필드 변경 없음. v1.237·v1.238은 다른 작업이 선점했다. |
| v1.238 | 2026-10-15 | Additive (D-763 10항 (c), feat/regulation-capabilities): 능력 `base_velocity.lane_crosswalk_gate`(CORE `line_follow.crosswalk_gate_enabled`)·`lane_junction_signal`(`junction_signal_enabled`), 없으면 꺼짐. Fleet trip 시작·바퀴·재계획이 횡단보도·신호 구역을 지나는 lane 경로를 그 능력이 `false`인 로봇에 422 `TRIP_REGULATION_CAPS_MISSING` `{missing}`로 거절, 필드 없는 옛 CORE는 `detail.regulation_caps_unknown` 경고와 함께 시작 |
| v1.237 | 2026-10-15 | Additive (D-763 조각 4, feat/fleet-work-read-sources): `GET /api/fleet/work`에 `trip`·`cell_job` 출처, 행의 `visible_state`·`wait`·`approval`, 응답의 `cell_jobs_available`·`kinds`. 두 사람 승인 `PROPOSED` Cell Job 요약 행은 제안하지 않은 이름 있는 운영자에게 보인다(개정 2 질문 6). 상세·본문 범위, 원장 상태, envelope 1.0 변경 없음. |
| v1.236 | 2026-10-15 | Additive (D-763 조각 6, feat/fleet-job-holds-lease): `PUT /api/v1/trip-lease` 선택 필드 `job_id` — 작업의 lease는 단계 사이 IDLE에서 끝나지 않는다. 주인 아닌 토큰의 `POST /mode {IDLE}`는 어떤 lease든 끝낸다(`mode_left`). 상태 `trip_lease.job_id`, 능력 `base_velocity.trip_lease_job`. 통행권·목표 임대의 만료는 그대로다. v1.233–v1.237는 다른 작업이 선점했다. envelope 1.0 변경 없음. |
| v1.234 | 2026-10-14 | Additive (D-758 0단계, fix/odom-log-monotonic-epoch, Safety-Review 대상): 스냅숏 `odom_pose.epoch`(odom 불연속 횟수)·`mono_s`(CORE 단조 수신 시각). CORE는 통행권·lane cue·호 기준의 odom 표본을 발행한 `odom_pose.stamp`로 찾고 나이·순서를 line-follow 시계로 잰다(벽시계 이동에 무관). 맞지 않는 stamp는 v1.226과 같다. Fleet 지도 자세 추적기는 `epoch`가 바뀌면 기준을 버린다. 요청·응답·envelope 1.0 변경 없음. |
| v1.232 | 2026-10-14 | Additive (D-763 조각 2, feat/fleet-work-wait-read): trip 읽기의 `wait`에 `waiting`·`bound_s`·`over_bound`를 싣는다. 한 주기에 한 번 쓰고, 판정에 닿지 못한 주기에는 null이다. 상한을 넘은 기다림은 경고이고 개입이 아니다(개정 2 질문 7). |
| v1.231 | 2026-10-14 | Additive (D-759 개정 1): `POST /api/v1/line-follow/junction` `map_entry`를 `turn_deg`가 있는 `left`·`right`에도 받는다(`yaw_rad` = 출구 차로의 지도 방향, 그 밖의 action은 400 `VALIDATION_ERROR`), 능력 `base_velocity.lane_turn_map_entry`(설정 `line_follow.turn_map_entry_enabled`, 기본 꺼짐), 회전에서도 `line_follow.junction.map_entry_used`·`map_entry_reason`. 오늘 목표에서 15° 넘게 어긋나거나 풀지 못한 방향은 거절이 아니라 오늘의 목표다. v1.231. Fleet trip 보기 `caps.lane_turn_map_entry`. envelope 1.0 변경 없음. |
| v1.230 | 2026-10-14 | Additive (D-763 조각 5·5b, feat/fleet-approval-registry): `POST /api/fleet/missions/{mission_id}/reject` — 승인 대기 작업의 철회·거절. 본문 `FleetWorkDecisionRequest` `{expected_generation}`. Cell Job은 HOLD/`CANCELLED_BY_OPERATOR`, 레거시 Mission은 `CANCELED`(reason `WITHDRAWN_BY_PROPOSER`\|`REJECTED_BY_OPERATOR`), claim 없음, 감사 사건. 409 `MISSION_REJECT_REFUSED`. admit 승인은 단계 종류 등록부에서 판정(동작 같음). |
| v1.227 | 2026-10-14 | Additive (D-760 개정 3 9항, feat/line-follow-regulation-wait): `GET /api/v1/line-follow` 와 상태 스냅숏 `line_follow` 의 선택 필드 `regulation_wait`(`authority`·`signal`·`crosswalk_held`·`crosswalk_wait`·`crosswalk_look`·null, 그 순서의 우선순위). CORE 2b 시계 도우미와 같은 판정. 동작·다른 필드·envelope 1.0 변경 없음. |
| v1.226 | 2026-10-14 | Additive + Behavior (D-760 1–3항, feat/authority-ttl5-shrink-under-lease, Safety-Review 대상): `POST /api/v1/line-follow/authority` `ttl_s` 상한 2 → 5 s, 선택 필드 `shrink`(bool)·`seq`(정수 ≥ 0), 응답 `reason: stale_seq`·`seq_required`·`seq_legs_full`·`shrink_none_held`. CORE trip lease 가 열려 있는 동안 line-follow 는 통행권이 없으면 `authority_none` 으로 선다(임대가 없으면 v1.225 그대로). 능력 `base_velocity.line_follow_authority_shrink`·`line_follow_authority_under_lease`. 추가 필드와 임대가 없는 요청의 동작은 v1.225와 같다. Fleet 송신은 바뀌지 않는다(D-760 3단계) |

| v1.225 | 2026-10-14 | Additive (D-754): `POST /api/v1/line-follow/junction` `action: bend` 선택 필드 `next_line_in_m`(0–2 m, 400 `VALIDATION_ERROR`), 능력 `base_velocity.lane_bend_next_line`, Fleet trip 보기 `caps.lane_bend_next_line`. 필드가 없는 지시와 능력이 없는 로봇은 그대로다. 상태·응답·envelope 1.0 변경 없음. |
| v1.224 | 2026-10-14 | Additive (D-759): `POST /api/v1/line-follow/junction` `action: bend` 선택 객체 `map_entry {yaw_rad, pose_yaw_rad, odom_stamp_s}`(400 `VALIDATION_ERROR`), 능력 `base_velocity.lane_bend_map_entry`(설정 `line_follow.bend_map_entry_enabled`, 기본 꺼짐), `line_follow.junction.map_entry_used`·`map_entry_reason`. 풀지 못한 방향은 거절이 아니라 v1.223의 로봇 yaw 닻이다. Fleet `/api/fleet/*` 변경 없음. |
| v1.223 | 2026-10-14 | Behavior + Additive (D-400 4항 구현): `enforce` 에서 `stale_hold_s` 미만의 센서 끊김은 HOLD(명령 0, E-stop 래치 없음, 자동 재개)이고 그 이상은 전과 같이 `control:<사유>` 래치다. 정책 답 시간 상한 10 ms → `/cmd_vel` 한 주기 20 ms. state `safety_policy.hold` `{count, reason}`(`enforce` 에서만). `off`·`shadow` 출력 변화 없음. |
| v1.222 | 2026-10-14 | Behavior (D-740 개정 3): 교차로 기동 중 운동 증명이 거절된 틱은 HOLD `junction_motion_unconfirmed`(명령 0, 기동 유지)이고, 처음 거절부터 `min(clearance_stale_s, 0.5 s)`를 넘기면 전과 같이 `aborted`·`motion_unconfirmed`다. 필드 변화 없음. |
| v1.243 | 2026-10-15 | Additive (D-440, D-24 개정; feat/device-power-policy-port): `power.wake` 에 사유 `command` 와 선택 필드 `source` — 무명령 타이머는 받아들여진(2xx) 명령 REST 호출과 0 이 아닌 최종 cmd_vel 이 리셋하고, GET·텔레메트리·WS 구독·`/power/*` 는 리셋하지 않는다. 기기별 전원 정책: `PowerStatus` 에 `devices[]`(`name`·`level`·`ready`·`managed`·`required_for_motion`, 선언된 기기만)와 `motion_ready`(false 면 CORE 최종 cmd_vel 이 0) 추가, 이벤트 `power.device_changed`. 꺼졌다 켜진 기기는 `wake_ready_s` 경과와 깨운 뒤의 확인 보고가 모두 있어야 `ready` 다. 정책은 벤치 스위치 `power.device_policy.enabled`(기본 false) 뒤에 있어 스위치가 꺼진 로봇의 동작은 바뀌지 않는다. Site Fleet 새 경로 `POST /api/fleet/robots/{robot_id}/power`(named operator, `sleep`\|`wake`). 기존 경로·필드 변화 없음. 초안은 v1.91 이었다 |
| v1.221 | 2026-10-13 | Additive (D-744): `POST /api/v1/line-follow/junction` 선택 객체 `exit_segment.map_anchor {centre_x_m, centre_y_m, pose_x_m, pose_y_m, pose_yaw_rad, odom_stamp_s}`(400 `VALIDATION_ERROR`), 능력 `base_velocity.lane_arc_map_anchor`, `line_follow.arc.map_anchor_used`·`map_anchor_reason`. 풀지 못한 고정점은 거절이 아니라 v1.220의 자세 기준 원이다. Fleet `/api/fleet/*` 변경 없음. |
| v1.247 | 2026-10-16 | Add explicit route-guide capability and pose-bound selected-plan producer; learned-drivable SIM opts in |
| v1.246 | 2026-10-16 | Add optional authority-bound selected-route geometry with exact source pose and bounded lifetime; producer/publication pending |
| v1.245 | 2026-10-16 | Additive D-769 internal selected-route prior schema and ordered expiring inbox; producer/subscription not enabled. REST and envelope 1.0 unchanged |
| v1.244 | 2026-10-15 | Additive (D-556 Proposed, fix/lane-odom-cross-veto-port): 내부 CAMERA_LINE `quality.reason=odom_side_conflict`를 불가시·신뢰도 0 증거로 허용; CORE bridge·로컬 복구는 이 사유에서 금지. `GET /api/v1/line-follow` `reason`과 `nav.lane_lost` `reason`에 `camera_odom_side_conflict` 값이 나타날 수 있다(생산자 `lane_odom_veto_enabled` 기본 false). REST 경로·스키마·envelope 1.0 변화 없음 |
| v1.220 | 2026-10-12 | Additive (D-732): CORE native owner outcome receipts for navigation/home, dock/undock, follow and one teleop pulse; exact bounded readback, conservative quiescence and paired owner-generation CAS. Fleet Task/channel receipts preserve exact operation and separate outcome, safe_released and quiescence evidence. Existing command ownership and envelope 1.0 remain. |
| v1.219 | 2026-10-12 | Additive (D-726): trip과 `/route` 200 응답의 `context` 사실 묶음, trip 선택 `blocked_edges`·`extra_cost`와 422 `TRIP_UNKNOWN_EDGE`, 재계획이 그 맥락을 유지, `/route` 점 목표가 차체 여유 밖으로 나가는 현에서만 0.12 m까지 단축. 빈 값의 경로는 동일. Additive (D-720): optional owner-bound read-only channel deliberation result; immutable receipt/profile/source observation, durable reservation, UNKNOWN no replay and existing Discord outbox. No action grant. envelope 1.0 유지. |
| v1.218 | 2026-10-12 | Additive (D-718): optional closed ASKING/attempts precondition for BACK_AND_RETRY; checked under CORE manager lock, mismatch refuses without restarting recovery. Envelope 1.0 unchanged. |
| v1.217 | 2026-10-12 | Additive (D-699): optional Fleet observation capture identity, sequence, monotonic clock and complete roster; retained coverage does not establish command, model or outcome truth. |
| v1.216 | 2026-10-12 | Merge (D-691): integrate authorized preview demand and phone cooling with the v1.215 named Console and Discord contracts; preserve all prior revision rows and CORE authority. |
| v1.212 | 2026-10-12 | Additive (D-691): `rosy-overhead/1` downlink `demand.wanted`. An authorized preview read from any Rosy keeps that source sending for 30 s, then the phone releases the sensor and stops JPEG. Severe phone heat pauses that sensor until it cools. Older peers keep streaming. |
| v1.204 | 2026-10-11 | Additive + Behavioural (D-623): current stuck inquiry lane_boundary revision and validated heading_review; authenticated live raw evidence with no-store and 3 s freshness; existing historical evidence and CORE execution gates preserved. |
| v1.206 | 2026-10-11 | Additive (D-660): 읽기 전용 현재 판단·만료와 자연 해소/관측 종료 근거; 실행 허가·CORE writer 유지. |
| v1.215 | 2026-10-12 | Merge (D-686/D-689, D-671/D-680/D-687/D-693): preserve named account/profile and Discord request/work/incident contracts together; initial-cookie restrictions and existing owners remain. Historical parallel revision rows are retained. |
| v1.211 | 2026-10-12 | Additive (D-689): cookie-owned basic profile and verified-current-password rotation; no human authority via Bearer, no role/account edits. |
| v1.210 | 2026-10-12 | Additive (D-686): initial-cookie password-change gate, auth/session boolean, POST auth/change-password and source-bound durable scrypt override; existing machine/Bearer and CORE authority unchanged. |
| v1.209 | 2026-10-11 | Additive (D-655): 지도 없는 조사 기준·도로/시설 근거, 카메라/주행 초안 누적과 지도 변경 경합 거절; 운행 pose와 CORE 권한 유지. |
| v1.210 | 2026-10-12 | Additive (D-692): native ISAAC containment 출처·같은 영상 경계/횡단보도 관측; 검증되지 않은 오차 null 유지. envelope 1.0과 CORE/Fleet 권한 유지. |
| v1.210 | 2026-10-12 | Additive (D-671): 전용 Discord transport 인증과 기명 접수 원장·Console owner read; 실행 권한 없음. |
| v1.211 | 2026-10-12 | Additive (D-680): 기명 Console 요청 검토와 기존 주행 Task 관계 조회·연결. 기존 실행·승인 계약 유지. |
| v1.212 | 2026-10-12 | Additive (D-680): 기명 요청의 최신 검토와 기존 Task 생성을 같은 트랜잭션에서 확인하는 submit. |
| v1.213 | 2026-10-12 | Additive (D-687): Discord 요청의 기존 Mission/Cell proposal 준비와 별도 admission. |
| v1.214 | 2026-10-12 | Additive (D-693): Discord 요청과 현재 열린 사건의 기명 인수·종료 원장 연결. |
| v1.207 | 2026-10-11 | Additive (D-661): 이름 있는 사건 인수·revision 경쟁 검사, 토큰 없는 인증 Console 사건 링크, 기본 OFF 팀 알림 outbox와 개별 전송 상태. |
| v1.205 | 2026-10-11 | Additive (D-631): named site map profile library with bounded validation, operator writes and revision comparison; active/draft maps and robot authority preserved. |
| v1.208 | 2026-10-11 | Additive (D-664): bounded Task/Mission work read projection; source identity and state, owner scope and existing execution authority preserved. |
| v1.203 | 2026-10-10 | Additive + Behavioural (D-620): paired Fleet heartbeat 교차로 신호 질의와 상관 답변, 기본 꺼짐인 CAMERA_LINE 감독 시험의 완전 무응답 3초 우측 회전 선택, 적색/미확인/오류/만료 대기, 요청 ID와 signal_state 상태 필드; CORE 보호 유지. |

| v1.202 | 2026-10-10 | Additive (D-619): optional frame-bound evidence.assessment with shared mobility/manipulation taxonomy, advisory direction and uncertainties; model verification stays unverified; no new execution authority. |
| v1.201 | 2026-10-10 | Behavioural + Additive (D-407 개정·D-607, feat/stuck-no-progress-dithering): CORE 막힘 `cause` 에 `no_progress`·`dithering` 추가(§8 `nav.line_stuck_opened` 행). 새 설정 `line_follow.progress_watch_enabled`(기본 `false`, YAML 불리언), `line_follow.no_progress_yaw_deg`(기본 30, 양수), `line_follow.no_progress_creep_enabled`(기본 `false`). 켜져 있을 때 명령은 있는데 odom 이 `stuck_report_s` 동안 몸 길이 절반 미만·|yaw| 30° 미만이면 연다(기어감 플래그를 켜면 20 s 에 0.30 m 미만도). 꺼져 있으면 동작 변화 없음. 의도한 대기(교차로·권한·횡단보도·신호/교통 게이트)는 세지 않는다. 답 전까지 보고만 한다(움직임 변화 없음). D-468 로컬 복귀 틱에서도 열린다. 상태 `line_follow.stuck.cause`·`detail` 도 같은 값. v1.195–v1.198 은 main, v1.199 는 D-607 REALIGN 브랜치, v1.200 은 D-511 lane cue. |
| v1.200 | 2026-10-10 | Additive (D-511 개정 1·2, feat/core-fleet-lane-cue, D-430 Safety-Review 대상): `POST /api/v1/line-follow/lane-cue` — Fleet 현장 등록 토큰(D-555 3 자리: 화면 코드 출처 + `site:` 라벨, 공유 dev 토큰 거절, 그 밖 403)만. `LaneCueRequest` `{cue_id, fleet_epoch, seq, ttl_s (0 < s ≤ 2), pose_stamp (CORE 벽시계 odom 시각, D-517 권한과 같음), state: ON_LANE\|ON_LINE\|OFF_LANE\|OFF_MAP\|WRONG_WAY, side?, bearing_deg?, turn_deg?, lane_heading_deg?, offset_m?, edge_id?, guide?: {ahead_m, heading_ahead_deg?, curvature_1pm, to_end_m, next_place_id, ring}, turn_spot? (기본 false), context?: {route: lap, segment_id, s_m, lap_m, heading_deg, ahead_m, heading_ahead_deg, offset_m?, next?: {kind, ds_m, action, ref?}, pose_age_s?, anchor_age_s?} (D-511 개정 6, 저장·표시만)}`, 응답 `{accepted, reason}`(`disabled`|`stale`|`epoch_busy`|`odom_stale`|`pose_stale`|`pose_future`). `(fleet_epoch, seq)`는 만료와 무관하게 유지(옛 seq는 늘 stale), 다른 epoch는 신선한 신호·회전·래치가 없을 때만. `pose_stamp`가 최신 odom보다 1.5 s 넘게 오래되면 거절(OFF_MAP은 정합 없이 받음). 회전 부호는 시작 때 고정, 끝은 odom 진행량. 켜려면 `obstacle_mode: path`. 설정 `line_follow.fleet_lane_cue_enabled`(기본 false, Pinky false). CAMERA_LINE에서 IR 감시 뒤, 몸 정지(D-422) 앞에서 판단하고 회전은 LOST 래치·NOMINAL 지면·카메라 신선 조건을 모두 지난 뒤에만 낸다: ON_LINE/OFF_LANE은 IR이 선을 못 볼 때 `\|offset_m\| ≥ 0.05` 같은 쪽 2회 연속이면 차로 가운데 쪽 IR 가장자리 조향(후진 없음, 사유 `fleet_cue_left\|right`); WRONG_WAY는 `turn_spot`이 true일 때만(아니면 래치 HOLD `fleet_wrong_way`, 회전 원 0.0926 m > 차로 안쪽 반폭 0.080 m) `turn_deg` > 30°이면, 그리고 OFF_LANE(재진입 방위 > 45°)은 같은 부호 2회·0.5 s 뒤 `pose_stamp` 시점 odom yaw + 각도를 목표로 제자리 회전(10° 안이면 끝, 예산 \|각도\|+30°, 시간 \|각도\|/속도+2 s를 넘으면 래치 HOLD `fleet_turn_unconfirmed`; 교차로 지시·arc·횡단보도 구역 중엔 시작 안 함). OFF_MAP, 회전 중 신호 만료(`fleet_cue_lost`)는 래치 HOLD — 같은 epoch의 ON_LANE/ON_LINE 신호, D-407 막힘 결정(STUCK_DECIDE), 모드 변경만 푼다. 모드 변경·E-stop은 신호를 지운다. 사건 `nav.lane_cue`. `guide`는 저장·표시만. 횡단보도 구역은 이 경로로 오지 않는다(D-573 권한 `crosswalks[]`). `GET /line-follow` `lane_cue`(신선한 신호·래치·회전이 있을 때) |
| v1.199 | 2026-10-10 | Additive (D-607 8, feat/core-stuck-realign, Safety-Review 대상): `POST /line-follow/stuck/decision` `REALIGN` + `realign` 본문(PIVOT 회전 자리 한정·KTURN), 능력 `controls.items[].stuck_realign`, 설정 `line_follow.stuck_realign_enabled`(기본 false), 막힘 단계 `REALIGNING`·`REALIGN_SETTLING`, 사유 `stuck_realign`, `nav.line_stuck_local_attempt` `trigger: realign` + `realign_attempt`·`realign {kind, leg, turn_spot, turned_deg, remaining_deg, ticks}`. |
| v1.199 | 2026-10-10 | Additive (D-613): Fleet `/trip` 선택 필드 `start_at`로 관제의 유한 한 바퀴 출발·복귀 장소를 지정한다. 계획과 시작에서 0.05 m 근접성 검사, 구역 정지 이동 거절. CORE API와 envelope 1.0 변경 없음. 현장 주행 수용 별도 |
| v1.198 | 2026-10-10 | Additive (D-596 개정 2026-10-10 사용자 결정, feat/core-lamp-identify-result): CORE `GET /host/lamp/identify/{request_id}` `{state: pending\|shown\|refused\|expired, reason}` — rosy-face가 식별 점멸을 거절한 이유(`CAUTION_ACTIVE` 등)를 CORE가 Fleet에 알린다(rosy-hw-test `hw-test.json`에 `reason`, 다음 payload부터). Fleet은 열린 요청마다 1 s에 한 번 묻고 `refused`면 창을 닫고 `GET /api/fleet/tracking/identity`의 `reason: "lamp_refused"`, `last.lamp_reason`으로 보인다. 404(이전 CORE)면 그 요청은 다시 묻지 않고 지금처럼 Vision 판정을 기다린다. |
| v1.198 | 2026-10-10 | Behavioural + Additive (D-577 개정 2026-10-10 Safety-Review, feat/d577-chain-supervision): AI PC 제안은 판단기 규칙과 같은 관문을 지난다 — `WAIT` 외의 단어는 CORE가 `line_follow.crosswalk`를 보고하고 null일 때만, `RESUME`은 어느 원인에서도 AI 단어가 아니다. `BACK_AND_RETRY`는 R3 전제 전부(R6 동료 면제 없음)·살아 있는 acting AI 사실 없음·앞 동료가 있으면 R1 먼저일 때만 보낸다. 보낸 `ABORT`는 사람 행 `ai_abort:<reason>`도 올리고, 보류된 `ABORT`는 R5 `WAIT` + `ai_abort_held:<판정>`이 된다. Fleet 지도 횡단보도 위의 `lane_lost`·`no_motion` 막힘은 R5 `WAIT` + 사람(`crosswalk_human`)이다(판단기 XW `RESUME` 제거, 독립 Safety-Review). 이미 답한 막힘의 제안은 감사만(`after_answer`). `POST /api/fleet/ai/heartbeat` `build_commit`(선택). `GET /api/fleet/ai` `chain`(판단기 켜짐, 로봇별 자격 유무·AI 실행·마지막 판단기 답, 1시간 제안 수)과 `proposals[].outcome`, 막힘 행 `ai_proposal`. 로봇 API 변경 없음. |
| v1.197 | 2026-10-10 | Additive (D-604, feat/core-line-camera-capability): `GET /api/v1/system/capabilities` 최상위 선택 필드 `line_follow.camera {available, age_ms, source}` — line-follow 서비스가 있을 때만. `GET /vision/front/status`와 같은 미리보기 저장소에서 계산한다(`available`·`age_ms` 같은 값, `source`는 미리보기 라벨이 `GAZEBO`면 `GAZEBO`, 다른 라벨이면 `DEVICE`, 프레임이 없으면 `NONE`). `drive_modes`의 `lane`은 그대로 서비스 존재만 뜻한다. Fleet `/trip` 계획의 D-601 차선 카메라 검사는 이 필드가 있으면 로봇을 따로 부르지 않고 이 값을 쓰고(`detail`에 `source` 추가), 없거나(이전 CORE) Fleet이 쥔 능력 값이 두 번의 갱신 주기보다 오래됐으면 지금처럼 `front/status`를 부른다. 사이트 스위치 `fleet.trip.lane_camera_check`는 그대로. envelope 1.0 유지 |
| v1.197 | 2026-10-10 | Additive (D-524·D-530, feat/host-health-read): `GET /api/fleet/hosts`에 읽기 전용 `guard`와 `drift`를 더한다. 없거나 객체가 아니면 null. PC `resources`는 가드가 이미 읽은 `avail_pct`·`swap_pct`·`load`·`cores`·`uptime_s`·`down`. 동작 집합과 POST는 그대로다. 프로세스 종료와 로봇 재부팅은 없다. envelope 1.0 변경 없음 |
| v1.196 | 2026-10-10 | 동작 변경 (SAF-001·D-502, fix/battery-estop-latch-release, Safety-Review 대상): EMERGENCY 에서 `POST /api/v1/mode` 는 IDLE 을 포함해 어느 목표든 409 `MODE_CONFLICT` 다. 전에는 IDLE 이 EMERGENCY 를 래치가 걸린 채로 떠났고, 그 뒤 `POST /safety/release` 가 409 "not in EMERGENCY" 로 막혔다 (8kcn 2026-10-10 battery_policy). line-follow 멈춤 답은 WAIT 말고는 E-Stop 래치·EMERGENCY 에서 멈춤을 소비하기 전에 409 `EMERGENCY_ACTIVE` 다(ABORT·MANUAL 포함). `POST /safety/release` 는 래치가 IDLE 에 남은 상태(이전 CORE)도 Admin 에게 푼다. 해제 경로는 `POST /safety/release` 하나다 |
| v1.195 | 2026-10-10 | 동작 변경 (D-573 개정 3, feat/crosswalk-clear-5s, Safety-Review 대상): CORE 횡단보도 게이트의 보기 창 설정 `line_follow.crosswalk_look_s`(1.0 s)를 `line_follow.crosswalk_clear_s`(기본 5.0 s, 0.5–60)로 바꾸고 `crosswalk_look_min_scans` 기본을 8에서 40(10 Hz × 5 s × 0.8)으로 올린다. 창 안 모든 스캔이 빔이어야 하고 사람·UNKNOWN·오래된 스캔은 창을 다시 연다. `crosswalk_report_s`는 `crosswalk_clear_s`보다 커야 한다(아니면 시작 거부). 비워진 창이 도는 동안 `crosswalk_blocked`를 열지 않는다. 옛 키 `crosswalk_look_s`가 있는 설정은 CORE 시작을 거부한다(별칭 없음). 스냅숏 필드는 그대로이고 `look_progress`의 분모가 `crosswalk_clear_s`가 된다 |
| v1.194 | 2026-10-10 | 동작 변경 (D-573 6 개정·D-577 남은 항목 2·3, feat/crosswalk-null-outside-zone, Safety-Review 대상): CORE 는 `line_follow.crosswalk` 를 게이트 설정과 무관하게 늘 보고한다(게이트 기본값은 여전히 꺼짐). 값은 게이트 객체, 새 `{state: inside}`·`{state: ahead}`, 새 `{state: unknown, reason: pose_stale\|perception_stale\|not_watched\|zone_unplaced}`, 또는 null(구역 밖이 증명됨). 게이트를 켠 로봇도 이제 증명하지 못하면 null 대신 `unknown` 이다. Fleet 판단기는 `unknown` 을 R5 `crosswalk_unknown` 으로 막고, 현장 지도 횡단보도 0.29 m 안(신뢰 지도 자세)이면 R5 `crosswalk`, 지도에 횡단보도가 있는데 신뢰 지도 자세가 없으면 R5 `crosswalk_unknown` 이며, R5 를 보낸 막힘의 재전송은 같은 R5 로만 하며(R3·AI 답으로 바뀌지 않음), Fleet 정지로 끊긴 R5 도 사람 행을 올린다. 계약(같은 버전): `LaneContainmentEvidence` 선택 필드 `crosswalk_uncertainty_m`(m, 0–1, 영상 시각 몸 좌표에서 횡단보도 가까운·먼 끝의 앞뒤 최악 한도, 검출기가 돈 모든 프레임에 있음, 없음 = 돌지 않음). CORE 설정 `line_follow.crosswalk_max_uncertainty_m`(0.058). 필드가 없거나 한도를 넘으면 `unknown` 사유 `camera_crosswalk_unadmittable`; 구역 앞뒤 여유는 그 필드(차선 `uncertainty_m`은 옆만). 인식은 이 버전의 CORE가 로봇에 들어간 뒤 플래그로 낸다(기본 꺼짐). envelope 1.0 변경 없음 |
| v1.194 | 2026-10-10 | Additive + 동작 변경 (D-603, feat/core-rotate-to-heading, Safety-Review 대상): 로봇 `POST`/`GET`/`DELETE /api/v1/motion/rotate_to`(제자리 회전, odom 닫힌 고리, ≤ 30°/s·≤ 15 s·≤ 180°, trip lease 주인 또는 이름 적은 운영자), 능력 최상위 `motion {rotate_to}`, 오류 `ROTATE_CLEARANCE`·`MOTION_BUSY`·`ODOMETRY_STALE`·`OPERATOR_NAME_REQUIRED`, 사건 `motion.rotate_to`, `localization.mission`의 `kind: rotate_to`. Fleet `fleet.trip.auto_align`(기본 false): 출발 방향 어긋남을 CORE 회전으로 맞춘 뒤 다시 검사, 새 거절 `TRIP_ALIGN_REFUSED`·`TRIP_ALIGN_ABORTED`, `start_check.auto_align`, trip `detail.aligned`. 설정이 꺼져 있으면 Fleet 동작은 v1.193과 같다 |
| v1.193 | 2026-10-10 | 동작 변경 (D-596 개정 2026-10-10 사용자 결정 (a)(b), feat/led-confirm-anywhere-pin-prefill): `matched` 판정이 파랑 점멸(`evidence.mode`가 `steady` 아님)이면 예상 자리 밖이어도 `far_from_robot` 없이 이름을 붙인다(source마다 파랑 요청은 하나). 주황과 정색 표시는 예상 자리 안에서만. 콘솔 "위치 찍기"는 지도 자세가 `LOCALIZED`가 아니고 `GET /api/fleet/tracking/identity`에 `CONFIRMED` 트랙이 있으면 그 자리를 핀 위치로 쓴다(방향은 운영자). 새 필드 없음 |
| v1.192 | 2026-10-10 | Behavioural + Additive (D-601, feat/trip-start-enables-camera-line): Fleet `POST /api/fleet/trips/{plan_id}/start`이 `lane` 계획에서 로봇 line-follow `OFF`를 거절하지 않고, 모든 시작 검사·trip lease·trip 열림 뒤 마지막으로 로봇 `PUT /api/v1/line-follow/mode {mode: CAMERA_LINE}`을 보낸다(trip 루프만; 운영자 `line-follow` 경로는 그대로 `IR_LINE`·`OFF`). 실패는 trip `failed`(`TRIP_LINE_FOLLOW_START_FAILED`) + 멈춤, 응답 409. 끝에서는 지금처럼 언제나 `OFF`. 새 시작 거절 422 `TRIP_START_HEADING_MISMATCH`(첫 차로 방향과 `fleet.trip.start_heading_tol_deg` 20° 넘게 다름)·`TRIP_START_OFF_LANE`(차로 반폭 밖), `detail {code, edge_id, heading_err_deg, tol_deg, off_lane_m}`. `/trip`: `lane` 계획은 로봇 `GET /api/v1/vision/front/status` `available`이 아니면 422 `TRIP_LANE_CAMERA_UNAVAILABLE`, 응답에 `start_check`(같은 검사), `TRIP_HEADING_CONFLICT` `detail.heading_err_deg`·`TRIP_START_OFF_MAP` `detail.off_lane_m`. 로봇 API 변경 없음. |
| v1.191 | 2026-10-10 | 동작 변경 + Additive (D-596 개정 2026-10-10·D-494 6항 개정, fix/marker-loss-auto-relocalize): `POST /api/fleet/robots/{id}/identify` 409 `IDENTIFY_ROBOT_CAUTION`(로봇이 주의 표시 중: 차선 HOLD 또는 도킹 실패, rosy-face가 점멸을 거절함). 자동 요청과 `matched` 확인의 예상 자리는 Fleet 지도 자세(반경 `auto_near_m` + odom 1 m마다 0.15 m, 최대 1.0 m), 없으면 마지막 마커 자리. 점수 0.1 미만 blob은 자동 규칙에서 세지 않음, 주의 중인 로봇은 자동으로 묻지 않음. Vision 판정 `processor_revision` `led-identity/3`(고리 2.6 r, S≥60, V≥120). `GET /api/fleet/robots/{id}/map-pose`: 서 있는 로봇은 sighting 사이가 10 s보다 길어도 일치 2회로 `LOCALIZED` |
| v1.190 | 2026-10-10 | Additive (D-511 개정 1, feat/fleet-lane-return): Fleet `GET /api/fleet/robots/{robot_id}/lane-compliance`와 `/api/fleet/state` 행 `lane_compliance`에 `return` `{state: ON_LANE|ON_LINE|OFF_LANE|OFF_MAP|WRONG_WAY, since, raw, edge_id, offset_m, side, bearing_deg, lane_heading_deg, turn_deg, entry, crosswalk, crosswalk_ahead}`(첫 판정 전 null). 설정 `fleet.lane_compliance` 새 키 `line_half_width_m`·`off_map_pad_m`·`off_map_unseen_s`·`return_persist_s`·`wrong_way_min_m`·`entry_ahead_m`·`crosswalk_ahead_m`·`return_cue`(기본 true). 켜져 있으면 Fleet이 로봇에 `POST /api/v1/line-follow/lane-cue`를 2 Hz로 보낸다(그 경로가 없는 CORE는 404, 60 s 뒤 다시). 콘솔 예외 한 줄 |
| v1.189 | 2026-10-10 | Additive (D-589 S1, feat/rosy-cam-recognition-tuning): `OverheadDetectionsPayload` 선택 필드 `tuning` `{state off/waiting/tuning/locked/paused/unsupported, score 0–1 또는 null, ev 실제 EV 또는 null, locked}`, `GET /api/fleet/tracking` `sources[].tuning`(lease 안, 아니면 null). `rosy-overhead/1` hello 뒤 텍스트 메시지 두 가지(공유 벡터 `overhead-ingest.v1.json` `messages.camera_example`·`camera_state_example`): 하향 `camera {seq, ev(보정 지수), ae_lock, awb_lock, max_exposure_us, antibanding}`, 상향 `camera_state {seq, applied{…, mode vision/local/disabled/thermal_hold}, supported{ev_min, ev_max, ev_step, …}, exposure_us, iso, thermal}`. `site-cameras.yaml` source 키 `auto_tune`(기본 true; Fleet은 읽고 무시). 표시 전용, 로봇 명령·envelope 1.0 변화 없음 |
| v1.188 | 2026-10-10 | Additive (D-577 개정 2026-10-10 AI PC 판단, feat/ai-pc-judge): 새 `POST /api/fleet/ai/proposals`(`ai_observer`; 사용자 결정 "AI PC 제안 → Fleet 검증 후 실행": Fleet이 봉투를 검증해 CORE에 결정으로 보내거나 규칙으로 되돌아감, `fleet_ai_proposals` 감사, `GET /api/fleet/ai` `proposals[]`). AI 사실 종류 `rear_blocked`·`path_blocked_by_robot`(분석기 `analyzer:stuck_scene@1`). 현장 설정 `fleet.stuck_resolver.ai_facts_acting`(로봇 id 목록, 기본 빈 목록)의 로봇에서 이 두 종류는 `stage: acting`이 되고, 살아 있는 동안 판단기의 후진 답(R2·R3·R6)을 R5 `WAIT` + 사람(`<cause>_hold:ai:<kind>`)으로 바꾼다. 다른 답은 만들지 않는다. 로봇 API 변경 없음. |
| v1.187 | 2026-10-10 | Behavioural + Additive (D-407·D-577 개정 2026-10-10, feat/stuck-5s-fleet-ai): CORE 설정 `line_follow.stuck_report_s`(기본 5.0, 0 = 끔, [0, 60]). 활성 차선 모드에서 결정이 그 시간 동안 0 이고 다른 막힘 원인이 없으면 막힘 `cause: no_motion`·`detail` = HOLD 사유를 열고 로컬 후진 없이 관제 답만 기다린다(`nav.line_stuck_asked` `reason: no_motion`). Fleet 판단기: `no_motion` 에 R6 `BACK_AND_RETRY`(R3 조건) 또는 R5 `WAIT` + 사람(`no_motion_hold:<이유>`); R3/R6 뒤 띠는 LEGACY odom 자세를 받지 않는다(`peer_unknown`); 현장 설정 `fleet.stuck_resolver.enrolled_robots`. 콘솔 원인 표시 `no_motion`. envelope 1.0 변경 없음 |
| v1.186 | 2026-10-10 | Additive (D-600, feat/background-relearn-with-robots): `GET /api/fleet/detections/config` `occupied`, `OverheadDetectionsPayload.unknown_floor`(선택, `OK`만), `GET /api/fleet/tracking` source `unknown_floor`, `POST /api/fleet/tracking/relearn` 응답 `occupied`·`unlocated`. Robot API와 envelope 1.0 변경 없음 |
| v1.185 | 2026-10-10 | 동작 변경 + Additive (D-596, feat/led-identity-active): `POST /api/fleet/robots/{id}/identify` 서 있는 로봇도 요청(`IDENTIFY_NOT_MOVING` 제거), source마다 색 하나씩 동시 요청(두 번째 로봇은 남은 색), 응답 `trigger`. detections config `identity_challenges`, `GET /api/fleet/tracking/identity` `pendings`·`last.trigger`·`config.auto_min_interval_s`. 사이트 `identity.auto_request` 기본 true와 자동 요청 규칙(`auto_marker_missing_s`·`auto_near_m`·`auto_min_interval_s`). CORE `POST /host/lamp/identify` 쿼리 `quiet`(자동 요청은 소리 없음, 다음 로봇 payload부터)와 Fleet 기본 색 파랑(자동은 파랑만, 마커가 계속 안 보이면 30 s→2 min→5 min), `matched`는 요청 로봇의 예상 자리 0.5 m 안(`far_from_robot`·`no_prediction`). Vision 판정 `processor_revision` `led-identity/2`(끔 0.8–2.2 s, 프레임 간격 1.1 s까지, 익명 blob 하나일 때 정색 표시 `evidence.mode:"steady"`). 확인 트랙은 여전히 D-511 입력·표시 전용 |
| v1.184 | 2026-10-10 | Additive (D-594, feat/fleet-robot-path-history): Fleet `GET /api/fleet/robots/{robot_id}/path`, the robot path Fleet records each second in map coordinates only (robot LOCALIZED map report, else D-494 3 map pose LOCALIZED/DEGRADED, else ceiling-camera CAMERA_ONLY), kept 24 h in the site DB. The console map trail draws this record (range 2 min / 10 min / this trip, per robot, solid/dashed/dotted by state) instead of building it from polled poses; a `localization: null` pose (may be odom) is no longer drawn. Robot API and envelope 1.0 unchanged |
| v1.183 | 2026-10-10 | Additive (D-577 3·4·5·8, feat/d577-ai-pc-situation-skeleton, shadow only): site-users 새 역할 `ai_observer`(토큰만, 콘솔 로그인 없음) — 모든 GET은 viewer처럼 읽고, 쓰기는 `POST /api/fleet/ai/facts`·`POST /api/fleet/ai/heartbeat`만 통과한다. 그 밖의 모든 쓰기 경로(비상정지·정지·막힘 답·trip·목표 포함)는 그 경로 자신의 guard와 무관하게 403 `AI_OBSERVER_FACTS_ONLY`. 새 `GET /api/fleet/ai`(viewer+). 막힘 행(`line_stuck`)에 `ai {state, owner_mode}`·`ai_facts[]`. 사실은 `fleet_ai_facts`(`--tasks-db`)와 메모리에만 두고 `stage: shadow`로 규칙 입력이 되지 않는다. AI PC 서비스 `operations/situation`(`rosy-situation`). 로봇 API 변경 없음. |
| v1.182 | 2026-10-10 | Additive (D-577 8, uiux/d577-queue-evidence-notify): Site Fleet 새 경로 `GET /api/fleet/robots/{robot_id}/line-stuck/evidence?stuck_id=`(viewer+) — 열린 막힘 하나에 로봇 앞 카메라 그림 한 장(`{robot_id, stuck_id, sequence, source, media_type, age_s, jpeg_base64}`). Fleet은 첫 읽기에 로봇 `GET /api/v1/vision/front/status`·`/front/frame?sequence=`로 받고 막힘이 열린 동안 메모리에만 둔다(디스크·버스·사건 없음, 막힘이 닫히면 버림). 404 `STUCK_NOT_OPEN`·`STUCK_PREVIEW_UNAVAILABLE`(실패는 남기지 않아 다음 읽기가 다시 묻는다). 콘솔 예외 큐의 막힘 행이 답 아래에 그림·프레임 번호·촬영 나이를 보이고, 행이 생기면 소리·브라우저 알림 한 번, 30 s 무응답이면 한 번 더 한다(로봇은 HOLD). 로봇 API 변경 없음. |
| v1.181 | 2026-10-10 | Behavioural + Additive (D-407 개정 2026-10-10, fix/keep-auto-resume): CORE CAMERA_LINE `LOST`는 차선이 다시 보이면 같은 모드로 자동으로 이어 간다. 설정 `line_follow.lost_auto_resume`(기본 true)·`lost_resume_frames`(3, = D-495 `junction_reacquire_frames`)·`lost_resume_s`(1.0, = D-407 `recovery_settle_s`); 조건은 연속 신선·확신 프레임, 앞 물체 정지 없음, IR 감시 비어 있음(또는 꺼짐). 사건 `nav.lane_reacquired` `{mode, frames, since_s}`. 상태·사유 문자열은 그대로이고 IR_LINE의 재선택 잠금도 그대로 |
| v1.180 | 2026-10-10 | Additive (D-593, feat/operator-map-pin-anchor): Fleet `POST /api/fleet/robots/{robot_id}/map-pin` (named operator), map-pose `anchor_source` (`sighting` \| `operator_pin`), `bridge_turn_deg` and `source` value `operator_pin`; trip start accepts a still operator pin up to 10 s old (`fleet.trip.pin_start_still_m` 0.02, `pin_start_still_deg` 2). Robot API and envelope 1.0 unchanged |
| v1.179 | 2026-10-10 | Additive (D-573 2·3·4·6, feat/crosswalk-core-gate, Safety-Review 대상, 기본 꺼짐): CORE line-follow 횡단보도 게이트. 설정 `line_follow.crosswalk_gate_enabled`(기본 false, URDF 몸 필요)·`crosswalk_look_s`(1.0)·`crosswalk_look_min_scans`(8)·`crosswalk_report_s`(10)·`crosswalk_cross_speed`(0.04)·`crosswalk_approach_default_m`(0, 보기 영역은 카메라가 본 차로 안쪽 경계 사이). 출처는 D-491 카메라 구역(Fleet 힌트는 나중). `GET /line-follow`·상태 `line_follow.crosswalk`(꺼짐이면 키 없음, 구역 밖 null), 막힘 원인 `crosswalk_blocked`와 `stuck.detail`, 그 원인의 움직이는 답 거부(`crosswalk_gate`). 꺼져 있으면 동작·응답 변경 없음. envelope 1.0 변경 없음 |
| v1.178 | 2026-10-10 | 동작 변경 + Additive (D-525 rev 6, feat/signal-occupancy-default): 가상 신호의 새 기본 모드이자 Fleet 재시작 상태는 `occupancy`(점유 기반)다(이전 `all_red`). 이 모드에서 신호는 D-517 구역 허가에 단계 관문을 더하지 않고(모든 입구 허용, 수용 1이 한 대만 들임) 등은 살아 있는 구역 상태에서 나온다: 비어 있음 모두 `green`, 허가만 쥠 그 입구 `green`·나머지 `yellow`(화면 주황), 점유·모름 모두 `red`. `POST /api/fleet/traffic/signals/{id}` 동사 `occupancy` 추가. `GET /api/fleet/traffic` `signals[]` `occupancy {state free\|reserved\|occupied\|unknown, holder, approach}`, `mode: occupancy`이면 `aspect`는 요약이고 `left_s`·입구 `left_s` null, `green_in_s`는 초록 0 아니면 null. `signal_ahead`(로봇 행과 `GET /api/fleet/traffic/signals/ahead/{robot_id}`)에 `mode`·`occupancy`. 설정 오류 신호의 입구 `lamp`는 늘 `red`. 등은 표시·참고이고 허가는 D-517만 준다. Robot API, D-551 advice `lamp` 값(green/yellow/red), CORE 명령과 envelope 1.0 그대로 |
| v1.177 | 2026-10-10 | Additive (D-587, feat/ceiling-marker-sightings): `SiteSightingPayload.calibration_source` 값 `approved_record`(승인 추적 보정으로 투영한 이름 있는 천장 로봇 마커, `corner_marker_ids: null`, revision = 그 source의 지금 승인 기록, 아니면 409 `CALIBRATION_MISMATCH`). `site-cameras.yaml` source 선택 키 `marker_yaw_offset_deg: {robot_id: deg}`(스티커 윗변 방향 − 로봇 앞, 반시계 +, 유한, 절댓값 360 이하; 그 source의 로봇만, `robot_ids: enrolled`이면 아무 로봇). 옛 Vision·Fleet은 이 키를 모른다며 시작을 거절하므로 릴리스 뒤에 설치한다 |
| v1.177 | 2026-10-10 | Additive (feat/vision-calibration-drift-watch): Fleet 교정 낡음 자동 검사 — GET /api/fleet/tracking 출처 행에 `calibration_drift`(서버가 승인 교정과 D-375 맞춤 제안을 주기 비교한 판정, 없으면 null). 새 엔드포인트 없음. Robot API·envelope 1.0 변경 없음 |
| v1.176 | 2026-10-10 | Additive (D-581, feat/trail-fleet-anchored-frame): §7.8 `anchor: fleet`·`for_robot_id`·`anchor_age_s`·`anchor_hold`(기준이 없을 때 침묵 대신 정지 표본, `swarm.hold` `anchor_withheld`, `stream_evidence[*].anchor_hold`) — TRAIL 대형에서 리더가 `frame: odom` 이면 Fleet 이 천장 카메라 기준(D-494 3)으로 팔로워마다 그 팔로워 odom 좌표의 표본을 만들어 보낸다(D-31 개정, `map` 프레임은 바이트 그대로). trail 팔로워는 자기 id 표본만 받아 자기 `odom_pose` 로 달린다. `swarm.hold` 사유 `reference_anchor_invalid`·`reference_frame_changed`, `swarm/state` `trail.anchor`, Fleet formation 상태 `anchor`. 안전 경로(D-422·SAF-004·D-400·스트림 단절) 변화 없음 |
| v1.175 | 2026-10-09 | Additive (D-580, feat/fleet-managed-site-roster): `GET /api/fleet/detections/config` `robot_markers`. `site-cameras.yaml` source `robot_ids: enrolled`(Fleet 명단을 따른다; `GET /api/fleet/site-map` 등의 `robot_ids`·`robot_markers`는 등록·해제 때 바뀐다). `POST /api/fleet/enrollment/robots`: 등록되었다 해제된 TLS binding은 다른 `robot_id`를 받는다(새 오류 코드 없음, 다른 binding의 ID면 `code_consumed` reason `robot_id_conflict`); 감사 동작 `tls_renumber`. `autoupdate.conf` `/api/fleet/state` 검사 `required_ids: "enrolled"` |
| v1.174 | 2026-10-09 | Additive (D-573 1, feat/crosswalk-fleet-map-zones): `rosy.site_map/1` 선택 필드 `crosswalks[] {id, polygon, approach[], lanes[], revision}`(lane_graph 다각형, 차로는 유도, 대기 띠는 편집기에서 그림; 차로에 닿지 않거나 D-507 9 바닥 밖이면 `SITE_MAP_INVALID`), `GET /api/fleet/site-map/lane-graph-crosswalks`(`SITE_MAP_NO_LANE_GRAPH`). 지도 자료와 표시만, CORE·교통·통행권 변경 없음 |
| v1.173 | 2026-10-09 | 동작 변경 (D-577 (a), feat/d577-resolver-default-lane-lost, Safety-Review 대상): `fleet console` 의 막힘 판단기 기본 켜짐(`--no-stuck-resolver` 로 끔, `--stuck-resolver` 는 호환용). `lane_lost` R3 `BACK_AND_RETRY` 조건 좁힘(로컬 복구·시도·예산·거절 없음·CORE가 `line_follow.crosswalk: null` 보고·Fleet 지도 자세 신선 또는 목격 출처 없음·신뢰 자세로 잰 뒤 띠 비어 있음; 모르면 닫힘)과 새 R5(`WAIT` + 사람, escalated `lane_lost_hold:<이유>`). 로봇 행 `line_stuck.resolver.age_s` 추가. 자격 없는 로봇과 trip 로봇(D-517 M4) 동작은 그대로. Robot API·envelope 1.0 변경 없음 |
| v1.172 | 2026-10-09 | 동작 변경 (D-517 3 개정, fix/trip-lap-hold-outside-zone, AI PC 신호 SIM): 현장 구역이 있으면 trip이 구역 안에 서지 않는다. 구역 차로로 들어오는 목적지나 반복 운행 바퀴의 마지막 장소는 경로를 따라 구역 밖에 설 수 있는 가장 가까운 장소로 옮긴다(사용자 결정 "다음 지점까지 가서 섬"). trip 보기 선택 필드 `stop_moved {from, to}`(옮기지 않았으면 null), 구역 옆 장소의 `stop`은 `stop_after_m`을 줄여 구역 밖에서 선다. 그런 장소가 경로에 없을 때만 `POST /api/fleet/trips/{plan_id}/start` 422 `TRIP_STOP_IN_ZONE`(`detail {place, repeat}`). 출발 차로를 고를 때 막힌 차로를 뺀다. Robot API·CORE 명령·envelope 1.0 그대로 |
| v1.171 | 2026-10-09 | Additive (D-575, fix/ceiling-marker-missed-and-unassigned): `GET /api/fleet/tracking` `unknown[].marker_id`(익명은 null, 배정 로봇 없는 마커는 그 id). Vision은 `robot_markers`에 없는 D-562 로봇 범위 마커(40–49)도 검출 payload에 싣는다(스키마 변화 없음). 표시 전용, 로봇 명령·envelope 1.0 변화 없음 |
| v1.170 | 2026-10-09 | Additive (D-559, feat/swarm-trail-follow): `POST /api/v1/swarm/follow` 선택 필드 `mode: offset\|trail`(기본 offset, 이전과 같다), `GET /api/v1/swarm/state` 의 `mode`·`trail`, §7.8 `payload.frame: map\|odom`, `swarm.hold` trail 사유, `swarm.aborted` `trail_join_too_far`, Fleet `formation: TRAIL`. trail 은 CORE 가 NAVIGATION 슬롯을 직접 조향한다(SAF-004 클리핑·D-400·D-422 몸체 정지를 지난다). envelope 1.0 유지 |
| v1.169 | 2026-10-09 | 동작 변경 (D-565, fix/fleet-tls-renumber-enroll, 보안 검토 대상): `POST /api/fleet/enrollment/robots`가 등록 행이 없는 HTTPS 로봇을 아직 등록되지 않은 승인 binding으로 등록한다(CA·호스트 이름·`robot_id` 셋이 맞아야 함). 새 오류 409 `tls_binding_mismatch`. Fleet 기동은 등록되지 않은 binding을 거절하지 않고 경고한다(다른 등록 행의 호스트 이름이면 계속 거절). v1.167·v1.168은 다른 브랜치(D-560·D-564)가 선점 |
| v1.168 | 2026-10-09 | Additive (D-564, feat/ceiling-place-markers): 바닥 장소 마커 `POST`/`GET /api/fleet/place-markers`(source token, 2 s), `POST /api/fleet/teach/place-from-marker`(이름 있는 운영자, 초안 장소 추가·이동), 공유 스키마 `PlaceMarkerPayload`, 사이트 카메라 설정 `place_markers`. 표시·가르치기만, 로봇 명령 없음. v1.166은 다른 브랜치(feat/route-context-bend-phase)가 쓴다 |
| v1.167 | 2026-10-09 | Additive (D-560 S1, feat/rosy-cam-map-plane): Vision 미리보기 lease `rectification`에 `{"mode": "map"}`(다른 필드 없음). Vision이 추적용 승인 보정 기록으로 원본을 지도 평면(track_bounds_m + 0.15 m, 400 px/m, 긴 변 ≤ 1920 px)에 펴서 `X-Frame-Rectified: map`·`X-Frame-Plane`·`X-Frame-Calibration`과 함께 돌려주고, 기록이 없거나 source·map·렌즈·비율이 다르면 409 `X-Frame-State: plane-unavailable`(원본 대체 없음). `manual`·`auto`와 원본 프레임·추적 불변. 스키마·envelope 1.0 변경 없음 |
| v1.166 | 2026-10-09 | Additive (D-531 굽이 단계 보완, 기본 꺼짐): `line/route_context`의 선택 필드 `bend_phase: bending|reacquiring`. CORE 굽이 진행·재획득 단계의 B9 기대 굽이 창을 표시한다. Fleet 경로 지시와 CORE의 최종 주행 권한은 그대로이며 실물 재생·SIM·DEVICE 수용은 별도 |
| v1.165 | 2026-10-09 | Additive (D-531 P1, 기본 꺼짐): CORE `line/route_context` 경로 증거, `line_follow.route_context`·`route_context_published_at_s` 상태, `base_velocity.route_context` 능력, 인식 `route_context_seq` 역검증. 기존 주행 판단 불변; P2/P3와 SIM·DEVICE 별도 검증 |
| v1.164 | 2026-10-09 | Additive (D-546 5–7 첫 조각, feat/d546-pose-request, Safety-Review 대상): `GET /api/v1/localization/request`, 오류 `NO_REQUEST`, 이벤트 `localization.request`·`localization.request_cleared`. lane_return(D-468)이 `pose_stale`(1 s 이상) 또는 `fleet_required` 에서 CORE 의 위치 요청을 열고 닫는다. 기존 필드·경로는 그대로이며 옛 Fleet 은 요청을 읽지 않을 뿐이다. 장치 기본값(`localization` 꺼짐)은 그대로다. |
| v1.163 | 2026-10-09 | Additive (D-555, feat/enrolled-hub-pairing, 보안 검토·Safety-Review 대상): `GET`/`PUT`/`DELETE /api/v1/fleet/link`(TLS 리스너, 관리자 또는 사이트 등록 토큰), 능력 최상위 `fleet_link_provisioning`, 사건 `fleet.link_provisioned`·`fleet.link_cleared`, 오류 `FLEET_GOAL_ACTIVE`·`FLEET_LINK_CONFIG_INVALID`(409), `GET` `arm_state`·`arm_deadline_s`, Fleet 강제 해제 `?force=true`. SAF-003 `configured` 는 지금 설정을 읽는다(실행 중 페어링·해제를 따른다). Fleet `POST`/`DELETE /api/fleet/robots/{robot_id}/hub-link`, 허브는 등록 로봇 HELLO 를 digest 로 확인. 스키마 변경 없음 — envelope 1.0 유지 |
| v1.162 | 2026-10-09 | Additive (D-541 7 Fleet side, feat/fleet-trip-lease-holder, Safety-Review 대상): 사이트 설정 `fleet.trip_lease_required`(기본 false)·`fleet.trip_lease_ttl_s`(기본 5, 1–10). 참이면 `POST /api/fleet/trips/{plan_id}/start` 가 CORE trip lease 를 열고(trip 마다 새 uuid `lease_id`), 주기마다 renew, 끝에서 정지 뒤 DELETE. 새 시작 거절 422 `TRIP_LEASE_UNSUPPORTED`, 409 `TRIP_ROBOT_LEASED`·`TRIP_ROBOT_MANUAL`·`CALIBRATION_ACTIVE`·`TRIP_LEASE_REFUSED`. 새 끝 `stopped`/`lease_lost`(`detail.lease_reason` `taken_over`·`expired`·`mode_left`·`estop`·`leased`·`core_restarted`·`renew_timeout`, `lease_by`), 다시 열지 않음. trip 보기 `lease`. 거짓이면 이전과 같다. Wi-Fi 끊김이 `ttl_s` 를 넘으면 trip 이 끝난다(현장별 10 s까지) |
| v1.161 | 2026-10-09 | 권한 변경 (D-540 9, fix/fleet-named-operator-motion-routes, Safety-Review 대상): 로봇을 움직이는 Fleet 경로는 이름 있는 운영자만. 공유 콘솔 토큰과 자격 없는 루프백(`site-console`)은 403 `OPERATOR_IDENTITY_REQUIRED`(자격 없음·틀림은 그대로 401). 대상: `POST /api/fleet/robots/{robot_id}/goal`, `/line-follow`(`OFF` 제외), `/route`, `/identify`, `/line-stuck/decision`(`RESUME`·`BACK_AND_RETRY`·`MANUAL`), `POST /api/fleet/dispatch/rearm`(발행 재개가 대기 작업을 움직인다), `POST /api/fleet/formation/{start,reform,resume}`, `POST /api/fleet/signals/{signal_id}/command`(`all_red`·`flash_red` 제외), `PUT`·`DELETE /api/fleet/start-points/{source_id}`, `POST /api/fleet/do`(`estop`·`cancel`·`stop`·`formation_stop`·`follow_cancel` 만인 요청 제외). 멈춤은 어느 운영자에게나 열림: `/api/fleet/estop`, `/cancel-all`, `/robots/{robot_id}/cancel`, `/tasks/{task_id}/cancel`, `/formation/stop`, 막힘 `WAIT`·`ABORT`와 `/line-stuck/claim`(콘솔이 `ABORT` 확인 전에 맡는다), 그리고 `POST /api/fleet/trips/{trip_id}/cancel`(v1.116–v1.160 은 이름 있는 운영자였다). 이미 이름이 필요했던 `POST /api/fleet/cell-jobs/{mission_id}/cancel`(HOLD 작업만 끝내고 점유를 푼다, 움직임을 세우지 않음)과 `POST /api/fleet/teach/stop`(녹화만 끝낸다, 로봇에 명령 없음)은 멈춤이 아니라 그대로 둔다. 이름 있는 운영자 = `site-users.yaml` 자격·D-519 로그인 쿠키·D-473 개발 세션. 현장 이행은 D-540 9 운영 메모(배포 전 `site-users.yaml` 로그인 줄). 스키마·envelope 1.0 변경 없음 |
| v1.160 | 2026-10-09 | Additive (D-550 10 목표 임대, feat/navigation-goal-lease, Safety-Review 대상): `POST /api/v1/navigation/goal` 선택 필드 `lease_ttl_s`(0 < s ≤ 5, `correlation_id` 필요), `POST /api/v1/navigation/goal/lease` 구현, 오류 `GOAL_LEASE_NOT_ACTIVE`(409), 능력 `controls` `base_velocity.goal_lease`. 임대 만료는 `nav.canceled` source `goal_lease`(사건 모양 변화 없음). `lease_ttl_s`가 없는 목표는 v1.159 와 같다. Fleet 쪽: 설정 `fleet.goal_lease_ttl_s`(기본 0 = 끔), `POST /api/fleet/goal-lease/presence`(이름 있는 운영자). envelope 1.0 변화 없음 |
| v1.159 | 2026-10-09 | Additive + 동작 변경 (D-548, feat/device-dev-profile): 이벤트 `auth.development_mode` `{marker}`. 장치 모드 CORE 는 `/etc/rosy/dev-mode` 가 있을 때만 공용 개발 토큰 `rosy-dev-*` 를 받는다(없으면 D-193 7 그대로). 그 토큰은 장치에서 `/host/ssh*`·`/auth/enrollment-codes` 전부와 `/host/*`·`/system/tokens*`·`/system/dds*` 쓰기에 403 `FORBIDDEN`. Fleet `--mission-api` 는 `--users-file` 대신 개발 연결 모드로도 시작. 스키마 변경 없음 — envelope 1.0 유지 |
| v1.158 | 2026-10-09 | Additive (D-526 1단계, feat/fleet-tether-watch, Safety-Review 대상): Fleet tether 감시. `GET /api/fleet/tethers` 행에 `watch {state, trip, distance_m, turn_deg, pose_age_s, stop_sent, stop_error}`(첫 틱 전 null); 반경+0.15 m·누적 회전 405°·지도 자세 2 s 없음이면 기존 로봇 E-Stop을 보내고 그 로봇의 trip을 `tether_trip`으로 끝낸다. 테더 POST가 감시를 다시 시작한다. 신뢰하는 지도 자세(LOCALIZED·map)만 지도 자세이고 `localization`이 없으면 2 s 안에 정지한다. 목록에 `watch_age_s`, `watch`에 `stop_failures`·`tick_age_s`, E-Stop 10회 실패는 관제 `alarms`의 `TETHER_STOP_FAILED`. 로봇 API·envelope 1.0 변경 없음 |
| v1.157 | 2026-10-09 | Additive + 동작 변경 (D-541 CORE 부분, feat/core-trip-lease, Safety-Review 대상): `PUT /api/v1/trip-lease`, `DELETE /api/v1/trip-lease/{lease_id}`, `POST /api/v1/trip-lease/takeover`; 상태 선택 필드 `trip_lease`·`trip_lease_ended`(없으면 키 없음); 능력 `base_velocity.trip_lease`; 오류 `TRIP_LEASED`·`MANUAL_MODE`; 이벤트 `trip_lease.opened|renewed|ended|shared_token`. 동작 변경은 lease 가 살아 있을 때만: 주인 아닌 `/mode`·`/teleop`·구동 쓰기 409 `TRIP_LEASED`, `POST /calibration/session` 409 `TRIP_LEASED`, `/ws/swarm/reference` 주인 아닌 프레임 버림, 주인 아닌 `navigation/cancel`·line-follow OFF 는 lease 를 끝내고 IDLE, 주인의 `navigation/goal` 은 line-follow 가 켜져 있어도 받음, 만료·넘겨받기는 IDLE, 끝난 `lease_id` 의 PUT 은 404(다시 열지 않음), `localization/mission` 409·`decision`·`suspect` 423 `TRIP_LEASED`, DOCKING 에서 열기 409 `MODE_CONFLICT`. lease 가 없으면 동작은 v1.156 과 같다. Fleet 쪽 코드(`TRIP_ROBOT_LEASED`·`TRIP_ROBOT_MANUAL`·`TRIP_LEASE_UNSUPPORTED`)는 Fleet 구현(D-541 7, feat/fleet-trip-lease-holder)과 함께 싣는다. envelope 1.0 변화 없음 |
| v1.156 | 2026-10-09 | Additive (D-551, feat/core-line-advice): `POST /api/v1/line-follow/advice` 구현(표시만, 허가 아님), `GET /line-follow` 선택 키 `advice`, 능력 `controls` `line_follow_advice`. 공유 schema `core_common.protocol.line_advice` |
| v1.155 | 2026-10-09 | Additive (D-535, feat/connect-failure-reasons): 연결 이유 코드 21개(ERR-102 행, 기계 원천 `connect-reasons.v1.json`). `/api/v1/auth/peer-pairing/*` 거절에 기존 상태·`detail`을 두고 `error {code, message, detail.action, detail.retry}`를 더함, 한도 거절에 `Retry-After`. `GET /api/v1/auth/connection`에 `connect_contract`·`api`·`core_ready`·`stage`·`release`·`tls_hostname`·`pairing`, 출발지별 30회/분 429, LAN 밖 403 코드 `LAN_REQUIRED`(이전 `FORBIDDEN`). Fleet `GET /api/fleet/state` 로봇 행 선택 필드 `link_reason {code, message, action, retry}`. envelope 1.0 변화 없음 |
| v1.154 | 2026-10-09 | 동작 변경 (D-520 개정 2026-10-09, fix/d520-arc-entry-tangent·feat/d520-arc-radial-tracking·docs/d520-default-on-ring, Safety-Review 대상): `line_follow.arc_enabled` 기본 켬, 능력 `lane_arc` 는 그 설정·`site_floor_map_id` 선언·`ir_guard_speed_scale` > 0 이 함께 있을 때만 참(선언 없는 켬은 시작 거부가 아님); 409 `LANE_ARC_UNAVAILABLE` 은 그 능력이 거짓일 때; 호 명령에 odom 지도 원으로의 반지름·방향 보정(\|c\| ≤ 1.5 1/m), 원과 0.075 m 넘게 떨어지면 HOLD `lane_arc_edge`, 첫 IR 판정이 원을 옮김. 스키마 필드 변경 없음. Fleet 은 `exit_segment` 가 있는 회전에도 `turn_target` 회전각을 보낸다 |
| v1.153 | 2026-10-09 | Additive (D-524 Proposed, feat/host-control, Safety-Review 대상): `GET /api/fleet/hosts`(운영자, 행에 `stoppable_units`)와 `POST /api/fleet/hosts/{host}/control`(이름 있는 운영자). 409 `REBOOT_ALREADY_SCHEDULED`·`NO_HOST_CONTROL_REBOOT`, 503 `HOST_HELPER_UNAVAILABLE`, 502 `HOST_HELPER_FAILED`. 사이트 유닛은 재시작만. envelope 1.0 변경 없음 |
| v1.152 | 2026-10-08 | Additive (lap SIM 2, fix/junction-corner-hold-scope, Safety-Review 대상): `POST /line-follow/junction` 선택 필드 `lane_turn_deg`(`straight` + 기대 창, −360…360); `junction_corner_hold` 는 지시와 어긋나는 모서리에서만(`left`/`right` 의 반대쪽, `straight` 는 `lane_turn_deg` 가 그쪽 20° 미만이거나 없을 때). Fleet 이 `straight` 에 지도 차로 방향 변화를 싣는다. envelope 1.0 그대로 |
| v1.151 | 2026-10-08 | Additive (D-517 M5 발견 1, fix/d517-trip-authority-mismatch, Safety-Review 대상): `POST /api/fleet/trips/{plan_id}/start` 422 `TRIP_AUTHORITY_SITE_OFF` — 사이트 `fleet.traffic.authority` 가 꺼져 있는데 로봇 능력 `line_follow_authority_required` 가 참이면 `lane` trip 을 열지 않는다(통행권이 나가지 않아 CORE 가 서 있고 trip 이 20 s 뒤 `stall` 로 끝나던 것). CORE 동작 변경 없음. envelope 1.0 변경 없음 |
| v1.150 | 2026-10-08 | Additive (D-361 S4 identity readback): robot `GET /api/v1/system/info` includes provisioned `device_uid` (or null); on a provisioned Pi with no configured serial, `serial_number` reads the CPU serial (or remains null). Fleet enrollment can store both on a new pairing; existing rows are unchanged. Envelope 1.0 and motion authority unchanged |
| v1.149 | 2026-10-08 | Additive (D-517 5 M4, feat/d517-m4-fleet-resolver, Safety-Review 대상): `GET /api/fleet/traffic` `resolver [{robot_id, trigger wait_cycle\|unknown, decision replan\|wait\|human, cycle, blocked_edges, since}]`; a wait cycle replans one member around the unit it waits for as an operator-confirmed `hold.reason: replan`; the D-438 stuck resolver answers trip robots with `WAIT` only. Robot API, CORE commands and envelope 1.0 unchanged |
| v1.148 | 2026-10-08 | Additive (lap SIM A, fix/junction-corner-hold, Safety-Review 대상): CORE HOLD 사유 `junction_corner_hold`(기대 창이 있는 지도 지시가 `armed` 이고 `line/keep_debug` `strategy` 가 기대 가로선 0.45 m + `expect_tol_m` 안에서 `corner_left`·`corner_right`, 2 s 래치; 그 정지 중 만료되면 새 지시나 모드 변경까지 HOLD). Fleet trip `stopped` `junction_corner_hold`(자기 지시에서 바로). envelope 1.0 그대로 |
| v1.147 | 2026-10-08 | Additive (uiux/robot-navigation-stage): `GET /api/v1/navigation/state`에 `mapping_active`를 추가해 CORE 맵핑 세션 수락 상태를 읽는다. 실제 SLAM Toolbox 실행 증거는 아니다. 같은 브랜치의 `/navigation/path` 수신 `map_id`·`frame_id`·`age_s`도 명시한다. 주행 권한과 envelope 1.0은 그대로다. |
| v1.146 | 2026-10-08 | Additive (D-517 9 M3, feat/d517-m3-lane-convoy, Safety-Review 대상): Fleet `POST /api/fleet/robots/{robot_id}/trip` `convoy {leader}` (with `repeat`), start refusals `TRIP_CONVOY_SELF`, `_LEADER_NOT_RUNNING`, `_LEADER_IS_FOLLOWER`, `_OTHER_LOOP`, `_NOT_BEHIND`, `_NO_AUTHORITY`, `_LOOP_FULL`, trip view `convoy`, `GET /api/fleet/traffic` robot `front_d_m` and `convoy {leader, follows, gap_m}`; a follower's authority end follows the member ahead (moving block). Robot API, CORE commands and envelope 1.0 unchanged |
| v1.145 | 2026-10-08 | Additive (D-520 단계 1 CORE, feat/d520-core-arc-feedforward): `POST /api/v1/line-follow/junction` 선택 객체 `exit_segment {curvature_1pm, length_m, outer_line_offset_m, end_place_id}`(`map_id` 필수, 400 `VALIDATION_ERROR`), 409 `LANE_ARC_UNAVAILABLE`, 능력 `base_velocity.lane_arc`, `line_follow.arc` 상태와 `junction.pivot_basis` 값 `segment_end`, 정지 사유 `lane_arc_edge`·`lane_arc_pose_lost`·`lane_arc_motion_unconfirmed`·`lane_arc_timeout`·`lane_arc_blind`(·`lane_arc_entry` 예약), 상태 사유 `lane_arc`·`lane_arc_correcting`, 이벤트 `nav.lane_arc_end_unarmed`, 지시 `aborted` 사유 `arc_mismatch`, 호 기록 `reason` `lane_arc_end_unarmed`, 횡단보도 구역 위 호 거절(`junction.reason` `arc_crosswalk`), 호가 도는 동안의 `bend` 409 `JUNCTION_ARC_RUNNING`(호 끝에 `armed` `bend` 가 있으면 `aborted`·`arc_mismatch` 로 지시 없는 끝과 같다). 설정 `line_follow.arc_enabled`(기본 false)·`arc_curvature_gain`·`arc_blind_max_m`. 카메라 호 맞춤(단계 2) 없음. v1.142–v1.144 는 다른 브랜치(feat/d507-bend-odom-pass, feat/d517-m2-authority, feat/d517-m3-lane-convoy 워크트리)가 쓰고 있어 건너뜀 |
| v1.143 | 2026-10-08 | Additive (D-517 4 M2, feat/d517-m2-authority, Safety-Review 대상): CORE `POST /api/v1/line-follow/authority` 와 에러 `AUTHORITY_ODOM_STALE`·`AUTHORITY_POSE_STALE`·`AUTHORITY_POSE_FUTURE`, 강제 중에만 붙는 `GET /line-follow` `authority`, 설정 `line_follow.authority_required`(기본 false), `base_velocity` 능력 `line_follow_authority`·`line_follow_authority_required`, 공유 schema `core_common.protocol.line_authority`. Fleet: 사이트 설정 `fleet.traffic.authority`(기본 false)와 능력이 있을 때만 trip 주기마다 통행권 전송, trip 보기 `traffic_authority`·`caps.line_follow_authority`, map-pose `odom_stamp`, `until_m` 은 표의 앞 끝 `d` 기준, trip 시작 거절 422 `TRIP_AUTHORITY_NOT_REQUIRED`. 둘 다 꺼져 있으면 동작 변경 없음. envelope 1.0 변경 없음 |
| v1.142 | 2026-10-08 | Additive (D-507 보충, feat/d507-bend-odom-pass): `POST /api/v1/line-follow/junction` `action: bend`(`turn_deg`, `map_id`, `bend_in_m`, `bend_tol_m`, `bend_radius_m`), `junction.state` `bending`, 사유 `junction_bending`, 중단 이유 `no_anchor`·`lane_lost_before_bend`·`distance`·`bend_basis_lost`·`off_path`, `rosy.controls/1` `base_velocity.lane_bend`; site map place kind `bend`(`exit_yaw`, `radius_m`); Fleet trip 루프의 굽이 지시. 굽이 장소가 없는 지도와 `lane_bend` 가 없는 로봇은 그대로다. envelope 1.0 변화 없음 |
| v1.141 | 2026-10-08 | Additive (D-517 M1a, feat/d517-m1-fleet): one Fleet trip per robot (`TRIP_BUSY` per robot, `GET /api/fleet/trips` `open`), `POST /trip` `repeat` laps with per-lap start checks and `hold.reason: lap`, D-513 start places part-way along a lane as goals and vias, `TRIP_LOOP_FULL`, read-only `GET /api/fleet/traffic` block table; a junction instruction into a refused block is held back and that wait is not a stall. No authority is sent; Robot API, CORE commands and envelope 1.0 unchanged |
| v1.140 | 2026-10-08 | Additive (D-512 개정 1 표시 쪽, feat/fleet-map-trail): Fleet `GET /api/fleet/tethers`, named operator `POST`·`DELETE /api/fleet/robots/{robot_id}/tether`. 지도 궤적은 기존 상태 pose(map 프레임만)를 브라우저가 모은다. 로봇 API·envelope 1.0·주행 권한 변경 없음 |
| v1.139 | 2026-10-08 | Behaviour (D-507 2 개정, 2026-10-08 사용자 결정, fix/d507-travelled-distance-window): Fleet trip 루프는 기대 창(`expect_in_m`·`expect_tol_m`) 없는 `left`·`right` 를 보내지 않고 trip 을 `stopped` `junction_no_window` 로 끝낸다(`detail.junction_place`·`junction_action`·`junction_fields`). `straight`·`stop` 은 그대로. 같은 결정 (1): `POST /api/v1/line-follow/junction` 의 기대 창은 주행 거리로 비교한다. `expect_in_m` 은 차로를 따른 거리이고 CORE 는 받은 뒤 odom 경로 길이 + `junction_ahead_m` 을 `expect_in_m − pivot_past_line_m` 과 비교한다(곧은 접근에서는 예전 값과 같다). Fleet 은 15° 굽이 규칙을 없애고 `expect_in_m` = 차로 polyline 거리, 선 찾기는 장소의 차로 방향, `expect_tol_m` 의 odom 오차 항에 갈 거리를 더하고 광선 옆 거리 항을 뺀다. 필드 이름·범위는 그대로. envelope 1.0 변경 없음 |
| v1.137 | 2026-10-08 | Additive (D-519): Fleet `POST /api/fleet/auth/login`, `POST /api/fleet/auth/logout`, `GET /api/fleet/auth/session`; `GET /api/fleet/auth/connection` adds `password_login`. Console people log in with site-users `login` + `password_scrypt` and get an HttpOnly `SameSite=Strict` `Secure` session cookie (12 h idle, 30 d with remember, 30 d absolute, voided on account change); Bearer still wins, cookie-authenticated unsafe methods need `Origin` = `Host` (403 `CSRF_REJECTED`). Robot API·envelope 1.0 변경 없음 |
| v1.136 | 2026-10-08 | Additive (feat/lane-bend-cue): Fleet lane trip `detail.bend_candidate` 읽기 전용 지도 굽이 후보. 활성 지도 버전·신선한 정렬 자세 조건에서만 표시하고 근거 상실·trip 종료 시 삭제한다. 로봇 API·CORE 명령·envelope 1.0 변화 없음. |
| v1.135 | 2026-10-08 | D-507 2·4 개정(fix/d507-map-cross-line-pivot, SIM 발견 1–2): `POST /api/v1/line-follow/junction` `pivot_past_line_m` 범위 [0, 0.30] → [−0.30, 0.30]. 음수는 측정 가로선이 장소 점 너머(먼 쪽 경계)라는 뜻이다. 접근 목표가 로봇 자리이거나 뒤면 접근 0, 후진 없음. 직진 띠 반폭은 양수 pivot 일 때만 그 값. 가로선 띠는 측정 선(테이프 중심) ± 테이프 폭/2 ± e. Fleet은 지도 `lane` 차로의 합집합 경계에서 장소 너머 첫 칠한 선을 찾아 부호 있는 거리를 보내고, 0.30 m 안에 선이 없으면 나가는 차로 폭/2 와 창 없음. 창을 보내지 않는 장소에는 음수 pivot 을 보내지 않는다(CORE `stop_point`). v1.131·v1.132는 다른 브랜치 몫 |
| v1.134 | 2026-10-08 | Behaviour (D-507 7 개정 2026-10-08, feat/d507-item7-departure-evidence): v1.133 위에서 — D-468 이탈은 (1) 신선한 `ready` 차로에서 `margin + uncertainty_m < 0` 외에 (2) 추종 중 자세 불연속(odom 점프)·연속성 epoch 변경, (3) 증명된 차로 안이지만 체크포인트 차로가 아님에서도 열린다(사용자 결정, D-507 7 개정). `lane_return_containment: unknown` 틱은 D-468이 결정을 내지 않아 D-407 막힘(`stuck`)이 `recovery_local_enabled: false` 와 같은 시각에 열리고, 그동안 필드는 `unknown` 이다. 점프 뒤 새로 잡은 체크포인트가 기준이 되어 같은 차로를 (3)으로 읽지 않는다. 필드 이름·형식 변화 없음 |
| v1.133 | 2026-10-07 | Additive + behaviour (D-507 7, feat/d468-departure-on-evidence): `GET /api/v1/line-follow` 선택 필드 `lane_return_containment`(`contained`\|`unknown`\|null). D-468은 이탈의 양의 증거(신선한 `ready` 차로에서 `margin + uncertainty_m < 0`)가 있을 때만 `lane_return_*` 로 선다. 근거가 없거나 낡거나 불확실도가 미상·초과이거나 몸 기하가 없으면 추종은 `recovery_local_enabled: false` 와 같다(손실 시계 → LOST). 체크포인트 규칙은 그대로다. 기존 필드 이름·형식 변화 없음 |
| v1.132 | 2026-10-08 | Additive (D-472 addendum 3 / D-511, feat/d511-led-track-input): Fleet lane compliance (`GET /api/fleet/robots/{robot_id}/lane-compliance`, `lane_compliance` of `/api/fleet/state` rows) judges a fresh LED-confirmed track when the map pose is not `LOCALIZED`; new fields `pose_source`, `heading_source`. Observe only: Robot API, envelope 1.0, map pose, trips unchanged. v1.131 is held by feat/fleet-console-password-login (D-519); D-507 7 is v1.134 |
| v1.130 | 2026-10-08 | D-513 7: `rosy.site_map/1` optional `view_turn_deg` (0/90/180/270, omitted when 0), the one clockwise screen turn of the plain +y-up map view that Fleet map and camera views follow. Display only. Robot API·envelope 1.0 변경 없음 |
| v1.130 | 2026-10-08 | Additive (D-472 addendum, feat/d472-led-identity): Fleet LED 신원 — `identity_challenge`(detections config), Vision 판정 `POST /api/fleet/detections/identity`, 읽기 전용 `GET /api/fleet/tracking/identity`, `/robots/{id}/identify` 색 생략·움직이는 로봇 한정. 확인 트랙은 D-511 입력·표시 전용, 지도 자세 중재·trip·initialpose·명령에 쓰지 않음 |
| v1.129 | 2026-10-08 | Additive (D-472 addendum, feat/d472-led-identity): CORE `POST /host/lamp/identify`의 `color` 생략 시 로봇 설정 색, 움직이는 로봇에서도 정상 패턴 위 점멸, 안전 표시 중 즉시 거절, 요청~종료 6 s 상한. 신원 확정·주행 권한은 열지 않음. v1.124~v1.128은 다른 브랜치(D-511 M0 v1.128) 몫 |
| v1.129 | 2026-10-08 | Additive (D-507 2/3/9 Fleet side, feat/d507-fleet-trip-expect): trip start refuses 422 `TRIP_SITE_FLOOR_MISMATCH` when the robot's `site_floor_map_id` capability names another map than the active one; to robots with `junction_pivot: true` the trip loop adds `map_id`, `expect_in_m`, `expect_tol_m`, `pivot_past_line_m` to `POST /api/v1/line-follow/junction`; CORE `unexpected`, or `waiting` beyond `arm_distance_m`, ends the trip at once as `stopped` `junction_unexpected`. Robot API fields are CORE's D-507 2 change; envelope 1.0 unchanged |
| v1.128 | 2026-10-08 | Additive (D-511 M0, feat/d511-lane-compliance-m0): Fleet `GET /api/fleet/robots/{robot_id}/lane-compliance` and the `lane_compliance` field of `GET /api/fleet/state` robot rows — signed lateral offset, body margin and `OK`/`WARN`/`ACT`/`UNKNOWN` (UNKNOWN off the graph, past arc ends, across lanes) from the D-494 3 map pose, site config `fleet.lane_compliance`. The console exception queue shows WARN/ACT. Observe only: Robot API, envelope 1.0, trip/`/route`/meet thresholds unchanged. v1.124–v1.127 are held by open peer branches |
| v1.127 | 2026-10-08 | Additive (D-507 2–5항 CORE, feat/d507-junction-approach): `POST /api/v1/line-follow/junction` 선택 필드 `map_id`·`expect_in_m`·`expect_tol_m`·`pivot_past_line_m`, 409 `JUNCTION_ODOM_STALE`, `junction.state` `approaching`·`unexpected`, HOLD `junction_unexpected`, `junction.pivot_basis`(`map`\|`stop_point`), `rosy.controls/1` `base_velocity.junction_pivot`(최근 2 s 안 `line/keep_debug` 표지 `junction_ahead_v` ≥ 1 일 때만 참), `straight` 의 `pivot_past_line_m`(창 전용), 접근·직진 통과 중 측정 가로선 띠 안의 IR `centre` 허용. CORE 는 `line/keep_debug` 의 `junction_ahead_m` 을 읽는다. 필드가 없는 옛 Fleet 요청은 동작이 그대로다 |
| v1.126 | 2026-10-08 | Breaking config + Additive (D-507 6·9, feat/d507-motion-admitted-site-floor): 설정 `line_follow.site_floor_map_id`(문자열 또는 null, 기본 null; `^[A-Za-z0-9_.-]{1,64}$`, `site` 아님, `ir_guard_enabled`·`obstacle_mode: path`·URDF 몸 필요)가 `bridge_site_no_dropoffs`·`junction_turn_site_accepted`를 대신한다. 옛 키가 어느 설정 겹에 있어도 CORE 는 새 키 이름을 담은 오류로 시작을 거부한다(별칭 없음). `rosy.controls/1` `base_velocity` 선택 필드 `site_floor_map_id`. D-468 복귀·역추적, D-476 bridge, D-495 회전이 한 운동 허가(enforce 또는 현장 근거)를 쓰고, 현장 근거의 후진은 D-468 역추적만(한도 그대로). 중단 사유 그대로. envelope 1.0 유지 |
| v1.125 | 2026-10-08 | Additive (D-509): Fleet `GET /api/fleet/state` 선택 로봇 행 필드 `power_health`(기존 공유 `PowerHealthResponse` 또는 null), `power_health_age_s`(초 또는 null). Fleet Operator 토큰으로 CORE Viewer `GET /api/v1/power/health` 읽기, 최대 5초 표시 캐시. 오프라인·실패·스키마 오류·낡음은 확인 불가. CORE 경로·envelope 1.0·안전/명령 판정 불변 |
| v1.124 | 2026-10-08 | D-513: site map place kind `start` (demo start slot with required `yaw`); activation refuses a start place a trip could not start from (`SITE_MAP_START_INVALID`). Teach `POST /place` accepts `kind: start`; a new place in `/teach/confirm` does not (it has no robot yaw). Robot API·envelope 1.0 변경 없음 |
| v1.123 | 2026-10-07 | Additive (D-499): Fleet `GET /api/fleet/state` 로봇 행 선택 필드 `link`(`up`·`unreachable`·`moved`·`tls-refused`·`protocol`). 401이 아닌 로봇 API 오류에는 필드가 없다. 표시 전용. CORE 경로·envelope 1.0·발행 루프의 online/state/goal 판정은 그대로다 |
| v1.122 | 2026-10-07 | Additive (D-493, fix/d493-attention-stale-state): `GET /api/fleet/state` 로봇 행에 `state_age_s`(상태가 관찰된 뒤 지난 초. hub 나이와 SharedGather 캐시 나이 포함, 오프라인이면 `null`)와 최상위 `gathered_at`(마지막 실제 수집의 서버 UTC epoch 초, 표시용)을 더함. 콘솔 예외 큐는 `state_age_s` + 받은 뒤 지난 시간이 5초를 넘으면 "상태 오래됨" warn 을 붙인다. 기존 필드는 그대로다. |
| v1.121 | 2026-10-07 | Additive (D-407 Fleet 쪽, feat/d407-stuck-episode-log): Site Fleet 새 경로 `GET /api/fleet/line-stuck/episodes`(viewer+) — 막힘 에피소드 기록(`fleet_line_stuck_episodes`, `--tasks-db` 파일). 보드 전이에서만 쓰고 로봇 요청은 늘지 않는다. Robot API·envelope 1.0 변경 없음 |
| v1.120 | 2026-10-07 | Corrective + Additive (D-502, fix/core-battery-health): SAF-005 배터리 래치(`battery_policy`·`battery_deep`)도 모드 EMERGENCY 로 들어가 Admin `POST /safety/release` 로 풀린다(전에는 409 `not in EMERGENCY` 로 풀 수 없었다). `GET /sensors/battery` 는 404 대신 `evidence`·`sample_age_s`·`stale_after_s` 를 싣고, 표본은 제품 토픽 `battery/voltage` 에서 온다. `GET /safety/state` `battery` 에 `evidence`·`sample_age_s`·`level`·`percent`. Fleet envelope `protocol_version` 1.0 유지 |
| v1.119 | 2026-10-07 | Additive (D-494 6, feat/d494-fleet-teach-drive): Fleet 주행 가르치기 `GET /api/fleet/teach`, `POST /api/fleet/teach/start`, `/stop`, `/confirm`, `/place`. 기록은 D-494 3 map pose만 읽고 로봇에 아무것도 보내지 않는다. 확정과 주소 만들기는 초안 PUT과 같은 규칙으로 초안에만 쓴다. Robot API·envelope 1.0 변경 없음 |
| v1.118 | 2026-10-07 | Additive (D-498, feat/d498-junction-turn-site-basis): 교차로 회전의 운동 근거에 현장 근거를 더함 — 설정 `line_follow.junction_turn_site_accepted`(기본 false, `ir_guard_enabled` 없이 true 면 CORE 시작 거부), `junction_turn` 능력은 enforce 증명 또는 현장 근거가 있을 때만 참(읽을 때마다 재판단), 중단 사유 `turn_basis_lost`. envelope 1.0 유지 |
| v1.117 | 2026-10-07 | Corrective/semantic (D-468): containment boundaries are the drivable inner edge of the paint (previously paint centre). 생산자가 칠 폭 절반(`lane_paint_half_width_m`, 260919 STL 공칭 12.5 mm)만큼 안쪽으로 옮기고 그 값을 `geometry_id`에 넣는다. 필드 모양·envelope 1.0 변경 없음 |
| v1.116 | 2026-10-07 | Additive (D-494 5, D-495 3): Fleet trip loop `POST /api/fleet/trips/{plan_id}/start` (opens the v1.111 501 reservation), `POST /api/fleet/trips/{trip_id}/cancel`, `POST /api/fleet/trips/{trip_id}/confirm-replan`, `GET /api/fleet/trips`, `GET /api/fleet/trips/{trip_id}`; map activation now waits for a running trip instead of a recent `/route` step. While a trip runs, `/goal`, `/route`, task dispatch, `formation/start|reform|resume`, moving line-stuck decisions and line-follow modes other than `OFF` for that robot answer 409 `TRIP_ROBOT_BUSY`; every operator stop (cancel, cancel-all, E-stop, `OFF`, stuck `ABORT`/`MANUAL`) reaches the robot and cancels the trip. Uses robot `POST /api/v1/line-follow/junction` (D-494 4) and the D-494 1/3 capability and map pose inputs. Robot API and envelope 1.0 unchanged |
| v1.115 | 2026-10-07 | Additive (D-491): 내부 `line/observation` CAMERA_LINE `containment`에 optional `crosswalk`(`near_m`, `far_m`). `GET /api/v1/line-follow` 추종 사유 `ir_guard_crosswalk`(IR 감시가 알려진 횡단보도 구간에서 쉼). 기본 동작 불변: IR 감시 기본 꺼짐, 로봇 패키지 `ir_row_x_m` 없으면 쉬지 않음 |
| v1.114 | 2026-10-07 | Additive (D-494 4항, D-495, feat/d491-core-junction-action): CORE `POST /api/v1/line-follow/junction`(operator, 보정 lease)·에러 `LINE_FOLLOW_NOT_ACTIVE`·`JUNCTION_CAMERA_ONLY`·`JUNCTION_ALREADY_DONE`(409)·line-follow 상태와 스냅숏의 `junction`(`LineJunctionStatus`: `pending_action, place_id, state, seq`)·정지 사유 `junction_waiting`·`junction_unresolved`·`junction_stop`. 좌·우는 분기 인식 없이 D-495 제한 회전(`turn_deg`·`advance_m`, 상태 `turning`·`advancing`·`reacquiring`·`aborted`, `junction.turn_deg`·`junction.reason`, 사유 `junction_turning`·`junction_advancing`·`junction_reacquiring`·`junction_aborted`)으로만 간다. envelope 1.0 유지 |
| v1.113 | 2026-10-07 | Additive (D-494 3): Fleet `GET /api/fleet/robots/{robot_id}/map-pose`, the trip-only map pose from Rosy Cam sightings and robot `odom_pose`; site config `fleet.map_pose`. `/route`, traffic and D-395 unchanged. Robot API and envelope 1.0 unchanged |
| v1.112 | 2026-10-07 | Additive (D-494 1·2): `rosy.controls/1` `base_velocity` 선택 필드 `robot_kind`·`drive_modes`·`trip_max_linear`와 D-495 `junction_turn`; 상태 스냅샷 선택 필드 `odom_pose {x, y, yaw, stamp}`(UTC epoch 초); Fleet `/trip` 계획이 능력 필드가 있을 때 그 주행 방식·종류·속도를 따른다. 옛 로봇·소비자는 그대로 동작한다. envelope 1.0 유지 |
| v1.111 | 2026-10-07 | Additive (D-488/D-490 M1): Fleet site map `GET /api/fleet/site-map/active`, `GET/PUT /api/fleet/site-map/draft`, `POST /api/fleet/site-map/activate`; `POST /api/fleet/robots/{robot_id}/trip` returns a lane-state A* plan only; `POST /api/fleet/trips/{plan_id}/start` is 501 until M2. `/route` reads the active site map instead of a repo lane graph. v1.109 (D-484) and v1.110 (D-483) landed first on main. Robot API and envelope 1.0 unchanged |
| v1.110 | 2026-10-06 | Additive (D-483): D-456 요청의 수신 LCD 승인 코드 경로 POST `/api/v1/auth/peer-pairing/requests/{id}/confirm`(`X-Request-Secret`, `{approval_code}`). 화면 코드 관계는 168 h·persistent=false·발급자 token 없음(`screen-code`). 콘솔 `decision` 유지, envelope 1.0 유지 |
| v1.109 | 2026-10-06 | Additive (D-484): 천장 카메라 측정 캘리브레이션에 필드 경계 자동 캘리브레이션 추가. `SiteSightingPayload.corner_marker_ids` 선택화·`calibration_source` 추가, 미리보기 리스 `rectification.mode: "auto"`와 `X-Frame-Rectified: auto`·`X-Field-Calib`·`X-Frame-State: field-unavailable`, site-map source에 `calibration_source`. 로봇 마커·전선·정책 증거 의미 불변 |
| v1.108 | 2026-10-06 | Additive (D-473): Fleet `GET /api/fleet/auth/connection` and `POST /api/fleet/auth/development-session`. Development connection mode (both `ROSY_DEPLOYMENT=development` and `--connection-mode development`) gives same-LAN (or tailnet) console browsers a 1 h in-memory named operator session; paired mode unchanged. Robot API and envelope 1.0 unchanged |
| v1.107 | 2026-10-06 | Fix (버전 번호 변경 없음) (fix/sensors-nonfinite-json): `GET /api/v1/sensors`·`/sensors/{type}` 가 LiDAR `ranges` 의 inf/NaN 때문에 500 이던 것을 비유한 값 `null` 로 직렬화. 필드 추가·이름 변경 없음 |
| v1.107 | 2026-10-06 | Additive (D-472): CORE 후면 LED 단기 식별 요청과 Fleet 단일 로봇 전달 경로. Rosy Cam 프레임 표시만 연결하며 자동 신원·주행 권한은 열지 않음 |
| v1.106 | 2026-10-05 | Additive (D-468): CAMERA_LINE 관측에 원본 시각과 같은 optional containment 경계 증거, geometry/ground source/uncertainty를 추가. 명령·자동 복구 활성화·envelope 1.0은 변경 없음 |
| v1.102 | 2026-10-05 | Additive (D-368, feat/d368-driver-mjpeg-stream): 운전자 전용 MJPEG 스트림 `GET /api/v1/vision/front/stream`(operator, `multipart/x-mixed-replace; boundary=frame`, `?overlay=`). 조종 소유권은 수락 teleop 토큰(D-460 — 임대 없음). 운전자 아님 409 `CAMERA_STREAM_NOT_DRIVER`, 이미 열림 409 `CAMERA_STREAM_BUSY`, 새 수락 teleop가 열린 스트림을 끝낸다. 관전자·관제는 기존 0.4 s 폴링 유지. envelope 1.0 유지. v1.100(D-463)·v1.101(D-456)을 main이 먼저 써 v1.102로 재번호 |
| v1.105 | 2026-10-05 | Additive: Fleet 상태 로봇 행의 선택 capabilities(CAP-001 원문 또는 null), 표시 캐시 5초. 목표·양보 및 대형 전송 전에 지원 기능 재확인. CORE 계약·최종 안전 판정·envelope 1.0 유지 |
| v1.104 | 2026-10-05 | Additive: D-456 Fleet/Cam LAN 수신 승인 프로파일과 typed field handoff. CORE 운영자 로그인과 Fleet 영상 자격을 분리하고 envelope 1.0 유지 |
| v1.103 | 2026-10-05 | Additive: 사용자 승인 무마커 시작점. Fleet `/api/fleet/start-points` GET·PUT·DELETE, 승인 보정 revision에 묶인 지도 x/y/yaw 참조 저장과 동시 편집 거절. 로봇 API·envelope·주행 권한 변경 없음 |
| v1.101 | 2026-10-05 | D-456: LAN 수신 승인·P256 관계·명시적 연결 기억·issuer-bound 단기 세션·선택적 CA first-contact. D-460 조작 게이트 유지; 실기 수용 별도 |
| v1.100 | 2026-10-05 | Additive (D-463): POST `/api/fleet/robots/{robot_id}/route` expands stored lane-graph edge ids into that polyline and submits only the next point about 0.20 m ahead through the existing goal path. The far junction is not one goal. A pose that is not LOCALIZED in the map frame, or is more than 0.08 m off the polyline, does not call CORE. GoalRequest stays {x, y, yaw}. envelope 1.0 unchanged |
| v1.99 | 2026-10-04 | D-457: 마커 우선·무마커 폴백 표시 추적, source-token 검출, operator 보정·재학습. 기존 sighting·envelope 1.0·주행 경계 유지 |
| v1.98 | 2026-10-04 | Additive (D-343·D-432·D-452): 공개 LAN 로봇 발견 목록의 typed 64행 계약, FQDN/TLS 링크, 공용 cache와 제한된 singleflight fallback. 인증·승인·제어 부여 없음; 기존 v1.97 중앙 GET 정본과 envelope 1.0 유지 |
| v1.97 | 2026-10-04 | Additive (D-454): 기존 등록 로스터를 읽는 opt-in 중앙 Fleet GET 목록·상세의 구현 상태와 응답을 명시. 기존 Viewer 인증·등록 정본·envelope 1.0 유지; 중앙 쓰기·명령·미션은 미구현 |
| v1.96 | 2026-10-04 | Additive integration (D-452, D-450, D-453): 역할 발견·승인 directory, Cell 수동 간지 readback, CORE 단일 구간 YIELD 계약을 함께 보존. 기존 인증·HOLD·보정 lease·E-Stop 및 envelope 1.0 유지 |
| v1.95 | 2026-10-04 | Additive (D-453, feat/meet-algorithms): CORE `POST /api/v1/line-follow/stuck/decision` 에 `YIELD` 와 선택 필드 `yield_m`·`yield_turn_rad`. 한 답은 한 구간이고 outcome 에 `yield` 가 있다. 필드가 없거나 다른 결정에 붙으면 400. 보정 lease·E-Stop 은 `RESUME`·`BACK_AND_RETRY` 와 같다. `stuck_resolver` 의 `MANUAL` 은 403. 운용자 Fleet `POST /api/fleet/robots/{robot_id}/line-stuck/decision` 의 다섯 단어와 추가 필드 422 는 그대로다. 판단기가 로봇에 `YIELD` 를 직접 보낸다. envelope `protocol_version` 1.0 유지 |
| v1.94 | 2026-10-04 | Additive (D-450): recipe/2 작업자 간지 지시와 Cell Job의 optional read-only `operator_checkpoints`, 공유 `CellOperatorCheckpoint` 스키마. durable HOLD·재시작/재개 우회 차단; owner 접근·삽입 확인 API는 미제공. envelope 1.0 유지 |
| v1.94 | 2026-10-04 | Additive (D-452): 별도 authenticated peers 역할 목록, 선택적 bounded scanner services, 실제 모델 SSH profile. 발견·승인·ready 분리, envelope 1.0 및 기존 등록/인증 유지 |
| v1.93 | 2026-10-04 | Additive (D-450): Fleet Console `/console/cell` 작업 화면의 revision 문서 저장·정본 compile·명시 service proposal API 및 `CellApp*Request` 스키마 추가. 기존 named operator admission/복구·원장을 재사용. envelope version 1.0 유지 |
| v1.92 | 2026-10-04 | Additive: Viewer GET /api/v1/power/health; battery age/freshness, timestamped charging evidence, software sleep blockers and wake constraints. Read-only; envelope protocol_version 1.0 unchanged. |
| v1.91 | 2026-10-04 | Additive (D-438 1단계, docs/d438-fleet-stuck-resolver): CORE 역할 `stuck_resolver`(순위 viewer)와 capability `STUCK_DECIDE`; `POST /api/v1/line-follow/stuck/decision` 은 `STUCK_DECIDE` 를 요구(operator·administrator 도 가짐), `stuck_resolver` 의 `MANUAL` 은 403. Site Fleet `POST /api/fleet/robots/{robot_id}/line-stuck/claim`(operator), 로봇 행 `line_stuck.resolver`, `robots.yaml` `resolver_token`, `fleet console --stuck-resolver`. `fleet_line_stuck_answers` 에 null 가능 열 `tier`·`rule`·`escalated`(옛 DB 는 열 때 추가), 판단기가 사람에게 올릴 때마다 `ESCALATE` 행. `GET /api/fleet/state` 와 판단기는 1 s 안에서 한 번의 gather 를 같이 쓴다. 로봇 이벤트·FleetAgent 프로토콜 변경 없음 |
| v1.90 | 2026-10-03 | Additive (D-432): LAN 장비 목록 접속, auth/connection·auth/development-session, 선택적 CORE TLS·발견 전송과 SSH 공개 키 등록. 기존 코드 규약·envelope 1.0 유지. |
| v1.89 | 2026-10-03 | Additive (D-418, feat/d418-ssh-access): 로봇 SSH 접속 §5.8 — Admin 전용 `GET /host/ssh/host-keys`, `GET\|POST /host/ssh/keys`, `DELETE /host/ssh/keys/{label}`, `GET\|POST\|DELETE /host/ssh/password` 신설. 오류 코드 `SSH_INVALID`(422)·`SSH_LABEL_EXISTS`·`SSH_KEY_EXISTS`·`SSH_KEYS_FULL`(409)·`SSH_KEY_NOT_FOUND`(404)·`SSH_ACCESS_UNAVAILABLE`(503). 스키마 `Ssh*`(`schemas.py`). 기존 경로·필드 변화 없음. 브랜치에서 v1.84 로 적었으나 main 이 v1.84(D-422)–v1.88(D-423)을 먼저 써서 v1.89 로 재번호 |
| v1.91 | 2026-10-04 | Additive: Pilot 녹화 preview_mode raw/annotated와 live typed start capability, 실제 옵션 readback. 같은 capture의 원본/주석 JPEG pair를 bounded cache·공유 admission으로 제공하고 브라우저 파생 영상은 먼저 저장된 원본과 provenance를 보존한다. source image age로 저조도 보조 만료를 보완한다. envelope protocol_version 1.0 유지. |
| v1.90 | 2026-10-04 | Additive: `GET/PUT /line-follow/perception` 신설. Viewer 설정·signed model integrity 조회, Administrator `paint_source`만 선택. `LanePerceptionRequest/Status` 스키마, Host Agent 정지 재검사·기하 보존·원자 적용/실패 복구와 CORE IDLE motion reservation. live source 미확인은 null로 구분한다. 운전 모드·물체 검출·envelope protocol_version 1.0은 유지. |
| v1.88 | 2026-10-03 | Additive (D-423, feat/d423-object-range-detection): `GET /api/v1/vision/models`(viewer, 읽기 전용) — 로봇 학습 모델 상태를 작업별로(`lane_seg` shadow, `object_det` active). §6.1.1 에 ROS `vision/detections`(DetectionEvidence 필드 + 추가 `ranges`)를 적음 — CORE 는 구독하지 않음. 카메라 관측 영역의 `s`(`L`/`G`)·`ground_source` 는 control 내부 증거(`camera/observation`)라 이 계약 밖. 쓰기 API·이벤트·FleetAgent 변경 없음. v1.82 는 main 의 D-403/D-413 행 |
| v1.87 | 2026-10-03 | Additive (D-411 B+C, feat/d411bc-pilot-controls-gripper; A 는 v1.83 에서 먼저 들어감): B: capabilities `controls`(`rosy.controls/1`, §9.1), OMX SIM `GET /sim/omx/target` `controls`; Pilot 이 `controls` 로 주행·팔 조작부를 조립(필드 없음 = 구 서버 대체, 빈 `items` = 조작부 없음, 팔 조이스틱은 순차 제한 목표·떼면 새 목표만 멈춤). C: OMX SIM `POST /sim/omx/gripper`(`OmxSimGripperGoal`, 절대 위치·0.2–2.0 s), `/state` `gripper` readback(`open`·`closed`·`holding`·`moving`·`unknown`), `/target` `controls` 의 `gripper` 항목(그리퍼는 `joint_jog` 에서 빠짐, 선택 `max_velocity`(`GripperControl.max_velocity`), 409 `gripper_velocity_limit`), SIM 허용 범위 = 셀 프로필 ∩ URDF·알리는 범위는 0.02 rad 안쪽·목표 길이 상한 2.0 s, 쥔 채 팔 조그는 멈춘 위치 + preload, 시연 기록 `action.gripper` 열과 LeRobot 특성(선택, 이전 에피소드 유효). 기존 필드 변화 없음 |
| v1.86 | 2026-10-03 | Additive (D-419, feat/d419-saf003-fleet-loss): SAF-003 이 처음으로 동작한다. 이벤트 `safety.fleet_lost`(warning)·`safety.fleet_restored`(info), `GET /safety/state` 선택 필드 `fleet_link`, 설정 `safety.fleet_loss_timeout_s`(기본 5.0, 4–60 s)·`fleet.heartbeat_reply_timeout_s`(기본 2.0, 0.5–10 s), 판정 시간 ≥ 1 + 답 시한 + 1 (어기면 기동 실패). §7.6 판정 규칙. `PUT /safety/limits` 의 받는 값은 그대로(`RETURN_HOME` 포함), `RETURN_HOME` 이면 응답 선택 필드 `warning`. 기동 때 저장된 모르는 정책은 `STOP` 으로 읽는다. envelope `protocol_version` 1.0 유지 |
| v1.85 | 2026-10-03 | Additive (D-413): opt-in independent Cell goal-evidence ingress, shared strict submission schema, isolated producer credentials and terminal callback reconciliation with atomic latest-terminal fencing. No physical dispatch or ROS-SIM promotion. |
| v1.84 | 2026-10-03 | Additive (D-422, feat/body-referenced-obstacle-stop): `GET /api/v1/line-follow` 상태에 선택 필드 `body_gap_m`·`stop_gap_m`·`clearance_source`(`lidar`·`memory`·`ultrasonic`), `nav.line_obstacle_hold` 데이터에 같은 세 필드(몸 기준 정지일 때만). 몸 기준 정지에서 `clearance_m` 은 LiDAR 원점 거리가 아니라 몸 간격이다(path + 로봇 패키지 몸 기하에서만; sector 와 몸 기하 없는 path 는 그대로). 설정 `line_follow.body_front_x_m`·`body_ultrasonic_x_m`(URDF, 로봇 패키지), `obstacle_body_margin_m`(0.02)·`obstacle_latency_s`(0.15)·`obstacle_decel_mps2`(0.5)·`obstacle_resume_hysteresis_m`(0.03)·`obstacle_ultrasonic_half_angle_deg`(15)·`obstacle_ultrasonic_stale_s`(0.3). `obstacle_stop_m`·`obstacle_resume_m` 은 기본 yaml 에서 빠지고(비면 0.20 / 0.28 또는 유도) LiDAR 원점 기준 덮어쓰기로 남는다 — 옛 overlay 는 그대로 읽힌다. 덮어쓰기는 앞으로 가는 판정에만 쓰고 제자리 회전(회전 반경 원 밖 `obstacle_body_margin_m`)에는 쓰지 않는다. 움직이는 판정의 `stop_gap_m` 은 초음파와 상관없이 LiDAR `range_min` 사각 하한 이상이고, `range_min` 아래로 사라진 반환은 기억해 `body_gap_m` 에 계속 든다(`clearance_source: memory`; 기억은 바퀴로 나간 명령으로 적분하고 차선 추종 출력이 아니면 지운다). 기존 필드 이름·형식 변화 없음 |
| v1.83 | 2026-10-03 | Additive (D-411 A, feat/d411-pilot-recording-controls): §5.10 Pilot 로봇 녹화 (`GET/POST /api/v1/recordings`, `GET /recordings/active`, `POST /recordings/active/stop`, `GET /recordings/{id}/archive`), ERR-102 `RECORDING_BUSY`·`RECORDING_NOT_ACTIVE`·`ROBOT_MOVING`·`RECORDING_NOT_FOUND`·`RECORDING_QUOTA_FULL`·`RECORDING_DISK_FULL`·`RECORDER_UNAVAILABLE`, §8 `recording.started`·`recording.stopped`, ROS 증거 토픽 `teleop/intent`, 녹화기 상태 `boot_id`·`seq`, 설정 `recording.pilot_root`. 기존 필드 변화 없음 |
| v1.82 | 2026-10-03 | Clarify (D-403 / D-413): Fleet uses existing UDS v2 for phased CELL_TRANSFER submission, readback and cancellation; missing phase summaries fail closed. OMX already accepts the additive grant in v2. Simulation dispatch gates and independent goal requirements remain unchanged. |
| v1.81 | 2026-10-02 | Additive (D-421, feat/d421-fleet-cancel-all): Site Fleet 새 경로 `POST /api/fleet/cancel-all`(operator, §10.8) — 래치 없는 전체 주행 취소(대기 작업 `CANCELED`/`FLEET_CANCEL_ALL`, 대형 해제, 로봇마다 `swarm/cancel`·`navigation/cancel`·`line-follow/mode OFF`, 로봇별 `cancelled`/`failed`/`unreachable`, `evidence: CORE_REPLY_ONLY`). 발행 겹침 작업은 `UNKNOWN`/`FLEET_CANCEL_ALL_DURING_DISPATCH`. 창마다 취소 기록(`cancel_all_id`)을 남기고, 표시된 진행 중 작업의 CORE `nav.canceled` 는 `HOLD`/`FLEET_CANCEL_ALL` 로 로봇 점유를 푼다(사건이 없으면 그대로). §10.2 에 `/api/fleet/estop` 이 래치형 전체 비상 정지임을 명시(의미 불변). FLEET SRS CTR-002 개정. 로봇 계약(`/api/v1/*`)·이벤트·FleetAgent 프로토콜 변경 없음 |
| v1.80 | 2026-10-02 | Corrective + Additive (D-407 관제 재실행, fix/d407-console-link-and-event-fields): **Corrective** `nav.line_stuck_answered` 의 `token_id` → `principal_ref`(비밀 아닌 이름: 설정 id, 없으면 프로세스 키 HMAC `anon-…`) — Fleet 사건 저장소가 `token` 이 든 키를 자격 증명으로 보고 `EVENT_NOT_AUDITABLE` 로 거부해 이 사건이 Fleet 감사에 남지 않았다. **Additive** `nav.line_stuck_opened` `rear_state`(`clear`·`blocked`·`unknown` — `rear_clearance_m` null 이 "띠가 비었다"와 "모른다"를 함께 뜻하던 것을 가름), 거부된 `BACK_AND_RETRY` 답에 `rear_blind_m`·`trail_m`·`trail_yaw_deg`·`trail_age_s`. FleetAgent 는 hub 의 모든 답을 한 수신 루프로 읽는다(사건 답이 쌓여 연결이 끊기던 결함; envelope 형식 변화 없음, `protocol_version` 1.0). 설정 `line_follow.recovery_console_grace_s`(3 s) |
| v1.79 | 2026-10-02 | Additive (D-407, fix/d407-trail-age-and-recording-marker): `nav.line_stuck_local_attempt`·`nav.line_stuck_local_result` 에 `trail_age_s`(지나온 길의 마지막 전진 명령 뒤 경과, 단조 초). 사각 띠 후진은 그 값이 `line_follow.recovery_trail_max_age_s`(30 s) 이하일 때만 — 넘으면 `rear_blind`. 기존 필드 변화 없음 |
| v1.78 | 2026-10-02 | Additive (D-403 / D-413 Task 4): define separate `FleetCellTransferGrant` and bounded `CELL_TRANSFER` body for one recipe/cell-bound pick/place pair. Existing `PICK_PLACE` schema, payload and digest remain unchanged; Fleet dispatch stays gated on simulation evidence. |
| v1.79 | 2026-10-02 | Additive (D-403 / D-413 Task 4): scope a `service` principal to Cell Job proposals/resolution, require a distinct named operator for admission, expose ordered Cell Job status, and persist ordered `CELL_TRANSFER` steps. Existing `PICK_PLACE` records remain unchanged; device dispatch and independent goal evidence remain gated. |
| v1.77 | 2026-10-02 | Additive (D-407 Fleet 쪽, feat/d407-console-stuck-decisions): Site Fleet 새 경로 `GET /api/fleet/line-stuck`(viewer+)·`POST /api/fleet/robots/{robot_id}/line-stuck/decision`(operator), `GET /api/fleet/state` 로봇 행에 선택 필드 `line_stuck`(§10.8). Fleet 은 CORE 거부를 그대로 409 로 옮긴다. 로봇 계약(`/api/v1/*`)·이벤트·FleetAgent 프로토콜 변경 없음 |
| v1.76 | 2026-10-02 | Additive (D-407 Gazebo 후속, fix/d407-sim-findings): `nav.line_stuck_opened` 에 `restuck_of`·`attempts` — `recovered` 로 닫힌 뒤 `line_follow.recovery_restuck_s`(20 s) 안이거나 순 전진 `recovery_restuck_m`(0.30 m) 전에 다시 막히면 같은 막힘으로 시도 수를 이어 센다(다 쓰면 곧바로 관제 답만 기다림). `nav.line_stuck_local_result` 에 판정한 scan 의 `rear_clearance_m`·`rear_blind_m`·`trail_m`·`trail_yaw_deg`. `nav.line_stuck_closed` 사유 `estop`. 뒤 띠 폭은 URDF 몸 반폭(`body_half_width_m`) + `recovery_rear_lateral_margin_m`(0.02). 기존 필드 변화 없음 |
| v1.75 | 2026-10-02 | Additive (D-395 개정 4 5항 후속, S1 R1, feat/d395-localized-objects): 상태 스냅샷·하트비트 `localization` 에 선택 필드 `unmapped_objects[≤16]` `{x, y}`(base_link)·`objects_stamp`(로봇 시각 s). `LOCALIZED` 로봇이 전체 스캔의 지도 밖 물체를 상태(2 Hz)마다 싣고, 밖에서는 빈 목록이다. CORE 는 그대로 넘기고 `pose_frame: odom`·`state_stale` 에서 비운다. Fleet 감시가 닻 로봇의 관찰로 다른 `LOCALIZED` 로봇의 거울 잠금을 잡는다. 기존 필드 변화 없음 |
| v1.74 | 2026-10-02 | Additive (D-407, feat/d407-stuck-recovery-core): `POST /api/v1/line-follow/stuck/decision`, line-follow 상태 `stuck`(`LineStuckStatus`: `stuck_id, cause, phase, held_s, attempts, max_attempts, local_enabled, ask_remaining_s, last_answer, decisions`, 막힘 없으면 null)·`state` 값 `RECOVERING`·사유 `stuck_back_off`·`stuck_<phase>`, 에러 `STUCK_ID_MISMATCH`·`STUCK_DECISION_REFUSED`, 이벤트 `nav.line_stuck_opened/asked/answered/local_attempt/local_result/closed`, 설정 `line_follow.recovery_*`(로컬 복구 기본 꺼짐; `recovery_trail_s`·`recovery_trail_yaw_deg` 는 사각 띠 후진 조건)·`body_lidar_x_m`·`body_rear_x_m`·`body_rotation_radius_m`(URDF, 로봇 패키지). Fleet 콘솔·FleetAgent 답 중계는 다음 단계. 기존 필드 변화 없음 |
| v1.73 | 2026-10-02 | Additive (D-395 P2-7, feat/d395-p2-7-missions): 새 경로 `POST /localization/mission`(`LOCALIZE_ASSIST`)·`GET /localization/mission`(Viewer) — `LOCALIZED` 가 아닌 로봇에서 CORE 가 확인 기동·귀환 미션(`rotate_in_place`, `nudge_forward`, `lane_to_stopline`; `to_square` 는 409 `unsupported`)을 자기 장애물 정지·e-stop·거리·시간 한도 아래 아주 느리게 실행한다; 거부 409 코드 `localized`·`busy`·`estop`·`path_not_clear`·`calibration_lease`·`unsupported`; 이벤트 `localization.mission`. **행동 변화:** `lane_to_stopline` 미션은 이 미션에 한해 line-follow 를 `LOCALIZED` 관문 없이 켠다(공개 `PUT /line-follow/mode` 의 관문은 그대로); 미션 중에는 Nav2 `nav_cmd_vel` 을 버린다; 미션이 도는 동안 모드는 NAVIGATION 이고 MANUAL·IDLE 로 바꾸면 미션이 `cancelled` 로 끝난다 |
| v1.72 | 2026-10-01 | Additive (D-395 2단계 lane B, feat/d395-p2-core-api): 스냅샷 `localization` 을 CORE 가 실제로 채움(`localization/state`, `pose_frame` 은 CORE 가 odom 을 대신 쓰는 동안 `odom`, 3 s 무응답이면 `UNKNOWN`/`state_stale`); 새 경로 `GET /localization/candidates`, `POST /localization/decision`, `POST /localization/suspect`(§5.3, §7.9); 토큰 capability `NAVIGATE`·`LOCALIZE_ASSIST`(§2 AUTH-102, 역할에서 정해짐, Fleet operator 토큰이 가짐); 새 에러 `NOT_LOCALIZED`·`STALE_REQUEST`·`NO_CANDIDATES`, D-395 경로의 lease 거부는 423; 이벤트 `localization.state`·`localization.candidates`·`localization.result` 추가, `localization.initialpose` 에 `source` 추가(§8). **행동 변화:** D-395 로봇(`localization` 이 null 아님)에서 `navigation/goal`·`home`·`line-follow/mode`(OFF 제외)는 `LOCALIZED` 가 아니면 409, 레거시 `localization/initialpose` 는 `/initialpose` 대신 `source: human` 결정으로 가며 응답 모양은 같다; `LOCALIZED` 진입이나 결정 수락 시 진행 중 Nav2 목표를 취소한다; `LOCALIZED` 를 벗어나면(3 s 무응답 포함) swarm follow·도킹·line-follow·Nav2 를 멈추고 NAVIGATION 을 IDLE 로 내린다(MANUAL 은 그대로); `docking/dock`·`swarm/follow` 도 `LOCALIZED` 가 아니면 409 `NOT_LOCALIZED`; `LOCALIZED` 라도 `pose_frame: odom` 이면 409; 저배터리 자동 도킹은 `LOCALIZED` 까지 대기, SAF-005 `RETURN_HOME` 은 `LOCALIZED` 가 아니면 e-stop. D-395 이전 로봇은 전부 예전 그대로 |
| v1.71 | 2026-10-01 | Additive: state `safety_policy`(상태 스냅샷·Fleet 하트비트에 실림), events `safety.shadow_verdict`·`safety.policy_off` (D-400). 기존 필드 변화 없음 |
| v1.70 | 2026-10-01 | Additive (D-390 부록): OMX SIM camera 상태/JPEG, 시연 기록 시작·종료·manifest, typed 기록 상태와 task outcome. 로컬 LeRobot v3 변환; 실물 권한 변화 없음 |
| v1.69 | 2026-10-01 | Additive (D-395 1단계, feat/d395-phase1): 상태 스냅샷(`/robot/state`·`/ws/state`)·하트비트 `localization` `{state, pose_frame, confidence, reason, needs_human, request_id}`(D-395 이전 로봇은 null); §7.9 `CandidateReport`·`LocalizationDecision`(`cues`, 수신 기준 `ttl_s`) 모델(스키마만, 전송 경로 없음). 기존 필드 변화 없음 |
| v1.68 | 2026-10-01 | Additive (D-321 부록, feat/calibration-session-mode): 보정 세션 lease `GET/POST /api/v1/calibration/session`, `POST …/{id}/heartbeat`, `DELETE …/{id}`; 상태 스냅샷(`/robot/state`·`/ws/state`) `activity` (보정 중이면 `{kind: CALIBRATING, session_id, calibration_kind, label, owner, started_at, remaining_s}`, 아니면 null); 에러 `CALIBRATION_ACTIVE`(다른 토큰의 teleop·`/mode`(IDLE 제외)·line-follow 모드(OFF 제외)·hold·navigation goal/home·docking dock/undock·swarm follow 409); 이벤트 `calibration.session_started/ended/expired`. E-Stop 은 막지 않는다. 기존 필드 변화 없음 |
| v1.67 | 2026-10-01 | Additive (D-390): 격리된 OMX-AI Gazebo Pilot 전용 `/api/v1/sim/omx/*` 목표·상태·조종권 계약. 실물과 Fleet 경계는 불변. 카메라·녹화는 미구현으로 명시. |
| v1.64 | 2026-09-30 | Additive (D-344 §11·§13): 이벤트 `nav.line_obstacle_hold`(앞 물체 정지가 `line_follow.obstacle_escalate_s` 넘게 이어지면 한 번), line-follow 정지 사유 `limit_level_too_low`(수동 한도가 L1 미만이면 차선 자동 HOLD)·`angular_limit_zero`(수동 각속도 한도를 읽을 수 없음), 설정 `obstacle_mode`(`sector` 기본·`path`)·`obstacle_release_s`·`obstacle_escalate_s`·`lane_auto_min_manual_angular`·`max_angular_follows_manual`. 와이어 형식 변화 없음 |
| v1.66 | 2026-10-01 | Clarify (D-382 부합): a local Action UDS response — success or error — carries the version of the request it answers; only frames rejected before version validation answer version 1. Fixes v2 stale-fence 403 and `GetAction` 404 being read as version-unsupported by the Fleet client. |
| v1.65 | 2026-10-01 | Additive (OMX Task 6): version the same-host phased `PICK_PLACE` receipt as UDS v2 with bounded durable phase snapshots; project current phase state into Fleet progress and the existing read-only ER 2 status result. V1 remains compatible for non-phased operations; no new command, public route, or Mission-completion shortcut. |
| v1.63 | 2026-09-30 | Additive + Corrective (D-344): `PUT /line-follow/mode` 가 선택 필드 `hold_s` 를 받고 `POST /line-follow/hold`·이벤트 `nav.line_driver_released`·에러 `LINE_FOLLOW_NOT_HELD` 를 둔다 — 운전자가 누르고 있는 동안만 가는 보조 자율. **Corrective**: line-follow 요구 능력을 `navigation.goal_navigation` 에서 `mobility.move` 로 — Nav2 가 없는 실물 `motor` 런타임에서 차선 추종이 늘 거절되던 것을 고친다(증거 검사는 그대로). `hold_s` 없는 기존 호출은 동작이 같다. envelope `protocol_version` 1.0 유지 |
| v1.62 | 2026-09-30 | Additive (D-358): Vision frame replies expose width, height, and source rotation for the exact no-store JPEG. A trusted Fleet post-action reader uses the existing source-scoped lease, capture timestamp/sequence/freshness headers, and immutable workcell-to-camera mapping; the app consumes provider turns only when a shared-database worker is explicitly injected. Default CLI remains provider-disabled. |
| v1.56 | 2026-09-29 | Additive (D-337): traffic policy status gains `signal_source_kind`/`signal_head_age_s`/`signal_head_frozen`; the optional file-only `traffic_policy.signal_observer` binding fuses the observer service's measured light with camera evidence (mismatch `signal_source_conflict` HOLD, dark/indeterminate `signal_dark`, silence falls back camera-only) and emits `nav.traffic_policy_signal_source_stale` once per lapse |
| v1.57 | 2026-09-29 | Additive (D-333): add owner-scoped Mission progress axes, a 50-event recent-history window with truncation signal, and bounded snapshot-first event cursor pages. Fleet event IDs are journal order; dispatch latch is distinct from physical stop (UNKNOWN); no percentage or provider status tool is introduced. |
| v1.61 | 2026-09-30 | Additive (D-358): expose Fleet ER 2 successor-candidate source Mission/action/attempt/generation/event/observation correlation and `supersedes_mission_id`; stop/source-event drift makes the candidate non-resolvable, and resolution creates a distinct linked Mission draft. This does not enable a provider worker, trusted Vision reader, policy dispatch, or ROS. |
| v1.60 | 2026-09-30 | Additive (D-360/D-357/D-358): Vision field-corner proposals for operator review; bounded ER 2 feedback tools, trusted turn scope, stateless `store=false` replay, transcript-free SQLite outbox with durable-cursor event scheduling, hard capacity bound and explicit ambiguous `UNKNOWN` behavior. No public tool route, ER 2 provider worker/model calls, policy dispatch, or ROS enablement. |
| v1.59 | 2026-09-30 | Additive (D-348): opt-in registered goal-evidence producer route, environment-only source tokens, SQLite evidence-ID idempotency, evaluator/freshness scope, terminal-action verification and grace-timeout HOLD. No model/action dispatch or ROS enablement. |
| v1.58 | 2026-09-29 | Additive (D-347): `GET /api/v1/system/capabilities` gains the per-flag `lifecycle` block — one vocabulary (`ready`/`unavailable`+reasons, `activating` reserved with no producer yet) derived from the existing `withheld` judgment; `withheld.flags` always equals the `unavailable` set. Presentation states on inventory descriptors are unchanged; the mapping lives in D-347. |
| v1.55 | 2026-09-29 | Additive (D-333): require an injected trusted producer verifier and a new post-action observation for Mission goal confirmation. Evidence is correlated to the Action/attempt and carries frame digest, evaluator revision, and a separate `OPEN` gripper readback; absent verifier, stale/mismatched evidence leaves claims held. |
| v1.54 | 2026-09-29 | Additive (D-18): include the operator-declared `junction_rule` in traffic policy status so an unsignalized stop-and-go junction is distinct from signal-detection failure. |
| v1.53 | 2026-09-29 | Additive (D-333/D-336): connect the explicit opt-in Fleet Mission dispatcher to the same-host OMX UDS Action API. Persist stable grants before one SubmitAction; reconcile restart/lost ACK through GetAction without replay; bind receipts to digest and both fences. Dispatcher stays disabled by default; Action success remains separate from goal evidence and physical acceptance. |
| v1.52 | 2026-09-29 | Additive (D-336): define the local software-stop OPEN projection and explicit newer-generation rearm; a persisted stop latch, stale Fleet fence, or process restart blocks the final driver submission boundary. This remains separate from driver standstill and physical E-stop proof. |
| v1.51 | 2026-09-29 | Clarify (D-336): define one-frame newline JSON UDS encoding, SO_PEERCRED UID derivation, 64 KiB bound, and FleetActionGrant canonical digest; source adds a disabled-by-default local Action runner with durable attempt IDs and no unknown replay. No service entrypoint or physical capability is enabled. |
| v1.50 | 2026-09-29 | Additive (D-333/D-334): separate Site Fleet candidate storage, observation/capability resolution, Mission draft readback, and named-operator generation-checked admission routes. Proposal creation does not invoke ER 2; admission only acquires Fleet claims and remains disconnected from Device Action/ROS. |
| v1.46 | 2026-09-29 | Additive (D-330): Fleet dispatch-control readback and explicit generation-checked operator rearm; startup/stop hold, unresolved-action rearm refusal, and device-side generation fencing remains unimplemented. |
| v1.47 | 2026-09-29 | Clarify (D-330): dedicated operator E-stop fanout proceeds on audit/latch/queue-storage failure with server logging; ordinary mutations remain audit fail-closed; request replies do not prove physical stop. |
| v1.49 | 2026-09-29 | Additive (D-333/D-336): typed Site Fleet-to-OMX local Device Action and software-stop contracts, same-host UDS boundary, attempt/generation fences, and explicit separation from Mission goal evidence and physical stop proof. No REST path, PRT envelope change, listener, runner, or device capability is implied. |
| v1.48 | 2026-09-29 | Additive (D-268 승격 사다리 1단계): Site Fleet 정책 적격 증거 계약 — source-token 제출·readback, `PolicyEvidencePayload`, `evidence_id` 멱등(다른 내용 409 `EVIDENCE_REPLAY`), transit 0~300 ms, v1 빈 관측 등록부로 잘 구성된 제출도 전부 거절(fail-closed), policy 작업 제출은 `evidence_id` 참조 필수(400 `INVALID_EVIDENCE_REFERENCE`)이며 admission 사유와 함께 HOLD. `POLICY_DISPATCH_ENABLED` False 유지 — 자동 실행 불변 |
| v1.44 | 2026-09-28 | Additive (D-316): correlate Pinky Site Fleet navigation attempts through optional CORE REST metadata and CORE navigation events; project matching results into durable task status. PRT-004/Envelope ACK and physical stop readback remain separate. |
| v1.45 | 2026-09-28 | Additive (D-318): bounded rectification settings in signed Site Fleet Vision preview leases; Vision applies OpenCV lens and plane correction only to the returned latest-frame preview copy. Raw sighting input and robot command paths are unchanged. |
| v1.43 | 2026-09-28 | Additive (D-313): CORE binds IR fallback to fresh IR-line evidence and its configured calibration digest; Fleet operator selection forwards through CORE. Refuse Nav2 goal/home while line-follow owns motion. Robot DDS/WSS envelope remains 1.0. |
| v1.41 | 2026-09-27 | Corrective(P0, D-297): document the observed navigation task/CORE event correlation gap and replace stale D-177 activation references. No path, schema, runtime, or robot PRT envelope change. |
| v1.40 | 2026-09-26 | Additive (D-293): typed Site Fleet intent/OpenAPI grammar, server-derived priority and identity, durable task/audit semantics, and purpose-specific message boundaries. No robot PRT envelope change. |
| v1.39 | 2026-09-26 | Additive: Operator camera preview screenshot/video evidence upload, list, download and bounded `VisionEvidenceRecord`/`VisionEvidenceList`. Browser PC storage stays local. Robot DDS/WSS envelope version remains 1.0. |
| v1.38 | 2026-09-26 | Robot FleetAgent location: paired robots may resolve a pinned site over mDNS with CA/TLS verification; no envelope change. |
| v1.37 | 2026-09-26 | Additive: site-only mDNS scan/readback and `DiscoveryScanPayload`; no robot envelope change. |
| v1.36 | 2026-09-26 | Additive(D-283): `UiPanelDescriptor.action_group` optional field exposes console operation groups. Only role-, capability-, and inventory-visible panels are included; unsupported action groups are absent. |
| v1.35 | 2026-09-26 | Additive(D-276): authenticated Fleet session identity endpoint for the console role cue. Robot DDS/WSS envelope version remains 1.0. |
| v1.34 | 2026-09-26 | Clarify(D-276 Accepted): individual site-user token digests, viewer/operator/policy-admin API roles, operator task actor identity, and pre-dispatch append-only mutation audit. Robot DDS/WSS envelope version remains 1.0. |
| v1.32 | 2026-09-26 | Additive(D-271): Fleet task `QUEUED` lifecycle, status/receipt semantics, shared `FleetTaskStatus`, and queued-only cancel contract. Robot DDS/WSS envelope version remains 1.0. |
| v1.33 | 2026-09-26 | Additive(D-271): Fleet console queued-task feedback/readback/cancel and cancel/stop/E-Stop queue coordination. |
| v1.31 | 2026-09-26 | Additive(D-269 Proposed): operator navigation `Idempotency-Key`, durable task status/history, authenticated `/api/fleet/tasks/{task_id}` readback. Policy work remains `HOLD`; D-177 command ACK and per-user identity are not implemented. |
| v1.30 | 2026-09-26 | Additive(D-269 Proposed): paired CORE Agent 이벤트를 credential-free bounded SQLite audit history에 저장, 중복 `event_id` 멱등 처리, 인증된 cursor 기반 `/api/fleet/events` 조회. 이는 자동 작업 승인이나 D-177 command ACK 구현을 뜻하지 않음 |
| v1.29 | 2026-09-26 | Clarify(D-257/D-269 Proposed): Fleet CLI source config와 SQLite latest/history storage, HTTPS API path 및 site Docker TLS boundaries. Synthetic Docker WSS→vision→Fleet readback은 LOCAL evidence만 제공; D-268/자동 실행 상태 불변 |
| v1.28 | 2026-09-26 | Additive(D-257 Proposed): Site Fleet sighting `quality`는 미측정 시 `null` 허용. 표시 전용이며 D-268 정책 증거로 사용하지 않음. envelope `protocol_version` 1.0 유지 |
| v1.26 | 2026-09-26 | Additive(D-257 Proposed): Site Fleet 전용 source-token `POST /api/fleet/sightings`, operator `GET` readback 및 `SiteSightingPayload` shared schema. 파생 pose만 전달하며 source identity는 서버가 token에서 결정. 1 s 표시 lease, D-268 자동 정책 경로는 계속 별도/HOLD |
| v1.25 | 2026-09-26 | Additive(D-260 5): `GET /host/status-summary`(Viewer) 신설 — 로봇 상태 하나·이유·장치 요약·배터리·온도·할 일. 기존 필드 불변 — envelope `protocol_version` 1.0 유지 |
| v1.24 | 2026-09-26 | Additive(D-263/D-265): 역할별 기반 화면 `GET /api/v1/ui/surfaces/{surface}` 및 `UiSurfaceManifest` REST 응답 스키마. 메뉴 노출은 패널 수와 독립이며 직접 요청은 역할에 따라 401/403/404. Fleet envelope `protocol_version` 1.0 유지 |
| v1.27 | 2026-09-26 | Additive: `GET /api/v1/docking/types` 는 Viewer가 설정된 도크 검출기 유형을 조회한다. `/types`의 POST 권한은 계속 Admin이며 도크 유형 구성 응답만 추가한다. |
| v1.23 | 2026-09-26 | Additive(D-247 6): `POST /host/hardware/test`·`POST /host/hardware/confirm`(Admin) 신설, `HW_TEST_COOLDOWN`(429)·`HW_TEST_UNAVAILABLE`(503)·`HW_CONFIRM_UNAVAILABLE`(503)·`HW_CONFIRM_NO_TEST`(409), `GET /host/hardware`의 `test` 필드와 `source:"human"` 행 덮기 추가. 기존 필드 불변 — envelope `protocol_version` 1.0 유지 |
| v1.22 | 2026-09-25 | Additive(D-247): `GET /host/hardware`(Viewer)·`POST /host/hardware/refresh`(Admin) 신설, 에러 코드 `HW_PROBE_UNAVAILABLE`(503) 신설, `GET /host/commissioning` 에 `motion_reason` 필드 추가. 기존 필드 불변 — envelope `protocol_version` 1.0 유지 |
| v1.21 | 2026-09-25 | Additive: 이벤트 `swarm.succession`(warning) `{leader, dead, role, by}` 문서화 — 공유 명단 대형에서 죽은 리더를 교체할 때 이미 발행되고 있었으나 §8 에 없었다. 스키마 변경 없음 — envelope `protocol_version` 1.0 유지 |
| v1.21 | 2026-09-24 | Corrective + Additive, 실기(rosy-pinky-e4us, release 2026.09.24-010, CORE-only 이미지 + 무동작 `rosy-io`) 근거. **Corrective**: CAP-001 `withheld` 판정이 설정 문자열 대신 살아 있는 증거를 쓴다 — 무동작 모드(`motor/ready: false`)에서 `teleop`·이동 플래그를 광고하던 것(D-32 위반)을 `drive_disabled:no_motion` 으로 내린다. 새 이유 `hardware_silent`·`drive_lease_expired`·`drive_absent`·`navigation_absent`. inventory descriptor 의 `reason` 은 런타임 이유가 `device_state` 보다 먼저다(≠v1.18). **Additive**: `withheld.reasons`(플래그별), `capabilities.runtime`(`hardware`·`evidence`·`drive`·`navigation`·`maps`), descriptor `reasons`. envelope `protocol_version` 1.0 유지 |
| v1.20 | 2026-09-24 | Additive + Corrective. **Additive**: 에러 코드 `LINE_FOLLOW_ACTIVE`(409)·`NO_ODOMETRY`(409) 신설. `POST /docking/dock` 는 라인 추종 중 409 `LINE_FOLLOW_ACTIVE`, DOCKING 모드를 쥘 수 없으면 409 `MODE_CONFLICT`; `POST /docking/undock` 는 여기에 오도메트리 부재 시 409 `NO_ODOMETRY`. `PUT /line-follow/mode` 는 도킹/언도킹 중 409 `DOCKING_ACTIVE`. `POST /docking/types` 에 주차형 도크 선택 필드(`tag_id`·`tag_size_m`·`staging`·`approach`·`settle`·`tag_offset_m`·`acquire_creep_m`·`backoff_m`·`undock_turn_rad`) — 생략하면 기존 동작. **Corrective**(코드를 고친 것): 내비게이션의 `DOCKING_ACTIVE` 거부가 HTTP 매핑이 없어 400 으로 나가던 것을 문서대로 409 로(409≠400). 스키마 변경 없음 — envelope `protocol_version` 1.0 유지 |
| v1.19 | 2026-09-24 | Additive(D-193): `auth/pair`·`auth/whoami`·`auth/logout`·`auth/enrollment-codes`, `PATCH system/tokens/{id}`. 토큰 목록에 `expires_at`·`source`·`current`·`last_used_at`, 생성 응답에 `expires_at`·`source`. 이벤트 `auth.paired`·`auth.code_burned`·`auth.enrollment_code_issued`·`auth.credentials_refused`. `whoami` 가 신원의 정본이고 `system/info.caller_role`(v1.18)은 호환용으로 남는다. WebSocket 첫 메시지 인증(`?token=` 은 한 릴리스 동안 유지). S3: `auth/pair` 의 코드를 폐기시킨 401 에 `error.detail.burned`, 대시보드는 첫 메시지 인증만 쓴다. **동작 변경**: 만료된 토큰은 401, 마지막 관리자 규칙은 만료 없는 administrator 만 센다, 장치 기본값에 토큰이 없다(개발 토큰은 `ROSY_DEV_AUTH=1` 일 때만, 장치 모드는 거부) |
| v1.18 | 2026-09-24 | US-010, 실기(rosy-pinky-e4us, CORE-only) 근거. **Corrective**: `battery.percent` 는 값이 없을 때 `null`(≠`0.0`) — 0.0 은 지어낸 치명 경보였다(D-82 Law 0). 형은 `number \| null` 이고 `voltage` 와 같은 규약이다. CORE-only 에서 값이 한 번도 오지 않은 evidence 채널은 `unavailable`(≠`disconnected`). `system/info` 의 `robot_name` 은 이름이 기본값뿐이면 프로비저닝 신원에서 온다(≠`Rosy 01`). **Additive**: `system/info.caller_role`, CAP-001 `withheld` 와 CORE-only 동안 하드웨어 플래그 `false`·descriptor `blocked`(`runtime_mode:core`) (D-32). envelope `protocol_version` 1.0 유지 |
| v1.17 | 2026-09-23 | Additive: `logs/audit` 의 `log` 에 `dir_sync_failures`·`last_dir_sync_error`, `/metrics` 에 `rosy_audit_dir_sync_failures_total`(counter). 정리의 바꿔 끼우기 뒤 디렉터리 fsync 실패를 정리 실패(`prune_failures`)에서 떼어 센다 — 파일은 이미 정리됐다 |
| v1.16 | 2026-09-22 | 상태 표기·계약 명확화: §10 Fleet REST 카탈로그에 **미구현** 표기(시드는 :8090 `/api/fleet/*`), §1 `Deprecation`/`Sunset` 헤더 구현 시점 명시, §2 AUTH-103 CORS 미제공 제약, §4 enum 대소문자 표. 스키마 변경 없음 — envelope `protocol_version` 1.0 유지 |
| v1.15 | 2026-09-22 | 상태 표기 정정: §7.5 PRT-004 로봇 측 구현(correlation_id 소비·AckPayload 확장)을 중앙 Fleet 서버 착수 조건부로 명시 (ADR D-170). 스키마 변경 없음 — envelope `protocol_version` 1.0 유지 |
| v1.14 | 2026-09-22 | Additive: `logs/audit` 응답에 `log` (기록 상태 — `writable`·`write_failures`·`write_failures_total`·`prune_failures`·`prune_skipped`·`serialize_failures`·`last_write_error`·`last_prune_error`·`last_skip_reason`·`last_serialize_error`), `/metrics` 에 `rosy_audit_write_failures_consecutive`(gauge)·`rosy_audit_write_failures_total`·`rosy_audit_prune_failures_total`·`rosy_audit_prune_skipped_total`·`rosy_audit_serialize_failures_total`(counter). 감사 기록 실패는 EventBus 가 삼켜 어디에도 남지 않았다. 조회는 이제 파일을 재작성하지 않고 메모리에서 걸러 답한다 — 보존 약속(30 일)은 그대로고, 이벤트 목록의 모양도 그대로다 |
| v1.13 | 2026-09-22 | Corrective + Additive. **Corrective**: 이벤트 카탈로그(§8)가 실제 발행과 갈라져 있던 것을 맞춤. payload 키명 — `nav.stuck` 은 `timeout_s`(≠`timeout_ms`), `mode.changed` 는 `by`(≠`source`), `nav.started` 는 `{goal, by}`(≠`{goal\|waypoint}`), `nav.completed`·`system.shutdown` 은 payload 없음(≠기존 표기), `nav.lane_lost` 는 `{mode, reason, lost_after_s}`(≠`{lost_ms}`), `slam.*`·`presence.*` 는 이벤트별로 다름. 심각도 — 문서를 고친 것: `nav.lane_lost` 는 warning(≠error). 코드를 고친 것: `config.changed`·`swarm.aborted` 는 문서대로 warning 을 실제로 싣는다(≠기본값 info). 문서를 그대로 읽은 소비자는 이 목록만큼 이미 깨져 있었다. **Additive**: 구현돼 있지만 적혀 있지 않던 `docking.*` 11 종, `battery.deep`(D-27), `battery.shutdown_request_failed`, `localization.initialpose`, `nav.line_mode_changed`(D-143), `nav.traffic_policy_staged/applied/reset`(D-151), `sim.traffic_signal_changed` 신규 문서화, `config.changed` key 에 `dds.rmw`. `safety.watchdog` 은 v1.0 부터 약속만 있었고 이제 실제로 발행된다(SAF-002). `nav.blocked` 는 미구현 표시. 카탈로그와 발행 지점의 일치는 `src/runtime/gateway/test/test_event_catalogue.py` 가 고정한다 |
| v1.12 | 2026-09-21 | Additive: 인증된 front camera preview status/JPEG API. latest-only bounded frame, source/overlay/sequence 메타데이터, stale 시 404, raw image의 상태 WebSocket·Fleet·명령 경로 제외 |
| v1.11 | 2026-09-21 | Additive: semantic road `traffic_policy` 상태와 §6.1.1 vision `DetectionEvidence.inference_ms`(선택). map/scene/policy revision과 camera evidence를 결합한 fail-closed traffic policy, 추론 지연 메타, `core_common.protocol.detections`와 control 생산 스냅샷 동기 계약을 추가. envelope `protocol_version`은 1.0 유지 |
| v1.10 | 2026-09-21 | Additive: D-143 `line-follow` 조회·모드 선택 API와 상태 스냅샷 `line_follow`. IR/카메라 소스는 상호 배타적이며 stale·저신뢰·형식 오류는 0 명령, 3초 손실은 재선택 전까지 `LOST` latch |
| v1.9 | 2026-09-20 | Additive: §6.1.1 vision `DetectionEvidence` — 박스 정규화 좌표, `model_revision` 바인딩(D-47), 신선도 300 ms(D-136), 빈 detections/seq 점프 구분, 자문 전용(SAF-006, D-137). envelope `protocol_version` 은 1.0 유지 |
| v1.8 | 2026-09-17 | Additive: §6.1 스냅샷에 채널별 `evidence` — 서버가 `fresh`/`delayed`/`disconnected`/`unavailable` 과 그 판정의 `stale_after_s` 를 계산해 싣는다. 타임스탬프만 주고 클라이언트가 임계값을 하드코딩하는 경로는 계약이 아니다(D-18, D-72 S3). `GET /api/v1/robot/state` 와 `/ws/state` 가 동일 필드다. envelope `protocol_version` 은 1.0 유지(PRT-006 additive / MINOR 는 문서 쪽) |
| v1.7 | 2026-09-06 | Additive: §7.8 pose payload 에 `map_id` — 다른 맵의 참조 pose 는 목표가 되지 않고 `swarm.hold(map_mismatch)` 를 낸다(MAP-002 를 추종으로 확장). `swarm/state` 에 `max_speed`·`map_mismatch`, `safety/state` 에 `limits.session_linear` 추가. `max_speed` 는 이제 검증만이 아니라 실제 상한으로 적용된다. 그리고 정정: `slam/reset` 은 리셋하지 않았는데도 200 을 돌려주고 있었다. 런타임 미지원은 501 `CAPABILITY_NOT_SUPPORTED`, 세션 없음은 400 `VALIDATION_ERROR` 로 답한다 — CAP-003 준수 시정이며 의미 변경이 아니다(200 쪽이 위반이었다). D-32 |
| v1.6 | 2026-09-06 | Additive: DIAG-001 `diagnostics` 조회 구현. 군집 추종 구현 — `swarm/follow·cancel·state` 가 실제로 서빙되고, `/ws/swarm/pose`(SWM-003)·`/ws/swarm/reference`(SWM-007) 소켓 신설(§7.8, D-31). `swarm/state` 에 `holding`·`target_robot_id`·`source`·`stream_age_s` 추가 |
| v1.5 | 2026-09-06 | Additive: 현장 설정 — `PUT system/info`, `system/tokens/*`, `system/runtime`, `host/*` 릴레이 카탈로그(§5.7) 신설. `safety/limits` 에 `fleet_loss_policy`·배터리 임계값 추가(SAF-004/005). 미구현 상태였던 `diagnostics/*`·`ros/*`·`swarm/*` 행에 표시. 토큰은 해시 저장이며 목록은 불투명 `id` 로 식별한다(D-30) |
| v1.4 | 2026-09-01 | Additive: 절전/근접 웨이크 — `power/*` REST, 스냅샷 `power` 필드, 이벤트 `power.*`·`presence.*`, 센서 `ultrasonic` (PWR-001~004, D-24) |
| v1.3 | 2026-08-29 | Additive: 이벤트 `slam.started`/`slam.stopped` (NAV-005 세션 API 구현에 수반) |
| v1.2 | 2026-08-29 | Additive: `swarm/follow`에 `source` 필드(fleet 기본, peer 예약 — D-21 분산 진화 훅), SWM-007 |
| v1.1 | 2026-08-29 | Additive: swarm 인터페이스 — `swarm/follow·cancel·state` REST, envelope `pose` 스트림(§7.8), 이벤트 `swarm.*`, capability `swarm` 필드 (D-20) |
| v1.0 | 2026-08-29 | 최초 작성. PKY-CORE-SRS-001 v0.1의 API 산재 정의를 통합·확장 (버전·폐기 정책, 에러코드, 이벤트 카탈로그, Fleet↔Robot 프로토콜, 데이터 스키마, Fleet API 신설) |


### D-432 구현 보충 — 발견과 승인 (2026-10-03)

CORE `network.tls = {cert_file, key_file}`는 읽을 수 있는 절대 경로의 인증서·키를 시작 전에 검증하며 실패하면 HTTP로 대체하지 않는다. `network.connection_mode` 기본값은 `paired`; `development`는 `link_policy_file`의 사이트·장치·예상 `.local` 호스트·UTC 만료와 TLS를 모두 요구한다. Fleet 로스터의 `tls_ca_file`, `discovery: true`, `link_policy_file`은 인증된 HTTPS/WSS에서만 주소 갱신을 허용한다. 공개 HTTP 로스터는 기존 등록 주소를 유지한다. 개발 모드는 운전 모드가 아니다.

현재 로봇 로그인·등록은 기존 8자 코드, Cam 승인은 기존 6자리 숫자 코드다. 4자 숫자·영문 통합은 D-432의 추후 적용 사항이며 이번 API 계약에 활성화하지 않는다. 기존 TLS leaf·양쪽 nonce 결합, 지문 확인, 권한별 자격 및 감사 규칙을 유지한다.

`POST /api/v1/host/ssh/pair` (administrator, HTTPS 전용): `SshPairRequest {public_key, confirmed:false}`. `public_key`는 옵션 없는 Ed25519 공개키이며 최대 512자다. `confirmed:true`에서만 Host Agent `ssh.register_key`로 릴레이한다. 기존 host 릴레이 응답 `{available, ok, code, detail, recovery, data}`를 사용한다. 성공 data는 `{account:"rosy", port:22, public_key_fingerprint, host_public_key, host_key_fingerprint, already_registered}`이며 개인키·암호는 반환하지 않는다. TLS 없는 요청은 403, 권한 부족은 기존 admin 검사, Host Agent 부재·거부는 `available/ok`로 구분한다. 원시 화면 코드·API 토큰은 응답 로그에 남기지 않는다.


### v1.90 — D-432 장비 목록 자동 접속 추가 결정 (2026-10-03)

Pilot은 같은 LAN에서 발견한 장비 목록으로 시작한다. 설정 파일 가져오기·주소 입력은 필수 단계가 아니다.
앞 D-432 절의 개발 연결 정책 파일·TLS 필수 조건은 다음 명시적 로컬 개발 경로에 한해 개정한다.

| Method/path | Admission | Response |
|---|---|---|
| `GET /api/v1/auth/connection` | LAN peer, 인증 불필요, `no-store`; D-535부터 출발지별 30회/분(넘으면 429 `RATE_LIMITED` + `Retry-After`), LAN 밖 403 `LAN_REQUIRED` | 200 `{mode: paired|development, robot_id: string, transport: http|https}` (`ConnectionInfo`). D-535 (v1.155) 추가: `connect_contract`(정수, 1), `api`(`v1`), `core_ready`(부팅 단계가 `CORE_READY`; 표시 파일이 없으면 CORE가 답하므로 true), `stage`, `release`(없으면 null), `tls_hostname`(TLS일 때 `<host>.local`, 아니면 null), `pairing`(`open`\|`console_only`(LCD가 화면 코드를 보일 수 없음 — 관제 승인)\|`full`(대기 요청 3개)\|`unavailable`(HTTP이거나 수신 초기화 불가)). mDNS TXT가 이미 광고하는 값과 개수·가능 여부뿐이며 신뢰 앵커가 아니다 |
| `POST /api/v1/auth/development-session` | 아래 개발 조건, LAN peer, 허용 Host와 같은 Origin 또는 Origin 없음 | 201 `{id, token, role: operator, label, source: pair-development, expires_at}` |

개발 자동 접속은 장비의 `network.connection_mode=development`와 `ROSY_DEPLOYMENT=development`가
동시에 지정된 경우만 허용한다. 기본 `paired`, `device`·생산·미지정 배포는 403이다. 기존 LAN HTTP API는
개발 예외로 사용할 수 있다. TLS 광고는 HTTPS 필수이며 인증서 오류 시 HTTP로 재시도하지 않는다.
개발 세션은 1시간, 살아 있는 세션 최대 8개, IP별 분당 5회·전체 분당 30회 제한이다. 만료 세션은 다음 발급 시
정리하고 모드·배포가 바뀌면 기존 개발 자격도 즉시 거부한다. token 원문은 응답에서만 전달하며 저장은 digest다.
`POST /api/v1/auth/logout`으로 자기 개발 세션을 회수할 수 있다. 관리자 코드 발급·SSH 등록 권한은 주지 않는다.
외부 Host·Origin은 거부한다. HTTP 자격을 DHCP의 새 주소로 자동 전달하지 않고 연결을 닫아 다시 입장한다.
기존 `POST /api/v1/auth/pair`는 8자리 코드로 일반 모드에 연결한다. 새 접속 API가 없는 기존 로봇도 이 경로로 연결한다.
envelope `protocol_version`은 1.0이다. 발견은 신뢰·안전 승인·액추에이터 허용의 증거가 아니다.


## D-456 Fleet/Cam LAN 수신 승인 프로파일

API Reference v1.104의 additive minor 변경이며 envelope 1.0은 유지한다. CORE 운영자 로그인과 Fleet 영상 자격은 서로 다른 권한이다.
`core_common.protocol.camera_peer`가 새 typed wire의 원천이며 기존 v1은 유지한다.

| 항목 | 계약 |
|---|---|
| profile | `rosy.camera-peer/1` |
| audience | `fleet-camera-ingest` |
| device_kind | `overhead-camera` |
| source_role | `camera` |
| 발급 자격 role | 기존 `overhead-camera` |
| TLS endpoint | 선택한 수신 장비의 기존 사이트 HTTPS origin; frame ingress와 동일 |
| 발견 TXT | 기존 `pair=rosy-pair/1`에 선택적 `peer=rosy.camera-peer/1` 추가 |

새 TXT는 capability hint이며 신원·준비 상태·승인 증거가 아니다. 새 signed site의
resolved Compose가 camera profile과 pairing CA/TLS/named-users/SQLite/sync 설정을
포함하고 기존 pairing이 활성일 때만 public env와 overhead advertiser가 추가한다.
권한·네트워크 daemon·수동 IP 설정은 추가하지 않는다. 실제 HTTPS identity/proof가
실패하면 자격을 전달하지 않는다. 광고로 CA, source 또는 endpoint를 바꾸지 않는다.

`/api/fleet/pairing/v2`는 HTTPS 전용이다. 초기 anonymous identity는 locally configured
site CA가 실제 configured leaf/chain/hostname을 검증한 public anchor만 제공한다.
client는 기존 D341 limited first-contact 및 물리 수신 지문 비교 후 operational proof로
넘어간다. QR/4문자에 bearer를 담지 않는다; 4문자는 요청 비교용이다.

| 경로 | 권한·결과 |
|---|---|
| GET `/identity` | anonymous, IdentitySnapshot, 공개 receiver P256 key와 CA |
| POST `/requests` | anonymous, SignedRequest -> CreatedRequest, 메모리 대기만 생성 |
| GET `/pending` | 실제 현재 named configured operator, PendingRequest 목록 |
| GET `/relationships` | 같은 operator, RelationshipSnapshot 목록; 비밀/digest 미노출 |
| GET `/requests/{id}` | request_secret Bearer, StateSnapshot |
| POST `/requests/{id}/cancel` | request_secret Bearer, 아직 pending인 요청만 취소 |
| POST `/requests/{id}/decision` | named operator; action/revision/source_id/persist_requested |
| POST `/challenge` | remembered relationship_id/generation; signed 60초 ChallengeSnapshot |
| POST `/session` | SignedSession; 원래 key/source/profile/generation에만 영상 자격 발급 |
| POST `/relationships/{id}/revoke` | current named operator, 관계 세대 폐기와 자식 자격 회수 |

모든 응답은 no-store. 승인 결과는 `credential_issued=false`이고 실제 session 발급과
구별한다. 관계의 `authorization_available=false`는 기록 삭제가 아니라 갱신 불가다.
relationship_id=request_id로 승인 직후 응답 유실/재시작 상태를 복구한다. request secret은
digest로만 SQLite에 보관하고 승인 전 요청은 restart 때 잊는다.

단기 자격은 기존 최대 180일과 사이트가 정한 더 짧은 credential lifetime을 넘지 않는다.
`persist_requested=true`와 실제 `site-users.yaml` strict loader의 configured static
named operator (principal_id+role+token digest)를 함께 확인한 경우만 관계 만료를 두지
않는다. direct-config의 extra expiry/unknown metadata를 버려 영구 issuer로 만드는
변환은 거부한다. 이 slice에는 임시 named-site-user issuer를 새로 만드는 기능이 없다.
remember=false 관계는 자격 lifetime으로 제한하고 기록은 남긴다.

issuer principal/digest/role/provenance는 갱신 및 sync 때 현재 loaded site config와
다시 비교한다. named user 변경은 기존 loader/restart 경계를 따른다. remembered
source는 오프라인/자격 만료 뒤에도 다른 key에 재할당하지 않으며 명시적 revoke가 필요하다.
SQLite 트랜잭션은 nonce 소비와 자격 digest/관계 marker/감사를 한 번에 commit한다.
재접속은 이전 active 자식을 대체하고 관계별 최근 자격 이력 4개만 남긴다.
missing/malformed marker, missing relationship, generation/issuer/source 불일치는
new camera credential을 legacy credential로 취급하지 않는다.

기존 Vision sync body와 source/lease/capability는 바꾸지 않는다. 정상 sync는 2초 주기이고
실패 때 last-good 목록은 기존 600초 한도를 유지하므로 즉시 offline revoke를 주장하지 않는다.
CORE route/좌석/주행/정지 해제나 카메라 시작 권한은 발급하지 않는다.

한도: pending 16개/300초+closed 300초, request 및 proof 각각 site-wide 30회/분,
status 600회/분 및 valid request별 2초, poll cache 144개, relationship 128개,
challenge 64개/60초, request body 4096bytes, transcript 4096bytes. 한도는 기존 상태를
밀어내지 않고 거부한다. receiver 웹 polling은 2.5초 singleflight이며 hidden/offscreen/
locked/lifetime 종료 시 멈춘다.

현재 source/host 후보이며 실제 Native Cam 연결, 배포/재부팅/lease 수용은 별도다.

## Typed field handoff for API v1.104

Every v2 expires_at and authorization_expires_at is an ISO-8601 UTC string,
for example 2026-10-05T00:05:00Z. Unchanged v1 Vision credential sync uses numeric
Unix seconds for expires_at; do not substitute the numeric field in v2 examples.
No live token belongs in a public example. State retains credential_issued=false
even after approval; SessionSnapshot alone contains the newly issued credential.
persistent=true plus authorization_expires_at=null describes only the explicit
remembered static-owner relationship, not child credential expiration.
SessionSnapshot role is exactly overhead-camera. Signed profile source_role=camera,
device_kind=overhead-camera, audience=fleet-camera-ingest and profile=rosy.camera-peer/1
remain mandatory. ChallengeFields/SessionSnapshot source_id is immutable. Initial
generation is 0; revocation increments it. Four-character display code is unique
among current bounded requests and is not a secret. Request status/cancel require
the exact request-secret Bearer header.

SessionSnapshot credential_id는 `^cam-peer-[A-Za-z0-9_-]{24}$` 전용 namespace다.
P-256 public key는 canonical padded Base64 DER SPKI이며 키 digest는 DER의 SHA256이다.
서명은 DER ECDSA SHA256이고 canonical padded Base64를 사용한다. 서명 입력은
`{version: rosy.peer-proof/1, context, fields}`의 키 정렬·공백 없는 ensure_ascii JSON이다.
context는 request, receiver-challenge, session-request로 분리한다. 공개 golden vector는
`test/fixtures/protocol/camera-peer.v1.json`이며 Native Cam resource와 바이트가 같아야 한다.

## Service Control (D-524 Proposed)

`GET /api/fleet/hosts`는 운영자가, `POST /api/fleet/hosts/{host}/control`은 이름 있는 운영자
(site-users 자격, 로그인 세션, 개발 세션)만 호출한다. 이름 없는 `site-console`은 403
`OPERATOR_IDENTITY_REQUIRED`이고, site-users와 로그인이 둘 다 없으면 Fleet은 도우미를 만들지 않는다.
`host`는 `site`, `ai`, `model`이다. GET 행은 `{host, actions, units, stoppable_units, reboot_delay_min}`이다.
GET 본문은 그 목록과 함께 읽기 전용 `guard`(관제 PC `/var/lib/rosy-host-guard/status.json`)와 `drift`(관제 PC `/var/lib/rosy-host-state/status.json`)를 붙인다(D-530). 파일이 없거나 객체가 아니면 그 필드는 null이고, 수치를 만들지 않는다. PC 가드 항목의 `resources`는 `{avail_pct, swap_pct, load, cores, uptime_s, down}`이다.
PC별 `guard[host].recovery`와 관제 PC `drift.recovery`는 D-530의 2026-10-18 실행값 감시 보고다(`time`, `role`, `state`, `issues`, `resources`, `watchdog`, `kernel`, `ssh`, `swap`). 구버전·접속 불가·해석 실패는 null/부재이며 정상으로 추정하지 않는다. 가드 자신의 행은 `source=local`이고 원래 보고 시각을 유지한다. 화면은 원격 호스트 보고 15분, 로컬/복구 보고 35분 초과를 점검 지연으로 표시한다. 새 제어 동작이나 설치 API는 추가하지 않는다.
POST 본문은 `{action, unit, operator_confirmed:true}`이고 추가 필드는 거절한다. `action`은 `reboot`,
`cancel-reboot`, `restart-unit`, `stop-unit`만이다. `pkill`, 시그널, 셸, 프로세스 이름은 400
`UNKNOWN_ACTION`이다. `unit`은 그 호스트의 허용 목록에 있고 그 동작이 허용될 때만 받는다(사이트 유닛은
`restart-unit`만, 아니면 400 `UNIT_NOT_ALLOWED`). 재부팅은 `shutdown -r +10`이다. 이미 예약된 재부팅이
있으면 409 `REBOOT_ALREADY_SCHEDULED`이다. `cancel-reboot`는 이 도우미가 예약한 재부팅만 `shutdown -c`로
취소하고, 아니면 409 `NO_HOST_CONTROL_REBOOT`이다. 그 호스트의 연결 설정이 없으면 503
`HOST_HELPER_UNAVAILABLE`, SSH나 도우미가 실패하면 502 `HOST_HELPER_FAILED`이다. 성공은 200
`{host, action, unit, requested_by, code:"ACCEPTED", output}`이다. 이 API는 로봇을 재부팅하지 않는다.


### D-631 Site map profiles

See [D-631](../adr/D-631-map-profiles-and-views.md) for the profile API contract. GET `/api/fleet/site-map/profiles` requires read permission and returns `{profiles: [...]}`. PUT `/api/fleet/site-map/profiles/{profile_id}` requires a named operator, accepts `{name,map,expected_revision}` and returns the saved row. Each row contains `profile_id`, `name`, `map`, `revision`, `saved_by`, `saved_at`. Maps use `rosy.site_map/1` validation and the 2 MiB body limit. Profile IDs match `[A-Za-z0-9_.-]{1,64}`; names have 1-64 characters with non-whitespace content. Updates compare revisions; new profiles use null. Errors: 409 `SITE_MAP_PROFILE_CHANGED`, 409 `SITE_MAP_PROFILE_LIMIT` (100 profiles), 422 `SITE_MAP_INVALID`, 413 `SITE_MAP_TOO_LARGE`. Saves emit `profile_saved` and do not change the active map or draft. Loading into draft and activation use the existing APIs.

D-635 adds profile kind (lane_course, soccer, general, default lane_course), description (up to 1000 characters, default empty), and soccer_field (default null). Soccer requires positive finite length_m, width_m, goal_width_m with goal_width_m <= width_m; other kinds require null. These fields are returned with each saved profile. Metadata updates use the same revision and permissions; they do not activate a map or start Games. Updates omitting all three metadata fields preserve existing metadata (older clients); new rows default to lane_course.


## v1.206 Fleet 현재 판단 참고와 관측 종료 (D-660)

`GET /api/fleet/state`(viewer+)의 로봇 행 `judgment`는 null 또는 `FleetJudgmentReceipt`다. `necessity`는 `INTERVENE | DO_NOT_INTERVENE | ABSTAIN`, `reason`, `policy_revision`, epoch-second `evaluated_at`/`valid_until`, `request`는 원본 subject/case/revision/owner/condition/evidence/since/until/conflicted 참고 metadata다. 잘못된 값·누락도 보류 근거이므로 request를 실행 인자로 사용하지 않는다. `shadow=true`, `action_admissible=false`는 고정이며 필요성은 장치 발행 허가가 아니다. 현재 시각에 신선도를 다시 검사하고 과거 증거 시각을 갱신하지 않는다.

`GET /api/fleet/judgments?limit=100`(viewer+)는 `{records:[{judgment_id,robot_id,recorded_at,assessment}]}`다. limit은 정수 1..1000(기본100), 미인증401, 범위 밖422다. assessment는 같은 receipt 형식의 당시 기록이며 7일 보존한다. 필요성/사유/case/owner/정책 변화와 같은 분류의 60초 표본을 기록한다. 조회·정상 표본은 장치 요청·새 사건·외부 발송을 만들지 않는다. 당시 receipt의 TTL은 현재 조치 허가가 아니다.

`GET /api/fleet/incidents`의 line_stuck report에 `closure: FleetObservedClosure`를 추가한다. status는 `OPEN | NATURAL_CLEARANCE | CLEARANCE_OBSERVED | OBSERVATION_ENDED`, action_credit은 `NONE | UNVERIFIED`, reason은 기존 close_reason 또는 null, observed_at은 closed_at 또는 null이다. 수락/응답불명 답 뒤 cleared는 관측상 해소이며 조치 성공 증명이 아니다. restart/replaced/left_roster는 관측 종료다. 기존 evidence.fleet.resolved_by는 마지막 수락 답의 주체이며 인과적 성공으로 해석하지 않는다. 과거 원인 초안 점수는 보정된 정확도·확률이 아니다.

추가 형식의 기계 계약은 `core_common.protocol.schemas.FleetJudgmentReceipt`와 `FleetObservedClosure`, producer는 `fleet.stuck.board/reports`, consumer는 Fleet Console이다. 로봇 WS envelope protocol_version(1.0)과 기존 명령/사람 인수/stop-generation 계약은 변경하지 않는다.

### D-661 이름 있는 사건 인수 (v1.207)

기존 `POST /api/fleet/robots/{robot_id}/line-stuck/claim` 본문에 선택 `judgment_revision`(소문자 SHA-256 64자리)을 추가한다. 없으면 기존 자동 해결기 중지이고 응답의 `kind`는 `resolver_pause`다. 있으면 이름 있는 operator와 기존 durable Fleet DB가 필요하며 현재 사건/의미 revision/최근 Fleet 평가/경쟁 담당을 다시 검사한다. 성공 응답은 기존 robot_id/stuck_id/claimed_by와 `kind:incident_handoff`, `handoff:{robot_id,stuck_id,principal_id,judgment_revision,claimed_at}`(UTC epoch seconds)다. 기한/사건/revision 변경 또는 다른 담당은409, 미인증401, viewer/이름 없는 인수403, 원장 미설정503다. 성공은 검토 책임이며 CORE 실행·목표·해소를 뜻하지 않는다. 같은 담당 중복은 같은 receipt다. 다른 담당자의 이동 답은409이며 WAIT/ABORT는 유지한다.

`GET /api/fleet/incidents`의 line_stuck report에 `handoff`(없으면null), `judgment_revision`(현재 열린 case가 아니면null)을 추가한다. 조회는 선택 `robot_id`와 `stuck_id`를 함께 받으며 기존 limit 안에서 해당 사건만 반환한다. 하나만 주거나 식별자 형식이 잘못되면422다. token 없는 `/console?inbox=1&robot=<id>&incident=<id>` 링크는 기존 viewer/operator 로그인 이후 이 조회와 인수 UI로 연결되며 GET으로 인수하지 않는다. 공개 인수·조회 producer는 Fleet routes/기존 원장, consumer는 Console이다.

`GET /api/fleet/notifications?limit=100`(viewer+)는 `{records:[{event_id,robot_id,stuck_id,kind,channel,state,created_at,expires_at,next_attempt_at,attempts,last_code,provider_id,delivered_at}]}`다. kind는 OPEN/CLOSED, state는 PENDING/SENDING/SENT/RETRY/UNKNOWN/FAILED/EXPIRED/SUPERSEDED, 시각은 UTC epoch seconds다. limit 1..1000, 미인증401/잘못된 limit422이며 private endpoint·메시지 payload·secret·설치 주소를 반환하지 않는다. line_stuck incident report의 `notifications`는 같은 형식의 해당 사건 최근20건이다. SENT는 provider 수락이며 실제 수신/인수/해소가 아니다. UNKNOWN은 맹목 재시도하지 않는다. durable producer는 Fleet 사건/판단 owner, consumer는 opt-in notification worker와 Console이다.
## v1.214 Discord 현재 사건 인수 (D-693)

`POST /api/fleet/channel-requests/{request_id}/incident`는 현재 등록된 기명 operator의 자기 요청만 허용한다. strict 본문은 `expected_hash`(SHA256 hex64), `expected_revision`(bool 제외 비음수 정수), `robot_id`(1..96자 inert identifier), `stuck_id`(1..64자 inert identifier), `judgment_revision`(SHA256 hex64), `reason`(공백 제외1..256자)다. 원문으로 사건·관측 근거를 생성하지 않는다. Console는 현재 사건을 조회한 뒤 명시 확인으로 인수를 요청한다.

현재 mapping/원문/review와 기존 gather lock/current open case/judgment revision/freshness/담당자 검사를 유지한다. 기존 IncidentHandoff와 같은 DB transaction 안에서 원문 관계·LINKED 회신 intent를 예약한다. 변경·다른 담당자409, 권한 철회403, 다른 원문 owner404, 잘못된 본문422, owner/공통 DB 미설정503이다. 원장/회신 실패는 claim·관계 모두 rollback하며 기존 안전상의 resolver pause는 유지한다. 동일 원문·사건·판단·원래 확인 revision 재시도는 같은 관계를 읽고 다른 사건으로 바꾸지 않는다.

응답은 additive `ChannelWorkflowView`: `work_kind=incident`, `work_id=request_id`, `incident={robot_id,stuck_id,judgment_revision}`, `work_status=CLAIMED|CLOSED|UNKNOWN`이다. 다른 work kind의 incident는 null이다. CLAIMED는 담당 인수, CLOSED는 같은 사건의 종료 관측 원장이며 장치/목표 성공을 보증하지 않는다. 누락·owner 충돌 원장은 UNKNOWN이다. 사건 종료는 현재 mapping과 원래 message에 `INCIDENT:CLOSED` 회신 intent로 연결한다. 기존 기본 OFF/UNKNOWN 전송 계약을 유지한다. 새로운 정지·취소·재개 권한, rearm, E-Stop 해제, provider·motion writer를 만들지 않는다. 조치는 해당 기존 소유자의 별도 확인/admission을 사용한다. WS protocol_version1.0은 유지한다.

## v1.212 Discord 요청의 원자적 Task 제출 (D-680)

### v1.213 Mission·Cell Job owner adapter (D-687)

`kind=mission`에는 `candidate` 객체 대신 `source_proposal_id`를 사용할 수 있다. 둘 중 정확히 하나가 필요하다. 기존 source proposal은 현재 사용자 소유이며 kind가 일반 Mission이고 workcell/instance가 본문과 일치해야 한다. PROPOSED/RESOLVED만 허용하며 source lineage 또는 supersedes metadata가 있는 feedback/replan 후보는 409로 거절한다. 서버가 기존 관측·selector metadata를 복사하고 기존 resolver에서 다시 검증한다. 없는/다른 owner source404, scope/type/state 충돌409, 양쪽 동시 입력 또는 모두 누락422다. Console는 현재 자신의 실행 전 Mission 후보를 선택하는 방식으로 이 경로를 사용한다.

`POST /api/fleet/channel-requests/{request_id}/prepare`는 현재 mapping의 기명 operator owner가 확인한 실행 전 proposal을 기존 소유자로 준비한다. strict 본문 공통 필드는 `kind`, `expected_hash`, `expected_revision`, `reason`(비어 있지 않은1..256자), `workcell_id`, `instance_id`다. `kind=mission`은 기존 Mission의 `candidate` 객체를 사용하며 원문을 observation으로 만들지 않는다. `kind=cell_job`은 기존 Cell app의 `recipe_id/recipe_digest/cell_id/cell_digest`를 사용한다. `principal_id`, `request_key`, 임의 work ID는 받지 않는다. Fleet가 `discord-{request_id}` key와 기존 author를 주입한다.

기존 proposal 생성·resolve 검증 뒤 현재 owner/hash/revision을 DB 트랜잭션에서 다시 확인하여 LINKED로 연결한다. 관계 연결 전 검토 변경409는 실행 전 proposal만 남기며 admission하지 않는다. 같은 본문/원문/원래 revision 재시도는 같은 관계를 반환하고 다른 본문409다. 기존 proposal key의 다른 candidate는 기존 conflict 계약을 따른다. 미설정503, invalid body422, 다른 owner404/403이다. `ChannelWorkflowView.work_kind`는 task/mission/cell_job/null이며 candidate가 null인 연결된 Mission/Cell은 별도 실행 전 제안이다.

`POST /api/fleet/channel-requests/{request_id}/admit`의 strict `ChannelWorkAdmitRequest`는 `expected_hash`, `expected_revision`, `expected_generation`(bool을 제외한 비음수 정수)뿐이다. 현재 owner와 LINKED proposal의 author/key/kind/RESOLVED provenance를 확인하고 기존 Mission admit 함수만 호출한다. Cell service author와 기명 approver는 다르며 resolver 최신성, generation/fence, claims 및 기존 admission 오류를 유지한다. 새로운 writer·dispatch 활성화·rearm이 없다. Console의 별도 명시 승인이 필요하다. 결과는 현재 기존 원장을 읽은 `ChannelWorkflowView`이며 ACTION_SUCCEEDED와 GOAL_CONFIRMED를 구분한다. 경로 인증은 기명 operator다(D-763 4 리뷰: 기존 Mission admit과 같다. 이름 없는 공유 토큰은 403 `OPERATOR_IDENTITY_REQUIRED`).

`POST /api/fleet/channel-requests/{request_id}/submit`은 현재 mapping의 기명 operator owner만 호출한다. strict `ChannelSubmitRequest` 본문은 `expected_hash`(원문 SHA256 64자리 hex), `expected_revision`(bool을 제외한 0 이상 정수)뿐이다. principal/goal/task ID는 본문에서 받지 않는다. Console의 명시 확인 후 서버가 검토 candidate와 기존 FleetTaskService의 operator actor 및 `discord-{request_id}` key를 사용한다. 경로 인증은 기명 operator다(D-763 4 리뷰: Task가 로봇을 움직이므로 `POST /api/fleet/robots/{robot_id}/goal`과 같다. 이름 없는 공유 토큰은 403 `OPERATOR_IDENTITY_REQUIRED`).

기존 Task 생성의 `BEGIN IMMEDIATE` 안에서 현재 원문 소유권·hash·revision·READY·candidate와 관계 예약을 검증하고 Task와 LINKED를 함께 commit한다. 검토가 HOLD 또는 다른 candidate로 바뀌면409이며 Task를 생성하지 않는다. 동일 확인 revision·원문·Task key 재시도는 같은 Task를 반환한다. 새 장치 writer/승인 우회/dispatch 활성화가 없으며 기존 큐·fence·CORE 결과 규약을 유지한다. 진행 중 trip이면409, Task service 미설정503, 잘못된 본문422, 다른 owner404/403이다. 응답은 기존 `ChannelWorkflowView`다. 불명 응답은 GET review와 기존 Task 원장에서 확인하며 자동 재전송하지 않는다.

## v1.211 Discord 요청의 Console 검토·기존 Task 연결 (D-680)

접수 원문은 D-671의 immutable receipt다. 다음 경로는 intake가 설정된 Fleet에서만 제공하며 등록된 기명 operator의 자기 요청만 허용한다. Bot transport credential로는 호출할 수 없다. 인증 없음401, 계정/역할 철회403, 다른 owner 또는 없는 요청404, 원문 hash·검토 revision·작업 관계 충돌409, 잘못된 본문422다.

`GET /api/fleet/channel-requests/{request_id}/review`는 `ChannelWorkflowView`를 반환한다. 필드는 request_id, content_hash, revision(최초0), state(REQUESTED/READY/HOLD/REJECTED/LINKED), candidate, reason, work_kind(task|null), work_id, work_status(기존 원장 상태 그대로 또는 null), request_key다. 없는 작업의 연결은 work_status=UNKNOWN이다. 접수 상태와 실행 상태를 구분한다.

`PUT /api/fleet/channel-requests/{request_id}/review`의 strict `ChannelReviewRequest`는 expected_hash(SHA256 hex64), expected_revision(비음수 정수), state(READY/HOLD/REJECTED), candidate, reason(비어 있지 않은1..256자)다. READY만 `ChannelNavigationCandidate`(robot_id, 유한한 x/y/yaw; map frame, yaw 기본0)를 요구한다. HOLD/REJECTED에는 candidate가 없다. 후보는 Console에서 원문을 확인한 구조화 입력이며 이 경로 자체는 Task 제출·승인·dispatch·장치 호출을 하지 않는다. 모호한 요청은 HOLD로 남긴다.

주행 작업 제출은 기존 `POST /api/fleet/robots/{robot_id}/goal` 및 기명 operator 규약을 유지한다. Idempotency-Key는 반환된 request_key(`discord-{request_id}`)를 사용한다. 기존 trip busy·Task 원장·dispatch admission과 CORE 최종 검사를 우회하지 않는다. 응답 불명 후 새 key나 새 작업을 만들지 않는다. 원장에 이 key의 작업이 있으면 요청 검토를 바꾸지 못한다.

`POST /api/fleet/channel-requests/{request_id}/task`의 strict `ChannelTaskLinkRequest`는 expected_hash, expected_revision, task_id다. READY 요청과 기존 Task의 operator source·actor·key·robot·navigate goal이 모두 일치할 때만 LINKED로 연결한다. 동일 작업의 동일 연결 재요청은 기존 관계를 반환한다. 원장 데이터와 연결은 기존 tasks DB에서 검사하고 기록한다. 작업을 생성·재실행하거나 Task 상태를 변경하지 않는다.

Mission/Cell Job은 기존 owner/proposer/독립 approver 규약을 유지한다. 이 주행 관계 API로 팔 작업을 승인하거나 주행으로 대체하지 않는다. 각 소유자의 관계 어댑터와 시험은 후속이다. 위험 사건 인수·정지 경로도 별도 현행 사건/revision 계약에 따른다.

private `replies_enabled`는 strict bool이며 기본false다. true는 Bot 자격을 요구하고 기존 Fleet lifecycle 안에서만 접수 회신을 처리한다. 회신은 원래 채널·message에 묶이며 immutable 접수와 atomic intent, bounded retry, UNKNOWN 복구를 사용한다. 실제 작업 결과 회신과 위험 사건 대응은 각각 source·배포·실제 수용 증거를 확인한다. WS protocol_version 1.0은 유지한다.

## Fleet private configuration: hourly KST Discord health (D-733, source only)

`hourly_health_enabled` is a strict boolean and defaults to false. When enabled, Fleet posts one cached-facts health summary to the configured Discord channel at each KST hour boundary. A durable SQLite slot claim prevents duplicate sends across workers and restarts; startup skips missed slots, known 429/connect failures have a bounded retry window, and ambiguous delivery is not retried. The report contains per-robot cache freshness and observed safety/battery facts, Fleet collection time, active/HOLD/UNKNOWN Task counts, and the actual AI observer heartbeat. Missing or stale facts are unknown; a heartbeat does not establish model admission. It does not issue robot commands, invoke a model, force a Fleet gather, or attach a synthetic human message reference. Default-off source configuration and tests do not prove deployment or actual Discord delivery; first due-hour channel readback remains required.

## v1.210 Discord 기명 요청 접수 (D-671, source only)

`POST /api/fleet/channel-requests/discord`는 전용 transport 인증만 받는다. `X-ROSY-Timestamp`는 epoch-second 정수 문자열, `X-ROSY-Signature`는 전용 secret으로 timestamp + ASCII `.` + raw UTF-8 body에 계산한 HMAC-SHA256 소문자 hex다. 서버 시각과 차이 60초 초과 또는 잘못된 서명은401다. 일반 bearer/cookie는 transport 인증을 대신하지 않는다. raw body 최대8192 bytes(초과413), unknown field/형식 오류422다.

본문은 `DiscordRequestEnvelope`: guild_id/channel_id/author_id/message_id(17..20자리 숫자 문자열), content(1..2000자), mentions(최대100개 user ID 문자열), author_bot(bool), webhook_id(string|null)다. Fleet private guild/channel/Bot mention/user mapping과 현재 operator 계정이 일치해야 한다. Bot/webhook/DM/권한 철회는403이며 개발 principal과 caller principal은 허용하지 않는다.

응답은 `ChannelRequestReceipt`: request_id(접수 key), principal_id, guild_id/channel_id/message_id/author_id, 원문 content 및 content_hash(SHA256), received_at(UTC ISO8601), status=`REQUESTED`다. 같은 scope와 같은 envelope는 같은 receipt이고 수정된 내용은409다. 설정된 DB 최대1000건에서503이며 자동 삭제하지 않는다. 재접수도 현재 권한을 다시 검사한다. 접수는 Task/Mission/Job/승인/장치 요청/모델 호출을 만들지 않는다.

`GET /api/fleet/channel-requests`는 등록된 기명 operator의 자기 요청 최근50건 `{rows:[ChannelRequestReceipt]}`만 읽는다. 미인증401/다른 역할·공용·development403다. CLI `--discord-intake-config`가 없으면 두 경로는404다. account/mapping 변경은 기존 site-users와 같이 서버 재시작으로 반영한다. Gateway 수신 실행기, Bot token 주입, 실수신 및 후보/승인 연결은 후속 gate다. CORE/OMX writer, 기존 Mission/Cell Job 권한 및 WS protocol_version 1.0은 유지한다.

D-675 source only: private intake 설정에 선택적 ot_token_file을 지정하면 기존 Fleet lifespan에 Discord 수신기를 연결한다. 토큰은 별도 private 파일이며 없으면 OFF다. 기명 접수 계약과 API는 그대로이며 실제 이미지/수신 검증은 후속 gate다.

### Fleet execution admission closure (D-678)

Fleet navigation goal/bay admission preserves its stop token across capability and state awaits. A cancel or E-stop during admission refuses the unsent command with `COMMAND_REJECTED`; a concurrent goal/bay pipeline for the same robot is refused with the same code. Sequential goal replacement remains supported. A goal receipt requires an explicit boolean `accepted`: false is a refusal; missing or malformed acknowledgement is an unknown result and cannot create a goal or lease record. A late receipt after a stop cannot restart lease renewal; Fleet reissues navigation cancellation while preserving ambiguous Task outcomes.

Trip start preserves its stop generation across capability, pose/alignment, and lease admission. A stop during those awaits returns HTTP 409 `TRIP_START_CANCELED`, opens no live trip, and releases a lease already obtained for that start. This does not establish physical standstill. Task policy evidence, enablement and current dispatch generation are checked again at the owner-send boundary; known-unsent refusals remain reasoned HOLD records. Robot API/envelope versions and final CORE/Arm command authority are unchanged.


### D-685 승인된 자율 운영과 Fleet 관측 이력

`fleet.stuck_resolver.autonomous_robots`는 site config의 robot ID 목록이다. 최초 site 승인이 자동 운영 범위를 정하며, 목록의 로봇은 복구 가능한 stuck를 사람 대신 자동 대기/관측하고 기존 admission을 통과한 새 후보로 복구한다. 기본 빈 목록은 현장 활성화를 뜻하지 않는다. AI 대상·profile·credential·policy dispatch gate는 각각 기존 조건을 유지한다. UNKNOWN 이동은 같은 사건의 CORE `nav.line_stuck_closed`를 관측할 때까지 재발행하지 않는다. 기한과 예산을 재설정하지 않으며 human claim/class와 AI MANUAL은 범위 밖 예외다.

| Method | Path | Authority | Response |
|---|---|---|---|
| GET | `/api/fleet/observations` | 기존 Fleet read_guard | `{observations, next_cursor, has_more, recording}` |

쿼리는 `after_id`(기본 0, 비음수), `limit`(기본 100, 1..200), `robot_id`(선택, 1..96자)다. 행은 `{observation_id, robot_id, received_at, sha256, observation}`이다. `observation`은 기기의 기존 state와 gather_source, online, 목표/queue/capability/link, Fleet 수신 epoch, 원래 `_state_mono`, 추정 observed_at와 state_age_s를 보존한다. clock은 `fleet_receive_epoch`, verification은 `observed_not_labeled`다. state 내부 기기 timestamp·센서 단위와 결측은 그대로 둔다. Fleet 추정 시각은 기기 시계 동기화 증명이 아니고, cached hub 상태를 새 센서 샘플로 간주하지 않는다.

`--tasks-db` 또는 기존 `--events-db`가 있을 때 같은 durable journal에 기록한다. SharedGather의 실제 refresh마다 기록하며 cache 반환은 재기록하지 않는다. 저장 없음은 recording.state `disabled`, 성공은 `recording`, 실패는 `error/observation_storage_failed`로 노출한다. 조회 저장 장애는 503 `OBSERVATION_STORAGE_UNAVAILABLE`다. 기록 실패가 E-stop/기존 상태 읽기를 차단하지 않는다. 새 원장 보존은 최대 30일/100000행, 한 행 64KiB이며 대용량 카메라/scan 원본은 기존 기기 녹화로 보존한다. 오래된 원장 전체를 보존한다고 주장하지 않는다.

오프라인 `learning/curation/pinky/fleet_observations.py <database> <new-output-on-X> [--robot-id ID]`는 SQLite read snapshot을 JSONL/해시 manifest로 내보내고 다시 검증한다. 신규 출력만 만들며 원본과 기존 출력은 변경하지 않는다. schema `rosy.fleet-observations/1`은 학습 준비 원본으로 `train_eligible:false`, `labels:null`, `action_outcome:not_inferred`다. 실제 센서/행동 학습은 기존 device recording → Pinky Episode/원본 검증 → DatasetManifest/registry → 독립 평가/승격 경로에서 수행한다. Fleet 목표와 AI 선택은 CORE 실제 출력/정답 라벨이 아니다. 이벤트·Task·Mission·stuck 원장의 ID와 시간/시계 근거를 함께 대조하고 모호한 연결을 확정하지 않는다.

### D-732 Fleet native outcome projection

The existing Task `receipt` and channel execution step `receipt_json` preserve the first
CORE `operation` unchanged. Optional `outcome` is an exact `NativeOperation` readback;
its first terminal result is immutable. Optional `safe_released:true` and `quiescence`
record a bounded fresh readback and an exact local claim CAS, independently of result.
Only `SUCCEEDED` together with safe release permits a channel step to become COMPLETED
and reach another step's original admission checks. `RUNNING` follow/HOLD retains its
resource; watchdog EXPIRED, PREEMPTED, CANCELED and FAILED are not goal success.
Stop steps own no motion claim: exact terminal plus fresh quiescence closes them as
CANCELED with `quiescence`, without `safe_released`, releasing another owner, or
advancing the plan. Site E-stop preserves each provided native `operation` in its
robot-associated `robots[]` receipt; RPC acknowledgement alone is not physical stop.
Channel steps additionally expose the persisted `caller_cid` used by that dispatch.
Task `receipt.native_required:true` records that native identity was required before
send; a missing ACK leaves UNKNOWN and cannot use legacy CID-only projection. Explicit
legacy Task attempts without native identity keep their existing event projection.
New channel native commands carry the paired current CORE boot/owner-generation CAS.
Read-only closure preserves immutable original-request linkage after expiry/withdrawal;
current authorization still controls delivery and access. A revoked recipient's reply
intent may be SUPERSEDED while result evidence remains in the existing Fleet database.


### D-755 검수 앱 협업 HTTP 경계

검수 앱의 선택적 `--collaboration`은 모델 PC의 HTTPS 프록시 뒤 loopback HTTP에 적용한다. CORE `/api/v1`, Fleet 역할, ROS와 장치 실행 프로토콜을 추가하거나 변경하지 않는다. 사용자·프로젝트 membership, 개인별 HF 연결, 자료 가져오기 경로와 요청 필드는 [검수 앱 공동 계정 설명](../../learning/curation/perception/docs/review-app.md#공동-계정과-hugging-face-가져오기-d-755)을 따른다.

`/api/accounts/*`는 세션·계정 연결, `/api/learning/imports`와 그 `create|retry|cancel` 하위 POST는 고정 revision 읽기 가져오기다. `/oauth/huggingface/callback`은 등록된 HTTPS URI에 대한 일회성 OAuth callback이다. 현재 신원과 프로젝트 권한은 기존 검수 자료 읽기·수정에도 적용되며 계정 연결 자체는 프로젝트 가입이나 학습 승인이 아니다. 협업 모드의 임의 서버 경로 등록과 인증 없는 `--decisions-port`는 허용하지 않는다. 가져오기 완료는 검수 대기이며 모델 적재·외부 게시·CORE/OMX 명령 권한을 만들지 않는다.

### D-765 비공개 데이터셋·모델 저장소

검수 앱 로컬 경로이며 CORE `/api/v1`이 아니다. `learning.publish`와 연결에 기록된 저장소 범위가 둘 다 있어야 한다. `learning.import`와 `learning.manage`는 이 경로를 대신하지 않는다. 개인 연결은 그 Hugging Face 사용자 이름의 저장소만 만들고, 프로젝트 연결은 허용 목록의 `dataset:`·`model:`만 다룬다. 생성은 `visibility: private`이며 만든 뒤 private가 아니면 실패한다. 공개 상태를 바꾸거나 자동으로 지우지 않는다. 삭제는 `confirm`이 `repo_id`와 같고 조회 결과가 private일 때만 한다. 응답에 토큰을 넣지 않는다. 파일 업로드, Spaces, 과금은 이 경로에 없다.

| 경로 | 입력과 반환 |
|---|---|
| `GET /api/accounts/repos` | 정확한 쿼리 `connection_id`, `repo_type`(dataset 또는 model). `repos`에 `repo_id`, `private`, `sha`를 최대 50개 반환한다. 프로젝트 연결의 없는 저장소는 `missing: true`다. |
| `POST /api/accounts/repos/create` | 정확한 본문 `connection_id`, `repo_type`, `repo_id`. 비공개로 확인된 저장소 항목을 반환한다. 409는 기존 저장소를 성공으로 보지 않는다. |
| `POST /api/accounts/repos/delete` | 정확한 본문 `connection_id`, `repo_type`, `repo_id`, `confirm`. `confirm`은 `repo_id`와 같아야 한다. |
| `POST /api/accounts/oauth` | `purpose`에 기존 `login`·`link` 외에 `manage`를 둔다. manage는 쓰기와 저장소 관리 범위가 모두 있을 때만 연결한다. |

권한 거부는 기존 403이다. 범위 부족, 이름 불일치, 공개 저장소, Hub 실패는 400이며 비밀이나 Hub 본문을 포함하지 않는다.

가져오기 작업은 파일별 `downloaded_bytes`, `partial_sha256`, 완료 `sha256`와 작업의 `reserved_bytes`를 반환한다. 부분 bytes는 검증 완료나 학습 승인이 아니다. 서버가 제공한 SHA-256과 로컬 부분 해시가 있는 파일만 같은 revision·연결 세대로 Range 재개한다. Range를 무시한 전체 응답은 덧붙이지 않고 처음부터 다시 받는다. `insufficient_space`, `storage_unavailable`, `verification_failed`, `access_revoked`, `worker_interrupted`, `import_failed`는 비밀을 포함하지 않는 실패 코드다. 저장소 실행 잠금과 남은 bytes의 논리 예약은 같은 imports root의 worker만 조정하며 파일시스템 전체의 물리 예약은 아니다. 운영자 전용 `import_limits` 설정은 웹 입력으로 변경할 수 없다.

### 학습 저장 현황과 공간 사전 점검 (D-755 후속)

검수 앱 로컬 경로이며 CORE API가 아니다. 관리자가 private `--storage-config` JSON에 프로젝트와 root ID·표시 이름·용도·절대 경로를 등록한다. 협업 프로젝트와 설정의 project_id는 일치해야 한다. 협업 사용자의 view 권한을 모든 요청에서 검사하며 실제 경로·파일명은 응답하지 않는다.

- `GET /api/learning/storage`: 설정 상태, 측정 시각, root별 파일 수·논리 bytes·하드링크 중복 제외 file_bytes·할당 bytes·미완료 파일 bytes·파일시스템 잔여 bytes, 일 증가량·추정 잔여 일수, 등록된 pending root의 bytes를 반환한다. 60초 캐시를 사용한다. 부분 스캔·오류·근거 부족은 null/partial/unavailable로 표시한다.
- `POST /api/learning/storage/preflight`: 기존 Origin·X-Pinky-Token 검사와 view 권한을 요구한다. 정확한 입력은 destination_id, download_bytes, staging_bytes, transform_bytes, upload_bytes이며 bytes는 0..9000000000000000 정수다. 알려진 root ID만 허용한다. 로컬 요구량은 세 로컬 항목과 관리자 reserve_bytes의 합이며 현재 같은 목적지 파일시스템 여유와 비교한다. 원격 업로드 요구량은 관리자 제공 quota의 잔여량·출처·측정 시각·유효기간과 비교한다. ready/hold/blocked는 순간 공간 추정이며 예약·전송·자료 품질 승인이 아니다.
- 미설정 GET은 not_configured, 미설정 사전 점검은 400이다. 잘못된 root/입력은 400, 세션·프로젝트 접근 거부는 기존 401/403 규칙을 따른다. 공개 wire는 파일 경로·삭제·업로드·유료 증설 입력을 받지 않는다.

### D-764 검수 AI 실행과 저장 버전

다음은 모델 PC 검수 앱 전용이며 CORE protocol schema를 변경하지 않는다. 협업 모드의
GET은 view, AI POST는 edit와 기존 Origin·X-Pinky-Token을 요구한다. 타인의 작업 취소에는
manage도 필요하다. actor는 서버 세션에서 정하며 비협업 모드는 local-unidentified다.

| 경로 | 입력과 반환 |
|---|---|
| `GET /api/review-ai/{index}` | 동작별 available/reason과 최신 30개 작업. 작업에는 id/frame/action/version/state/actor/model/model_digest/created_at/updated_at/error/result와 입력 해시가 포함된다. 비밀·서버 경로는 반환하지 않는다. |
| `POST /api/review-ai/{index}` | 정확히 action과 version. action은 object_draft/pixel_draft/mask_check, version은 해당 객체/픽셀 저장 revision 정수. 새 작업 반환. |
| `POST /api/review-ai-cancel/{id}` | 빈 JSON 객체. 작업 ID는 32자리 hex. 종료된 작업의 취소는 상태 유지. |
| `GET /api/review-history/{lane}/{index}` | lane은 object/pixel. 선택적 before 양의 정수, limit 1..100(기본 20). events와 next_before, version 내림차순. |
| `GET /api/review-versions/{lane}/{index}/{version}` | 저장 snapshot metadata, available, actor/ts/status(기록된 경우). 객체 boxes 또는 픽셀 해시·크기·클래스. 미보존은 available=false. |
| `GET /api/review-version-images/{index}/{version}` | 검증된 과거 픽셀 overlay PNG. 미보존·해시/형식 오류는 400. |

AI 작업 상태는 queued/running/succeeded/failed/cancelled/stale다. 성공은 후보·참고 의견 저장이며
승인·학습 투입이 아니다. 생성 시 stale version은 409, 잘못된 입력·미설정은 400,
권한 거부는 403이다. 결과 등록 전 요청자의 세션/권한과 입력을 재검사한다.
재시도는 현재 revision으로 새 POST다. 기존 작업 이력은 유지한다.


## 실측 카메라 지도 미리보기 (D-775, v1.256)

기존 tracking 승인·sighting 허용 revision은 유지한다. 실측 묶음 schema는
`rosy.measured-calibration/1`이며 `core_common.protocol.measured_calibration`이 정본이다.
source/map/revision, 원본 lens/floor 후보, 서로 다른 training/validation SHA-256 목록,
독립 survey digest, capture(signature·reported lens·rotation), bounds_m, evidence_kind,
canonical digest를 보존한다. 원본 후보 revision도 내용·원본 digest로 다시 계산한다.
`rosy-camera-calibrate bundle --input <bundle-input.json> --output <new-dir>` 입력은
`{report:<relative-report>, floor:<relative-floor>, context:{map_revision, survey_digest,
capture, bounds_m, evidence_kind}}`다. 출력은 수치 전용 bundle.json이며 자동 승인하지 않는다.

- POST `/api/fleet/calibrations`: 기존 body는 그대로, 새 body는
  `{purpose:"preview", kind:"measured", bundle, expected_revision:string|null,
  limits:{p95_m,max_m}}`. 이름 있는 operator만, measured 근거와 명시적 양수 한도 필수.
- GET `/api/fleet/calibrations?purpose=preview`: preview 승인 목록·persistent와 적용 readback.
  목적 생략은 기존 tracking 목록만 반환한다.
- DELETE `/api/fleet/calibrations/{source_id}?purpose=preview&expected_revision=<revision>`:
  이름 있는 operator의 원자적 철회. 기대 revision 불일치는 409이며 기존 tracking 기록은 유지한다.
- GET `/api/fleet/detections/config?include_preview=true`: 해당 source token에만 optional
  measured_preview를 추가한다. 기본 응답과 기존 calibration 필드는 유지한다.
- POST `/api/fleet/detections/preview-status`: source token으로 자신의 revision/session/state/reason과
  frame_seq, optional render_age_s(0 이상 5초 미만)를 보고한다. 추가 필드·영상은 거절한다.
  readback 신선도는 Fleet 수신 시각과 마지막 render의 나이를 함께 확인한다.
- POST `/api/fleet/vision/lease`: optional measured 요청은 source/session/revision/capture_signature와
  confirm_conditions를 결속한다. 확인 권한은 named operator, 일반 viewer는 읽기만 가능하다.
  서명마다 새 jti를 부여하여 조건 변경 뒤 옛 확인을 재사용하지 않는다.
- Vision direct GET `/api/vision/sources/{id}/measured-status`는 기존 signed viewer lease로
  session·입력 조건·적용 상태를 JSON으로 읽는다. frame GET의 signed measured 요청만 새 변환을 사용한다.

저장 승인과 실제 적용은 다르다. Vision은 receiver boot/session과 정확한 입력 조건을 확인하고
monotonic 기준 최대 5초의 config lease가 만료되면 적용을 중단한다. 갱신 실패는 lease를 연장하지
않고 remap 뒤에도 generation/session을 다시 검사한다. 원본·기준 지도를 유지하며 미관측은 mask로
구분한다. 실측 승인·미리보기는 위치 앵커·마커 높이 보정·주행·DEVICE/FIELD 수용을 부여하지 않는다.

### v1.275 — D-801 관제 콘솔 사이트 발급 영상 위임

D-789 Decision 3을 대체한다. Fleet에 `ROSY_FLEET_MEDIA_CONFIG`(JSON: `site_url`, `audience`=`site:<id>`,
`key_id`, `signing_key_file`=사이트 전용 Ed25519 PEM, `audit_db`)가 있을 때만 열린다. 없으면 아래 경로는 404다.

| Method | Path | Authorization | Result |
|---|---|---|---|
| POST | `/api/fleet/robots/{robot_id}/media-grant` | 사이트 로그인 쿠키 또는 사이트 Bearer, `fleet.read`. LAN 카메라 프록시 주체·ai_observer 불가 | 201 읽기 위임(아래 receipt). 모르는 로봇 404 |
| POST | `/api/fleet/robots/{robot_id}/media-grant/{grant_id}/renew` | 같은 주체 | 200 같은 grant_id, 새 token. 끝난 위임 403 |
| DELETE | `/api/fleet/robots/{robot_id}/media-grant/{grant_id}` | 같은 주체 | 204, 감사 종료 `closed` |
| POST | `/api/fleet/media/validate` | Authorization의 사이트 위임 Bearer(세션 없음) | `{active:false}` 또는 `{active:true, grant_id, robot_id, path, action:"read", audience, expires_at}` |

receipt는 v1.265와 같은 모양(`grant_id`, `token`, `expires_at`, `audience`, `robot_id`, `path`, `action:"read"`,
`site_url`)이며 `no-store`다. 위임은 `rosy-media+jwt`, iss=aud=`site:<id>`, action은 read만, 최대 60초다.
validate는 발급 때의 브라우저 자격으로 Fleet 인증·권한을 다시 검사하므로 로그아웃·역할 회수 뒤 inactive다.
70초 동안 갱신이 없으면 위임은 `expired`로 끝난다. 감사 표 `fleet_media_audit`(grant_id, principal_id, role,
robot_id, started_at, last_seen_at, ended_at, end_reason)에 위임마다 한 행을 남긴다.

미디어 권한 서비스 설정 `site_issuer`(`fleet_url`, `fleet_ca`, `keys`)가 있으면 사이트 위임을 받는다.
1초 재확인은 로봇 CORE `POST /api/v1/vision/media/validate`의 영상 설정 상태(200=켜짐, 503=꺼짐; 로봇 거부권)와
Fleet validate가 모두 활성일 때만 통과한다. 로봇 키로 서명된 위임은 사이트를 대신할 수 없다.
콘솔 페이지 CSP `connect-src`에는 설정된 site media origin 하나만 추가된다. Fleet은 영상을 중계하지 않는다.

### v1.265 — D-789 WebRTC 영상 위임 자격

실시간 영상 전환을 위한 추가 계약이다. 장치 설치·6대 현장 수용은 뜻하지 않는다.
`site_url`(고정 HTTPS origin)이 설정되면 영상 위임은 기본 활성이고 `vision.media.enabled: false`로만 끈다
(D-789 부록 2026-10-18, 측정 생략). `site_url`이 없으면 비활성이다. `audience`(`site:<id>`),
`key_id`, `signing_key_file`(로봇별 전용 Ed25519 PEM)을 갖춰야 읽기 위임이 열린다.
`source_credential_file`은 선택 설치된 로컬 영상 발행자만 읽을 32~512바이트 전용 자격이다.
키·source 자격은 저장소 밖에 두고 media 서비스에만 필요한 최소 파일 권한으로 설치한다.
없거나 잘못된 설정은 영상만 503 `MEDIA_UNAVAILABLE`이며 CORE 시작은 유지한다. 뷰어는 503이면 기존 JPEG에 남는다.
설정되면 `/pilot` 페이지 CSP `connect-src`에 그 site origin 하나만 추가된다.

| Method | Path | Authorization / body | Result |
|---|---|---|---|
| POST | `/api/v1/vision/media/grants` | CORE Viewer 이상; `{robot_id}` | 201 읽기 위임 |
| POST | `/api/v1/vision/media/grants/{grant_id}/renew` | 같은 CORE 소유자 | 200 같은 grant_id, 수명 갱신 |
| DELETE | `/api/v1/vision/media/grants/{grant_id}` | 같은 CORE 소유자 | 204 철회; 없는 ID는 같은 소유자 범위에서 멱등 |
| POST | `/api/v1/vision/media/source-grant` | 전용 source Bearer; `{robot_id, grant_id?}` | 201 발행 위임; grant_id가 있으면 같은 발행 위임 갱신 |
| POST | `/api/v1/vision/media/validate` | Authorization의 영상 위임 Bearer | `{active:false}` 또는 신선한 위임 상태 |

읽기/발행 receipt는 `grant_id`, 새 `token`, `expires_at`(UTC epoch 초), `audience`,
`robot_id`, `path`(`robots/<robot_id>/front`), `action`(`read|publish`), `site_url`이다.
일반 Viewer body로 `action=publish`를 요청할 수 없다(기존 validation envelope의 추가 필드 400). 다른 robot·소유자·원본 권한
상실은 403이다. 토큰·키는 URL이나 로그로 보내지 않으며 모든 위임 응답은 `no-store`다.
CORE의 일반 Bearer는 validate에서 영상 자격으로 인정되지 않고, 영상 자격도 CORE 명령 권한이 없다.

서명된 `rosy-media+jwt`는 Ed25519, key id와 정확한 robot/path/action/audience 및 최대 60초의
iat/exp에 결속된다. 원본 CORE 권한을 매 검사마다 다시 확인하고 서버의 철회 기록과 대조한다.
CORE 재시작은 이전 위임을 닫는다. Account는 현재 앱 cookie 세션에 결속하고 영상 재검사에서
기존 Account 10초 cache/offline grace를 사용하지 않는다. cookie 없는 Account Bearer 위임은
403 `MEDIA_BROWSER_SESSION_REQUIRED`다. 미디어 서비스는 1초마다 validate하고 원본 권한 상실·
CORE 단절·활성 lease 만료 시 실제 MediaMTX 세션을 5초 안에 종료해야 한다.
활성 미디어 세션의 20초 갱신과 종료 집행은 사이트 media 서비스의 별도 책임이다.

사이트 media origin은 Fleet과 별도 서비스이며 다음 좁은 관리 경로를 제공한다. 전부 영상 위임
Bearer를 헤더로 받고 `no-store`로 응답한다. 일반 CORE/source 장기 자격을 이 origin으로 보내지 않는다.

| Method | Path | Scope / result |
|---|---|---|
| POST | `/v1/intents` | read 위임. 201 `{grant_id}`; 시작 demand 최대 10초 |
| DELETE | `/v1/intents/{grant_id}` | 같은 read 위임의 시작 취소, 204 |
| GET | `/v1/sources/{robot_id}/demand` | 해당 robot의 publish 위임. `{active, robot_id, fps, target_bitrate, max_bitrate}`; bitrate는 bit/s, 최대 1000000 |
| GET | `/v1/session` | 위임 jti에 결속한 실제 MediaMTX `{session_id, expires_at}`; 아직 없으면 404 |
| POST | `/v1/session/renew` | 갱신된 같은 위임으로 기존 실제 세션 lease 갱신. `{active:true, session_id}`; 소유자/scope 변경은 403 |
| DELETE | `/v1/session` | 같은 위임의 실제 세션 종료, 204; 소유 불일치는 403 |

MediaMTX WHIP/WHEP의 Location resource 식별자를 관리 API의 session_id로 추정하지 않는다.
실제 session_id는 MediaMTX auth callback에서 얻은 id와 위임 jti의 결속으로 조회한다.
관리 callback `/auth`와 `/health`, MediaMTX 관리 API는 loopback 전용이며 외부 proxy에 공개하지 않는다.
`/auth`는 publish/read에 `protocol=webrtc`와 정확한 path·위임을 확인하고, action=api에는 별도 로컬
관리 자격만 인정한다. source/read 위임으로 관리 API를 호출할 수 없다.

### D-834 Learning 로컬 SIM HTTP 계약 (Proposed)

기존 검수 앱의 `/learning/sim`이며 CORE `/api/v1` 버전·장치 명령 schema에 속하지 않는다. 같은 모델 PC의 공통 Isaac 실행기와 CLI run 저장소를 사용한다. 운영 binding으로 source SHA·고정 entrypoint·SDK·외부 데이터 루트를 고정하며 요청에서 shell·argv·호스트·경로·unit·환경변수를 받지 않는다. 상세 설정과 실행 의미는 [검수 앱 SIM 설명](../../learning/curation/perception/docs/review-app.md#sim-실험-d-834-proposed), [운영 절차](../deployment/isaac-experiment-runs.md)를 따른다.

| 경로 | 요청·응답·권한 |
|---|---|
| `GET /api/learning/sim/catalog` | view: `scenarios`, 고정 `source_sha`. 비활성 시나리오도 선행 조건·이유를 반환 |
| `GET /api/learning/sim/runs` | view: `runs`. 실패·중단·UNKNOWN 포함, 원시 runtime·SDK 로그·private 경로 제외 |
| `GET /api/learning/sim/runs/<run_id>` | view: 불변 입력 지문·설정·source SHA, revision·상태·단계·공개 결과·산출물 metadata |
| `GET /api/learning/sim/runs/<run_id>/artifacts/import-report` | view: 최종 manifest로 해시·크기를 검증한 최대1MiB JSON 모델 검사 보고서 |
| `POST /api/learning/sim/check` | manage: `scenario_id`, `config`, 선택적 현재 `source_sha`. 서버가 고정 SHA로 준비 상태·입력 지문 확인 |
| `POST /api/learning/sim/start` | manage: `request_id`, `scenario_id`, `config`, `expected_input_sha256`, 선택적 현재 `source_sha`·`parent_run_id`. 같은 요청·입력은 같은 run |
| `POST /api/learning/sim/stop` | manage: `run_id`, 현재 `expected_revision`. 소유 worker pidfd로 중지 요청, 종료 확인과 구분 |

기존 Host·Origin·`X-Pinky-Token`·최대1MiB JSON 검사 뒤 프로젝트 권한을 다시 적용한다. 비협업 로컬 모드의 SIM 제어는403이며 연결 미설정은503이다. 시작 응답 유실은 새 실험을 만들지 않고 같은 요청으로 관찰한다. 입력/revision 충돌은 기존 로컬 HTTP의400 응답으로 거절한다. UNKNOWN은 자동 재시작하지 않는다. 첫 시나리오는 모델 import·관절·120프레임 검사이며 `task_success=null`, seed 미사용·영상 없음 사유를 명시한다. 물리 집기·학습 수용·정책 승격·로봇 명령 권한을 부여하지 않는다.
