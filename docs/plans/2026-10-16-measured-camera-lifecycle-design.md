# 실측 카메라 교정의 승인·적용·무효화 설계

상태: 사용자 검토용 설계. 제품 코드·외부 계약·운영 설정은 아직 바꾸지 않았다.
브랜치: `docs/camera-calibration-lifecycle`. 조사 기준: `cd50cde54`.
관련 결정: D-633, D-636, D-457, D-587, D-595, D-598, D-630, D-752.

## 목표와 진행 순서

운영자가 실제 카메라의 측정 결과와 독립 검증 오차를 확인하고 승인하면, 승인한
렌즈·바닥 교정 한 쌍으로 같은 촬영 조건의 지도 영상을 보게 한다. 조건이 바뀌거나
승인이 철회되면 측정 교정을 사용할 수 없다는 이유를 표시하고 재승인을 요구한다.
후보 파일 생성, 승인 기록 저장, Vision 적용 readback, 실제 좌표 정확도를 각각 확인한다.

사용자는 이 작업을 먼저 하고 마커 공백 대응(D-598)을 이어가는 목표에 동의했다.
첫 구현 단위는 **실측 교정의 영속 승인과 Vision 지도 미리보기 연결**이다. 로봇 마커의
높이 보정과 실측 sighting 사용, D-598의 오차 한도 주행은 후속 단위다. 미리보기 연결을
마커 위치추정이나 실물 주행 완료로 보고하지 않는다. Nav2 설정 재평가(D-393)는 이번 목표에 넣지 않는다.

## 현재 연결과 확인한 공백

| 경계 | 현재 근거 | 남은 연결 |
|---|---|---|
| 측정 | `operations/overhead/rosy_vision/camera_calibration.py`의 `fit_lenses`, `fit_floor`, `plane_image` | 후보는 `applied:false`이고 운영 저장·선택과 연결되지 않음 |
| 후보 식별 | 렌즈 후보의 source·capture_signature·image_size·K/D·revision·검증 잔차, 바닥 후보의 lens_revision·undistorted_to_map·독립 점 오차 | 운영용으로 가져올 때 내용 hash, 원본 계보, 선택한 한 쌍의 무결성을 다시 검증해야 함 |
| 승인 | Fleet `tracking_routes.py` → `TrackingService.approve` → `TrackingCalibrationStore` | 현행 요청·SQLite 기록은 raw 픽셀용 `map_to_image` 평면 변환만 표현함 |
| 적용 | Vision `track/calibration.py`와 `track/model.py` | 런타임 Calibration도 단일 homography로만 표현됨. 비선형 렌즈 후보를 넣을 수 없음 |
| 마커 | `track/marker_sightings.py` → Fleet `sightings.py`의 approved revision 검증 → World MapPose | 기존 시차 보정은 homography와 HFOV로 카메라를 푸는 경로. 실측 렌즈 지원을 뜻하지 않음 |
| 촬영 조건 | `rosy_vision/protocol.py`의 hello sensor 크기·rotation과 선택 lens 정보 | 오프라인 capture_signature 문자열을 실시간 초점·zoom·crop·ISP 상태 검증으로 간주할 수 없음 |
| 공백 추적 | World `state/projections/map_pose.py`, Fleet `server/identity_triggers.py` | `source=bridged`는 기존 odom 이어가기. D-598의 오차 한도 상태와 다름; identity trigger도 고정 거리당 오차를 사용함 |

기존 `operations/overhead/docs/compact-camera-calibration.md`의 촬영·측량 절차와 도구를
재사용한다. 학습·검증에 같은 원본을 쓰지 않는 D-636 규칙을 유지한다. 관련 교훈은
`docs/solutions/workflow-issues/measure-the-real-camera-from-recorded-video-before-tuning-sim-perception-2026-09-24.md`다.

## 선택한 접근

기존 Fleet 승인 서비스·SQLite·권한 검사를 확장하고, **실측 교정은 명시적인 별도 형식**으로
저장한다. 기존 paint-fit 기록을 실측 형식으로 자동 변환하지 않는다. Vision은 실측 후보의
기존 `plane_image` 계산을 재사용하며, raw→교정 픽셀→map 변환을 한 번의 inverse remap으로 그린다.
JPEG는 기존처럼 Vision에 있고 Fleet에는 수치·근거 식별자만 전달한다.

대안으로 새 승인 서비스/DB를 만드는 방법은 승인 주인과 철회를 둘로 나누므로 채택하지 않는다.
실측 렌즈를 기존 3×3 행렬에 근사해 넣는 방법도 형식이 표현하지 못하는 오차를 숨기므로 채택하지 않는다.
오프라인 도구만 유지하는 방법은 가장 작지만 사용자가 요청한 승인·운영 연결을 충족하지 않는다.

## 첫 구현 단위의 계약

아래 필드와 상태는 제안이다. 구현 전 새 ADR을 선점하고, 공개 변경은 API reference·관련
스키마·소비자와 함께 반영한다. 이 설계 문서만으로 새 API가 제공되지는 않는다.

### 교정 묶음과 무결성

- 묶음은 schema version, source_id, map identity/revision, 렌즈 후보, 바닥 후보,
  학습/검증 manifest의 digest, 독립 측량 근거 digest, 촬영 조건, 승인에 사용한 오차 한도를 갖는다.
  원본 JPEG·비밀값·실제 장치 주소·로컬 절대 경로는 Fleet 요청에 넣지 않는다.
- 렌즈는 pinhole/fisheye model·K/D·image_size, 바닥은 undistorted_to_map·reference_pixel과
  독립 check 오차를 보존한다. 바닥의 source_id와 lens_revision은 렌즈와 정확히 같아야 한다.
  `pixel_space`는 `undistorted`여야 한다. raw homography를 대신 받지 않는다.
- 기존 오프라인 revision 문자열을 신뢰의 증거로 쓰지 않는다. loader는 유한한 수·행렬 조건·
  계수 개수·양의 크기·source/map 일치와 canonical payload digest를 다시 검사한다.
  같은 렌즈 revision을 달고 K/D가 바뀐 묶음, 잘린 보고서, NaN/Infinity/bool은 거절한다.
- digest는 파일 결속을 검사할 뿐 측정 진실성이나 물리 정확도를 증명하지 않는다.
  독립 측량의 출처·촬영 조건을 사람이 확인했다는 기록을 별도로 남긴다.
- 잔차(px), 지도 오차(m), valid-pixel 관측 비율은 서로 다른 항목으로 보인다.
  승인 한도는 명시적인 유한 양수 p95/max 지도 오차로 받고 누락 시 승인하지 않는다.
  합성 표본과 실측 표본을 구분하고, 합성 자료는 현장 정확도 승인의 근거로 받지 않는다.

### 승인·영속 저장·동시 수정

- 기존 `/api/fleet/calibrations`의 읽기·승인·철회 경로와 source-token 전용
  `/api/fleet/detections/config`를 유지한다. 실측 요청은 `purpose: preview`와 형식 판별자를
  명시한다. 목록·철회도 preview 목적을 명시해야 해당 기록에 접근한다. 목적이 없는 기존
  요청은 기존 tracking 기록만 읽고 바꾼다. 기존 config의 `calibration`은 그대로 유지하고
  실측 미리보기는 별도 선택 필드로 전달한다. 구형 소비자에게 실측 기록을 paint-fit처럼 전달하지 않는다.
- 승인에는 이름 있는 operator, 묶음 digest, 명시적 검증 한도, 직전에 읽은 revision
  (처음에는 null)이 필요하다. 승인·교체·철회는 SQLite transaction에서 기대 revision을
  비교하고 감사 이력을 남긴다. 한 소유자가 바꾼 뒤 도착한 오래된 승인은 덮어쓰지 못한다.
- 승인 revision은 보존한 전체 묶음과 승인 사건을 식별한다. 후보 생성·낮은 RMS·AI 권고는
  승인이 아니다. DB 쓰기 실패 후 메모리만 성공으로 바꾸지 않는다.
- 첫 단위의 preview 선택은 source마다 하나이며 기존 tracking 선택과 구분한다.
  같은 Fleet 저장 소유자 안에서 목적별로 구분하고, preview 승인이 기존 tracking 승인과
  sighting admission revision을 교체하지 않는다. 철회·잘못된 DB row·불완전한 묶음은
  해당 실측 선택을 사용할 수 없게 한다. 마지막 성공 영상이나 다른 교정을 몰래 대신 쓰지 않는다.
  과거 revision 복귀도 현재 조건을 확인한 새 operator 승인 사건으로 기록한다.
- 공개 응답에는 persistent 여부를 보인다. 메모리 전용 구성의 결과를 재시작 뒤 유지된다고 표시하지 않는다.

### 적용과 촬영 조건 무효화

- 첫 단위의 실측 선택은 지도 **미리보기 전용**이다. 기존 tracking용 Calibration 및
  `approved_revision` sighting 허용 경로에 실측 revision을 공급하지 않는다.
  두 경로의 use와 revision을 구분해 승인 목록의 모양만으로 sighting 권한이 생기지 않게 한다.
- Vision은 묶음 검증 뒤 정확히 일치하는 source·map·렌즈·실제 JPEG 크기/회전에만 적용한다.
  같은 종횡비라는 이유로 임의 resize/crop를 허용하지 않는다. 초점·zoom·ISP·crop 등
  확인 불가능한 조건은 확인 불가로 보존하고, 사용자가 현재 입력 조건을 확인한 session에만
  미리보기를 허용한다. 이 확인은 자동 telemetry 검증이나 주행 수용을 뜻하지 않는다.
- source 재접속·수신 프로세스 재시작은 새 session이다. 이전 session 확인은 효력이 없다.
  렌즈 변경·프레임 크기/회전 변경·map 변경·철회·잘못된 digest에서도 적용을 멈추고
  재확인 사유를 표시한다. runtime session 식별은 Vision 수신 연결이 소유한다.
- 승인 저장 성공과 적용 성공은 따로 보인다. 적용 readback에는 source, 승인 revision,
  현재 session과 적용/미적용 이유가 있어야 한다. 오래된 readback으로 새 session을 성공 표시하지 않는다.
- 미리보기는 기존 signed Viewer lease와 direct Vision 경로를 사용한다. Fleet은 수치 상태만 읽는다.
  영상 요청 시 선택한 revision을 고정하고 처리 도중 철회·교체되면 구 revision을 새 것으로 표시하지 않는다.
- 원격 철회와 Vision의 config 갱신 사이에는 지연이 있다. 직전에 검증한 config에만 짧은
  적용 lease를 주고 갱신 실패·만료 시 미리보기를 중단한다. UI는 철회 요청과 Vision의
  철회 readback을 구분한다. 비동기 경계 너머의 즉시 철회를 보장한다고 쓰지 않는다.
- 원본을 보존하며 유효 mask 밖은 미관측으로 표시한다. 카메라가 못 보는 곳에서도 기준 지도는 유지한다.
  lens·floor 변환이나 무효화 때문에 기존 로봇 운행 설정을 자동 변경하지 않는다.

## 마커 입력과 D-598로 넘어가는 조건

첫 단위 뒤, 다음 검토에서는 측정 교정을 실제 관측에 적용할 계약을 별도로 확정한다.
바닥 좌표 변환에 로봇 상단 마커를 직접 넣지 않고, 측정 렌즈 ray·검증된 카메라 자세·
마커 장착 높이/offset으로 위치를 계산해야 한다. 이 자료나 독립 실측이 없으면
새 교정에서 위치 sighting을 내지 않는다. 익명 blob·LED 확인은 위치 앵커가 아니다.

D-598은 과거의 Fleet MapPose 소유 표기를 현행 D-630·D-752에 맞춰 후속 ADR에서 정리한다.
오차 한도 현재 자세 projection의 주인은 World, 신원 대응·운영 확인과 admission·감속·정지는
각각 현행 Fleet 소유자를 따른다. CORE의 최종 명령·안전 권한은 유지한다.

다음 구현을 여는 증거는 D-587 마커 sighting, D-593 지도 핀, D-596 LED의 현장 readback,
승인 교정의 독립 바닥/마커 오차, 두 로봇의 실제 속도별 odom 오차와 마커 공백 기록이다.
현장 증거가 없는 동안에는 replay fixture·검증 절차까지만 준비하고 주행 한도를 늘리지 않는다.
`source=bridged`라는 기존 문자열을 D-598의 새 `BRIDGED` 상태로 재해석하지 않는다.

[기존 근거 점검](../validation/measured-camera-lifecycle-2026-10-16/evidence-inventory.md)에서
D-587의 과거 설치·sighting readback은 확인했다. D-636의 합성 결과와 D-593의 원격 계약
시험도 존재한다. 이들을 새 실측 교정이나 현재 현장 수용으로 확대하지 않는다.
현재 로컬 자료의 제한된 조사 범위에서는 독립 촬영·검증 원본이 연결된 실측 묶음을 확보하지 못했다.

## 책임과 기존 계약의 관계

| 결정/소유자 | 이 설계가 유지하거나 추가하는 것 |
|---|---|
| Rosy Cam / D-636 | 실제 원본 취득. 첫 단위는 원격 카메라 설정 변경이나 새 Android protocol을 요구하지 않음 |
| Vision / D-633·D-636 | 실측 계산·수치 검증·최신 프레임 미리보기·적용 readback. 원본 경로 유지 |
| Fleet / D-457·D-595 | 승인·선택·SQLite·권한·감사 소유. 프레임마다 승인 교정을 다시 맞추지 않음 |
| World / D-630·D-752 | 현재 MapPose 소유 유지. 첫 단위는 새로운 위치 입력을 추가하지 않음 |
| D-427 | 기존 overhead·Fleet·site_ui holder 안에서 변경; 새 최상위 폴더·서비스 없음 |
| D-429 | 계산·관측과 운영 승인·명령 권한 분리 유지 |
| D-430 | safety-tagged 소비자를 건드리면 독립 리뷰와 trailer 필요. 실측 정확도나 안전 수용을 자가 승인하지 않음 |

## 검증과 완료 기준

기존 원격 pytest 절차로 **커밋한 revision**을 시험하고 `test/known_failures.py`로 판정한다.
실측 자료가 없어도 가능한 코드 검증과 실제 자료가 필요한 검증을 같은 통과 수로 합치지 않는다.

| 검증 | 관찰할 결과 |
|---|---|
| 묶음 loader | 다른 source/map/lens, digest 변조, raw/undistorted 혼합, 잘못된 계수·검증 한도·검증 누락 거절 |
| SQLite 재시작/경합 | 승인·철회 이력 보존, 기대 revision 경합 한 명만 성공, 쓰기 실패의 메모리 성공 없음, legacy DB 읽기 보존 |
| API/권한 | viewer 쓰기 금지, source token이 다른 source 기록을 못 읽고 승인을 못 함, extra field 거절, 구형 요청 의미 보존 |
| 실제 소비자 연결 | 승인→재시작→source config→Vision direct preview/readback을 연결; 요청한 revision·source·session 일치 |
| 무효화 | 재접속·렌즈/해상도/회전/map 변화·교체·철회 후 옛 영상/승인으로 적용 성공 표시 없음 |
| 영상 기하 | 기존 synthetic pinhole/fisheye fixture로 좌표 round trip·valid mask·horizon·crop 경계를 검사; raw 보존 |
| 관측 권한 | 미리보기 실측 revision은 기존 sighting admission에 사용 불가; 익명 검출·LED로 LOCALIZED를 만들지 않음 |
| Console | 승인 전 후보/오차/한도, 승인 뒤 저장·미적용·적용 구분, stale readback·재확인 사유, 좁은 화면과 기존 legacy 경로 확인 |
| 실제 카메라 | 독립 촬영·바닥 측량으로 중앙/가장자리 p95/max 오차와 조건 변경을 확인; 없으면 DEVICE/FIELD 미검증 |

회귀 출발점은 Vision `test_camera_calibration.py`, `test_overhead_track_calibration.py`,
`test_marker_sightings.py`, Fleet `test_overhead_tracking_calibration.py`,
`test_overhead_tracking_api.py`, `test_sightings_api.py`, `test_start_points.py`,
루트 `test_overhead_tracking_browser.py`다. 세부 선택과 추가 시험은 승인 후 구현 계획에서 정한다.

첫 단위 SOURCE 완료는 새 형식의 승인·영속 저장·명시적 철회·Vision 미리보기/readback과
거절 경로가 연결되어 관련 원격 시험 및 브라우저 회귀가 통과한 상태다. 실측이 없으면
배포 정확도·마커 위치·주행·D-598 완료는 주장하지 않는다. 착지와 push는 별도 지시를 따른다.

## 다음 행동

사용자가 이 설계를 검토하면 첫 단위의 구현 계획을 작성하고 실행 방법을 확인한다.
구현 직전에 ADR·API 번호를 도구로 선점한다. 실제 측정 자료는 기존 승인된 저장 위치에서
확인하고, 필요한 촬영·측량과 장치 접근은 그때의 현장 조건을 확인한 뒤 진행한다.
